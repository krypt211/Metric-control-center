"""Database configuration shared by backend, migrations and sync workers."""

import os
from pathlib import Path

from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


def database_url() -> str | URL:
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit
    password_file = os.environ.get("POSTGRES_PASSWORD_FILE")
    if not password_file:
        raise RuntimeError("Configure DATABASE_URL or POSTGRES_PASSWORD_FILE")
    password = Path(password_file).read_text(encoding="utf-8-sig").strip()
    if not password:
        raise RuntimeError("Database password is empty")
    return URL.create(
        "postgresql+psycopg", username=os.environ.get("POSTGRES_USER", "metric_control"),
        password=password, host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "metric_control"),
    )


def make_engine(url: str | URL | None = None) -> Engine:
    engine = create_engine(url if url is not None else database_url(), pool_pre_ping=True, hide_parameters=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def sessions(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
