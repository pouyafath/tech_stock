"""Theme tokens, platform constants, and the font ladder for the desktop app.

Extracted from ``src/desktop/app.py`` so the visual language lives in one place
and can be imported without pulling in Tkinter (this module deliberately has no
``tkinter`` dependency, which also makes it unit-testable on headless machines).
"""

from __future__ import annotations

import sys

try:
    from src.ui_theme import PALETTE  # noqa: F401 — re-exported
except Exception:  # pragma: no cover — defensive fallback for early bundle init

    class _PaletteFallback:
        bg = "#0b0d14"
        surface = "#12141c"
        panel = "#171a26"
        card = "#1c1f2e"
        border = "#272b3c"
        border_strong = "#363b52"
        text = "#e6e9f2"
        text_strong = "#ffffff"
        muted = "#8a93a8"
        subtle = "#5b6478"
        accent = "#22c55e"
        accent_hover = "#16a34a"
        warn = "#f59e0b"
        danger = "#ef4444"
        info = "#38bdf8"
        neutral = "#94a3b8"

    PALETTE = _PaletteFallback()  # type: ignore[assignment]


IS_MACOS = sys.platform == "darwin"
MOD_KEY = "Command" if IS_MACOS else "Control"
MOD_LABEL = "⌘" if IS_MACOS else "Ctrl+"


def platform_fonts() -> dict[str, tuple]:
    """Return a font ladder tuned per-platform.

    On macOS we use the system "SF Pro" stack (Apple's modern default). On
    Windows we use Segoe UI; elsewhere we fall back to TkDefaultFont. Each
    entry is ``(family, size, weight)``.
    """
    if IS_MACOS:
        family_display = "SF Pro Display"
        family_text = "SF Pro Text"
        mono = "SF Mono"
    elif sys.platform == "win32":
        family_display = "Segoe UI"
        family_text = "Segoe UI"
        mono = "Consolas"
    else:
        family_display = "TkDefaultFont"
        family_text = "TkDefaultFont"
        mono = "TkFixedFont"
    return {
        "title": (family_display, 28, "bold"),
        "heading": (family_display, 17, "bold"),
        "subheading": (family_text, 13, "bold"),
        "body": (family_text, 12, "normal"),
        "small": (family_text, 11, "normal"),
        "mono": (mono, 12, "normal"),
    }


# Backward-compatible alias — app.py historically exposed ``_platform_fonts``.
_platform_fonts = platform_fonts
