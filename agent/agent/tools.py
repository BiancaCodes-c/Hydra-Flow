"""Tools available to the agent: profiling and sandbox runner.

This module contains lightweight helpers used by the agent. In production,
profiling and sandboxing should be hardened and permission-restricted.
"""

import polars as pl, duckdb
from pathlib import Path
import json


def _read_df(path: str, nrows: int | None = None):
    p = Path(path)
    s = p.suffix.lower()
    if s == ".csv":
        try:
            return pl.read_csv(path, n_rows=nrows) if nrows else pl.read_csv(path)
        except Exception:
            # fallback to Python csv.DictReader for irregular CSVs
            import csv
            records = []
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    # Remove ragged extra fields keyed by None and trim values
                    if None in r:
                        del r[None]
                    clean = { (k.strip() if isinstance(k, str) else k): (v.strip() if isinstance(v, str) else v) for k,v in r.items() }
                    records.append(clean)
            return pl.DataFrame(records)
    if s in (".parquet", ".parq"):
        return pl.read_parquet(path)
    if s in (".jsonl", ".ndjson"):
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return pl.DataFrame(records)
    if s == ".json":
        # try polars reader first, fall back to json.loads
        try:
            return pl.read_json(path)
        except Exception:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # data can be a list of objects or a single object
            if isinstance(data, list):
                return pl.DataFrame(data)
            else:
                return pl.DataFrame([data])
    # fallback: try CSV then parquet
    try:
        return pl.read_csv(path)
    except Exception:
        return pl.read_parquet(path)


def profile_file(path: str) -> dict:
    df = _read_df(path, nrows=20000)
    total = len(df)
    return {
        "path": str(path),
        "rows": total,
        "columns": [
            {
                "name": c,
                "dtype": str(df[c].dtype),
                "null_pct": round(df[c].null_count() / total if total else 0, 3),
                "sample": df[c].drop_nulls().head(3).to_list(),
            }
            for c in df.columns
        ],
    }


def run_sandbox(code: str, df_path: str) -> dict:
    try:
        ns = {"pl": pl, "df": _read_df(df_path)}
        exec(code, {}, ns)
        if "clean" not in ns:
            return {"error": "Must define def clean(df)"}
        out = ns["clean"](ns["df"])
        # ensure out is a polars DataFrame-like
        if hasattr(out, "to_dicts"):
            sample = out.head(2).to_dicts()
        else:
            sample = None
        return {"success": True, "rows": len(out), "cols": list(out.columns), "sample": sample}
    except Exception as e:
        return {"error": str(e)}
