"""Shared UI theme, color palette, and reusable HTML component snippets.

Centralises the visual language used by every front-end (Streamlit, Tkinter
launcher, embedded desktop) so the brand stays consistent and a colour tweak
only needs to happen in one place.

Design tokens follow a small, deliberate palette:

  ┌──────────────────────────────────────────────────────────────────┐
  │  bg / panel / card     dark navy gradient for surface depth      │
  │  accent (green)        primary call-to-action and BUY signals    │
  │  warn (amber)          ADD / partial-trim signals                │
  │  danger (red)          SELL / quality breaches                   │
  │  neutral (slate)       HOLD / placeholders                       │
  │  text / muted          high-contrast body and de-emphasised meta │
  └──────────────────────────────────────────────────────────────────┘

The HTML helpers below intentionally return *strings* (not Streamlit calls)
so they can be reused inside Markdown, Streamlit, Textual rich text, or
written to a static HTML report.  They escape all user content via
``html.escape`` to prevent injection from recommendation logs.
"""

from __future__ import annotations

import html
from dataclasses import dataclass


# ── Colour palette ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Palette:
    """Immutable colour tokens shared by every UI surface."""

    bg: str = "#0b0d14"
    surface: str = "#12141c"
    panel: str = "#171a26"
    card: str = "#1c1f2e"
    border: str = "#272b3c"
    border_strong: str = "#363b52"

    text: str = "#e6e9f2"
    text_strong: str = "#ffffff"
    muted: str = "#8a93a8"
    subtle: str = "#5b6478"

    accent: str = "#22c55e"  # green — primary CTA + BUY
    accent_hover: str = "#16a34a"
    accent_bg: str = "rgba(34, 197, 94, 0.12)"

    warn: str = "#f59e0b"  # amber — ADD / cautions
    warn_bg: str = "rgba(245, 158, 11, 0.12)"

    danger: str = "#ef4444"  # red — SELL / blocked
    danger_bg: str = "rgba(239, 68, 68, 0.12)"

    info: str = "#38bdf8"  # cyan — info chips
    info_bg: str = "rgba(56, 189, 248, 0.12)"

    neutral: str = "#94a3b8"  # slate — HOLD / placeholders
    neutral_bg: str = "rgba(148, 163, 184, 0.10)"


PALETTE = Palette()


# ── Action / severity / readiness mapping ──────────────────────────────────


ACTION_META: dict[str, dict[str, str]] = {
    "BUY": {"color": PALETTE.accent, "bg": PALETTE.accent_bg, "emoji": "🟢"},
    "ADD": {"color": PALETTE.warn, "bg": PALETTE.warn_bg, "emoji": "🟡"},
    "HOLD": {"color": PALETTE.neutral, "bg": PALETTE.neutral_bg, "emoji": "⚪"},
    "TRIM": {"color": "#fb923c", "bg": "rgba(251, 146, 60, 0.14)", "emoji": "🟠"},
    "SELL": {"color": PALETTE.danger, "bg": PALETTE.danger_bg, "emoji": "🔴"},
    "NONE": {"color": PALETTE.subtle, "bg": PALETTE.neutral_bg, "emoji": "—"},
}

SEVERITY_META: dict[str, dict[str, str]] = {
    "critical": {"color": PALETTE.danger, "bg": PALETTE.danger_bg, "emoji": "🛑"},
    "high": {"color": PALETTE.danger, "bg": PALETTE.danger_bg, "emoji": "⛔"},
    "medium": {"color": PALETTE.warn, "bg": PALETTE.warn_bg, "emoji": "⚠️"},
    "low": {"color": PALETTE.info, "bg": PALETTE.info_bg, "emoji": "ℹ️"},
    "info": {"color": PALETTE.info, "bg": PALETTE.info_bg, "emoji": "ℹ️"},
}

READINESS_META: dict[str, dict[str, str]] = {
    "TRADE_READY": {"color": PALETTE.accent, "bg": PALETTE.accent_bg, "label": "Trade Ready"},
    "REVIEW_FIRST": {"color": PALETTE.warn, "bg": PALETTE.warn_bg, "label": "Review First"},
    "BLOCKED": {"color": PALETTE.danger, "bg": PALETTE.danger_bg, "label": "Blocked"},
}

