"""Canonical report pipeline service shared by CLI and UIs.

``src.main.run`` remains the public compatibility wrapper for existing scripts,
but the default orchestration path now flows through ``ReportPipeline``.  The
pipeline keeps UI callers on a typed artifact object while preserving the
historical dictionary payload for CLI-adjacent code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any


@dataclass
class ReportArtifacts:
    recommendation: dict[str, Any]
    usage: dict[str, Any]
    report_path: Path | None
    csv_path: Path | None
    log_path: Path | None
    session_type: str
    model_name: str | None = None
    quality_warnings: list[dict[str, Any]] | None = None
    source_degradation: list[dict[str, Any]] | None = None
    data_confidence: dict[str, Any] | None = None
    timings: dict[str, Any] | None = None
    errors: list[dict[str, Any]] | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> ReportArtifacts:
        payload = payload or {}
        recommendation = payload.get("recommendation") or {}
        enriched = recommendation.get("enriched") or {}
        report_path = _optional_path(payload.get("report_path"))
        csv_path = _optional_path(payload.get("csv_path"))
        log_path = _optional_path(payload.get("log_path"))
        return cls(
            recommendation=recommendation,
            usage=payload.get("usage") or recommendation.get("usage") or {},
            report_path=report_path,
            csv_path=csv_path,
            log_path=log_path,
            session_type=payload.get("session_type") or "",
            model_name=payload.get("model_name"),
            quality_warnings=payload.get("quality_warnings") or recommendation.get("quality_warnings") or [],
            source_degradation=payload.get("source_degradation")
            or enriched.get("degradation")
            or recommendation.get("source_degradation")
            or [],
            data_confidence=payload.get("data_confidence") or recommendation.get("data_confidence") or {},
            timings=payload.get("timings") or {},
            errors=payload.get("errors") or [],
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return the legacy dictionary shape expected by older callers."""
        return {
            "recommendation": self.recommendation,
            "usage": self.usage,
            "report_path": self.report_path,
            "csv_path": self.csv_path,
            "log_path": self.log_path,
            "session_type": self.session_type,
            "model_name": self.model_name,
            "quality_warnings": self.quality_warnings or [],
            "source_degradation": self.source_degradation or [],
            "data_confidence": self.data_confidence or {},
            "timings": self.timings or {},
            "errors": self.errors or [],
        }


class ReportPipeline:
    """Run a report and return structured artifacts."""

    def __init__(self, runner: Callable[..., dict[str, Any] | None] | None = None) -> None:
        self.runner = runner

    def run(self, **kwargs: Any) -> ReportArtifacts:
        runner = self.runner
        if runner is None:
            from src.main import _run_impl

            runner = _run_impl

        started = perf_counter()
        payload = runner(**kwargs)
        artifacts = payload if isinstance(payload, ReportArtifacts) else ReportArtifacts.from_mapping(payload)
        timings = dict(artifacts.timings or {})
        timings.setdefault("elapsed_seconds", round(perf_counter() - started, 3))
        artifacts.timings = timings
        return artifacts


def _optional_path(value: Any) -> Path | None:
    if value is None or isinstance(value, Path):
        return value
    return Path(value)
