"""Provision the local runtime identity; migration authority stays with relay_m0."""

import secrets
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

root = Path(__file__).resolve().parents[1]
env_path = root / ".env"
values = dotenv_values(env_path)
password = values.get("POSTGRES_RUNTIME_PASSWORD")
if not password or password.startswith("REPLACE_"):
    password = secrets.token_hex(24)
    with env_path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(f"\nPOSTGRES_RUNTIME_PASSWORD={password}\n")
with psycopg.connect(
    host="127.0.0.1", port=int(values["POSTGRES_PORT"]), dbname="relay_m0",
    user="relay_m0", password=values["POSTGRES_PASSWORD"], autocommit=True,
) as connection:
    database = connection.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'relay'").fetchone()
    if not database:
        connection.execute("CREATE DATABASE relay OWNER relay_m0")
    elif database[0] != "relay_m0":
        raise RuntimeError("Existing relay database has an unexpected owner; refusing setup")
    exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = 'relay_runtime'").fetchone()
    if not exists:
        connection.execute("CREATE ROLE relay_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
    privileges = connection.execute("SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname = 'relay_runtime'").fetchone()
    if privileges[0]:
        raise RuntimeError("Existing runtime identity has administrative privileges; refusing setup")
    memberships = connection.execute("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='relay_runtime'").fetchone()[0]
    if memberships:
        raise RuntimeError("Existing runtime identity has role memberships; refusing setup")
    # No password is interpolated into a shell command, error message or output.
    connection.execute(sql.SQL("ALTER ROLE relay_runtime WITH PASSWORD {}").format(sql.Literal(password)))
    connection.execute("GRANT CONNECT ON DATABASE relay TO relay_runtime")
print("Separate relay database and relay_runtime identity configured; password stays in ignored .env.")