# v1.16: thesis-verdict colour map (matches thesis_tracker.evaluate_progress
# output).  ``materialized`` is the success state, ``invalidated`` is exit,
# the middle two are warning / neutral.
VERDICT_META: dict[str, dict[str, str]] = {
    "materialized": {"color": PALETTE.accent, "bg": PALETTE.accent_bg, "emoji": "✅", "label": "Materializing"},
    "partial": {"color": PALETTE.warn, "bg": PALETTE.warn_bg, "emoji": "🟡", "label": "Partial"},
    "not_yet": {"color": PALETTE.neutral, "bg": PALETTE.neutral_bg, "emoji": "⏳", "label": "Not yet"},
    "invalidated": {"color": PALETTE.danger, "bg": PALETTE.danger_bg, "emoji": "❌", "label": "Invalidated"},
}


def action_meta(action: str | None) -> dict[str, str]:
    """Look up colour/emoji metadata for a recommendation action."""
    if not action:
        return ACTION_META["NONE"]
    return ACTION_META.get(str(action).upper(), ACTION_META["NONE"])


def severity_meta(severity: str | None) -> dict[str, str]:
    """Look up colour/emoji metadata for a quality-warning severity."""
    if not severity:
        return SEVERITY_META["info"]
    return SEVERITY_META.get(str(severity).lower(), SEVERITY_META["info"])


def readiness_meta(readiness: str | None) -> dict[str, str]:
    """Look up colour/label metadata for buy-signal readiness."""
    if not readiness:
        return {"color": PALETTE.subtle, "bg": PALETTE.neutral_bg, "label": "Unknown"}
    return READINESS_META.get(
        str(readiness).upper(),
        {"color": PALETTE.subtle, "bg": PALETTE.neutral_bg, "label": str(readiness)},
    )


def verdict_meta(verdict: str | None) -> dict[str, str]:
    """Look up colour/emoji/label for a thesis-tracker verdict."""
    if not verdict:
        return {"color": PALETTE.subtle, "bg": PALETTE.neutral_bg, "emoji": "·", "label": "Unknown"}
    return VERDICT_META.get(
        str(verdict).lower(),
        {"color": PALETTE.subtle, "bg": PALETTE.neutral_bg, "emoji": "·", "label": str(verdict)},
    )


# ── HTML component helpers (escape user content!) ──────────────────────────


