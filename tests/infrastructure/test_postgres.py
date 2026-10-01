"""Only disposable infrastructure tables; no Relay schema."""

from datetime import datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql


@pytest.fixture
def table(pg_connect):
    name = "m0_lock_" + uuid4().hex
    identifier = sql.Identifier(name)
    with pg_connect() as connection:
        connection.execute(sql.SQL("CREATE TABLE {} (id integer PRIMARY KEY, value integer NOT NULL)").format(identifier))
        connection.execute(sql.SQL("INSERT INTO {} VALUES (1, 0)").format(identifier))
    try:
        yield identifier
    finally:
        with pg_connect() as connection:
            connection.execute(sql.SQL("DROP TABLE {}").format(identifier))


def test_driver_and_server_major(pg_connect):
    with pg_connect() as connection:
        version, database, user = connection.execute(
            "SELECT current_setting('server_version_num')::integer, current_database(), current_user"
        ).fetchone()
        assert isinstance(connection, psycopg.Connection)
        assert version // 10000 == 18
        assert connection.info.server_version == version
        assert database == "relay_m0"
        assert user == "relay_m0"
        print(f"psycopg={psycopg.__version__}; server_version_num={version}; database={database}; user={user}")


def test_clock_timestamp_is_fresh_within_transaction(pg_connect):
    with pg_connect() as connection, connection.transaction():
        first_clock, first_transaction = connection.execute(
            "SELECT clock_timestamp(), transaction_timestamp()"
        ).fetchone()
        connection.execute("SELECT pg_sleep(0.05)")
        second_clock, second_transaction = connection.execute(
            "SELECT clock_timestamp(), transaction_timestamp()"
        ).fetchone()
        assert isinstance(first_clock, datetime)
        assert first_clock.utcoffset() == timedelta(0)
        assert second_clock > first_clock
        assert first_transaction == second_transaction
        print(f"clock advanced {(second_clock - first_clock).total_seconds():.6f}s; transaction timestamp unchanged")


def test_transactions_commit_and_rollback(pg_connect, table):
    update = sql.SQL("UPDATE {} SET value = %s WHERE id = 1").format(table)
    read = sql.SQL("SELECT value FROM {} WHERE id = 1").format(table)
    with pg_connect() as first, pg_connect() as second:
        with first.transaction():
            first.execute(update, (7,))
            assert first.execute(read).fetchone() == (7,)
            assert second.execute(read).fetchone() == (0,)
        assert second.execute(read).fetchone() == (7,)
        with pytest.raises(RuntimeError, match="deliberate rollback"):
            with first.transaction():
                first.execute(update, (9,))
                raise RuntimeError("deliberate rollback")
        assert second.execute(read).fetchone() == (7,)
        print("uncommitted update invisible; committed value=7; rolled-back value=9 absent")


def test_two_connections_and_for_update_lock(pg_connect, table):
    lock = sql.SQL("SELECT value FROM {} WHERE id = 1 FOR UPDATE").format(table)
    with pg_connect() as first, pg_connect() as second:
        first_pid = first.execute("SELECT pg_backend_pid()").fetchone()[0]
        second_pid = second.execute("SELECT pg_backend_pid()").fetchone()[0]
        assert first_pid != second_pid
        with first.transaction():
            assert first.execute(lock).fetchone() == (0,)
            with pytest.raises(psycopg.errors.LockNotAvailable) as rejected:
                with second.transaction():
                    second.execute("SET LOCAL lock_timeout = '200ms'")
                    second.execute(lock)
            assert rejected.value.sqlstate == "55P03"
        with second.transaction():
            assert second.execute(lock).fetchone() == (0,)
        print(f"independent backend PIDs={first_pid},{second_pid}; held row lock caused SQLSTATE 55P03; lock acquired after release")
