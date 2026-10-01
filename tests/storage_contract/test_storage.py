"""Safety gates use actual MinIO requests, never mocks or admin write fallback."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError


def key():
    return f"jobs/{uuid4()}/partitions/0/attempt-1/{uuid4()}/output.parquet"


def create(runtime, bucket, object_key, content):
    return runtime.put_object(
        Bucket=bucket, Key=object_key, Body=content, IfNoneMatch="*"
    )


def version_from(response):
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200, response
    version = response.get("VersionId")
    assert isinstance(version, str) and version and version != "null", response
    return version


def read_exact(runtime, bucket, object_key, version, expected):
    response = runtime.get_object(Bucket=bucket, Key=object_key, VersionId=version)
    try:
        content = response["Body"].read()
    finally:
        response["Body"].close()
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
    assert response["VersionId"] == version
    assert content == expected
    return content


def reject(operation, code, status):
    with pytest.raises(ClientError) as error:
        operation()
    response = error.value.response
    observed = {
        "operation": error.value.operation_name,
        "http_status": response["ResponseMetadata"]["HTTPStatusCode"],
        "code": response["Error"]["Code"],
        "message": response["Error"]["Message"],
    }
    print(json.dumps(observed))
    assert observed["code"] == code, observed
    assert observed["http_status"] == status, observed
    return observed


def only_version(admin, bucket, object_key, expected_version):
    listing = admin.list_object_versions(Bucket=bucket, Prefix=object_key)
    assert not listing.get("IsTruncated"), listing
    versions = [v for v in listing.get("Versions", []) if v["Key"] == object_key]
    markers = [v for v in listing.get("DeleteMarkers", []) if v["Key"] == object_key]
    assert len(versions) == 1, versions
    assert versions[0]["VersionId"] == expected_version
    assert versions[0]["IsLatest"] is True
    assert not markers, markers


def test_s1_versioning(storage):
    admin, runtime, bucket = storage
    response = admin.get_bucket_versioning(Bucket=bucket)
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
    assert response["Status"] == "Enabled", response
    object_key = key()
    version = version_from(create(runtime, bucket, object_key, b"versioning-probe"))
    read_exact(runtime, bucket, object_key, version, b"versioning-probe")
    print(f"S1 GetBucketVersioning=Enabled; runtime PutObject returned opaque VersionId={version}")


def test_s2_conditional_create(storage):
    admin, runtime, bucket = storage
    object_key = key()
    version = version_from(create(runtime, bucket, object_key, b"original"))
    reject(lambda: create(runtime, bucket, object_key, b"conflict"), "PreconditionFailed", 412)
    read_exact(runtime, bucket, object_key, version, b"original")
    only_version(admin, bucket, object_key, version)
    print("S2 If-None-Match:* initial=200; conflicting=412; one original version retained")


def test_s3_explicit_version_identity(storage):
    admin, runtime, bucket = storage
    object_key, expected = key(), b"opaque-version-read\x00\xff"
    version = version_from(create(runtime, bucket, object_key, expected))
    # Trusted admin deliberately creates a newer version only for this probe.
    # This distinguishes honoring VersionId from silently reading the latest.
    newer = version_from(admin.put_object(Bucket=bucket, Key=object_key, Body=b"admin-newer-version"))
    assert newer != version
    read_exact(runtime, bucket, object_key, newer, b"admin-newer-version")
    read_exact(runtime, bucket, object_key, version, expected)
    print(f"S3 runtime original VersionId={version}; admin probe newer VersionId={newer}; runtime exact reads distinguished both versions and bytes")


def test_s4_sha256_readback(storage):
    _, runtime, bucket = storage
    object_key, expected = key(), bytes(range(256)) * 1024
    expected_hash = hashlib.sha256(expected).hexdigest()
    version = version_from(create(runtime, bucket, object_key, expected))
    actual = read_exact(runtime, bucket, object_key, version, expected)
    actual_hash = hashlib.sha256(actual).hexdigest()
    assert actual_hash == expected_hash
    print(f"S4 readback bytes={len(actual)}; SHA-256={actual_hash}; expected matched; ETag unused")


def test_s5_immutable_identity_and_concurrent_create(storage):
    admin, runtime, bucket = storage
    object_key, barrier = key(), Barrier(2)
    candidates = [b"concurrent-A", b"concurrent-B"]

    def write(content):
        barrier.wait(timeout=10)
        try:
            return content, create(runtime, bucket, object_key, content), None
        except ClientError as error:
            return content, None, error.response

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, candidates))
    winners = [outcome for outcome in outcomes if outcome[1] is not None]
    losers = [outcome for outcome in outcomes if outcome[2] is not None]
    assert len(winners) == len(losers) == 1, outcomes
    original, response, _ = winners[0]
    assert losers[0][2]["ResponseMetadata"]["HTTPStatusCode"] == 412, losers
    assert losers[0][2]["Error"]["Code"] == "PreconditionFailed", losers
    version = version_from(response)
    for content in [original, b"different-authoritative-bytes", original]:
        reject(lambda: create(runtime, bucket, object_key, content), "PreconditionFailed", 412)
        read_exact(runtime, bucket, object_key, version, original)
    only_version(admin, bucket, object_key, version)
    print("S5 concurrent requests: exactly one 200 and one 412; identical/conflicting/repeated writes all 412; one unchanged pinned version")


def test_s6_runtime_delete_denial(storage):
    admin, runtime, bucket = storage
    object_key, original = key(), b"must-survive-runtime-delete"
    version = version_from(create(runtime, bucket, object_key, original))
    for args in ({"VersionId": version}, {}):
        reject(
            lambda: runtime.delete_object(Bucket=bucket, Key=object_key, **args),
            "AccessDenied", 403,
        )
        read_exact(runtime, bucket, object_key, version, original)
    only_version(admin, bucket, object_key, version)
    print("S6 runtime exact-version and key deletion both 403 AccessDenied; original bytes remain; no delete marker")


def test_s7_admin_runtime_separation(storage, settings):
    admin, runtime, bucket = storage
    # Inspect actual signer identities without printing credential values.
    assert admin._request_signer._credentials.access_key == settings["S3_ADMIN_ACCESS_KEY"]
    assert runtime._request_signer._credentials.access_key == settings["S3_RUNTIME_ACCESS_KEY"]
    assert admin._request_signer._credentials.access_key != runtime._request_signer._credentials.access_key
    assert admin.get_bucket_versioning(Bucket=bucket)["Status"] == "Enabled"
    reject(
        lambda: runtime.put_bucket_versioning(
            Bucket=bucket, VersioningConfiguration={"Status": "Suspended"}
        ),
        "AccessDenied", 403,
    )
    assert admin.get_bucket_versioning(Bucket=bucket)["Status"] == "Enabled"
    object_key = key()
    version = version_from(create(runtime, bucket, object_key, b"runtime-only"))
    read_exact(runtime, bucket, object_key, version, b"runtime-only")
    print("S7 distinct explicit signer identities; admin versioning read allowed; runtime versioning mutation=403; runtime create/read=200; no fallback")


def test_s8_lost_reply_and_repeated_write(storage):
    admin, runtime, bucket = storage
    object_key, original = key(), b"committed-before-reply-loss"

    class ReplyLost(RuntimeError):
        pass

    def lose_reply(http_response, parsed, **kwargs):
        assert http_response.status_code == 200
        assert parsed.get("VersionId")
        # Real store write succeeded; discard reply before the caller sees identity.
        raise ReplyLost("intentional post-write SDK response loss")

    event, handler_id = "after-call.s3.PutObject", "m0-lost-reply"
    runtime.meta.events.register(event, lose_reply, unique_id=handler_id)
    try:
        with pytest.raises(ReplyLost, match="intentional post-write"):
            create(runtime, bucket, object_key, original)
    finally:
        runtime.meta.events.unregister(event, unique_id=handler_id)
    reject(lambda: create(runtime, bucket, object_key, original), "PreconditionFailed", 412)
    discovered = runtime.head_object(Bucket=bucket, Key=object_key)
    version = version_from(discovered)
    actual = read_exact(runtime, bucket, object_key, version, original)
    assert hashlib.sha256(actual).digest() == hashlib.sha256(original).digest()
    only_version(admin, bucket, object_key, version)
    print("S8 real PutObject 200 reply discarded at SDK boundary; retry=412; HEAD recovered opaque version; exact read/SHA match; one version retained")
