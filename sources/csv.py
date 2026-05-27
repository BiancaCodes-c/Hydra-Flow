"""CSV extractor for local or remote CSV files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import SourceBase, SourceValidationError


def _polars() -> Any:
    import importlib

    try:
        return importlib.import_module("polars")
    except ModuleNotFoundError as exc:
        raise SourceValidationError("CSV source requires the 'polars' package.") from exc


class CsvSource(SourceBase):
    """Read CSV data into a Polars DataFrame."""

    def __init__(self, path: str, name: str | None = None, **read_options: Any) -> None:
        super().__init__(name=name)
        self.path = path
        self.read_options = read_options

    def validate(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise SourceValidationError("CSV source requires a non-empty path.")

        if "://" in self.path:
            return

        if not Path(self.path).exists():
            raise SourceValidationError(f"CSV path does not exist: {self.path}")

    def extract(self, path: str | None = None, **overrides: Any) -> Any:
        source_path = path or self.path
        if not isinstance(source_path, str) or not source_path.strip():
            raise SourceValidationError("CSV source requires a non-empty path.")

        if "://" not in source_path and not Path(source_path).exists():
            raise SourceValidationError(f"CSV path does not exist: {source_path}")

        read_options = {**self.read_options, **overrides}
        return _polars().read_csv(source_path, **read_options)


def extract(path: str, **read_options: Any) -> Any:
    """Backward-compatible convenience wrapper."""

    return CsvSource(path, **read_options).extract()
