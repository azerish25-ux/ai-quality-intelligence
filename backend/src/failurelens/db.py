from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

from .config import get_settings


class Base(DeclarativeBase):
    pass


def create_database_engine(url: str | None = None):
    database_url = url or get_settings().database_url
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
    else:
        settings = get_settings()
        kwargs["pool_size"] = settings.database_pool_size
        kwargs["max_overflow"] = settings.database_max_overflow
    return create_engine(database_url, **kwargs)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_authentication_session_factory() -> sessionmaker[Session]:
    """Return storage configuration without opening a credential-free Session."""
    return SessionLocal


def validate_authentication_storage(factory: sessionmaker[Session]) -> None:
    """Require independently checked-out transactions before touching credentials.

    A Session bound to an existing Connection, or an engine with a shared pool,
    could commit another Session's pending business writes. Authentication accepts
    only engine-bound factories on the supported independent-connection stores.
    """
    error = (
        "authentication requires an engine-bound sessionmaker with QueuePool or "
        "NullPool and file-backed SQLite or PostgreSQL storage"
    )
    if not isinstance(factory, sessionmaker):
        raise TypeError(error)
    bind = factory.kw.get("bind")
    if (
        not isinstance(bind, Engine)
        or factory.kw.get("binds")
        or type(bind.pool) not in {QueuePool, NullPool}
    ):
        raise RuntimeError(error)
    if bind.dialect.name == "sqlite":
        database = bind.url.database
        if (
            not database
            or ":memory:" in database
            or database.startswith("file:")
            or "uri" in bind.url.query
            or "mode" in bind.url.query
            or "cache" in bind.url.query
        ):
            raise RuntimeError(error)
    elif bind.dialect.name != "postgresql":
        raise RuntimeError(error)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def initialize_database(bind=None) -> None:
    from . import models

    models.Base.metadata.create_all(bind or engine)
