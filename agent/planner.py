"""Planner: converts a high-level goal into DAG steps (placeholder)."""

def plan(goal: str):
    """Return a list of pipeline steps derived from goal."""
    # very naive example
    if "revenue" in goal.lower():
        return ["extract:orders", "transform:stg_orders", "transform:fct_revenue"]
    return []
