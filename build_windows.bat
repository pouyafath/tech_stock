@echo off
:: build_windows.bat — Build tech_stock.exe for Windows
::
:: Usage:
::   build_windows.bat
::
:: Requirements:
::   - Windows 10/11
::   - Python 3.11+ on PATH  (python.org installer, "Add to PATH" checked)
::   - Internet access for pip
::
:: Output: dist\tech_stock\tech_stock.exe  (standalone folder)
::         dist\tech_stock_setup.exe       (optional — requires Inno Setup)

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set APP_NAME=tech_stock
set DIST=%~dp0dist

echo.
echo  ══════════════════════════════════════
echo   tech_stock Windows build
echo  ══════════════════════════════════════
echo.

:: ── 1. Check Python ────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found on PATH.
    echo  Download from https://www.python.org/downloads/
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo  Using: %%v

:: ── 2. Create/activate venv ────────────────────────────────────────────────
if not exist ".venv\" (
    echo.
    echo  Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

:: ── 3. Install dependencies ────────────────────────────────────────────────
echo.
echo  Installing dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet "pyinstaller>=6.0"

:: ── 4. Generate .ico icon ──────────────────────────────────────────────────
if not exist "assets\icon.ico" (
    echo  Generating icon.ico...
    python -c "
from pathlib import Path
import struct, zlib

def write_ico(path):
    # Minimal 32x32 green icon in ICO format
    size = 32
    img_data = bytearray()
    for y in range(size):
        for x in range(size):
            cx, cy = size//2, size//2
            r = ((x-cx)**2 + (y-cy)**2) ** 0.5
            if r < size*0.46:
                img_data += bytes([94, 197, 34, 255])  # BGRA green
            else:
                img_data += bytes([0, 0, 0, 0])

    # BMP header for ICO
    bmp_header = struct.pack('<IiiHHIIiiII',
        40, size, -size, 1, 32, 0, len(img_data), 0, 0, 0, 0)
    img = bmp_header + bytes(img_data)

    ico_dir = struct.pack('<HHH', 0, 1, 1)
    img_entry = struct.pack('<BBBBHHII',
        size, size, 0, 0, 1, 32, len(img), 22)
    Path(path).write_bytes(ico_dir + img_entry + img)
    print('  icon.ico written')

import os; os.makedirs('assets', exist_ok=True)
write_ico('assets/icon.ico')
"
)

:: ── 5. Clean previous build ────────────────────────────────────────────────
echo.
echo  Cleaning previous build...
if exist "build\" rmdir /s /q build
if exist "%DIST%\%APP_NAME%\" rmdir /s /q "%DIST%\%APP_NAME%"

:: ── 6. PyInstaller ─────────────────────────────────────────────────────────
echo.
echo  Running PyInstaller (this takes 2-5 minutes)...
pyinstaller tech_stock.spec --noconfirm --clean
if errorlevel 1 (
    echo  ERROR: PyInstaller failed. Check output above.
    pause & exit /b 1
)

:: ── 7. Verify output ───────────────────────────────────────────────────────
if not exist "%DIST%\%APP_NAME%\%APP_NAME%.exe" (
    echo  ERROR: Expected %DIST%\%APP_NAME%\%APP_NAME%.exe not found.
    pause & exit /b 1
)

:: ── 8. Optional Inno Setup installer ──────────────────────────────────────
:: v1.19: AppVersion is now parsed from src\version.py and passed to iscc
:: via /D so the installer carries the real version (was hard-coded 1.0.0).
if exist "installer_windows.iss" (
    where iscc >nul 2>&1
    if not errorlevel 1 (
        echo.
        echo  Reading version from src\version.py ...
        for /f "tokens=2 delims== " %%v in ('findstr /B "APP_VERSION =" src\version.py') do (
            set APP_VERSION_RAW=%%v
        )
        set APP_VERSION=!APP_VERSION_RAW:"=!
        echo  Version: !APP_VERSION!
        echo.
        echo  Building installer with Inno Setup...
        iscc /DAppVersion=!APP_VERSION! installer_windows.iss
    ) else (
        echo  Inno Setup not found -- skipping installer. Install from https://jrsoftware.org/isinfo.php
    )
)

:: ── 8b. Optional code-signing hook ────────────────────────────────────────
:: Set SIGN_PFX_PATH and SIGN_PFX_PASSWORD in the environment to enable.
:: Without those, the installer ships unsigned (users will see a SmartScreen
:: prompt — they can click "More info" → "Run anyway").
if defined SIGN_PFX_PATH (
    where signtool >nul 2>&1
    if not errorlevel 1 (
        echo.
        echo  Signing dist\tech_stock_setup.exe ...
        signtool sign /f "%SIGN_PFX_PATH%" /p "%SIGN_PFX_PASSWORD%" /tr http://timestamp.sectigo.com /td SHA256 /fd SHA256 "%DIST%\tech_stock_setup.exe"
    ) else (
        echo  signtool not found -- skipping signing.
    )
)

:: ── 9. Summary ─────────────────────────────────────────────────────────────
echo.
echo  ══════════════════════════════════════
echo   Build complete!
echo   Output: dist\%APP_NAME%\%APP_NAME%.exe
echo.
echo   Distribute the entire dist\%APP_NAME%\ folder.
echo   Users double-click %APP_NAME%.exe to launch.
echo  ══════════════════════════════════════
echo.
pause
