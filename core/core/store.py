import duckdb, json
from datetime import datetime
from pathlib import Path
from typing import Any

class Store:
    def __init__(self, db_path: str = "state/dataforge.duckdb"):
        Path(db_path).parent.mkdir(exist_ok=True)
        self.con = duckdb.connect(db_path)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT, task TEXT, status TEXT,
                started_at TIMESTAMP, duration_ms INT,
                row_count INT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS lineage (
                run_id TEXT, task TEXT, inputs JSON, outputs JSON
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                run_id TEXT, task TEXT, path TEXT, type TEXT
            );
        """)

    def log_run(self, run_id: str, task: str, status: str, start: datetime,
                rows: int = 0, error: str = None):
        duration = int((datetime.now() - start).total_seconds() * 1000)
        self.con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
            [run_id, task, status, start, duration, rows, error])

    def log_artifact(self, run_id: str, task: str, path: str, type: str):
        self.con.execute("INSERT INTO artifacts VALUES (?,?,?,?)",
            [run_id, task, path, type])
