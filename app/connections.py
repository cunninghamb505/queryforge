"""Builds SQLAlchemy engines for user-supplied connection URLs and runs queries against them."""

import time

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DEFAULT_MSSQL_DRIVER = "ODBC Driver 18 for SQL Server"


def normalize_url(db_type: str, raw_url: str) -> str:
    """Fixes up common URL quirks so SQLAlchemy/drivers accept them."""
    url = raw_url.strip()

    # Heroku/legacy-style "postgres://" isn't accepted by SQLAlchemy's psycopg2 dialect.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif db_type == "PostgreSQL" and url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]

    if db_type == "SQL Server" and "driver=" not in url.lower():
        driver_param = f"driver={DEFAULT_MSSQL_DRIVER.replace(' ', '+')}"
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{driver_param}"
        # Local/dev SQL Server instances commonly use self-signed certs.
        if "trustservercertificate=" not in url.lower():
            url = f"{url}&TrustServerCertificate=yes"

    return url


def build_engine(db_type: str, raw_url: str) -> Engine:
    url = normalize_url(db_type, raw_url)
    return create_engine(url, pool_pre_ping=True)


def test_connection(db_type: str, raw_url: str) -> tuple[bool, str]:
    try:
        engine = build_engine(db_type, raw_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True, "Connection succeeded."
    except Exception as exc:  # noqa: BLE001 - surfacing the raw driver error is the point here
        return False, str(exc)


def run_query(db_type: str, raw_url: str, sql: str) -> dict:
    """Executes sql and returns a dict describing the outcome.

    Shape: {"kind": "rows", "dataframe": pd.DataFrame, "elapsed_ms": float} for statements that
    return rows, or {"kind": "rowcount", "rowcount": int, "elapsed_ms": float} for statements that
    don't (INSERT/UPDATE/DDL/etc). elapsed_ms is wall-clock time to execute and fetch.
    """
    engine = build_engine(db_type, raw_url)
    try:
        with engine.connect() as conn:
            started = time.perf_counter()
            result = conn.execute(text(sql))
            if result.returns_rows:
                rows = result.fetchall()
                df = pd.DataFrame(rows, columns=list(result.keys()))
                elapsed_ms = (time.perf_counter() - started) * 1000
                return {"kind": "rows", "dataframe": df, "elapsed_ms": elapsed_ms}
            conn.commit()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return {"kind": "rowcount", "rowcount": result.rowcount, "elapsed_ms": elapsed_ms}
    finally:
        engine.dispose()