def _esc(value) -> str:
    """HTML-escape any input, including None."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def badge(text: str, *, color: str, bg: str | None = None, title: str | None = None) -> str:
    """Render a small coloured pill suitable for inline tables and headers."""
    bg = bg or "rgba(255,255,255,0.06)"
    title_attr = f' title="{_esc(title)}"' if title else ""
    return f'<span class="ts-badge"{title_attr} style="color:{color};background:{bg};border:1px solid {color}55;">{_esc(text)}</span>'


def action_badge(action: str | None, *, with_emoji: bool = True) -> str:
    """Pill for a recommendation action (BUY / ADD / HOLD / TRIM / SELL)."""
    meta = action_meta(action)
    label = (action or "NONE").upper()
    if with_emoji:
        label = f"{meta['emoji']} {label}"
    return badge(label, color=meta["color"], bg=meta["bg"])


def severity_badge(severity: str | None) -> str:
    """Pill for quality-warning severity."""
    meta = severity_meta(severity)
    label = (severity or "info").lower()
    return badge(f"{meta['emoji']} {label}", color=meta["color"], bg=meta["bg"])


def readiness_badge(readiness: str | None) -> str:
    """Pill for buy-signal readiness state."""
    meta = readiness_meta(readiness)
    return badge(meta["label"], color=meta["color"], bg=meta["bg"])


def verdict_badge(verdict: str | None) -> str:
    """Pill for a thesis-tracker verdict (materialized / partial / not_yet / invalidated)."""
    meta = verdict_meta(verdict)
    label = f"{meta['emoji']} {meta['label']}".strip()
    return badge(label, color=meta["color"], bg=meta["bg"])


# v1.17: health colour map for the Diagnostics tab and inline degradation
# pills.  Mirrors the readiness scale: green/amber/red/idle-grey.
HEALTH_META: dict[str, dict[str, str]] = {
    "ok": {"color": PALETTE.accent, "bg": PALETTE.accent_bg, "emoji": "●", "label": "ok"},
    "degraded": {"color": PALETTE.warn, "bg": PALETTE.warn_bg, "emoji": "▲", "label": "degraded"},
    "down": {"color": PALETTE.danger, "bg": PALETTE.danger_bg, "emoji": "✖", "label": "down"},
    "idle": {"color": PALETTE.subtle, "bg": PALETTE.neutral_bg, "emoji": "·", "label": "idle"},
}


def health_meta(health: str | None) -> dict[str, str]:
    if not health:
        return HEALTH_META["idle"]
    return HEALTH_META.get(str(health).lower(), HEALTH_META["idle"])


def health_badge(health: str | None) -> str:
    """Pill for an API source health verdict (ok / degraded / down / idle)."""
    meta = health_meta(health)
    label = f"{meta['emoji']} {meta['label']}"
    return badge(label, color=meta["color"], bg=meta["bg"])


def degradation_pill(source: str, health: str | None) -> str:
    """Inline pill showing the source name + its current health.

    Designed to live next to a data field that might be stale (e.g. a quote
    label).  Returns empty string when the source is healthy so callers can
    unconditionally interpolate the result.

    ``source`` is escaped inside ``badge()`` — do NOT pre-escape here, or
    the user-supplied source string ends up double-escaped.
    """
    if not health or health.lower() == "ok":
        return ""
    meta = health_meta(health)
    # ``badge()`` runs _esc() on the whole text once. Pass the raw source
    # straight through.
    return badge(f"{meta['emoji']} {source} {meta['label']}", color=meta["color"], bg=meta["bg"])


def conviction_bar(score: float | int | None, *, max_score: int = 10) -> str:
    """Compact horizontal bar visualising a 0–10 conviction score."""
    try:
        value = max(0.0, min(float(score or 0), float(max_score)))
    except (TypeError, ValueError):
        value = 0.0
    pct = (value / max_score) * 100 if max_score else 0
    if pct >= 70:
        color = PALETTE.accent
    elif pct >= 40:
        color = PALETTE.warn
    else:
        color = PALETTE.neutral
    return (
        '<span class="ts-conviction" '
        f'style="--ts-conv-pct:{pct:.0f}%;--ts-conv-color:{color};">'
        f'<span class="ts-conviction-fill"></span>'
        f'<span class="ts-conviction-label">{value:.1f}</span></span>'
    )


def metric_card(label: str, value: str, *, hint: str = "", tone: str = "neutral") -> str:
    """Stand-alone metric card with optional sub-hint."""
    tones = {
        "good": PALETTE.accent,
        "warn": PALETTE.warn,
        "bad": PALETTE.danger,
        "info": PALETTE.info,
        "neutral": PALETTE.text_strong,
    }
    color = tones.get(tone, PALETTE.text_strong)
    return (
        '<div class="ts-metric">'
        f'<div class="ts-metric-label">{_esc(label)}</div>'
        f'<div class="ts-metric-value" style="color:{color};">{_esc(value)}</div>'
        f'<div class="ts-metric-hint">{_esc(hint)}</div>'
        "</div>"
    )


def status_dot(ok: bool | None, *, label: str = "") -> str:
    """Tiny status pip — green if ok, red if not, grey if unknown."""
    if ok is None:
        color = PALETTE.subtle
        title = "Unknown"
    elif ok:
        color = PALETTE.accent
        title = "OK"
    else:
        color = PALETTE.danger
        title = "Unavailable"
    return f'<span class="ts-status-dot" title="{_esc(label or title)}" style="background:{color};box-shadow:0 0 6px {color}88;"></span>'


# ── Streamlit CSS bundle ────────────────────────────────────────────────────


STREAMLIT_CSS = f"""
<style>
:root {{
    --ts-bg: {PALETTE.bg};
    --ts-surface: {PALETTE.surface};
    --ts-panel: {PALETTE.panel};
    --ts-card: {PALETTE.card};
    --ts-border: {PALETTE.border};
    --ts-border-strong: {PALETTE.border_strong};
    --ts-text: {PALETTE.text};
    --ts-muted: {PALETTE.muted};
    --ts-accent: {PALETTE.accent};
    --ts-accent-hover: {PALETTE.accent_hover};
    --ts-warn: {PALETTE.warn};
    --ts-danger: {PALETTE.danger};
}}

html, body, [class*="css"] {{
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}

.stApp {{
    background: linear-gradient(180deg, var(--ts-bg) 0%, var(--ts-surface) 100%);
    color: var(--ts-text);
}}

section[data-testid="stSidebar"] {{
    background: var(--ts-panel);
    border-right: 1px solid var(--ts-border);
}}

section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] label {{
    color: var(--ts-text);
}}

