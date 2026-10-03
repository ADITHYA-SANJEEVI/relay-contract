from tests.integration.conftest import api  # noqa: F401; real PostgreSQL/MinIO/API

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path():
    # Same workspace temp root for sandboxed and real-service test identities.
    cache = Path(__file__).resolve().parents[2] / ".cache/browser-unit-tests"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run_", dir=cache) as directory:
        path = Path(directory).resolve()
        assert path.parent == cache.resolve() and path.name.startswith("run_")
        yield path
