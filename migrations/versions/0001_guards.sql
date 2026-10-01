-- Migration-owned guards. Invoker functions grant no privileged execution path.
CREATE FUNCTION relay_reject_history_change() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION '% is immutable history', TG_TABLE_NAME
        USING ERRCODE = '23514', CONSTRAINT = 'relay_immutable_history';
END;
$$;

CREATE FUNCTION relay_guard_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE field text;
BEGIN
    FOREACH field IN ARRAY TG_ARGV LOOP
        IF to_jsonb(OLD)->field IS DISTINCT FROM to_jsonb(NEW)->field THEN
            RAISE EXCEPTION 'immutable %.% changed', TG_TABLE_NAME, field
                USING ERRCODE = '23514', CONSTRAINT = 'relay_immutable_column';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;

CREATE FUNCTION relay_guard_state() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE previous text; following text; valid boolean := false;
BEGIN
    following := to_jsonb(NEW)->>(CASE WHEN TG_TABLE_NAME = 'workers' THEN 'state' ELSE 'status' END);
    IF TG_OP = 'INSERT' THEN
        valid := following = CASE TG_TABLE_NAME
            WHEN 'jobs' THEN 'QUEUED' WHEN 'partitions' THEN 'READY'
            WHEN 'attempts' THEN 'ACTIVE' WHEN 'workers' THEN 'REGISTERED'
            ELSE 'RESERVED' END;
        IF TG_TABLE_NAME = 'jobs' THEN
            NEW.creation_xid := pg_current_xact_id()::text;
        END IF;
        IF TG_TABLE_NAME = 'partitions' THEN
            IF NEW.generation <> 0 THEN valid := false; END IF;
        END IF;
    ELSE
        previous := to_jsonb(OLD)->>(CASE WHEN TG_TABLE_NAME = 'workers' THEN 'state' ELSE 'status' END);
        valid := previous = following;
        IF TG_TABLE_NAME = 'jobs' THEN
            valid := valid OR (previous = 'QUEUED' AND following IN ('RUNNING','CANCELLED'))
                OR (previous = 'RUNNING' AND following IN ('SUCCEEDED','FAILED','CANCELLED'));
            -- Terminal jobs can still allocate sequence numbers for rejection audit.
            IF previous IN ('SUCCEEDED','FAILED','CANCELLED')
               AND (to_jsonb(OLD) - 'next_event_seq') IS DISTINCT FROM (to_jsonb(NEW) - 'next_event_seq') THEN
                valid := false;
            END IF;
        ELSIF TG_TABLE_NAME = 'partitions' THEN
            valid := valid OR (previous = 'READY' AND following IN ('RUNNING','CANCELLED'))
                OR (previous = 'RUNNING' AND following IN ('SUCCEEDED','READY','FAILED','CANCELLED'));
            IF NEW.generation IS DISTINCT FROM OLD.generation THEN
                valid := valid AND previous = 'READY' AND following = 'RUNNING'
                    AND NEW.generation = OLD.generation + 1;
            ELSIF previous = 'READY' AND following = 'RUNNING' THEN
                valid := false;
            END IF;
            IF previous IN ('SUCCEEDED','FAILED','CANCELLED') AND NEW IS DISTINCT FROM OLD THEN
                valid := false;
            END IF;
        ELSIF TG_TABLE_NAME = 'attempts' THEN
            valid := valid OR (previous = 'ACTIVE' AND following IN ('SUCCEEDED','FAILED','EXPIRED','CANCELLED'));
            IF previous <> 'ACTIVE' AND NEW IS DISTINCT FROM OLD THEN valid := false; END IF;
        ELSIF TG_TABLE_NAME = 'workers' THEN
            valid := valid OR (previous = 'REGISTERED' AND following IN ('DRAINING','STOPPED'))
                OR (previous = 'DRAINING' AND following = 'STOPPED');
        ELSE
            valid := valid OR (previous = 'RESERVED' AND following IN ('VERIFIED','REJECTED'));
            IF previous <> 'RESERVED' AND NEW IS DISTINCT FROM OLD THEN valid := false; END IF;
        END IF;
    END IF;
    IF NOT valid THEN
        RAISE EXCEPTION 'invalid % state transition % -> %', TG_TABLE_NAME, previous, following
            USING ERRCODE = '23514', CONSTRAINT = 'relay_state_transition';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION relay_guard_manifest_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE creating_xid text; input_state text;
BEGIN
    SELECT creation_xid INTO creating_xid FROM jobs WHERE id = NEW.job_id;
    IF creating_xid IS DISTINCT FROM pg_current_xact_id()::text THEN
        RAISE EXCEPTION 'job manifest can only be inserted in its creation transaction'
            USING ERRCODE = '23514', CONSTRAINT = 'relay_manifest_frozen';
    END IF;
    IF TG_TABLE_NAME = 'job_inputs' THEN
        SELECT status INTO input_state FROM input_artifacts WHERE id = NEW.input_artifact_id;
        IF input_state IS DISTINCT FROM 'VERIFIED' THEN
            RAISE EXCEPTION 'only VERIFIED inputs may attach'
                USING ERRCODE = '23514', CONSTRAINT = 'relay_input_verified';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION relay_check_consistency() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    partition_uuid uuid; job_uuid uuid; worker_uuid uuid;
    p partitions%ROWTYPE; j jobs%ROWTYPE; a attempts%ROWTYPE;
    r accepted_results%ROWTYPE; f artifacts%ROWTYPE;
    greatest_generation bigint; attempt_count bigint; total bigint;
    successful bigint; failed bigint; nonterminal bigint; accepted boolean;
