"""Postgres source implementation.

This module provides a lightweight wrapper that executes a SQL query
against a provided DB-API connection or a connection string (if a
driver is installed). It returns a Polars DataFrame.
"""

from __future__ import annotations

from typing import Any
import importlib

from .base import SourceBase, SourceValidationError


def _polars() -> Any:
    try:
        return importlib.import_module("polars")
    except ModuleNotFoundError as exc:
        raise SourceValidationError("Postgres source requires the 'polars' package.") from exc


class PostgresSource(SourceBase):
    """Execute a SQL query and return a Polars DataFrame.

    - `query` : SQL string to execute
    - `conn` : DB-API connection object or DSN string (DSN requires a DB driver)
    """

    def __init__(self, query: str, conn: Any = None, name: str | None = None, params: dict | None = None) -> None:
        super().__init__(name=name)
        self.query = query
        self.conn = conn
        self.params = params or {}
        self._owns_connection = False

    def validate(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise SourceValidationError("Postgres source requires a non-empty SQL query.")

    def connect(self) -> Any | None:
        if isinstance(self.conn, str):
            # Try to create a connection from a DSN string if a driver is present.
            for driver in ("psycopg", "psycopg2", "pg8000"):
                try:
                    mod = importlib.import_module(driver)
                    conn = mod.connect(self.conn)
                    self.conn = conn
                    self._owns_connection = True
                    return conn
                except ModuleNotFoundError:
                    continue
                except Exception:
                    raise
            raise SourceValidationError("No suitable Postgres driver found for DSN; pass a connection object or install a driver.")

        return self.conn

    def close(self) -> None:
        if getattr(self, "_owns_connection", False) and hasattr(self.conn, "close"):
            try:
                self.conn.close()
            finally:
                self._owns_connection = False

    def extract(self, query: str | None = None, conn: Any | None = None) -> Any:
        q = query or self.query
        if not isinstance(q, str) or not q.strip():
            raise SourceValidationError("Postgres source requires a non-empty SQL query.")

        connection = conn or self.conn
        if connection is None:
            raise SourceValidationError("Postgres source requires a DB-API connection or DSN.")

        # If the user passed a DSN string, ensure a real connection
        if isinstance(connection, str):
            self.conn = connection
            connection = self.connect()

        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(q, self.params)
            cols = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            records = [dict(zip(cols, r)) for r in rows] if cols else [tuple(r) for r in rows]
            return _polars().DataFrame(records)
        finally:
            try:
                if cursor is not None:
                    cursor.close()
            except Exception:
                pass


def extract(query: str, conn: Any):
    """Convenience wrapper preserving previous module-level API."""
    return PostgresSource(query, conn).extract()
