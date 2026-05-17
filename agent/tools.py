"""Tools available to the agent: read_csv, profile_df, write_task (stubs)."""

def read_csv(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def profile_df(df):
    return {"rows": len(df)}

def write_task(path: str, source: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    return path
