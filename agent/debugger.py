"""Debugging helpers for pipeline inspection, simulation, and failure analysis."""

from __future__ import annotations

import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def _safe_type_name(value: Any) -> str:
    return type(value).__name__


def _copy_frame(frame: Any) -> Any:
    if hasattr(frame, "copy"):
        try:
            return frame.copy(deep=True)
        except TypeError:
            return frame.copy()
    return frame


def _row_count(frame: Any) -> int:
    if hasattr(frame, "__len__"):
        try:
            return len(frame)
        except Exception:
            return 0
    return 0


def _column_schema(frame: Any) -> Dict[str, str]:
    if hasattr(frame, "dtypes") and hasattr(frame, "columns"):
        try:
            dtypes = frame.dtypes
            if isinstance(dtypes, Mapping):
                return {str(col): str(dtype) for col, dtype in dtypes.items()}
            return {str(col): str(dtype) for col, dtype in zip(frame.columns, dtypes)}
        except Exception:
            pass

    if hasattr(frame, "columns"):
        schema: Dict[str, str] = {}
        for col in frame.columns:
            try:
                series = frame[col]
                dtype = getattr(series, "dtype", None)
                schema[str(col)] = str(dtype) if dtype is not None else _safe_type_name(series)
            except Exception:
                schema[str(col)] = "unknown"
        return schema

    if isinstance(frame, Mapping):
        return {str(key): _safe_type_name(value) for key, value in frame.items()}

    return {}


def _null_ratio(frame: Any) -> float:
    if hasattr(frame, "isna"):
        try:
            nulls = frame.isna().sum().sum()
            size = getattr(frame, "size", 0) or 1
            return float(nulls) / float(size)
        except Exception:
            pass
    if hasattr(frame, "isnull"):
        try:
            nulls = frame.isnull().sum().sum()
            size = getattr(frame, "size", 0) or 1
            return float(nulls) / float(size)
        except Exception:
            pass
    return 0.0


@dataclass
class GhostStepResult:
    step_name: str
    status: str
    runtime_seconds: float
    rows_before: int
    rows_after: int
    schema_before: Dict[str, str]
    schema_after: Dict[str, str]
    warnings: List[str] = field(default_factory=list)
    predicted_failures: List[str] = field(default_factory=list)


@dataclass
class GhostPipelineReport:
    pipeline_name: str
    simulation_mode: bool
    estimated_total_runtime: float
    steps: List[GhostStepResult]
    expected_output_rows: int
    expected_output_schema: Dict[str, str]
    overall_status: str


@dataclass
class RootCauseReport:
    failed_step: str
    probable_root_cause: str
    severity: str
    impacted_downstream_jobs: List[str]
    suggested_fixes: List[str]
    correlated_events: List[str]


class PipelineGhostMode:
    """Run pipeline steps in simulation without mutating the original data."""

    def __init__(self, pipeline_name: str):
        self.pipeline_name = pipeline_name
        self.results: List[GhostStepResult] = []

    def simulate_step(self, step_name: str, func, frame: Any):
        start = time.time()
        warnings: List[str] = []
        predicted_failures: List[str] = []

        rows_before = _row_count(frame)
        schema_before = _column_schema(frame)

        try:
            simulated_frame = _copy_frame(frame)
            output_frame = func(simulated_frame)
            runtime = round(time.time() - start, 4)

            rows_after = _row_count(output_frame)
            schema_after = _column_schema(output_frame)

            removed_cols = set(schema_before) - set(schema_after)
            new_cols = set(schema_after) - set(schema_before)

            if removed_cols:
                warnings.append(f"Columns removed: {sorted(removed_cols)}")
            if new_cols:
                warnings.append(f"New columns introduced: {sorted(new_cols)}")

            if rows_before and (rows_before - rows_after) > (rows_before * 0.5):
                warnings.append("Large row reduction detected")

            if _null_ratio(output_frame) > 0.30:
                warnings.append("High null percentage predicted")

            return output_frame, GhostStepResult(
                step_name=step_name,
                status="success",
                runtime_seconds=runtime,
                rows_before=rows_before,
                rows_after=rows_after,
                schema_before=schema_before,
                schema_after=schema_after,
                warnings=warnings,
                predicted_failures=predicted_failures,
            )
        except Exception as exc:
            runtime = round(time.time() - start, 4)
            predicted_failures.append(str(exc))
            predicted_failures.append(traceback.format_exc(limit=1))

            return frame, GhostStepResult(
                step_name=step_name,
                status="failed",
                runtime_seconds=runtime,
                rows_before=rows_before,
                rows_after=rows_before,
                schema_before=schema_before,
                schema_after=schema_before,
                warnings=warnings,
                predicted_failures=predicted_failures,
            )

    def run_simulation(self, frame: Any, pipeline_steps: Sequence[Any]):
        self.results = []
        current_frame = frame

        for step in pipeline_steps:
            if isinstance(step, (list, tuple)) and len(step) >= 2:
                step_name, func = step[0], step[1]
            else:
                raise ValueError("pipeline_steps must contain (step_name, func) pairs")

            current_frame, result = self.simulate_step(step_name, func, current_frame)
            self.results.append(result)

        estimated_runtime = sum(step.runtime_seconds for step in self.results)
        overall_status = "failed" if any(r.status == "failed" for r in self.results) else "success"

        report = GhostPipelineReport(
            pipeline_name=self.pipeline_name,
            simulation_mode=True,
            estimated_total_runtime=estimated_runtime,
            steps=self.results,
            expected_output_rows=_row_count(current_frame),
            expected_output_schema=_column_schema(current_frame),
            overall_status=overall_status,
        )
        return asdict(report)


