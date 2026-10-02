import pytest
import sqlalchemy as sa

from relay.db import schema as db
from tests.integration.test_m1b import row_for
from tests.publication.test_m1c import assert_unaccepted, complete, events, prepared, run_worker, shorten_lease
from .helpers import Processes, advance_eligibility, report, target_results


@pytest.mark.parametrize("after_abort", ["live", "expired"])
def test_t10_verified_artifact_real_publication_rollback_and_safe_retry(api, after_abort):
    claimed, owner, body = prepared(api)
    artifact = row_for(api, db.artifacts, body["artifact_id"])
    before = events(api)
    with api.admin_engine.begin() as c:
        c.exec_driver_sql("CREATE FUNCTION m3_abort_publish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF (SELECT status FROM partitions WHERE id=NEW.partition_id) <> 'SUCCEEDED' THEN RAISE EXCEPTION 'missing fence'; END IF; "
            "RAISE EXCEPTION 'test abort after real SQL fence' USING ERRCODE='23514'; END; $$")
        c.exec_driver_sql("CREATE TRIGGER m3_abort_publish BEFORE INSERT ON accepted_results FOR EACH ROW EXECUTE FUNCTION m3_abort_publish()")
    try:
        response = complete(api, claimed, owner, body)
        assert response.status_code == 503 and response.json()["error"]["outcome"] == "not_committed"
        assert_unaccepted(api, claimed)
        assert events(api) == before and row_for(api, db.artifacts, str(artifact["id"])) == artifact
    finally:
        with api.admin_engine.begin() as c:
            c.exec_driver_sql("DROP TRIGGER m3_abort_publish ON accepted_results")
            c.exec_driver_sql("DROP FUNCTION m3_abort_publish()")
    processes = Processes(api)
    try:
        if after_abort == "live":
            retry = complete(api, claimed, owner, body)
            assert retry.status_code == 201 and retry.json()["accepted_result"]["artifact_id"] == body["artifact_id"]
            outcome = dict(retry=retry.json(), original_generation=1)
        else:
            shorten_lease(api, claimed, expired=True)
            rejected = complete(api, claimed, owner, body)
            assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "lease_expired"
            assert target_results(api, claimed["partition_id"]) == []
            recovery = processes.recover_once()
            backoff = advance_eligibility(api, claimed)
            result = run_worker(api)
            assert result["generation"] == "2" and result["artifact_id"] != body["artifact_id"]
            assert row_for(api, db.attempts, claimed["attempt_id"])["status"] == "EXPIRED"
            outcome = dict(rejection_code="lease_expired", recovery=recovery, backoff=backoff, new_worker=result)
        assert row_for(api, db.artifacts, str(artifact["id"])) == artifact
        assert [e["type"] for e in events(api)].count("RESULT_ACCEPTED") == 1
        report("T10", after_abort=after_abort, abort_status=503, abort_outcome="not_committed",
               retained_artifact=artifact, outcome=outcome)
    finally: processes.close()
