"""Compatibility launcher for the embedded desktop app.

The implementation lives in :mod:`src.desktop.app` so the desktop UI can be
split into smaller components over time without breaking existing commands such
as ``python src/desktop_app.py`` or imports from ``src.desktop_app``.
"""

from __future__ import annotations

import sys

from src.desktop import app as _app

main = _app.main

if __name__ != "__main__":
    sys.modules[__name__] = _app


if __name__ == "__main__":
    main()
