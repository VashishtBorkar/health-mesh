from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .settings import data_directory


def database_url() -> str:
    override = os.getenv("HEALTHMESH_DATABASE_URL")
    if override:
        return override
    filename = "healthmesh-personal.db" if os.getenv("HEALTHMESH_PROFILE") == "personal" else "healthmesh.db"
    return f"sqlite:///{data_directory() / filename}"


engine = create_engine(database_url(), connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

