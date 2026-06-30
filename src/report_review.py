"""Report review and feedback-loop view model.

This module turns one recommendation JSON log plus the local decision journal
into a compact review payload that every UI can render. It does not call live
APIs or Claude.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.data_confidence import build_data_confidence
from src.decision_journal import ACTIONABLE_ACTIONS, decision_id, execution_checklist_status, load_journal
from src.view_models import BLOCKED, REVIEW_FIRST, TRADE_READY

BLOCKING_REVIEW_CODES = {
    "market_data_error",
    "stale_or_unstamped_quote",
    "missing_catalyst_verification",
    "buy_add_over_position_cap",
    "oversized_company_exposure",
}

QUOTE_REVIEW_CODES = {
    "stale_or_unstamped_quote",
    "quote_source_mismatch",
}

CATALYST_REVIEW_CODES = {
    "missing_catalyst",
    "missing_catalyst_on_large_move",
    "missing_catalyst_verification",
}


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _warning_status(warnings: list[dict[str, Any]]) -> str:
    codes = {str(row.get("code") or "") for row in warnings}
    has_high = any(str(row.get("severity") or "").lower() == "high" for row in warnings)
    if has_high or codes & BLOCKING_REVIEW_CODES:
        return BLOCKED
    if warnings:
        return REVIEW_FIRST
    return TRADE_READY


def _readiness_status(rec: dict[str, Any], warning_rows: list[dict[str, Any]]) -> str:
    readiness = rec.get("trade_readiness") or rec.get("readiness")
    if isinstance(readiness, dict):
        value = readiness.get("status") or readiness.get("label")
    else:
        value = readiness
    normalized = str(value or "").strip().upper().replace(" ", "_")
    if normalized in {TRADE_READY, REVIEW_FIRST, BLOCKED}:
        return normalized
    if rec.get("manual_review_required"):
        return REVIEW_FIRST
    return _warning_status(warning_rows)


def _display_status(status: str) -> str:
    return {
        TRADE_READY: "Trade Ready",
        REVIEW_FIRST: "Review First",
        BLOCKED: "Blocked",
    }.get(status, status.title())


def _warning_counts(warnings: list[dict[str, Any]]) -> tuple[Counter, Counter]:
    severities: Counter = Counter()
    codes: Counter = Counter()
    for warning in warnings:
        severity = str(warning.get("severity") or "unknown").lower()
        code = str(warning.get("code") or "unknown")
        severities[severity] += 1
        codes[code] += 1
    return severities, codes


def _risk_control_summary(rec: dict[str, Any]) -> str:
    controls = rec.get("risk_controls") or {}
    if not isinstance(controls, dict):
        controls = {}
    parts: list[str] = []
    low = controls.get("entry_zone_low_pct")
    high = controls.get("entry_zone_high_pct")
    if low is not None or high is not None:
        parts.append(f"entry {low if low is not None else '?'}% to {high if high is not None else '?'}%")
    if controls.get("stop_loss_pct") is not None:
        parts.append(f"stop {controls.get('stop_loss_pct')}%")
    if controls.get("take_profit_pct") is not None:
        parts.append(f"take profit {controls.get('take_profit_pct')}%")
    return " | ".join(parts) if parts else "missing"


def _action_size(rec: dict[str, Any]) -> str:
    label = rec.get("action_size_label")
    if label:
        return str(label)
    amount = rec.get("action_amount") or rec.get("invest_amount_usd")
    shares = rec.get("shares")
    fraction = rec.get("action_fraction")
    parts = []
    if shares not in (None, ""):
        parts.append(f"{shares} sh")
    if fraction not in (None, ""):
        try:
            parts.append(f"{float(fraction) * 100:.0f}%")
        except (TypeError, ValueError):
            parts.append(str(fraction))
    if amount not in (None, ""):
        parts.append(f"${amount}")
    return " / ".join(parts)


def _decision_map(journal_path: Path) -> dict[str, dict[str, Any]]:
    journal = load_journal(journal_path)
    return {row.get("id"): row for row in journal.get("decisions", []) if row.get("id")}


def _data_confidence(payload: dict[str, Any], recommendations: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    existing = payload.get("data_confidence")
    if isinstance(existing, dict) and existing:
        return existing
    readiness_counts = Counter()
    warnings_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for warning in warnings:
        warnings_by_ticker[str(warning.get("ticker") or "")].append(warning)
    for rec in recommendations:
        ticker = str(rec.get("ticker") or "")
        readiness_counts[_readiness_status(rec, warnings_by_ticker.get(ticker, []))] += 1
    return build_data_confidence(
        recommendations=recommendations,
        quality_warnings=warnings,
        enriched={"degradation": payload.get("source_degradation") or payload.get("degradation") or []},
        readiness_counts=dict(readiness_counts),
    )


def _overall_status(confidence: dict[str, Any], warnings: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> str:
    status = str(confidence.get("status") or "").lower()
    warning_status = _warning_status(warnings)
    if status == "blocked" or warning_status == BLOCKED:
        return BLOCKED
    if status == "review_first" or warning_status == REVIEW_FIRST:
        return REVIEW_FIRST
    if any(rec.get("manual_review_required") for rec in recommendations):
        return REVIEW_FIRST
    return TRADE_READY


def _change_rows(drift_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in drift_events:
        was = event.get("was") or {}
        now = event.get("now") or {}
        rows.append(
            {
                "ticker": event.get("ticker") or "",
                "change": event.get("drift_type") or "change",
                "before": _drift_side(was),
                "after": _drift_side(now),
                "detail": event.get("message") or event.get("summary") or "",
            }
        )
    return rows


def _drift_side(side: dict[str, Any]) -> str:
    pieces = []
    if side.get("action"):
        pieces.append(str(side.get("action")))
    if side.get("conviction") is not None:
        pieces.append(f"conv {side.get('conviction')}")
    if side.get("net_expected_pct") is not None:
        pieces.append(f"net {side.get('net_expected_pct')}%")
    return " / ".join(pieces)


def build_report_review(
    *,
    log_path: str | Path | None = None,
    report_path: str | Path | None = None,
    journal_path: str | Path,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a report-review payload from saved artifacts."""
    log = Path(log_path).expanduser() if log_path else None
    report = Path(report_path).expanduser() if report_path else None
    journal = Path(journal_path).expanduser()
    payload = dict(payload or _read_json(log))
    if payload.get("error"):
        return {
            "ok": False,
            "status": BLOCKED,
            "status_label": "Blocked",
            "log_path": log,
            "report_path": report,
            "error": payload.get("error"),
            "metric_rows": [
                {
                    "metric": "JSON log",
                    "status": "FAIL",
                    "value": "unreadable",
                    "detail": payload.get("error"),
                    "next_action": "Open Diagnostics or regenerate the report.",
                }
            ],
            "support_summary": f"Report review failed for {log}: {payload.get('error')}",
        }

    recommendations = payload.get("recommendations") or []
    warnings = payload.get("quality_warnings") or []
    source_degradation = payload.get("source_degradation") or payload.get("degradation") or []
    confidence = _data_confidence(payload, recommendations, warnings)
    overall_status = _overall_status(confidence, warnings, recommendations)
    severities, codes = _warning_counts(warnings)

    warnings_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for warning in warnings:
        warnings_by_ticker[str(warning.get("ticker") or "")].append(warning)

    decisions = _decision_map(journal)
    readiness_counts: Counter = Counter()
    recommendation_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    execution_checklist_rows: list[dict[str, Any]] = []
    session_file = log.name if log else str(payload.get("session_file") or "")
    for rec in recommendations:
        ticker = str(rec.get("ticker") or "").upper()
        if not ticker or ticker == "CASH":
            continue
        ticker_warnings = warnings_by_ticker.get(ticker, [])
        readiness = _readiness_status(rec, ticker_warnings)
        readiness_counts[readiness] += 1
        row_id = decision_id(session_file, ticker) if session_file else ""
        journal_row = decisions.get(row_id) or {}
        action = str(rec.get("action") or "HOLD").upper()
        recommendation_rows.append(
            {
                "ticker": ticker,
                "action": action,
                "size": _action_size(rec),
                "conviction": rec.get("conviction"),
                "readiness": readiness,
                "readiness_label": _display_status(readiness),
                "warnings": ", ".join(str(row.get("code") or "") for row in ticker_warnings) or "none",
                "catalyst": rec.get("catalyst_source") or ("verified" if rec.get("catalyst_verified") else "not verified"),
                "risk_controls": _risk_control_summary(rec),
                "decision": journal_row.get("user_decision") or "pending",
                "decision_id": row_id,
            }
        )
        if action in ACTIONABLE_ACTIONS:
            decision_rows.append(
                {
                    "id": row_id,
                    "ticker": ticker,
                    "recommended_action": action,
                    "size": _action_size(rec),
                    "conviction": rec.get("conviction"),
                    "user_decision": journal_row.get("user_decision") or "pending",
                    "reason": journal_row.get("reason") or "",
                    "can_record": bool(row_id),
                }
            )
            execution_checklist_rows.extend(
                _execution_checklist_rows(
                    rec=rec,
                    journal_row=journal_row,
                    row_id=row_id,
                    ticker=ticker,
                    warnings=ticker_warnings,
                )
            )

    quote_warning_count = sum(count for code, count in codes.items() if code in QUOTE_REVIEW_CODES)
    catalyst_warning_count = sum(count for code, count in codes.items() if code in CATALYST_REVIEW_CODES)
    manual_review_count = sum(1 for rec in recommendations if rec.get("manual_review_required"))
    pending_decisions = sum(1 for row in decision_rows if row.get("user_decision") == "pending")
    pending_checklist = sum(1 for row in execution_checklist_rows if row.get("status") == "PENDING")

    metric_rows = [
        {
            "metric": "Data confidence",
            "status": _display_status(overall_status),
            "value": confidence.get("label") or "unknown",
            "detail": confidence.get("summary") or "",
            "next_action": "Review blockers before trading." if overall_status == BLOCKED else "Use as research input.",
        },
        {
            "metric": "Quality warnings",
            "status": "WARN" if warnings else "OK",
            "value": str(len(warnings)),
            "detail": f"high {severities.get('high', 0)}, medium {severities.get('medium', 0)}, low {severities.get('low', 0)}",
            "next_action": "Resolve high/medium warnings before execution." if warnings else "No quality-gate warnings.",
        },
        {
            "metric": "Quote checks",
            "status": "WARN" if quote_warning_count else "OK",
            "value": str(quote_warning_count),
            "detail": confidence.get("quote_freshness") or "unknown",
            "next_action": "Verify live quotes before placing orders." if quote_warning_count else "Quote gates clear.",
        },
        {
            "metric": "Catalyst checks",
            "status": "WARN" if catalyst_warning_count or manual_review_count else "OK",
            "value": str(catalyst_warning_count + manual_review_count),
            "detail": f"{manual_review_count} manual-review recommendation(s)",
            "next_action": "Confirm catalyst/news source for event-driven trades."
            if catalyst_warning_count or manual_review_count
            else "Catalyst gates clear.",
        },
        {
            "metric": "Source degradation",
            "status": "WARN" if source_degradation else "OK",
            "value": str(len(source_degradation)),
            "detail": ", ".join(str(row.get("source") or row.get("name") or "source") for row in source_degradation[:4]),
            "next_action": "Open Diagnostics if a required source is degraded."
            if source_degradation
            else "No source degradation recorded.",
        },
        {
            "metric": "Decision feedback",
            "status": "WARN" if pending_decisions else "OK",
            "value": f"{pending_decisions} pending",
            "detail": f"{len(decision_rows)} actionable recommendation(s)",
            "next_action": "Record accepted/ignored/modified decisions to improve the learning loop."
            if pending_decisions
            else "Feedback loop is up to date for this report.",
        },
        {
            "metric": "Execution checklist",
            "status": "WARN" if pending_checklist else "OK",
            "value": f"{pending_checklist} pending",
            "detail": f"{len(execution_checklist_rows)} checklist item(s)",
            "next_action": "Confirm quote, catalyst, sizing, fee/FX, and manual-review items before trading."
            if pending_checklist
            else "Execution checklist is fully reviewed.",
        },
    ]

    top_reasons = list(confidence.get("reasons") or [])
    for code, count in codes.most_common(3):
        top_reasons.append(f"{count}x quality warning: {code}")
    for row in source_degradation[:3]:
        source = row.get("source") or row.get("name") or "source"
        message = row.get("message") or row.get("detail") or row.get("code") or "degraded"
        top_reasons.append(f"{source}: {message}")
    if not top_reasons:
        top_reasons = ["No deterministic review issues found."]

    support_summary = _support_summary(
        status=overall_status,
        log_path=log,
        report_path=report,
        confidence=confidence,
        warnings=warnings,
        source_degradation=source_degradation,
        pending_decisions=pending_decisions,
        top_reasons=top_reasons,
    )

    return {
        "ok": True,
        "status": overall_status,
        "status_label": _display_status(overall_status),
        "log_path": log,
        "report_path": report,
        "session_file": session_file,
        "session_summary": payload.get("session_summary") or "",
        "data_confidence": confidence,
        "metric_rows": metric_rows,
        "top_reasons": top_reasons[:8],
        "warning_counts": {"severity": dict(severities), "code": dict(codes)},
        "readiness_counts": dict(readiness_counts),
        "recommendation_rows": recommendation_rows,
        "decision_rows": decision_rows,
        "execution_checklist_rows": execution_checklist_rows,
        "change_rows": _change_rows(payload.get("drift_vs_previous") or []),
        "source_rows": source_degradation,
        "support_summary": support_summary,
    }


