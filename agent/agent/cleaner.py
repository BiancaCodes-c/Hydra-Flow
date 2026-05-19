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

    def _write_progress(self, file_path: str, payload: Dict[str, Any]) -> None:
        try:
            progress_dir = Path('state/progress')
            progress_dir.mkdir(parents=True, exist_ok=True)
            progress_file = progress_dir / f"{Path(file_path).stem}.json"
            existing = {}
            if progress_file.exists():
                try:
                    existing = json.loads(progress_file.read_text(encoding='utf-8'))
                except Exception:
                    existing = {}
            now = datetime.now(timezone.utc).isoformat()
            merged = {**existing, **payload}
            merged["started_at"] = merged.get("started_at") or now
            merged["updated_at"] = now
            if merged.get("status") == "done":
                merged["finished_at"] = now
            progress_file.write_text(json.dumps(merged))
        except Exception:
            pass

    def _read_progress_started_at(self, file_path: str) -> str | None:
        try:
            progress_file = Path('state/progress') / f"{Path(file_path).stem}.json"
            if not progress_file.exists():
                return None
            data = json.loads(progress_file.read_text(encoding='utf-8'))
            return data.get('started_at')
        except Exception:
            return None

    def _read_progress_duration_ms(self, file_path: str) -> int | None:
        try:
            progress_file = Path('state/progress') / f"{Path(file_path).stem}.json"
            if not progress_file.exists():
                return None
            data = json.loads(progress_file.read_text(encoding='utf-8'))
            started_at = data.get('started_at')
            finished_at = data.get('finished_at') or datetime.now(timezone.utc).isoformat()
            if not started_at:
                return None
            started = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            ended = datetime.fromisoformat(finished_at.replace('Z', '+00:00'))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
            return int((ended - started).total_seconds() * 1000)
        except Exception:
            return None

    def _infer_column_roles(self, profile: Dict[str, Any]) -> Dict[str, list]:
        date_cols, time_cols, tag_cols, id_cols = [], [], [], []
        for col in profile.get("columns", []):
            name = col["name"].lower()
            if "date" in name or "day" in name or "created" in name or "updated" in name:
                date_cols.append(col["name"])
            if "time" in name or "hour" in name or "timestamp" in name:
                time_cols.append(col["name"])
            if "tag" in name or "tags" in name or "category" in name or "label" in name:
                tag_cols.append(col["name"])
            if name.endswith("id") or name == "id" or name.endswith("_id"):
                id_cols.append(col["name"])
        return {"date_cols": date_cols, "time_cols": time_cols, "tag_cols": tag_cols, "id_cols": id_cols}

    def _build_plan(self, profile: Dict[str, Any], user_intent: str) -> Dict[str, Any]:
        roles = self._infer_column_roles(profile)
        actions = [
            "scan the file and profile each column",
            "strip whitespace from text fields",
            "coerce numeric fields where possible",
        ]
        if roles["date_cols"]:
            actions.append(f"parse date columns: {', '.join(roles['date_cols'])}")
            actions.append("sort rows by date so the data is organized chronologically")
        if roles["time_cols"]:
            actions.append(f"parse time columns: {', '.join(roles['time_cols'])}")
            actions.append("use time columns to keep event order consistent")
        if roles["tag_cols"]:
            actions.append(f"normalize tag columns: {', '.join(roles['tag_cols'])}")
            actions.append("split comma-separated tags into individual tags when present")
        if roles["id_cols"]:
            actions.append(f"dedupe by ids when present: {', '.join(roles['id_cols'])}")
        if not roles["date_cols"] and not roles["time_cols"] and not roles["tag_cols"]:
            actions.append("no obvious date/time/tag columns found, so keep the raw structure and clean obvious formatting issues")
        explain = "This run profiles the file, detects date/time/tag columns, cleans text and numeric values, sorts chronologically when possible, and writes the cleaned result plus run history."
        return {"roles": roles, "actions": actions, "explain": explain, "goal": user_intent}

    async def analyze(self, file_path: str, user_intent: str = "") -> Dict[str, Any]:
        """Profile data and suggest cleaning strategy"""
        profile = profile_file(file_path)
        client = _openai_client_or_none()
        plan = self._build_plan(profile, user_intent)
        self._write_progress(file_path, {"status": "analyzing", "file": str(file_path), "goal": user_intent, "stage": "profile", **plan})
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
            res = {"issues": issues, "primary_key": pk, "strategy": "Heuristic: strip strings, coerce types, drop empty cols, dedupe if pk.", "goal": user_intent, **plan}
            self._write_progress(file_path, {"status":"ready","analysis":res, "goal": user_intent, "stage": "profile", **plan})
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
        result["goal"] = user_intent
        result.update(plan)
        self._write_progress(file_path, {"status":"ready","analysis":result, "goal": user_intent, "stage": "profile", **plan})
        return result

    async def generate_code(self, file_path: str, issues: Dict, user_intent: str = "") -> str:
        """Generate cleaning code based on issues + user intent"""
        profile = profile_file(file_path)
        plan = self._build_plan(profile, user_intent)
        client = _openai_client_or_none()
        # indicate generation started
        self._write_progress(file_path, {"status":"generating_code", "goal": user_intent, "stage": "generate", **plan})
        if client is None:
            # simple deterministic cleaner
            date_cols = plan["roles"]["date_cols"]
            time_cols = plan["roles"]["time_cols"]
            tag_cols = plan["roles"]["tag_cols"]
            sort_cols = date_cols + time_cols
            tag_col = tag_cols[0] if tag_cols else None
            # build a stricter fallback cleaner without broad try/except blocks
            code_lines = [
                "def clean(df: pl.DataFrame) -> pl.DataFrame:",
                "    # deterministic fallback cleaner: explicit transforms, no broad try/except",
                "    # 1) strip whitespace from all string columns",
                "                # strip Utf8 columns by iterating schema at runtime",
                "    for c in df.columns:",
                "        if df.schema.get(c) == pl.Utf8 or str(df.schema.get(c)).lower().startswith('utf8'):",
                "            df = df.with_columns(pl.col(c).str.strip().alias(c))",
                "    # 2) coerce numeric-looking string columns to Float64 (non-numeric become null)",
                "    for c in df.columns:",
                "        if df.schema.get(c) == pl.Utf8 or str(df.schema.get(c)).lower().startswith('utf8'):",
                "            cleaned = pl.col(c).str.replace_all(r'[^0-9\\.-]', '')",
                "            df = df.with_columns(cleaned.cast(pl.Float64).alias(c))",
            ]

            # parse date/time columns explicitly
            for col in date_cols:
                code_lines.append(f"    df = df.with_columns(pl.col('{col}').cast(pl.Utf8).str.strptime(pl.Date, strict=False).alias('{col}'))")
            for col in time_cols:
                code_lines.append(f"    df = df.with_columns(pl.col('{col}').cast(pl.Utf8).str.strptime(pl.Datetime, strict=False).alias('{col}'))")

            # normalize tag columns and produce list versions
            for col in tag_cols:
                code_lines.append(f"    df = df.with_columns(pl.col('{col}').cast(pl.Utf8).str.to_lowercase().alias('{col}'))")
                code_lines.append(f"    df = df.with_columns(pl.col('{col}').str.split(',').alias('{col}_list'))")

            # drop completely empty rows/columns and sort/dedupe
            code_lines.append("    df = df.drop_nulls(how='all')")
            if sort_cols:
                sort_list = ", ".join([f"'{c}'" for c in sort_cols])
                code_lines.append(f"    df = df.sort([{sort_list}])")
            if plan["roles"]["id_cols"]:
                ids = plan["roles"]["id_cols"]
                if len(ids) == 1:
                    code_lines.append(f"    df = df.unique(subset=['{ids[0]}'])")
                else:
                    cols_list = ", ".join([f"'{c}'" for c in ids])
                    code_lines.append(f"    df = df.unique(subset=[{cols_list}])")

            code_lines.append("    return df")
            code = "\n".join(code_lines) + "\n"
            self._write_progress(file_path, {"status":"generated_fallback", "goal": user_intent, "stage": "generate", **plan})
            return code

        prompt = f"""
        File: {file_path}
        User intent: {user_intent or "Make this analysis-ready"}
        Detected issues: {json.dumps(issues)}
        Profile: {json.dumps(profile)}
        Plan: {json.dumps(plan)}

        Write the clean() function. Handle ALL detected issues.
        If date columns exist, parse them and sort by them.
        If time columns exist, parse them as datetimes and keep event order.
        If tag columns exist, normalize them, and if comma-separated, split them into individual tags.
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
        analysis = await self.analyze(file_path, user_intent)
        print(f"[yellow]Issues found: {', '.join(analysis.get('issues', []))}[/yellow]")

        code = await self.generate_code(file_path, analysis, user_intent)

        # update progress: code generated
        self._write_progress(file_path, {"status":"running", "stage": "sandbox", "goal": user_intent, **self._build_plan(profile_file(file_path), user_intent)})

        for attempt in range(self.max_retries):
            test = run_sandbox(code, file_path)
            if test.get("success"):
                print(f"[green]✓ Clean successful: {test['rows']} rows, {len(test['cols'])} cols[/green]")
                # write progress success
                self._write_progress(file_path, {"status":"sandbox_ok","rows_in": test.get('rows'), "cols": test.get('cols'), "goal": user_intent, "stage": "apply"})
                df = pl.read_csv(file_path) if file_path.endswith('.csv') else pl.read_parquet(file_path)
                local_ns = {"pl": pl, "df": df}
                exec(code, local_ns)
                clean_df = local_ns["clean"](df)

                if save_to:
                    Path(save_to).parent.mkdir(parents=True, exist_ok=True)
                    Path(f"{save_to}.py").write_text(f"import polars as pl\n\n{code}\n")
                    clean_df.write_parquet(f"{save_to}.parquet")
                    print(f"[green]✓ Saved code to {save_to}.py, data to {save_to}.parquet[/green]")
                    stem = Path(file_path).stem
                    self._write_progress(file_path, {"status":"done","rows_in": len(df), "rows_out": len(clean_df), "goal": user_intent, "stage": "done", "finished_at": datetime.now(timezone.utc).isoformat()})
                    try:
                        history_dir = Path('state/history')
                        history_dir.mkdir(parents=True, exist_ok=True)
                        history_entry = {
                            "file": Path(file_path).name,
                            "job": stem,
                            "goal": user_intent,
                            "rows_in": len(df),
                            "rows_out": len(clean_df),
                            "output": f"{save_to}.parquet",
                            "status": "done",
                            "started_at": self._read_progress_started_at(file_path),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "duration_ms": self._read_progress_duration_ms(file_path),
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
