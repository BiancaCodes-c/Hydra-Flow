
"""Core kernel for dataforge.

Expose common types at package level for convenience.
"""

from .dag import Platform, task
from .store import Store

__all__ = ["dag", "contract", "context", "store", "task", "checks", "cli", "Platform", "Store"]
