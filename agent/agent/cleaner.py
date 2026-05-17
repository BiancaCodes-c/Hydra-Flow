import os, json, polars as pl
from pathlib import Path
from typing import Dict, Any, Tuple
from datetime import datetime, timezone
from .tools import profile_file, run_sandbox
from rich import print


def _openai_client_or_none():
    try:
        from openai import AsyncOpenAI
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return None
        return AsyncOpenAI(api_key=key)
    except Exception:
        return None


SYSTEM = """You are a senior data engineer specializing in data cleaning.
You output ONLY Python code for: def clean(df: pl.DataFrame) -> pl.DataFrame
Rules:
1. Use polars only. No pandas.
2. Handle nulls explicitly: drop, fill, or flag.
3. Cast types: dates to pl.Date, money to Float64, IDs to Utf8.
4. Strip whitespace from strings.
5. Dedupe if a primary key exists.
6. Add data quality columns if useful: _is_valid, _error_reason
7. No try/except. Let it fail if data is truly bad.
8. No print statements. No comments needed."""


class CleaningAgent:
    def __init__(self):
        self.max_retries = 2

    async def analyze(self, file_path: str) -> Dict[str, Any]:
        """Profile data and suggest cleaning strategy"""
        profile = profile_file(file_path)
        client = _openai_client_or_none()
        # initialize progress file
        try:
            prog_stem = Path(file_path).stem
            prog_dir = Path('state/progress')
            prog_dir.mkdir(parents=True, exist_ok=True)
            (prog_dir / f"{prog_stem}.json").write_text(json.dumps({"status": "analyzing", "file": str(file_path)}))
        except Exception:
            pass
        if client is None:
            # heuristic analysis
            issues = []
            pk = None
            for col in profile.get("columns", []):
                if col["null_pct"] > 0.2:
                    issues.append(f"high_nulls:{col['name']}")
                if col["name"].lower().endswith("id"):
                    pk = col["name"]
                if "date" in col["name"].lower():
                    issues.append(f"date_like:{col['name']}")
            if pk:
                issues.append(f"likely_pk:{pk}")
            res = {"issues": issues, "primary_key": pk, "strategy": "Heuristic: strip strings, coerce types, drop empty cols, dedupe if pk."}
            try:
                (Path('state/progress') / f"{Path(file_path).stem}.json").write_text(json.dumps({"status":"ready","analysis":res}))
            except Exception:
                pass
            return res

        prompt = f"""
        Data profile: {json.dumps(profile, indent=2)}

        Return JSON with:
        1. "issues": list of problems you see: nulls, types, dupes, formatting
        2. "primary_key": likely PK column or null
        3. "strategy": 3-sentence plan to clean this
        """
        resp = await client.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            messages=[{"role":"system","content":"You are a data profiler. Return JSON only."},
                      {"role":"user","content":prompt}]
        )
        result = json.loads(resp.choices[0].message.content)
        try:
            (Path('state/progress') / f"{Path(file_path).stem}.json").write_text(json.dumps({"status":"ready","analysis":result}))
        except Exception:
            pass
        return result

    async def generate_code(self, file_path: str, issues: Dict, user_intent: str = "") -> str:
        """Generate cleaning code based on issues + user intent"""
        profile = profile_file(file_path)
        client = _openai_client_or_none()
        # indicate generation started
        try:
            (Path('state/progress') / f"{Path(file_path).stem}.json").write_text(json.dumps({"status":"generating_code"}))
        except Exception:
            pass
        if client is None:
            # simple deterministic cleaner
            code = (
                "def clean(df: pl.DataFrame) -> pl.DataFrame:\n"
                "    # basic fallback cleaner: strip strings, coerce numbers, drop all-empty cols, dedupe\n"
                "    for c in df.columns:\n"
                "        try:\n"
                "            if df[c].dtype == pl.Utf8:\n"
                "                df = df.with_columns(pl.col(c).str.strip().alias(c))\n"
                "        except Exception:\n"
                "            pass\n"
                "    for c in df.columns:\n"
                "        try:\n"
                "            df = df.with_columns(pl.col(c).cast(pl.Float64).alias(c))\n"
                "        except Exception:\n"
                "            pass\n"
                "    df = df.drop_nulls(how='all')\n"
                "    df = df.unique()\n"
                "    return df\n"
            )
            try:
                (Path('state/progress') / f"{Path(file_path).stem}.json").write_text(json.dumps({"status":"generated_fallback", "test": test}))
            except Exception:
                pass
            return code

        prompt = f"""
        File: {file_path}
        User intent: {user_intent or "Make this analysis-ready"}
        Detected issues: {json.dumps(issues)}
        Profile: {json.dumps(profile)}

        Write the clean() function. Handle ALL detected issues.
        """
        resp = await client.chat.completions.create(
            model="gpt-4o-mini", temperature=0.1,
            messages=[{"role":"system","content":SYSTEM},
                      {"role":"user","content":prompt}]
        )
        code = resp.choices[0].message.content
        return code.strip().strip("` python").strip("`")

    async def self_heal(self, code: str, error: str, file_path: str) -> str:
        """Fix code based on runtime error"""
        client = _openai_client_or_none()
        if client is None:
            # cannot self-heal without OpenAI: return original code
            return code

        prompt = f"""
        This code failed: {error}

        Code:
        {code}

        Fix it. Return ONLY the corrected def clean(df) function.
        """
        resp = await client.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            messages=[{"role":"user","content":prompt}]
        )
        return resp.choices[0].message.content.strip("` python").strip("`")

    async def clean(self, file_path: str, user_intent: str = "", save_to: str = None) -> Tuple[pl.DataFrame, str]:
        """
        Main entry: file_path -> cleaned DataFrame + code used
        """
        print(f"[cyan]CleaningAgent: Analyzing {file_path}[/cyan]")
        analysis = await self.analyze(file_path)
        print(f"[yellow]Issues found: {', '.join(analysis.get('issues', []))}[/yellow]")

        code = await self.generate_code(file_path, analysis, user_intent)

        # update progress: code generated
        try:
            (Path('state/progress') / f"{Path(file_path).stem}.json").write_text(json.dumps({"status":"running", "stage": "sandbox"}))
        except Exception:
            pass

        for attempt in range(self.max_retries):
            test = run_sandbox(code, file_path)
            if test.get("success"):
                print(f"[green]✓ Clean successful: {test['rows']} rows, {len(test['cols'])} cols[/green]")
                # write progress success
                try:
                    (Path('state/progress') / f"{Path(file_path).stem}.json").write_text(json.dumps({"status":"sandbox_ok","rows_in": test.get('rows'), "cols": test.get('cols')}))
                except Exception:
                    pass
                df = pl.read_csv(file_path) if file_path.endswith('.csv') else pl.read_parquet(file_path)
                local_ns = {"pl": pl, "df": df}
                exec(code, {}, local_ns)
                clean_df = local_ns["clean"](df)

                if save_to:
                    Path(save_to).parent.mkdir(parents=True, exist_ok=True)
                    Path(f"{save_to}.py").write_text(f"import polars as pl\n\n{code}\n")
                    clean_df.write_parquet(f"{save_to}.parquet")
                    print(f"[green]✓ Saved code to {save_to}.py, data to {save_to}.parquet[/green]")
                    try:
                        stem = Path(file_path).stem
                        progress_dir = Path('state/progress')
                        history_dir = Path('state/history')
                        progress_dir.mkdir(parents=True, exist_ok=True)
                        history_dir.mkdir(parents=True, exist_ok=True)
                        result = {"status":"done","rows_out": len(clean_df)}
                        (progress_dir / f"{stem}.json").write_text(json.dumps(result))
                        history_entry = {
                            "file": Path(file_path).name,
                            "job": stem,
                            "goal": user_intent,
                            "rows_in": len(df),
                            "rows_out": len(clean_df),
                            "output": f"{save_to}.parquet",
                            "status": "done",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                        with open(history_dir / "history.jsonl", "a", encoding="utf-8") as fh:
                            fh.write(json.dumps(history_entry) + "\n")
                    except Exception:
                        pass
                return clean_df, code
            else:
                print(f"[red]Attempt {attempt+1} failed: {test.get('error')}[/red]")
                if attempt < self.max_retries - 1:
                    code = await self.self_heal(code, test.get('error',''), file_path)

        raise RuntimeError(f"Agent failed to clean {file_path} after {self.max_retries} attempts")