class AIRootCauseAnalyzer:
    def __init__(self):
        self.known_patterns = {
            "KeyError": "Missing expected column",
            "ValueError": "Datatype conversion failure",
            "MemoryError": "Pipeline exceeded memory limits",
            "ParserError": "Malformed CSV or ingestion issue",
        }

    def detect_schema_drift(self, expected_schema: Dict[str, str], actual_schema: Dict[str, str]):
        drift: List[str] = []
        expected_cols = set(expected_schema.keys())
        actual_cols = set(actual_schema.keys())

        missing = expected_cols - actual_cols
        new = actual_cols - expected_cols

        if missing:
            drift.append(f"Missing columns: {sorted(missing)}")
        if new:
            drift.append(f"Unexpected columns: {sorted(new)}")

        return drift

    def correlate_events(self, failed_logs: str, ingestion_events: Iterable[str], schema_changes: Sequence[str]):
        correlations: List[str] = []

        if schema_changes:
            correlations.append("Recent schema drift detected upstream")
        if "upload failed" in failed_logs.lower():
            correlations.append("Ingestion instability detected")
        if "memory" in failed_logs.lower():
            correlations.append("High resource usage correlated")
        if ingestion_events:
            event_list = list(ingestion_events)
            if event_list:
                correlations.append(f"Observed {len(event_list)} related ingestion events")

        return correlations

    def analyze_failure(
        self,
        failed_step: str,
        error_message: str,
        expected_schema: Dict[str, str],
        actual_schema: Dict[str, str],
        ingestion_events: List[str],
        downstream_jobs: List[str],
    ):
        probable_root_cause = "Unknown failure"

        for pattern, explanation in self.known_patterns.items():
            if pattern in error_message:
                probable_root_cause = explanation

        schema_drift = self.detect_schema_drift(expected_schema, actual_schema)
        correlations = self.correlate_events(error_message, ingestion_events, schema_drift)

        suggested_fixes: List[str] = []
        if schema_drift:
            suggested_fixes.append("Regenerate cleaning transform")
            suggested_fixes.append("Re-map schema columns")
        if "ValueError" in error_message:
            suggested_fixes.append("Add explicit datatype casting")
        if "MemoryError" in error_message:
            suggested_fixes.append("Enable chunked processing")

        severity = "critical" if downstream_jobs else "medium"

        report = RootCauseReport(
            failed_step=failed_step,
            probable_root_cause=probable_root_cause,
            severity=severity,
            impacted_downstream_jobs=downstream_jobs,
            suggested_fixes=suggested_fixes,
            correlated_events=correlations,
        )
        return asdict(report)


class RuntimeProfiler:
    def profile(self, frame: Any) -> Dict[str, Any]:
        return {
            "rows": _row_count(frame),
            "columns": len(_column_schema(frame)),
        }


class SchemaDriftDetector:
    def compare(self, expected_schema: Dict[str, str], actual_schema: Dict[str, str]) -> Dict[str, List[str]]:
        return {
            "missing": sorted(set(expected_schema) - set(actual_schema)),
            "unexpected": sorted(set(actual_schema) - set(expected_schema)),
        }


class ReplayEngine:
    def replay(self, frame: Any, steps: Sequence[Any]):
        ghost = PipelineGhostMode("replay")
        return ghost.run_simulation(frame, steps)


class SandboxDiagnostics:
    def diagnose(self, error: Exception) -> str:
        return diagnose(error)


def diagnose(error: Exception) -> str:
    return f"Diagnose: {type(error).__name__}: {error}"
