import yaml, asyncio
from pathlib import Path
from .coder import generate_cleaner

async def _maybe_add_aggregator(goal: str, file_path: str, task_name: str, cfg: dict):
    if any(w in goal.lower() for w in ['sum','avg','daily','group','total']):
        from .coder import generate_aggregator
        agg_code = await generate_aggregator(
            file_path, goal,
            group_by=['date'],
            metrics=[('sum','amount','revenue'), ('count','order_id','orders')]
        )
        agg_task_name = f"{task_name}_agg"
        Path("transforms/agent").mkdir(parents=True, exist_ok=True)
        py_agg_path = f"transforms/agent/{agg_task_name}.py"
        Path(py_agg_path).write_text(f"import polars as pl\n\n{agg_code}\n")

        # insert agg task between clean and load
        agg_entry = {"name": agg_task_name, "deps": [task_name], "type": "python", "file": py_agg_path}
        # find load index (last item) and insert before it
        insert_idx = len(cfg["tasks"]) - 1
        cfg["tasks"].insert(insert_idx, agg_entry)
        # update load deps to depend on agg task
        if cfg["tasks"][-1].get("type") == "duckdb":
            cfg["tasks"][-1]["deps"] = [agg_task_name]

async def build_from_file(file_path: str, goal: str, table: str):
    task_name = Path(file_path).stem + "_clean"
    code, test = await generate_cleaner(file_path, goal)
    if test.get("error"): raise RuntimeError(test["error"])

    Path("transforms/agent").mkdir(parents=True, exist_ok=True)
    py_path = f"transforms/agent/{task_name}.py"
    Path(py_path).write_text(f"import polars as pl\n\n{code}\n")

    Path("pipelines/agent_generated").mkdir(parents=True, exist_ok=True)
    yml_path = f"pipelines/agent_generated/{task_name}.yml"
    cfg = {
        "name": task_name,
        "tasks": [
            {"name": "extract", "type": "csv", "path": file_path},
            {"name": task_name, "deps": ["extract"], "type": "python", "file": py_path},
            {"name": "load", "deps": [task_name], "type": "duckdb", "table": table}
        ]
    }
    await _maybe_add_aggregator(goal, file_path, task_name, cfg)
    Path(yml_path).write_text(yaml.dump(cfg))
    return yml_path
