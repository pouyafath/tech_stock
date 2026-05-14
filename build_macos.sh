#!/usr/bin/env bash
# build_macos.sh — Build tech_stock.dmg for macOS
#
# Usage:
#   ./build_macos.sh              # builds dist/tech_stock.dmg
#   ./build_macos.sh --skip-venv  # skip re-creating venv (faster rebuild)
#
# Requirements:
#   - macOS 12+
#   - Python 3.11+ (uses .venv if present, otherwise creates one)
#   - Xcode Command Line Tools: xcode-select --install

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="tech_stock"
DIST="$SCRIPT_DIR/dist"
APP_BUNDLE="$DIST/${APP_NAME}.app"
DMG_PATH="$DIST/${APP_NAME}.dmg"
STAGED="$DIST/dmg_staging"

# ── Colour helpers ─────────────────────────────────────────────────────────
green() { printf '\033[32m%s\033[0m\n' "$1"; }
blue()  { printf '\033[34m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; exit 1; }

# ── 0. Check macOS ──────────────────────────────────────────────────────────
[[ "$(uname)" == "Darwin" ]] || red "This script is macOS-only. Use build_windows.bat on Windows."
green "→ macOS confirmed"

# ── 1. Activate venv ────────────────────────────────────────────────────────
if [[ "$*" != *"--skip-venv"* ]]; then
    if [[ ! -d ".venv" ]]; then
        blue "  Creating .venv …"
        python3 -m venv .venv
    fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
blue "  Python: $(python --version)"

# ── 2. Install / upgrade build dependencies ─────────────────────────────────
blue "→ Installing dependencies …"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet "pyinstaller>=6.0"

# Optional: UPX compressor (makes bundle smaller; skip if not installed)
if ! command -v upx &>/dev/null; then
    blue "  UPX not found — skipping compression (install with: brew install upx)"
fi

# ── 3. Generate icon ────────────────────────────────────────────────────────
if [[ ! -f "assets/icon.icns" ]]; then
    blue "→ Generating icon …"
    python - << 'PYEOF'
import subprocess, os, shutil
from pathlib import Path

src = 'assets/icon.png'
if not Path(src).exists():
    print("  No assets/icon.png found — skipping icon generation")
    exit(0)

iconset = 'assets/icon.iconset'
os.makedirs(iconset, exist_ok=True)
for s in [16,32,64,128,256,512]:
    subprocess.run(['sips','-z',str(s),str(s),src,'--out',f'{iconset}/icon_{s}x{s}.png'], capture_output=True)
    subprocess.run(['sips','-z',str(s*2),str(s*2),src,'--out',f'{iconset}/icon_{s}x{s}@2x.png'], capture_output=True)
subprocess.run(['iconutil','-c','icns',iconset,'-o','assets/icon.icns'], check=True)
shutil.rmtree(iconset)
print("  icon.icns created")
PYEOF
fi

# ── 4. Clean previous build ─────────────────────────────────────────────────
blue "→ Cleaning previous build …"
rm -rf build/ "$APP_BUNDLE" "$DMG_PATH" "$STAGED"

# ── 5. PyInstaller ──────────────────────────────────────────────────────────
blue "→ Running PyInstaller …"
pyinstaller tech_stock.spec --noconfirm --clean 2>&1 | tail -20

[[ -d "$APP_BUNDLE" ]] || red "PyInstaller did not produce $APP_BUNDLE"
green "  .app bundle created: $APP_BUNDLE"

# ── 6. Ad-hoc code-sign (removes quarantine warning for local use) ──────────
blue "→ Code-signing (ad-hoc) …"
codesign --force --deep --sign - "$APP_BUNDLE" 2>/dev/null && green "  Signed." || blue "  Skipped (codesign not available)."

# ── 7. Build .dmg with hdiutil ──────────────────────────────────────────────
blue "→ Creating .dmg …"
mkdir -p "$STAGED"
cp -R "$APP_BUNDLE" "$STAGED/"

# Create a symlink so users can drag to Applications
ln -s /Applications "$STAGED/Applications"

# Create a writable temporary image
TEMP_DMG="$DIST/${APP_NAME}_tmp.dmg"
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$STAGED" \
    -ov \
    -format UDRW \
    "$TEMP_DMG" > /dev/null

# Convert to read-only compressed DMG
hdiutil convert "$TEMP_DMG" -format UDZO -o "$DMG_PATH" > /dev/null
rm -f "$TEMP_DMG"
rm -rf "$STAGED"

[[ -f "$DMG_PATH" ]] || red "DMG creation failed"
DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
green "  ✓ dist/${APP_NAME}.dmg  ($DMG_SIZE)"

# ── 8. Summary ──────────────────────────────────────────────────────────────
echo ""
green "════════════════════════════════════════"
green "  Build complete!"
green "  Output: dist/${APP_NAME}.dmg"
green ""
green "  Install: double-click the .dmg, drag"
green "  tech_stock.app to Applications."
green "════════════════════════════════════════"
