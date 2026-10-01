"""Only Alembic applies deployed DDL. URLs/passwords are never logged."""

from pathlib import Path

from alembic import context
from dotenv import dotenv_values

from relay.db.connection import database_url, make_engine
from relay.db.schema import metadata

config = context.config
target_metadata = metadata


def run_migrations():
    # Tests may supply an already-open migration connection to an isolated DB.
    supplied = config.attributes.get("connection")
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    settings = dotenv_values(Path(config.config_file_name).resolve().parent / ".env")
    engine = make_engine(database_url(settings, migration=True))
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("M1A migrations require a real PostgreSQL connection")
run_migrations()
