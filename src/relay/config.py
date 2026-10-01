"""API-only local configuration; worker never loads this module or .env."""

from pathlib import Path

from dotenv import dotenv_values


def load_settings(path):
    values = dotenv_values(Path(path))
    names = ("POSTGRES_RUNTIME_PASSWORD", "POSTGRES_PORT", "POSTGRES_DATABASE", "S3_PORT", "S3_BUCKET",
             "S3_RUNTIME_ACCESS_KEY", "S3_RUNTIME_SECRET_KEY", "RELAY_OPERATOR_TOKEN", "RELAY_WORKER_BOOTSTRAP_TOKEN",
             "RELAY_MAX_INPUT_BYTES", "RELAY_MAX_WORKERS")
    settings = {name: values[name] for name in names if values.get(name)}
    for name in ("POSTGRES_RUNTIME_PASSWORD", "POSTGRES_PORT", "S3_PORT", "S3_BUCKET",
                 "S3_RUNTIME_ACCESS_KEY", "S3_RUNTIME_SECRET_KEY", "RELAY_OPERATOR_TOKEN", "RELAY_WORKER_BOOTSTRAP_TOKEN"):
        value = settings.get(name)
        if not value or value.startswith("REPLACE_"):
            raise ValueError(f"Missing local configuration: {name}")
    if settings["RELAY_OPERATOR_TOKEN"] == settings["RELAY_WORKER_BOOTSTRAP_TOKEN"]:
        raise ValueError("Operator and worker bootstrap credentials must be distinct")
    if not 1 <= int(settings.get("RELAY_MAX_WORKERS", 32)) <= 32:
        raise ValueError("Configured worker capacity must be between 1 and 32")
    if not 1 <= int(settings.get("RELAY_MAX_INPUT_BYTES", 268435456)) <= 2**63-1:
        raise ValueError("Configured input size bound must fit positive bigint")
    return settings
