import typer, asyncio, os
from pathlib import Path
from dotenv import load_dotenv
from .loader import load_pipeline_yaml
from agent.planner import build_from_file
from rich import print

load_dotenv()
app = typer.Typer()

@app.command()
def init():
    for d in ["state","transforms/agent","pipelines/agent_generated","data/raw"]:
        Path(d).mkdir(parents=True, exist_ok=True)
    Path(".env").write_text("OPENAI_API_KEY=sk-...\n") if not Path(".env").exists() else None
    print("[green]✓ dataforge ready[/green]")

@app.command()
def agent(file: str, goal: str, table: str = "agent_output"):
    async def _run():
        print(f"[cyan]Agent building pipeline for {file}[/cyan]")
        yml = await build_from_file(file, goal, table)
        print(f"[green]✓ Generated {yml}[/green]")
    asyncio.run(_run())

@app.command()
def run(pipeline: str):
    platform, tasks = load_pipeline_yaml(pipeline)
    asyncio.run(platform.run(tasks))

@app.command()
def runs():
    import duckdb
    con = duckdb.connect("state/dataforge.duckdb")
    print(con.execute("SELECT run_id,task,status,duration_ms,row_count FROM runs ORDER BY started_at DESC LIMIT 20").pl())

@app.command()
def clean(file: str, goal: str = "make analysis-ready", output: str = None):
    """Run cleaning agent on a file"""
    from agent.cleaner import CleaningAgent
    import asyncio
    from pathlib import Path

    async def _run():
        agent = CleaningAgent()
        df, code = await agent.clean(file, goal, save_to=output or f"data/processed/{Path(file).stem}_clean")
        print(df.head())
        print(f"\n[dim]Rows: {len(df)} | Nulls: {df.null_count().sum_horizontal()[0]}[/dim]")

    asyncio.run(_run())

if __name__ == "__main__": app()
"""CLI entrypoints (placeholder)."""

def run():
    print("dataforge run (not implemented)")
