"""Database engine and session factory.

SQLite by default. Point DATABASE_URL at SQL Server / Azure SQL
(e.g. mssql+pyodbc://...) and the same models and queries run unchanged:
nothing here relies on dialect-specific features.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    if not database_url.startswith("sqlite"):
        return create_engine(database_url)

    engine = create_engine(database_url, connect_args={"check_same_thread": False})

    # SQLite ignores foreign keys unless asked. Enforce them so local runs
    # fail the same way SQL Server would.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _record) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    from app import models  # noqa: F401  (registers tables on Base.metadata)

    Base.metadata.create_all(engine)
