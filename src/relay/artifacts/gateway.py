import hashlib
import json
import logging
from contextlib import closing
from tempfile import SpooledTemporaryFile

import boto3
import sqlalchemy as sa
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from relay.control.common import Rejection, one
from relay.control.service import artifact_response, input_response
from relay.db import schema as db
from relay.workloads.reference import INPUT_SCHEMA, OUTPUT_SCHEMA, WorkloadError, read_parquet, write_parquet

logger = logging.getLogger("relay.artifacts")


class Gateway:
    def __init__(self, engine, settings):
        self.engine = engine
        self.store = boto3.client("s3", endpoint_url=f"http://127.0.0.1:{settings['S3_PORT']}",
            region_name="us-east-1", aws_access_key_id=settings["S3_RUNTIME_ACCESS_KEY"],
            aws_secret_access_key=settings["S3_RUNTIME_SECRET_KEY"], config=Config(
                signature_version="s3v4", s3={"addressing_style": "path"}, retries={"total_max_attempts": 1},
                connect_timeout=5, read_timeout=10))
        self.bucket = settings["S3_BUCKET"]

    def ready(self):
        # Runtime cannot administer buckets. A HEAD on an absent, fixed probe key
        # establishes service/auth reachability without creating an object.
        try:
            self.store.head_object(Bucket=self.bucket, Key="readiness/nonexistent")
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404: raise

    def snapshot(self, table, identity):
        with self.engine.connect() as c:
            return one(c, table, table.c.id == identity)

    def read_exact(self, row, version, expected_hash, expected_size):
        if not version or version == "null": raise Rejection("missing_object_version", 422)
        result = self.store.get_object(Bucket=row["bucket"], Key=row["object_key"], VersionId=version)
        if result.get("VersionId") != version:
            result["Body"].close()
            raise Rejection("object_version_mismatch", 422)
        spool = SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        digest, count = hashlib.sha256(), 0
        try:
            with closing(result["Body"]) as body:
                for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                    count += len(chunk)
                    if count > expected_size: raise Rejection("stored_size_mismatch", 422)
                    digest.update(chunk); spool.write(chunk)
            if count != expected_size or digest.hexdigest() != expected_hash:
                raise Rejection("stored_integrity_mismatch", 422)
            spool.seek(0)
            return spool
        except Exception:
            spool.close()
            raise

    def upload(self, identity, file, incoming_hash, incoming_size, *, is_input):
        table = db.input_artifacts if is_input else db.artifacts
        row = self.snapshot(table, identity)  # Connection closed BEFORE storage/parsing.
        if row["status"] == "REJECTED": raise Rejection("artifact_rejected", 422)
        expected_hash = row["expected_sha256"]
        expected_size = row["size_bytes"] if is_input else row["expected_size_bytes"]
        if incoming_hash != expected_hash or incoming_size != expected_size:
            raise Rejection("content_identity_mismatch", 422)
        file.seek(0)
        try:
            try:
                written = self.store.put_object(Bucket=row["bucket"], Key=row["object_key"], Body=file,
                    ContentLength=incoming_size, ContentType="application/vnd.apache.parquet", IfNoneMatch="*")
                version = written.get("VersionId")
            except ClientError as error:
                if error.response["ResponseMetadata"]["HTTPStatusCode"] not in (409, 412): raise
                # Reserved-key reconciliation. No overwrite, delete or inferred version.
                version = row["object_version"] or self.store.head_object(
                    Bucket=row["bucket"], Key=row["object_key"]).get("VersionId")
            if row["object_version"] and version != row["object_version"]:
                raise Rejection("object_version_mismatch", 422)
            with self.read_exact(row, version, expected_hash, expected_size) as stored:
                parsed = read_parquet(stored, INPUT_SCHEMA if is_input else OUTPUT_SCHEMA)
                count = parsed.num_rows
        except (BotoCoreError, ClientError) as error:
            raise Rejection("storage_unavailable", 503) from error
        except (WorkloadError, Rejection) as error:
            if row["status"] == "RESERVED":
                with self.engine.begin() as c:
                    current = one(c, table, table.c.id == identity, lock=True)
                    if current["status"] == "RESERVED":
                        c.execute(table.update().where(table.c.id == identity, table.c.status == "RESERVED").values(
                            status="REJECTED", **({"error_code": "stored_integrity_failure"} if is_input
                                                  else {"rejection_code": "stored_integrity_failure"})))
            raise Rejection("stored_integrity_failure", 422) from error
        # All object I/O and Parquet parsing finished. Lock ONLY this metadata row.
        with self.engine.begin() as c:
            current = one(c, table, table.c.id == identity, lock=True)
            if current["status"] == "REJECTED": raise Rejection("artifact_rejected", 422)
            if current["status"] == "RESERVED":
                values = dict(status="VERIFIED", object_version=version, verified_at=sa.func.clock_timestamp())
                values.update(dict(sha256=expected_hash, row_count=count) if is_input else dict(
                    verified_sha256=expected_hash, verified_size_bytes=expected_size,
                    verified_schema_hash=current["expected_schema_hash"]))
                current = dict(c.execute(table.update().where(table.c.id == identity, table.c.status == "RESERVED")
                    .values(**values).returning(table)).mappings().one())
            elif current["object_version"] != version:
                raise Rejection("object_version_mismatch", 422)
            response = input_response(current) if is_input else artifact_response(current)
        return response

    def assigned_slice(self, attempt_id, ordinal, worker):
        with self.engine.connect() as c:
            attempt = one(c, db.attempts, db.attempts.c.id == attempt_id)
            if attempt["worker_session_id"] != worker: raise Rejection("wrong_owner", 403)
            part = one(c, db.partition_inputs, sa.and_(db.partition_inputs.c.partition_id == attempt["partition_id"],
                        db.partition_inputs.c.slice_ordinal == ordinal))
            reference = one(c, db.job_inputs, sa.and_(db.job_inputs.c.job_id == part["job_id"],
                            db.job_inputs.c.input_ordinal == part["input_ordinal"]))
            row = one(c, db.input_artifacts, db.input_artifacts.c.id == reference["input_artifact_id"])
        try:
            with self.read_exact(row, row["object_version"], row["sha256"], row["size_bytes"]) as stored:
                assigned = read_parquet(stored, INPUT_SCHEMA).slice(part["first_row"], part["row_count"])
            output = SpooledTemporaryFile(max_size=8 * 1024 * 1024)
            write_parquet(assigned, output)
            output.seek(0)
            return output
        except (BotoCoreError, ClientError) as error:
            raise Rejection("storage_unavailable", 503) from error
        except WorkloadError as error:
            raise Rejection("input_integrity_failure", 422) from error

    def verified_result(self, row):
        stored = None
        try:
            stored = self.read_exact(row, row["object_version"], row["verified_sha256"], row["verified_size_bytes"])
            read_parquet(stored, OUTPUT_SCHEMA)
            stored.seek(0)
            return stored
        except (BotoCoreError, ClientError) as error:
            if stored is not None: stored.close()
            if not isinstance(error, ClientError) or error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise Rejection("storage_unavailable", 503) from error
        except (WorkloadError, Rejection):
            if stored is not None: stored.close()
        logger.error(json.dumps({"component": "artifacts", "operation": "accepted_read",
                                "artifact_id": str(row["id"]), "error_code": "integrity_failure"}))
        # No mutation, fallback version or automatic recomputation.
        raise Rejection("integrity_failure", 422)
