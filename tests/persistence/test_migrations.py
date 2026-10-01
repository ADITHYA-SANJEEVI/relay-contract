import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.config import Config
from alembic.script import ScriptDirectory

from relay.db.connection import database_url, make_engine, session_factory
from relay.db.lock_order import LOCK_ORDER
from relay.db.schema import metadata

from .conftest import migrate

HEAD_REVISION = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()


def test_clean_upgrade_downgrade_upgrade(isolated_database, settings):
    with isolated_database() as name:
        engine = make_engine(database_url(settings, migration=True).set(database=name))
        try:
            migrate(settings, name, "head")
            with engine.connect() as c:
                assert c.scalar(sa.text("SELECT version_num FROM alembic_version")) == HEAD_REVISION
                assert set(sa.inspect(c).get_table_names()) == set(metadata.tables) | {"alembic_version"}
                assert c.execute(sa.text("SELECT id,next_ticket FROM scheduler_state")).all() == [(1, 1)]
            migrate(settings, name, "base", downgrade=True)
            with engine.connect() as c:
                assert sa.inspect(c).get_table_names() == ["alembic_version"]
                assert c.scalar(sa.text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'relay_%'")) == 0
            migrate(settings, name, "head")
            # A repeat upgrade is a no-op, not a second seed or duplicate DDL.
            migrate(settings, name, "head")
            with engine.connect() as c:
                assert c.scalar(sa.text("SELECT version_num FROM alembic_version")) == HEAD_REVISION
                assert c.scalar(sa.text("SELECT count(*) FROM scheduler_state")) == 1
            print(f"clean upgrade -> base downgrade -> upgrade -> repeat upgrade: head={HEAD_REVISION}")
        finally:
            engine.dispose()


def test_actual_schema_matches_metadata(persistence_database, settings):
    engine = make_engine(database_url(settings, migration=True).set(database=persistence_database))
    try:
        with engine.connect() as c:
            differences = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True,
                                           "compare_server_default": True}), metadata)
            assert differences == [], differences
            inspector = sa.inspect(c)
            for name, table in metadata.tables.items():
                assert inspector.get_pk_constraint(name)["constrained_columns"] == [col.name for col in table.primary_key]
                assert {x["name"] for x in inspector.get_check_constraints(name)} == {
                    x.name for x in table.constraints if isinstance(x, sa.CheckConstraint)}
                assert {x["name"] for x in inspector.get_foreign_keys(name)} == {
                    x.name for x in table.constraints if isinstance(x, sa.ForeignKeyConstraint)}
                assert {x["name"] for x in inspector.get_unique_constraints(name)} == {
                    x.name for x in table.constraints if isinstance(x, sa.UniqueConstraint)}
                actual_indexes = {x["name"]: x for x in inspector.get_indexes(name) if not x.get("duplicates_constraint")}
                assert set(actual_indexes) == {x.name for x in table.indexes}
                for index in table.indexes:
                    actual = actual_indexes[index.name]
                    assert actual["unique"] == index.unique
                    assert actual["column_names"] == [col.name for col in index.columns]
                    if index.dialect_options["postgresql"].get("where") is not None:
                        assert actual["dialect_options"]["postgresql_where"]
                print(f"INSPECTED {name}: columns={len(table.columns)} PK/FK/CHECK/UNIQUE/indexes match")
            fk = c.execute(sa.text("SELECT condeferrable, condeferred, pg_get_constraintdef(oid) "
                                   "FROM pg_constraint WHERE conname='fk_partitions_latest_attempt'")).one()
            assert fk[:2] == (True, True)
            assert "FOREIGN KEY (id, latest_generation_fk) REFERENCES attempts(partition_id, generation)" in fk[2]
            assert c.scalar(sa.text("SELECT confmatchtype FROM pg_constraint WHERE conname='fk_events_attempt_id_attempts'")) == "f"
            triggers = c.execute(sa.text("SELECT c.relname,t.tgname,t.tgdeferrable,t.tginitdeferred,t.tgenabled "
                "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE NOT t.tgisinternal")).all()
            for name in metadata.tables:
                assert (name, "guard_history_delete", False, False, "O") in triggers
            for name in ("jobs", "partitions", "attempts", "accepted_results", "workers"):
                assert (name, "check_consistency", True, True, "O") in triggers
            assert c.scalar(sa.text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'relay_%' AND prosecdef")) == 0
            print(f"INSPECTED {len(triggers)} enabled migration-owned triggers; no SECURITY DEFINER functions")
    finally:
        engine.dispose()


def test_runtime_engine_configuration_and_explicit_rollback(persistence_database, settings):
    engine = make_engine(database_url(settings).set(database=persistence_database))
    factory = session_factory(engine)
    try:
        with factory.begin() as session:
            assert session.scalar(sa.text("SELECT current_user")) == "relay_runtime"
            for setting, value in {"transaction_isolation": "read committed", "synchronous_commit": "on",
                    "lock_timeout": "2s", "statement_timeout": "5s", "idle_in_transaction_session_timeout": "5s"}.items():
                assert session.scalar(sa.text(f"SHOW {setting}")) == value
            ticket = session.scalar(sa.text("SELECT next_ticket FROM scheduler_state WHERE id=1 FOR UPDATE"))
        import pytest
        with pytest.raises(RuntimeError, match="fixture abort"):
            with factory.begin() as session:
                session.execute(sa.text("UPDATE scheduler_state SET next_ticket=next_ticket+1 WHERE id=1"))
                raise RuntimeError("fixture abort")
        with factory.begin() as session:
            assert session.scalar(sa.text("SELECT next_ticket FROM scheduler_state WHERE id=1")) == ticket
        assert len(LOCK_ORDER) == 7
        print("runtime psycopg engine: required settings, real FOR UPDATE and explicit exception rollback verified")
    finally:
        engine.dispose()


def test_missing_runtime_password_never_falls_back(settings):
    import pytest
    with pytest.raises(ValueError, match="POSTGRES_RUNTIME_PASSWORD"):
        database_url({k: v for k, v in settings.items() if k != "POSTGRES_RUNTIME_PASSWORD"})
