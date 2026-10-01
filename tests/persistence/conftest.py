"""Disposable databases on the real M0 PostgreSQL service; no M0 data deletion."""

from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from relay.db.connection import database_url, make_engine


@pytest.fixture(scope="session")
def isolated_database(pg_connect, settings):
    @contextmanager
    def allocate():
        name = "relay_m1a_test_" + uuid4().hex
        with pg_connect() as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} OWNER relay_m0").format(sql.Identifier(name)))
            admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO relay_runtime").format(sql.Identifier(name)))
        try:
            yield name
        finally:
            # This exact UUID-named database was created above; never an M0 DB.
            assert name.startswith("relay_m1a_test_") and len(name) == 47
            with pg_connect() as admin:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    return allocate


def migrate(settings, name, target, *, downgrade=False):
    engine = make_engine(database_url(settings, migration=True).set(database=name))
    try:
        with engine.begin() as connection:
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            (command.downgrade if downgrade else command.upgrade)(config, target)
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def persistence_database(isolated_database, settings):
    with isolated_database() as name:
        migrate(settings, name, "head")
        print(f"M1A isolated PostgreSQL database: {name}; revision=0001_persistence")
        yield name


@pytest.fixture
def db_connect(persistence_database, settings):
    def connect(*, admin=False):
        url = database_url(settings, migration=admin).set(database=persistence_database)
        return psycopg.connect(host=url.host, port=url.port, dbname=url.database,
                               user=url.username, password=url.password, autocommit=True,
                               connect_timeout=5, options="-c synchronous_commit=on -c statement_timeout=5000 "
                               "-c lock_timeout=2000 -c idle_in_transaction_session_timeout=5000")
    return connect


@pytest.fixture
def runtime(db_connect):
    with db_connect() as connection:
        assert connection.execute("SELECT current_user, session_user").fetchone() == ("relay_runtime", "relay_runtime")
        yield connection
