"""Executor: runs generated code safely in a sandbox (placeholder).

This module should be implemented with strict sandboxing in production.
"""

def execute_source(source: str, globals_dict=None):
    """Execute source in a restricted globals dict (very minimal stub)."""
    safe_globals = {"__builtins__": {}}
    if globals_dict:
        safe_globals.update(globals_dict)
    exec(source, safe_globals)
    return safe_globals
