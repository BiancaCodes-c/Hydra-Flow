import os, json
from .tools import profile_file, run_sandbox
import polars as pl


def _openai_client_or_none():
    try:
        from openai import AsyncOpenAI
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return None
        return AsyncOpenAI(api_key=key)
    except Exception:
        return None


SYS = """You write data engineering code. Output ONLY Python code for: def clean(df: pl.DataFrame) -> pl.DataFrame
Use polars. No explanations."""


async def generate_cleaner(file_path: str, goal: str) -> tuple[str, dict]:
    profile = profile_file(file_path)
    client = _openai_client_or_none()
    if client is None:
        # Fallback: simple deterministic cleaner
        code = (
            "def clean(df: pl.DataFrame) -> pl.DataFrame:\n"
            "    # Basic fallback cleaner: strip strings, coerce numbers, drop empty cols, dedupe\n"
            "    for c in df.columns:\n"
            "        try:\n"
            "            if df[c].dtype == pl.Utf8:\n"
            "                df = df.with_columns(pl.col(c).str.strip().alias(c))\n"
            "        except Exception:\n"
            "            pass\n"
            "    # try numeric coercion\n"
            "    for c in df.columns:\n"
            "        try:\n"
            "            df = df.with_columns(pl.col(c).cast(pl.Float64).alias(c))\n"
            "        except Exception:\n"
            "            pass\n"
            "    df = df.drop_nulls(how='all')\n"
            "    df = df.unique()\n"
            "    return df\n"
        )
        test = run_sandbox(code, file_path)
        return code, test

    prompt = f"Goal: {goal}\nProfile: {json.dumps(profile)}\nRules: handle nulls, cast dates to Date, numbers to Float64, strip strings, dedupe if ID exists."

    resp = await client.chat.completions.create(
        model="gpt-4o-mini", temperature=0,
        messages=[{"role":"system","content":SYS},{"role":"user","content":prompt}]
    )
    code = resp.choices[0].message.content.strip("` python")
    test = run_sandbox(code, file_path)

    if test.get("error") and client is not None: # one retry
        fix = await client.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            messages=[{"role":"user","content":f"Fix error: {test['error']}\n\n{code}"}]
        )
        code = fix.choices[0].message.content.strip("` python")
        test = run_sandbox(code, file_path)
    return code, test


async def generate_aggregator(file_path: str, goal: str, group_by: list, metrics: list) -> str:
    client = _openai_client_or_none()
    if client is None:
        # simple aggregators using polars
        gb = group_by or []
        ms = metrics or []
        cols = ", ".join([f"pl.col('{m}').sum().alias('{m}_sum')" for m in ms]) or ""
        return (
            "def aggregate(df: pl.DataFrame) -> pl.DataFrame:\n"
            f"    return df.groupby({gb}).agg([{cols}])\n"
        )

    prompt = f"""
    Goal: {goal}
    Group by: {group_by}
    Metrics: {metrics}
    Write: def aggregate(df: pl.DataFrame) -> pl.DataFrame
    Use polars group_by and agg. Return only code.
    """
    resp = await client.chat.completions.create(
        model="gpt-4o-mini", temperature=0,
        messages=[{"role":"system","content":"You write polars aggregations."},
                  {"role":"user","content":prompt}]
    )
    return resp.choices[0].message.content.strip("` python")
