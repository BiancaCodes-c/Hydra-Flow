"""Shared source foundations for extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class SourceError(Exception):
    """Base exception for source failures."""


class SourceValidationError(SourceError):
    """Raised when source configuration or input is invalid."""


class SourceConnectionError(SourceError):
    """Raised when a source cannot connect to its backend."""


@dataclass(slots=True)
class SourceContext:
    """Optional runtime state shared by source implementations."""

    name: str | None = None
    connection: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceBase(ABC):
    """Base class for all source implementations."""

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__.lower()

    def validate(self) -> None:
        """Validate configuration before extraction."""

    def connect(self) -> Any | None:
        """Open any external resources needed by the source."""

    def close(self) -> None:
        """Release any resources held by the source."""

    @abstractmethod
    def extract(self, *args: Any, **kwargs: Any) -> Any:
        """Extract data from the source."""

    def __enter__(self) -> SourceBase:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False