def _execution_checklist_rows(
    *,
    rec: dict[str, Any],
    journal_row: dict[str, Any],
    row_id: str,
    ticker: str,
    warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    status = execution_checklist_status(journal_row)
    checklist = status.get("checklist") or {}
    warnings_text = ", ".join(str(row.get("code") or "") for row in warnings)
    manual_review = bool(rec.get("manual_review_required") or warnings)
    definitions = [
        (
            "quote_confirmed",
            "Quote confirmed",
            "Required",
            "Confirm live broker quote, previous close, currency, and timestamp.",
        ),
        (
            "catalyst_checked",
            "Catalyst checked",
            "Required" if rec.get("catalyst_source") or rec.get("catalyst_verified") or warnings else "Recommended",
            rec.get("catalyst_source") or warnings_text or "Check recent news before execution.",
        ),
        (
            "sizing_checked",
            "Sizing checked",
            "Required",
            _action_size(rec) or "Confirm shares, position percent, and cash impact.",
        ),
        (
            "fee_fx_checked",
            "Fee/FX checked",
            "Required",
            "Confirm Wealthsimple account type, USD/CAD cash, bid/ask, and fee hurdle.",
        ),
        (
            "manual_review_accepted",
            "Manual review accepted",
            "Required" if manual_review else "Optional",
            "Accept manual-review warnings before trading." if manual_review else "No manual-review blocker detected.",
        ),
    ]
    rows = []
    for key, label, required, detail in definitions:
        done = bool(checklist.get(key))
        rows.append(
            {
                "id": row_id,
                "ticker": ticker,
                "check": key,
                "label": label,
                "required": required,
                "status": "DONE" if done else "PENDING",
                "detail": detail,
                "updated_at": status.get("updated_at") or "",
                "notes": status.get("notes") or "",
            }
        )
    return rows


def _support_summary(
    *,
    status: str,
    log_path: Path | None,
    report_path: Path | None,
    confidence: dict[str, Any],
    warnings: list[dict[str, Any]],
    source_degradation: list[dict[str, Any]],
    pending_decisions: int,
    top_reasons: list[str],
) -> str:
    severity_counts = confidence.get("warning_severity_counts") or {}
    lines = [
        "tech_stock report review",
        f"Status: {_display_status(status)}",
        f"Report: {report_path or 'unknown'}",
        f"JSON log: {log_path or 'unknown'}",
        f"Data confidence: {confidence.get('label') or 'unknown'} - {confidence.get('summary') or ''}",
        "Warnings: "
        f"{len(warnings)} total "
        f"(high {severity_counts.get('high', 0)}, medium {severity_counts.get('medium', 0)}, low {severity_counts.get('low', 0)})",
        f"Source degradation records: {len(source_degradation)}",
        f"Pending decision-journal rows: {pending_decisions}",
        "Top reasons:",
    ]
    lines.extend(f"- {reason}" for reason in top_reasons[:5])
    return "\n".join(lines)
