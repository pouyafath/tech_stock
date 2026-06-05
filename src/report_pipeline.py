"""Reusable report pipeline facade shared by CLI-adjacent UIs.

The canonical orchestration still lives in ``src.main.run``.  This facade gives
UI code and tests a stable typed return object while preserving the existing CLI
entrypoint and command-line behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> ReportArtifacts:
        payload = payload or {}
        recommendation = payload.get("recommendation") or {}
        enriched = recommendation.get("enriched") or {}
        return cls(
            recommendation=recommendation,
            usage=payload.get("usage") or recommendation.get("usage") or {},
            report_path=payload.get("report_path"),
            csv_path=payload.get("csv_path"),
            log_path=payload.get("log_path"),
            session_type=payload.get("session_type") or "",
            model_name=payload.get("model_name"),
            quality_warnings=payload.get("quality_warnings") or recommendation.get("quality_warnings") or [],
            source_degradation=payload.get("source_degradation")
            or enriched.get("degradation")
            or recommendation.get("source_degradation")
            or [],
        )


class ReportPipeline:
    """Small adapter around the existing report run function."""

    def __init__(self, runner: Callable[..., dict[str, Any] | None] | None = None) -> None:
        self.runner = runner

    def run(self, **kwargs: Any) -> ReportArtifacts:
        runner = self.runner
        if runner is None:
            from src.main import run as main_run

            runner = main_run
        return ReportArtifacts.from_mapping(runner(**kwargs))
