from typing import Callable, List, Any
import inspect

class Task:
    def __init__(self, name: str, func: Callable, deps: List[str] = None, config: dict = None):
        self.name = name
        self.func = func
        self.deps = deps or []
        self.config = config or {}
        self.is_async = inspect.iscoroutinefunction(func)

def task(_func=None, *, deps: List[str] = None):
    def decorator(func: Callable) -> Task:
        return Task(func.__name__, func, deps or [])
    if _func is None:
        return decorator
    else:
        return decorator(_func)
