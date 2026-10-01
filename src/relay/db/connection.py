"""Explicit PostgreSQL engine/session construction; never creates schema."""

from collections.abc import Mapping

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def database_url(settings: Mapping[str, str], *, migration: bool = False) -> URL:
    """Runtime is the default; missing runtime credentials never fall back to admin."""
    password_key = "POSTGRES_PASSWORD" if migration else "POSTGRES_RUNTIME_PASSWORD"
    password = settings.get(password_key)
    if not password or password.startswith("REPLACE_"):
        raise ValueError(f"Missing local database configuration: {password_key}")
    return URL.create(
        "postgresql+psycopg",
        username="relay_m0" if migration else "relay_runtime",
        password=password,
        host="127.0.0.1",
        port=int(settings.get("POSTGRES_PORT", "54328")),
        database=settings.get("POSTGRES_DATABASE", "relay"),
    )


def make_engine(url: URL) -> Engine:
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Relay requires PostgreSQL through psycopg 3")
    return create_engine(
        url,
        isolation_level="READ COMMITTED",
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c synchronous_commit=on -c lock_timeout=2000 "
            "-c statement_timeout=5000 -c idle_in_transaction_session_timeout=5000 "
            "-c timezone=UTC",
        },
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Callers explicitly open `with factory.begin() as session:` transactions.

    Commit follows successful scope exit; exceptions roll back. No helper locks,
    flushes, publishes or silently commits an operation on the caller's behalf.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)
