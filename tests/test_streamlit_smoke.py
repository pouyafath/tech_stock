"""Smoke test: Streamlit + Textual UI modules import and run-to-render.

We mock the ``streamlit`` package with a tiny ``DummyCtx`` so the module
body executes without spinning up a Streamlit server. Catches obvious
errors like ``AttributeError`` on missing helpers, malformed CSS injection,
or NameError-on-import after a refactor.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


class _DummyCtx:
    """Replaces every Streamlit widget + container with a no-op."""

    def __enter__(self) -> _DummyCtx:
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        return _no_op

    def button(self, *_a, **_kw) -> bool:
        return False

    def checkbox(self, *_a, **_kw) -> bool:
        return False

    def download_button(self, *_a, **_kw) -> bool:
        return False

    def selectbox(self, label, options, **kw):  # type: ignore[no-untyped-def]
        opts = list(options or [])
        idx = kw.get("index", 0) or 0
        return opts[idx] if opts else None

    def radio(self, label, options, **kw):  # type: ignore[no-untyped-def]
        return self.selectbox(label, options, **kw)

    def text_input(self, *_a, **_kw) -> str:
        return ""

    def text_area(self, *_a, **_kw) -> str:
        return "{}"

    def number_input(self, label, **kw):  # type: ignore[no-untyped-def]
        return kw.get("value", 0.0)

    def file_uploader(self, *_a, **_kw):
        return None

    def columns(self, spec):  # type: ignore[no-untyped-def]
        if isinstance(spec, list):
            n = len(spec)
        elif isinstance(spec, (int, float)):
            n = int(spec)
        else:
            n = 2
        return [self for _ in range(n)]

    def tabs(self, labels):  # type: ignore[no-untyped-def]
        return [self for _ in labels]

    def container(self, *_a, **_kw):
        return self

    def expander(self, *_a, **_kw):
        return self

    def status(self, *_a, **_kw):
        return self

    def spinner(self, *_a, **_kw):
        return self

    def empty(self, *_a, **_kw):
        return self


def _no_op(*_args, **_kwargs):
    return None


def _make_fake_streamlit() -> _DummyCtx:
    fake_st = _DummyCtx()
    fake_st.session_state = {}  # real dict so subscript access works
    object.__setattr__(fake_st, "sidebar", _DummyCtx())
    return fake_st


@pytest.fixture
def mocked_streamlit(monkeypatch):
    fake = _make_fake_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    return fake


def _import_module_from_path(name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_streamlit_app_imports_and_executes_without_errors(mocked_streamlit, monkeypatch):
    monkeypatch.setenv("TECH_STOCK_SKIP_UPDATE_CHECK", "1")
    try:
        _import_module_from_path("streamlit_app_smoke", ROOT / "ui" / "streamlit_app.py")
    except SystemExit:
        # st.stop() raises SystemExit in real Streamlit; tolerate it
        pass


def test_ui_theme_helpers_are_well_formed():
    """Sanity check the building blocks the Streamlit app depends on."""
    from src.ui_theme import (
        STREAMLIT_CSS,
        action_badge,
        empty_state,
        hero,
    )

    assert "<style>" in STREAMLIT_CSS and "</style>" in STREAMLIT_CSS
    assert "ts-badge" in action_badge("BUY")
    assert "ts-empty" in empty_state("Nothing")
    assert "ts-hero" in hero("Title", "Sub", ["meta"])
