#!/usr/bin/env bash
# build_linux.sh — Build a portable Linux artefact for tech_stock (v1.19).
#
# Default outputs:
#   - ./dist/tech_stock-x.y.z-linux-x86_64.tar.gz (always produced)
#   - ./dist/tech_stock-x86_64.AppImage (when appimagetool is available)
#
# Requirements (best-effort — script self-detects what's missing):
#   - Linux x86_64
#   - Python 3.11+
#   - appimagetool on PATH (optional — produces the AppImage)
#     Install: https://appimage.github.io/appimagetool/

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="tech_stock"
DIST="$SCRIPT_DIR/dist"
APPDIR="$DIST/${APP_NAME}.AppDir"

# ── Colour helpers ─────────────────────────────────────────────────────────
green() { printf '\033[32m%s\033[0m\n' "$1"; }
blue()  { printf '\033[34m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; exit 1; }

# ── 0. OS check ────────────────────────────────────────────────────────────
[[ "$(uname)" == "Linux" ]] || red "This script is Linux-only. Use build_macos.sh on macOS or build_windows.bat on Windows."

# ── 1. Version from src/version.py ─────────────────────────────────────────
APP_VERSION=$(grep '^APP_VERSION' src/version.py | head -1 | sed 's/.*"\(.*\)"/\1/')
green "→ Building tech_stock v${APP_VERSION}"

# ── 2. Activate venv ───────────────────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
    blue "  Creating .venv …"
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
blue "  Python: $(python --version)"

# ── 3. Install deps ────────────────────────────────────────────────────────
blue "→ Installing dependencies …"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet "pyinstaller>=6.0"

# ── 4. PyInstaller build ───────────────────────────────────────────────────
blue "→ Running PyInstaller …"
rm -rf build/ "$DIST/$APP_NAME"
pyinstaller tech_stock.spec --noconfirm --clean 2>&1 | tail -20
[[ -d "$DIST/$APP_NAME" ]] || red "PyInstaller did not produce $DIST/$APP_NAME"
green "  Built: $DIST/$APP_NAME/"

# ── 5. AppDir layout ───────────────────────────────────────────────────────
blue "→ Composing AppDir …"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -R "$DIST/$APP_NAME/." "$APPDIR/usr/bin/"

# Standard freedesktop .desktop file
cat > "$APPDIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=tech_stock
Comment=AI-powered portfolio advisor built on Claude
Exec=tech_stock
Icon=tech_stock
Categories=Finance;Office;
Terminal=false
EOF
cp "$APPDIR/$APP_NAME.desktop" "$APPDIR/usr/share/applications/"

# Icon — fall back to PNG if .ico-style 256x256 isn't present
if [[ -f "assets/icon.png" ]]; then
    cp assets/icon.png "$APPDIR/$APP_NAME.png"
    cp assets/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APP_NAME.png"
fi

# AppRun launcher
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/bin/tech_stock" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# ── 6. AppImage (optional) ─────────────────────────────────────────────────
APPIMAGE="$DIST/${APP_NAME}-x86_64.AppImage"
if command -v appimagetool >/dev/null 2>&1; then
    blue "→ Running appimagetool …"
    ARCH=x86_64 appimagetool "$APPDIR" "$APPIMAGE"
    green "  ✓ $APPIMAGE"
else
    blue "  appimagetool not found — skipping AppImage."
    blue "  Install AppImage builder: https://appimage.github.io/appimagetool/"
fi

# ── 7. Portable tarball (required) ─────────────────────────────────────────
TARBALL="$DIST/${APP_NAME}-${APP_VERSION}-linux-x86_64.tar.gz"
blue "→ Packaging Linux tarball …"
tar -C "$DIST" -czf "$TARBALL" "$APP_NAME/"
green "  ✓ $TARBALL"

green "════════════════════════════════════════"
green "  Build complete!"
green "  v$APP_VERSION"
green "════════════════════════════════════════"