/* Tabs */
button[data-baseweb="tab"] {{
    color: var(--ts-muted) !important;
    font-weight: 600;
    letter-spacing: 0.02em;
    border-radius: 8px 8px 0 0 !important;
    padding: 12px 18px !important;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
    color: var(--ts-accent) !important;
    background: rgba(34, 197, 94, 0.06) !important;
    border-bottom: 2px solid var(--ts-accent) !important;
}}

/* Buttons */
.stButton > button {{
    border-radius: 10px;
    border: 1px solid var(--ts-border-strong);
    background: var(--ts-card);
    color: var(--ts-text);
    transition: all 120ms ease;
    font-weight: 600;
    padding: 0.5rem 1rem;
}}
.stButton > button:hover {{
    border-color: var(--ts-accent);
    color: var(--ts-accent);
    transform: translateY(-1px);
}}
.stButton > button[kind="primary"] {{
    background: var(--ts-accent);
    border-color: var(--ts-accent);
    color: #06170d;
}}
.stButton > button[kind="primary"]:hover {{
    background: var(--ts-accent-hover);
    border-color: var(--ts-accent-hover);
    color: #06170d;
}}

/* Metric cards (native Streamlit metric) */
[data-testid="stMetric"] {{
    background: var(--ts-card);
    border: 1px solid var(--ts-border);
    border-radius: 12px;
    padding: 16px 18px;
    transition: border-color 120ms ease, transform 120ms ease;
}}
[data-testid="stMetric"]:hover {{
    border-color: var(--ts-border-strong);
    transform: translateY(-1px);
}}
[data-testid="stMetricLabel"] {{
    color: var(--ts-muted) !important;
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}}
[data-testid="stMetricValue"] {{
    color: var(--ts-text) !important;
    font-weight: 700;
    font-size: 1.6rem !important;
}}

/* Dataframes */
[data-testid="stDataFrame"] {{
    border: 1px solid var(--ts-border);
    border-radius: 10px;
    overflow: hidden;
}}

/* Custom components */
.ts-badge {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    white-space: nowrap;
    line-height: 1.4;
}}

.ts-conviction {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    width: 110px;
    height: 18px;
    position: relative;
    background: rgba(255,255,255,0.05);
    border-radius: 999px;
    overflow: hidden;
}}
.ts-conviction-fill {{
    position: absolute;
    inset: 0 auto 0 0;
    width: var(--ts-conv-pct, 0%);
    background: var(--ts-conv-color, var(--ts-accent));
    opacity: 0.85;
}}
.ts-conviction-label {{
    position: relative;
    z-index: 1;
    margin-left: auto;
    padding-right: 8px;
    font-size: 0.72rem;
    font-weight: 700;
    color: var(--ts-text);
    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}}

.ts-metric {{
    background: var(--ts-card);
    border: 1px solid var(--ts-border);
    border-radius: 12px;
    padding: 16px 18px;
    height: 100%;
}}
.ts-metric-label {{
    color: var(--ts-muted);
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 600;
    margin-bottom: 6px;
}}
.ts-metric-value {{
    font-size: 1.55rem;
    font-weight: 700;
    line-height: 1.1;
}}
.ts-metric-hint {{
    color: var(--ts-muted);
    font-size: 0.78rem;
    margin-top: 6px;
}}

.ts-status-dot {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
}}

.ts-hero {{
    border-radius: 16px;
    padding: 22px 28px;
    background: linear-gradient(135deg, rgba(34,197,94,0.08), rgba(34,197,94,0.02));
    border: 1px solid var(--ts-border-strong);
    margin-bottom: 18px;
}}
.ts-hero h1 {{
    margin: 0;
    font-size: 1.8rem;
    color: var(--ts-text);
}}
.ts-hero .ts-hero-sub {{
    color: var(--ts-muted);
    margin-top: 4px;
    font-size: 0.95rem;
}}
.ts-hero .ts-hero-meta {{
    margin-top: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    align-items: center;
    color: var(--ts-muted);
    font-size: 0.85rem;
}}

.ts-action-card {{
    background: var(--ts-card);
    border: 1px solid var(--ts-border);
    border-left: 3px solid var(--ts-accent);
    border-radius: 12px;
    padding: 16px 18px;
    margin-bottom: 10px;
}}
.ts-action-card.is-add {{ border-left-color: var(--ts-warn); }}
.ts-action-card.is-trim {{ border-left-color: #fb923c; }}
.ts-action-card.is-sell {{ border-left-color: var(--ts-danger); }}
.ts-action-card.is-hold {{ border-left-color: {PALETTE.neutral}; }}
.ts-action-card .ts-ac-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 6px;
}}
.ts-action-card .ts-ac-ticker {{
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--ts-text);
    letter-spacing: 0.04em;
}}
.ts-action-card .ts-ac-rationale {{
    color: var(--ts-muted);
    font-size: 0.88rem;
    line-height: 1.5;
}}

