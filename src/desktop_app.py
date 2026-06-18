"""Compatibility launcher for the embedded desktop app.

The implementation lives in :mod:`src.desktop.app`.  This module keeps old
imports and commands working:

- ``import src.desktop_app``
- ``python src/desktop_app.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.desktop import app as _app

main = _app.main

if __name__ != "__main__":
    sys.modules[__name__] = _app


if __name__ == "__main__":
    main()
