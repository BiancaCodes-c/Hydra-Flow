import yaml, importlib.util, asyncio, polars as pl, json
from pathlib import Path
from .dag import Platform
from .task import task

def load_python_task(name: str, file_path: str, deps: list):
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    @task(deps=deps)
    def wrapper(ctx):
        return mod.clean(ctx[deps[0]]) # assumes first dep is df
    wrapper.__name__ = name
    return wrapper

def load_pipeline_yaml(path: str) -> Platform:
    cfg = yaml.safe_load(Path(path).read_text())
    p = Platform()

    for t in cfg["tasks"]:
        if t["type"] == "csv":
            @task()
            def extract(ctx, path=t["path"]): return pl.read_csv(path)
            extract.__name__ = t["name"]
            p.register(extract)
        elif t["type"] == "json":
            @task()
            def extract_json(ctx, path=t["path"]):
                pth = Path(path)
                s = pth.suffix.lower()
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
                    try:
                        return pl.read_json(path)
                    except Exception:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, list):
                            return pl.DataFrame(data)
                        else:
                            return pl.DataFrame([data])
                # fallback
                return pl.read_csv(path)
            extract_json.__name__ = t["name"]
            p.register(extract_json)
        elif t["type"] == "python":
            p.register(load_python_task(t["name"], t["file"], t.get("deps", [])))
        elif t["type"] == "duckdb":
            @task(deps=t.get("deps"))
            def load(ctx, table=t["table"]):
                df = ctx[t["deps"][0]]
                ctx["_store"].con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM df")
                return df
            load.__name__ = t["name"]
            p.register(load)
    return p, [t["name"] for t in cfg["tasks"]]
