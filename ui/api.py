from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Form
from fastapi.responses import HTMLResponse
from pathlib import Path
import asyncio, json
from datetime import datetime, timezone

from agent.cleaner import CleaningAgent

app = FastAPI(title="DataForge Upload API")
UI_PATH = Path(__file__).with_name("index.html")

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
Path('state/progress').mkdir(parents=True, exist_ok=True)
Path('state/history').mkdir(parents=True, exist_ok=True)


async def _clean_uploaded_file(file_path: str, goal: str, output_stem: str):
    agent = CleaningAgent()
    await agent.clean(file_path, user_intent=goal, save_to=str(PROCESSED_DIR / output_stem))


def _run_cleaning(file_path: str, goal: str, output_stem: str):
    asyncio.run(_clean_uploaded_file(file_path, goal, output_stem))


@app.get("/", response_class=HTMLResponse)
def home():
        return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    return {"status": "ok"}


def _parse_iso_dt(value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


@app.post("/upload")
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    goal: str = Form("make analysis-ready"),
    output_name: str | None = Form(None),
    convert_to: str | None = Form(None),
):
    dest = RAW_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)

    output_stem = output_name or f"{dest.stem}_clean"
    background_tasks.add_task(_run_cleaning, str(dest), goal, output_stem)

    # optional immediate conversion (csv <-> jsonl <-> parquet)
    converted = None
    if convert_to:
        try:
            import polars as pl, json
            s = dest.suffix.lower()
            if s == ".csv":
                df = pl.read_csv(dest)
            elif s in (".json", ".jsonl", ".ndjson"):
                try:
                    df = pl.read_json(dest)
                except Exception:
                    # fallback ndjson
                    records = []
                    with open(dest, "r", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            records.append(json.loads(line))
                    df = pl.DataFrame(records)
            else:
                df = pl.read_csv(dest)

            if convert_to == "parquet":
                outp = PROCESSED_DIR / f"{output_stem}.parquet"
                df.write_parquet(outp)
                converted = str(outp)
            elif convert_to in ("jsonl", "ndjson"):
                outp = PROCESSED_DIR / f"{output_stem}.jsonl"
                with open(outp, "w", encoding="utf-8") as fh:
                    for r in df.to_dicts():
                        fh.write(json.dumps(r) + "\n")
                converted = str(outp)
            elif convert_to == "csv":
                outp = PROCESSED_DIR / f"{output_stem}.csv"
                df.write_csv(outp)
                converted = str(outp)
        except Exception as e:
            converted = f"conversion_error: {e}"

    return {
        "status": "accepted",
        "filename": file.filename,
        "saved_to": str(dest),
        "goal": goal,
        "output": str(PROCESSED_DIR / output_stem),
        "progress_key": output_stem,
        "converted": converted,
        "processing": "cleaning started in background",
    }


@app.get('/progress')
def progress(file: str):
    p = Path('state/progress') / f"{file}.json"
    if not p.exists():
        return {"status": "waiting"}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {"status": "error", "message": "failed to read progress file"}


@app.get('/jobs')
def jobs():
    jobs = []
    for p in sorted(Path('state/progress').glob('*.json')):
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            data = {"status": "error"}
        started_at = _parse_iso_dt(data.get("started_at"))
        finished_at = _parse_iso_dt(data.get("finished_at"))
        anchor = finished_at or datetime.now(timezone.utc)
        duration_ms = int((anchor - started_at).total_seconds() * 1000) if started_at else None
        jobs.append({
            "name": p.stem,
            "status": data.get("status", "unknown"),
            "rows_in": data.get("rows_in"),
            "rows_out": data.get("rows_out"),
            "stage": data.get("stage"),
            "goal": data.get("goal"),
            "actions": data.get("actions", []),
            "explain": data.get("explain"),
            "roles": data.get("roles", {}),
            "started_at": data.get("started_at"),
            "updated_at": data.get("updated_at"),
            "finished_at": data.get("finished_at"),
            "duration_ms": duration_ms,
        })
    active_jobs = [job for job in jobs if job.get("status") not in {"done", "error"}]
    return {"active_jobs": len(active_jobs), "jobs": active_jobs, "all_jobs": jobs}


@app.get('/history')
def history(limit: int = 20):
    path = Path('state/history/history.jsonl')
    if not path.exists():
        return {"items": []}
    items = []
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
        for line in reversed(lines[-limit:]):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return {"items": [], "error": "failed to read history"}
    return {"items": items}
