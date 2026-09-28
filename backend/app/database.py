from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # Additive migration: preserve existing projects and predictions.
    columns = {item["name"] for item in inspect(engine).get_columns("communities")}
    with engine.begin() as connection:
        if "population_records" not in columns:
            connection.execute(text("ALTER TABLE communities ADD COLUMN population_records JSON NOT NULL DEFAULT '[]'"))
        if "population_base_year" not in columns:
            connection.execute(text("ALTER TABLE communities ADD COLUMN population_base_year INTEGER"))
        if "migration_rate_unit" not in columns:
            connection.execute(text("ALTER TABLE communities ADD COLUMN migration_rate_unit VARCHAR(12) NOT NULL DEFAULT '%'"))
    from .services.rate_units import migrate_community_rate_units
    with SessionLocal() as session:
        migrate_community_rate_units(session)
