# Release process

> **TL;DR** — push a `vX.Y.Z` tag, GitHub Actions does the rest.

## Daily flow

1. Land work on `codex/report-output-fixes` (or your branch).
2. Run the full suite locally:
   ```
   .venv/bin/python -m pytest -q
   .venv/bin/ruff check src/ tests/ ui/ tools/
   .venv/bin/ruff format --check src/ tests/ ui/ tools/
   ```
3. Bump `src/version.py`.
4. Add a new section to the top of `CHANGELOG.md`:
   ```markdown
   ## [1.20.0] — 2026-05-27

   ### Added
   - ...
   ### Fixed
   - ...

   ---
   ```
5. Commit + push the branch.
6. When ready to release: tag and push.
   ```
   git tag v1.20.0
   git push --tags
   ```

That's it. CI takes over.

## What CI does on a `v*.*.*` tag push

`.github/workflows/build_release.yml`:

```
                          ┌──────────────────────┐
                          │  test-gate (matrix)  │
                          │  macOS / Win / Linux │
                          │  pytest + ruff       │
                          └──────┬───────────────┘
                                 │ on green
       ┌─────────────────────────┼─────────────────────────┐
       ▼                         ▼                         ▼
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│ build-macos  │         │ build-windows│         │ build-linux  │
│ → .dmg       │         │ → .exe       │         │ → AppImage   │
│              │         │ → installer  │         │ → tarball    │
└──────┬───────┘         └──────┬───────┘         └──────┬───────┘
       │                        │                        │
       └────────────┬───────────┴────────────────────────┘
                    ▼
            ┌───────────────┐
            │   release     │   reads CHANGELOG.md section for the tag
            │ → draft       │   computes SHA256SUMS.txt
            │ → attach all  │   uploads every artefact
            └───────────────┘
```

### test-gate

Runs on macOS-14, windows-latest, ubuntu-22.04 in parallel:

- ruff format check (no drift)
- ruff lint
- `pytest -q`

If any platform fails the gate, the build jobs **do not run**. The
release is silently aborted — there's no draft to publish.

### build-macos

- `pyinstaller tech_stock.spec` produces `dist/tech_stock.app`
- Ad-hoc code-sign (`codesign --force --deep --sign -`) — placeholder
  for the future Developer ID + notarytool flow
- `hdiutil` packages into `dist/tech_stock.dmg`
- Artefact uploaded as `tech_stock-macos`

### build-windows

- `pyinstaller tech_stock.spec` produces `dist/tech_stock/`
- Reads `APP_VERSION` from `src/version.py` and passes it as
  `/DAppVersion=…` to `iscc`
- Inno Setup (installed via Chocolatey) builds
  `dist/tech_stock_setup.exe`
- Two artefacts uploaded: the folder build + the installer

### build-linux

- Installs `appimagetool` from upstream
- Runs `build_linux.sh` which composes the AppDir layout and produces
  `dist/tech_stock-x86_64.AppImage`
- Falls back to a tarball when `appimagetool` is missing
- Both potential artefacts uploaded with `continue-on-error: true`

### release

- Extracts the version from the tag (`refs/tags/v1.20.0` → `1.20.0`)
- Runs `python -m src.changelog_utils 1.20.0` to extract the
  matching CHANGELOG section, falling back to `--latest` if the
  version isn't in the file yet
- Downloads every artefact
- Generates `SHA256SUMS.txt` with `sha256sum *.dmg *.exe *.zip *.AppImage *.tar.gz`
- Publishes a **draft** GitHub Release with:
  - Title: `tech_stock vX.Y.Z`
  - Body: the parsed CHANGELOG section
  - Files: all artefacts + the checksum file

The release is intentionally drafted so a human can review the body
and any attached binaries before publishing.

## Hot fixes / re-tagging

If something is wrong with an artefact:

```
git tag -d v1.20.0
git push --delete origin v1.20.0
# fix
git tag v1.20.0
git push --tags
```

The CI re-runs end-to-end. The draft release is regenerated.

## Future tightening (planned)

- macOS notarisation via `notarytool` once an Apple Developer ID is
  available (the workflow comment marks the spot).
- Windows code-signing via `signtool` and a PFX certificate (the
  `build_windows.bat` already has the hook; CI just needs the secrets).
- Snyk / `pip-audit` step as part of `test-gate` so dependency vulns
  block releases.

## Files involved

- `.github/workflows/build_release.yml` — the workflow
- `.github/workflows/tests.yml` — runs on every push, not tied to releases
- `src/changelog_utils.py` — CHANGELOG parser
- `build_macos.sh`, `build_windows.bat`, `build_linux.sh` — invoked
  locally for builds outside CI
- `tech_stock.spec` — PyInstaller specification (consumed by macOS,
  Windows, Linux jobs)
- `installer_windows.iss` — Inno Setup script with HKCU CSV
  association and Start-Menu group