.ts-warning-row {{
    background: var(--ts-card);
    border-radius: 10px;
    padding: 10px 12px;
    border-left: 3px solid var(--ts-warn);
    margin-bottom: 6px;
    font-size: 0.88rem;
}}
.ts-warning-row.is-critical {{ border-left-color: var(--ts-danger); }}
.ts-warning-row.is-low {{ border-left-color: {PALETTE.info}; }}
.ts-warning-row .ts-wr-ticker {{
    font-weight: 700;
    margin-right: 8px;
    color: var(--ts-text);
}}
.ts-warning-row .ts-wr-message {{
    color: var(--ts-muted);
}}

.ts-empty {{
    text-align: center;
    padding: 36px 18px;
    color: var(--ts-muted);
    border: 1px dashed var(--ts-border);
    border-radius: 12px;
    background: var(--ts-card);
}}
.ts-empty .ts-empty-title {{
    color: var(--ts-text);
    font-weight: 600;
    margin-bottom: 6px;
}}

/* Sidebar polish */
section[data-testid="stSidebar"] h2 {{
    font-size: 1rem;
    color: var(--ts-text);
    border-bottom: 1px solid var(--ts-border);
    padding-bottom: 6px;
    margin-bottom: 10px;
}}
</style>
"""


def empty_state(title: str, hint: str = "") -> str:
    """Friendly placeholder card used when a section has no data yet."""
    return f'<div class="ts-empty"><div class="ts-empty-title">{_esc(title)}</div><div>{_esc(hint)}</div></div>'


def hero(title: str, sub: str = "", meta: list[str] | None = None) -> str:
    """Big banner for the top of a page or dashboard."""
    meta_chunks = " · ".join(_esc(part) for part in (meta or []))
    meta_html = f'<div class="ts-hero-meta">{meta_chunks}</div>' if meta_chunks else ""
    return f'<div class="ts-hero"><h1>{_esc(title)}</h1><div class="ts-hero-sub">{_esc(sub)}</div>{meta_html}</div>'


def action_card(ticker: str, action: str | None, rationale: str = "", conviction: float | None = None) -> str:
    """Priority-queue card used on the dashboard."""
    css_class = {
        "BUY": "is-buy",
        "ADD": "is-add",
        "HOLD": "is-hold",
        "TRIM": "is-trim",
        "SELL": "is-sell",
    }.get((action or "").upper(), "")
    conviction_html = conviction_bar(conviction) if conviction is not None else ""
    return (
        f'<div class="ts-action-card {css_class}">'
        '<div class="ts-ac-header">'
        f'<span class="ts-ac-ticker">{_esc(ticker)}</span>'
        f"{action_badge(action)}"
        f"{conviction_html}"
        "</div>"
        f'<div class="ts-ac-rationale">{_esc(rationale)}</div>'
        "</div>"
    )


def warning_row(severity: str | None, ticker: str | None, message: str) -> str:
    """One-line quality-warning row used in dashboard lists."""
    css_class = {
        "critical": "is-critical",
        "high": "is-critical",
        "low": "is-low",
        "info": "is-low",
    }.get((severity or "").lower(), "")
    return (
        f'<div class="ts-warning-row {css_class}">'
        f"{severity_badge(severity)}"
        f'<span class="ts-wr-ticker">{_esc(ticker or "")}</span>'
        f'<span class="ts-wr-message">{_esc(message)}</span>'
        "</div>"
    )


__all__ = [
    "PALETTE",
    "Palette",
    "STREAMLIT_CSS",
    "ACTION_META",
    "SEVERITY_META",
    "READINESS_META",
    "VERDICT_META",
    "HEALTH_META",
    "action_meta",
    "severity_meta",
    "readiness_meta",
    "verdict_meta",
    "health_meta",
    "action_badge",
    "severity_badge",
    "readiness_badge",
    "verdict_badge",
    "health_badge",
    "degradation_pill",
    "badge",
    "conviction_bar",
    "metric_card",
    "status_dot",
    "empty_state",
    "hero",
    "action_card",
    "warning_row",
]