BEGIN
    IF TG_TABLE_NAME = 'workers' THEN
        worker_uuid := NEW.session_id;
    ELSIF TG_TABLE_NAME = 'jobs' THEN
        job_uuid := NEW.id;
    ELSE
        partition_uuid := (to_jsonb(NEW)->>(CASE WHEN TG_TABLE_NAME = 'partitions' THEN 'id' ELSE 'partition_id' END))::uuid;
        SELECT * INTO p FROM partitions WHERE id = partition_uuid;
        job_uuid := p.job_id;
        SELECT * INTO j FROM jobs WHERE id = job_uuid;
        SELECT COALESCE(max(generation), 0), count(*) INTO greatest_generation, attempt_count
            FROM attempts WHERE partition_id = p.id;
        SELECT * INTO a FROM attempts WHERE partition_id = p.id AND generation = p.generation;
        SELECT * INTO r FROM accepted_results WHERE partition_id = p.id;
        accepted := FOUND;
        IF p.generation > j.max_attempts OR p.generation <> greatest_generation
            OR p.generation <> attempt_count
            OR ((p.status = 'RUNNING') IS DISTINCT FROM COALESCE(a.status = 'ACTIVE', false))
            OR ((p.status = 'SUCCEEDED') IS DISTINCT FROM accepted)
            OR ((p.status = 'SUCCEEDED') IS DISTINCT FROM COALESCE(a.status = 'SUCCEEDED', false))
            OR (p.status IN ('READY','FAILED','CANCELLED') AND EXISTS
                (SELECT 1 FROM attempts WHERE partition_id = p.id AND status = 'ACTIVE'))
            OR (p.status = 'READY' AND p.generation > 0 AND a.status NOT IN ('FAILED','EXPIRED'))
            OR (p.status = 'FAILED' AND a.status NOT IN ('FAILED','EXPIRED'))
            OR (p.status = 'CANCELLED' AND p.generation > 0 AND a.status <> 'CANCELLED')
            OR (p.status = 'RUNNING' AND j.status <> 'RUNNING') THEN
            RAISE EXCEPTION 'partition ownership/history/result consistency failed'
                USING ERRCODE = '23514', CONSTRAINT = 'relay_partition_consistency';
        END IF;
        IF accepted THEN
            SELECT * INTO f FROM artifacts WHERE id = r.artifact_id;
            IF r.attempt_id IS DISTINCT FROM a.id OR r.generation <> p.generation
                OR f.status IS DISTINCT FROM 'VERIFIED' THEN
                RAISE EXCEPTION 'accepted result requires latest SUCCEEDED attempt and VERIFIED artifact'
                    USING ERRCODE = '23514', CONSTRAINT = 'relay_accepted_consistency';
            END IF;
        END IF;
        IF EXISTS (SELECT 1 FROM attempts AS history WHERE history.partition_id = p.id
            AND history.status = 'SUCCEEDED' AND NOT EXISTS
                (SELECT 1 FROM accepted_results AS result WHERE result.attempt_id = history.id)) THEN
            RAISE EXCEPTION 'SUCCEEDED attempt requires its accepted result'
                USING ERRCODE = '23514', CONSTRAINT = 'relay_accepted_consistency';
        END IF;
        IF TG_TABLE_NAME = 'attempts' THEN worker_uuid := NEW.worker_session_id; END IF;
        IF a.id IS NOT NULL AND a.hard_deadline_at IS DISTINCT FROM
            a.claimed_at + make_interval(secs => j.max_attempt_seconds) THEN
            RAISE EXCEPTION 'hard deadline must equal immutable claim time plus job policy'
                USING ERRCODE = '23514', CONSTRAINT = 'relay_hard_deadline';
        END IF;
    END IF;
    IF job_uuid IS NOT NULL THEN
        SELECT * INTO j FROM jobs WHERE id = job_uuid;
        SELECT count(*), count(*) FILTER (WHERE status = 'SUCCEEDED'),
               count(*) FILTER (WHERE status = 'FAILED'),
               count(*) FILTER (WHERE status IN ('READY','RUNNING'))
            INTO total, successful, failed, nonterminal FROM partitions WHERE job_id = job_uuid;
        IF total <> j.partition_count
            OR (j.status = 'SUCCEEDED' AND successful <> total)
            OR (j.status = 'FAILED' AND (nonterminal <> 0 OR failed = 0))
            OR (j.status = 'CANCELLED' AND nonterminal <> 0)
            OR (j.status IN ('QUEUED','RUNNING') AND nonterminal = 0)
            OR (j.status = 'QUEUED' AND EXISTS
                (SELECT 1 FROM partitions WHERE job_id = j.id AND (status <> 'READY' OR generation <> 0)))
            OR (j.status = 'RUNNING' AND NOT EXISTS
                (SELECT 1 FROM partitions WHERE job_id = j.id AND generation > 0))
            OR (j.status <> 'RUNNING' AND EXISTS
                (SELECT 1 FROM attempts JOIN partitions ON partitions.id = attempts.partition_id
                    WHERE partitions.job_id = j.id AND attempts.status = 'ACTIVE')) THEN
            RAISE EXCEPTION 'job partition-count/terminal consistency failed'
                USING ERRCODE = '23514', CONSTRAINT = 'relay_job_consistency';
        END IF;
    END IF;
    IF worker_uuid IS NOT NULL AND EXISTS
        (SELECT 1 FROM workers WHERE session_id = worker_uuid AND state = 'STOPPED')
        AND EXISTS (SELECT 1 FROM attempts WHERE worker_session_id = worker_uuid AND status = 'ACTIVE') THEN
        RAISE EXCEPTION 'STOPPED worker cannot retain ACTIVE attempt'
            USING ERRCODE = '23514', CONSTRAINT = 'relay_worker_consistency';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER guard_jobs_identity BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION relay_guard_immutable(
    'id','version','parent_job_id','definition_hash','workload_name','workload_version','workload_digest',
    'parameters','manifest_hash','max_attempts','lease_seconds','max_attempt_seconds','partition_count','created_at','creation_xid');
