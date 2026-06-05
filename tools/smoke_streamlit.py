"""Quick smoke test: import the Streamlit app with streamlit mocked.

Catches obvious import errors and template typos without spinning up an
actual Streamlit server.

Strategy: build a single ``DummyCtx`` object that returns ``False`` for any
interactive widget, returns sensible defaults for selectboxes/text inputs,
and supports the context-manager protocol so ``with st.container(...)``
blocks work transparently.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DummyCtx:
    """One object that pretends to be every Streamlit widget / container.

    Any attribute access returns a callable that returns *self* (so chaining
    and context-manager usage both work). The well-known widget methods are
    overridden below to return useful defaults.
    """

    # — context-manager protocol —
    def __enter__(self) -> DummyCtx:
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        return False

    # — generic catch-all so any uncovered method just no-ops —
    def __getattr__(self, _name: str) -> Any:
        return _no_op

    # — interactive widgets default to false / empty —
    def button(self, *args, **kwargs) -> bool:
        return False

    def checkbox(self, *args, **kwargs) -> bool:
        return False

    def download_button(self, *args, **kwargs) -> bool:
        return False

    def selectbox(self, label, options, **kwargs):
        opts = list(options or [])
        index = kwargs.get("index", 0) or 0
        return opts[index] if opts else None

    def radio(self, label, options, **kwargs):
        return self.selectbox(label, options, **kwargs)

    def text_input(self, *args, **kwargs) -> str:
        return ""

    def text_area(self, *args, **kwargs) -> str:
        return "{}"

    def number_input(self, label, **kwargs):
        return kwargs.get("value", 0.0)

    def file_uploader(self, *args, **kwargs):
        return None

    def columns(self, spec):
        if isinstance(spec, list):
            n = len(spec)
        elif isinstance(spec, (int, float)):
            n = int(spec)
        else:
            n = 2
        return [self for _ in range(n)]

    def tabs(self, labels):
        return [self for _ in labels]

    def container(self, *args, **kwargs):
        return self

    def expander(self, *args, **kwargs):
        return self

    def status(self, *args, **kwargs):
        return self

    def spinner(self, *args, **kwargs):
        return self

    def empty(self, *args, **kwargs):
        return self

    def sidebar(self, *args, **kwargs):
        return self


def _no_op(*args, **kwargs):
    return None


def _make_fake_streamlit() -> DummyCtx:
    fake_st = DummyCtx()
    fake_st.session_state = {}  # real dict so subscript access works
    # ``st.sidebar`` is accessed as an attribute, not a call, so override
    object.__setattr__(fake_st, "sidebar", DummyCtx())
    return fake_st


def main() -> int:
    fake_st = _make_fake_streamlit()
    sys.modules["streamlit"] = fake_st  # type: ignore[assignment]

    import importlib.util

    target = ROOT / "ui" / "streamlit_app.py"
    spec = importlib.util.spec_from_file_location("streamlit_app_smoke", target)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        # st.stop() raises SystemExit — that's fine for our purposes
        print("OK (st.stop)")
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print(f"FAIL: {exc}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
