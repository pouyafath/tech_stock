# tech_stock.spec  — PyInstaller build specification
#
# Build on macOS:   pyinstaller tech_stock.spec
# Build on Windows: pyinstaller tech_stock.spec
#
# The output is always placed in dist/:
#   macOS   → dist/tech_stock.app   (then wrapped in .dmg by build_macos.sh)
#   Windows → dist/tech_stock/      + dist/tech_stock.exe  (--onedir for speed)

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)  # directory containing this .spec file
version_ns = {}
exec((ROOT / "src" / "version.py").read_text(), version_ns)
APP_VERSION = version_ns.get("APP_VERSION", "1.0.0")

# ── Data files ────────────────────────────────────────────────────────────────
# Streamlit ships a large static/ directory (JS, CSS, images) that must be
# included verbatim.  collect_data_files walks the installed package and
# returns (src_path, dest_rel_dir) pairs.
datas = []
datas += collect_data_files("streamlit")
datas += collect_data_files("textual")
datas += collect_data_files("altair")
datas += collect_data_files("pyarrow")      # required by streamlit
datas += collect_data_files("vaderSentiment")
datas += collect_data_files("certifi")      # CA bundle for HTTPS update checks

# Our own source trees
datas += [(str(ROOT / "src"),  "src")]
datas += [(str(ROOT / "ui"),   "ui")]
datas += [(str(ROOT / "config"), "config")]
for filename in ("API_KEYS.template.txt", ".env.example"):
    path = ROOT / filename
    if path.exists():
        datas += [(str(path), ".")]

# ── Hidden imports ────────────────────────────────────────────────────────────
# Modules that are imported dynamically (plugins, lazy-loaded, etc.)
hiddenimports = [
    # Streamlit internals loaded at runtime
    "streamlit.web.bootstrap",
    "streamlit.web.server",
    "streamlit.runtime",
    "streamlit.runtime.scriptrunner",
    "streamlit.elements",
    "streamlit.components.v1",
    # Textual
    "textual",
    "textual.widgets",
    "textual.app",
    "textual.css",
    # Data / science
    "pandas",
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.offsets",
    "pandas._libs.skiplist",
    "pyarrow",
    "pyarrow.vendored.version",
    "numpy",
    "yfinance",
    "requests",
    "urllib3",
    "certifi",
    # Anthropic SDK
    "anthropic",
    "httpx",
    "httpcore",
    # Project modules
    "src.main",
    "src.ui_support",
    "src.updater",
    "src.version",
    "src.desktop_app",
    "src.claude_analyst",
    "src.market_data",
    "src.portfolio_loader",
    "src.portfolio_analytics",
    "src.report_quality",
    "src.backtester",
    "src.enricher",
    "src.report_renderer",
    "src.constants",
    "src._utils",
    # Other
    "vaderSentiment.vaderSentiment",
    "jsonschema",
    "tenacity",
    "dotenv",
    "python_dotenv",
    "tkinter",
    "tkinter.font",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "tkinter.ttk",
]
hiddenimports += collect_submodules("streamlit")
hiddenimports += collect_submodules("anthropic")
hiddenimports += collect_submodules("textual")

# ── Platform-specific icon ────────────────────────────────────────────────────
if sys.platform == "darwin":
    icon = str(ROOT / "assets" / "icon.icns")
elif sys.platform == "win32":
    icon = str(ROOT / "assets" / "icon.ico")
else:
    icon = None

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "src" / "app_gui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "pyinstaller_hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "sklearn",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "sphinx",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

# ── EXE / app bundle ──────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # --onedir: binaries go in COLLECT
    name="tech_stock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,              # No black terminal window on Windows/macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="tech_stock",
)

# ── macOS .app bundle ─────────────────────────────────────────────────────────
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="tech_stock.app",
        icon=icon,
        bundle_identifier="com.techstock.app",
        info_plist={
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,   # supports dark mode
            "LSMinimumSystemVersion": "12.0",
            "CFBundleDisplayName": "tech_stock",
            "NSHumanReadableCopyright": "© 2026 tech_stock",
        },
    )