CREATE TRIGGER guard_partitions_identity BEFORE UPDATE ON partitions FOR EACH ROW EXECUTE FUNCTION relay_guard_immutable('id','job_id','ordinal','created_at');
CREATE TRIGGER guard_workers_identity BEFORE UPDATE ON workers FOR EACH ROW EXECUTE FUNCTION relay_guard_immutable('session_id','display_name','registration_hash','session_secret_hash','deployment_workload_digest','created_at');
CREATE TRIGGER guard_attempts_identity BEFORE UPDATE ON attempts FOR EACH ROW EXECUTE FUNCTION relay_guard_immutable('id','partition_id','generation','worker_session_id','claimed_at','hard_deadline_at');
CREATE TRIGGER guard_inputs_identity BEFORE UPDATE ON input_artifacts FOR EACH ROW EXECUTE FUNCTION relay_guard_immutable('id','import_key','reservation_fingerprint','expected_sha256','size_bytes','media_type','schema_hash','bucket','object_key','created_at');
CREATE TRIGGER guard_artifacts_identity BEFORE UPDATE ON artifacts FOR EACH ROW EXECUTE FUNCTION relay_guard_immutable('id','attempt_id','partition_id','generation','expected_sha256','expected_size_bytes','expected_schema_hash','reservation_fingerprint','bucket','object_key','created_at');

-- No history deletion, even through ordinary migration-owner DML.
DO $$ DECLARE table_name text; BEGIN
    FOREACH table_name IN ARRAY ARRAY['jobs','input_artifacts','job_inputs','partitions','partition_inputs','workers',
        'attempts','artifacts','accepted_results','events','worker_events','request_receipts','scheduler_state'] LOOP
        EXECUTE format('CREATE TRIGGER guard_history_delete BEFORE DELETE ON %I FOR EACH ROW EXECUTE FUNCTION relay_reject_history_change()', table_name);
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY['job_inputs','partition_inputs','accepted_results','events','worker_events','request_receipts'] LOOP
        EXECUTE format('CREATE TRIGGER guard_history_update BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION relay_reject_history_change()', table_name);
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY['jobs','partitions','attempts','workers','input_artifacts','artifacts'] LOOP
        EXECUTE format('CREATE TRIGGER guard_state BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION relay_guard_state()', table_name);
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY['partitions','job_inputs','partition_inputs'] LOOP
        EXECUTE format('CREATE TRIGGER guard_manifest_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION relay_guard_manifest_insert()', table_name);
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY['jobs','partitions','attempts','accepted_results','workers'] LOOP
        EXECUTE format('CREATE CONSTRAINT TRIGGER check_consistency AFTER INSERT OR UPDATE ON %I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION relay_check_consistency()', table_name);
    END LOOP;
END; $$;

INSERT INTO scheduler_state (id, next_ticket) VALUES (1, 1);
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO relay_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM relay_runtime;
GRANT SELECT, INSERT, UPDATE ON jobs, input_artifacts, job_inputs, partitions, partition_inputs,
    workers, attempts, artifacts TO relay_runtime;
GRANT SELECT, INSERT ON accepted_results, events, worker_events, request_receipts TO relay_runtime;
GRANT SELECT, UPDATE ON scheduler_state TO relay_runtime;
REVOKE ALL ON FUNCTION relay_reject_history_change(), relay_guard_immutable(), relay_guard_state(),
    relay_guard_manifest_insert(), relay_check_consistency() FROM PUBLIC;
