"""Local metadata store: saved connections and favorite queries.

This is a small SQLite database (separate from any user database the app connects to) that
lives at data/app_metadata.db so it persists across container restarts via the mounted volume.
"""

import datetime
import os
from pathlib import Path

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from app.crypto import encrypt_str, decrypt_str

DATA_DIR = Path(os.environ.get("SQL_OPTIMIZER_DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
METADATA_DB_PATH = DATA_DIR / "app_metadata.db"

engine = create_engine(f"sqlite:///{METADATA_DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

DB_TYPES = ["PostgreSQL", "SQLite", "SQL Server"]


class Connection(Base):
    __tablename__ = "connections"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    db_type = Column(String, nullable=False)
    url_encrypted = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    favorite_queries = relationship(
        "FavoriteQuery", back_populates="connection", cascade="all, delete-orphan"
    )

    @property
    def url(self) -> str:
        return decrypt_str(self.url_encrypted)


class FavoriteQuery(Base):
    __tablename__ = "favorite_queries"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sql_text = Column(Text, nullable=False)
    connection_id = Column(Integer, ForeignKey("connections.id"), nullable=True)
    # When true, clicking the favorite's button runs it immediately (one-click quick-run)
    # instead of only loading it into the editor.
    auto_run = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    connection = relationship("Connection", back_populates="favorite_queries")


Base.metadata.create_all(engine)


def _ensure_column(table: str, column: str, ddl: str) -> None:
    """Adds a column to an existing SQLite table if it's missing (lightweight migration)."""
    with engine.connect() as conn:
        existing = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            conn.commit()


# create_all won't add columns to a pre-existing table, so migrate auto_run in explicitly.
_ensure_column("favorite_queries", "auto_run", "auto_run INTEGER NOT NULL DEFAULT 0")


# --- Connections ---------------------------------------------------------

def list_connections():
    with SessionLocal() as session:
        return session.query(Connection).order_by(Connection.name).all()


def get_connection(connection_id: int):
    with SessionLocal() as session:
        return session.get(Connection, connection_id)


def create_connection(name: str, db_type: str, url: str) -> Connection:
    with SessionLocal() as session:
        conn = Connection(name=name, db_type=db_type, url_encrypted=encrypt_str(url))
        session.add(conn)
        session.commit()
        session.refresh(conn)
        return conn


def delete_connection(connection_id: int) -> None:
    with SessionLocal() as session:
        conn = session.get(Connection, connection_id)
        if conn:
            session.delete(conn)
            session.commit()


# --- Favorite queries -----------------------------------------------------

def list_favorite_queries():
    with SessionLocal() as session:
        return (
            session.query(FavoriteQuery)
            .order_by(FavoriteQuery.name)
            .all()
        )


def create_favorite_query(
    name: str,
    sql_text: str,
    connection_id: int | None = None,
    auto_run: bool = False,
) -> FavoriteQuery:
    with SessionLocal() as session:
        fav = FavoriteQuery(
            name=name, sql_text=sql_text, connection_id=connection_id, auto_run=auto_run
        )
        session.add(fav)
        session.commit()
        session.refresh(fav)
        return fav


def delete_favorite_query(favorite_id: int) -> None:
    with SessionLocal() as session:
        fav = session.get(FavoriteQuery, favorite_id)
        if fav:
            session.delete(fav)
            session.commit()
