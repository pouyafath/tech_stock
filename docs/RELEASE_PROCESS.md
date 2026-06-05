# Release Process

> **TL;DR**: merge the release-ready code, push a `vX.Y.Z` tag, let GitHub
> Actions build a draft release, smoke-test the attached packages, then publish
> the draft.

The workflow also has a manual `workflow_dispatch` trigger. A manual run is
useful for testing the three-platform build, but the release job only creates a
GitHub Release when the workflow is running from a version tag.

## Daily flow

1. Land work on a feature branch and merge it into `main`.
2. Run the full suite locally:
   ```
   .venv/bin/python -m pytest -q
   .venv/bin/ruff check src/ tests/ ui/ tools/
   .venv/bin/ruff format --check src/ tests/ ui/ tools/
   ```
3. Bump `src/version.py`.
4. Add a new section to the top of `CHANGELOG.md`:
   ```markdown
   ## [1.23.0] — 2026-06-05

   ### Added
   - ...
   ### Fixed
   - ...

   ---
   ```
5. Commit + push the branch.
6. When ready to release: tag and push.
   ```
   git checkout main
   git pull --ff-only
   git tag v1.23.0
   git push origin v1.23.0
   ```

CI now takes over and creates a draft release after the test and build gates
pass.

## What CI Does On A `v*.*.*` Tag Push

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

- Extracts the version from the tag (`refs/tags/v1.23.0` -> `1.23.0`)
- Runs `python -m src.changelog_utils 1.23.0` to extract the
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

## Draft Release Checklist

Do not publish a draft release until these checks pass:

1. Download every attached artifact: macOS `.dmg`, Windows installer/zip,
   Linux AppImage or tarball, and `SHA256SUMS.txt`.
2. Verify checksums:
   ```
   shasum -a 256 -c SHA256SUMS.txt
   ```
   On Windows, use `CertUtil -hashfile <artifact> SHA256` and compare to
   `SHA256SUMS.txt`.
3. Smoke-open each package on the target OS. Confirm the app starts,
   opens the embedded Desktop App, and the Updates tab reports the
   published version.
4. Run `python src/main.py doctor --json --force-refresh --demo-smoke`
   from a source checkout and confirm:
   - latest public release equals the tag you are publishing
   - update result is live, not cached
   - release asset and checksum availability are true where expected
   - demo smoke passes without API keys or Anthropic spend
5. Publish the draft release only after the checklist is clean.

If the in-app updater still sees an older public version, use
`doctor --json --force-refresh` to separate a real GitHub Releases issue
from a local update-cache issue.

## Hot Fixes And Re-Tagging

If something is wrong with an artefact:

```
git tag -d v1.23.0
git push --delete origin v1.23.0
# fix
git tag v1.23.0
git push origin v1.23.0
```

The CI re-runs end-to-end. The draft release is regenerated. If a tag
has already been published publicly, prefer a new patch/minor tag rather
than reusing history.

## V2 Readiness Gate

Do not ship `v2.0.0` until all of these are true:

- Latest public GitHub Release matches the repo version.
- The in-app updater works from an older installed release to the new
  release and preserves `reports/`, `data/`, `temporary_upload/`,
  `config/`, `API_KEYS.txt`, `.env`, logs, and journals.
- Demo mode and `doctor --json --demo-smoke` work without API keys.
- Installers pass smoke tests on macOS, Windows, and Linux.
- Workspace schema and recommendation-log schema are documented and
  stable enough for migration rules.
- Broker abstraction is no longer Wealthsimple-only.
- Production installers are signed/notarized where the platform expects
  it.

Reserve `v2.0.1` for the first patch **after** a real public `v2.0.0`.

## Future Tightening

- macOS notarisation via `notarytool` once an Apple Developer ID is
  available (the workflow comment marks the spot).
- Windows code-signing via `signtool` and a PFX certificate (the
  `build_windows.bat` already has the hook; CI just needs the secrets).
- `pip-audit` step as part of `test-gate` so dependency vulns block
  releases after false-positive handling is documented.

## Files Involved

- `.github/workflows/build_release.yml` — the workflow
- `.github/workflows/tests.yml` — runs on every push, not tied to releases
- `src/changelog_utils.py` — CHANGELOG parser
- `src/preflight.py` — doctor/preflight payload and demo smoke test
- `build_macos.sh`, `build_windows.bat`, `build_linux.sh` — invoked
  locally for builds outside CI
- `tech_stock.spec` — PyInstaller specification (consumed by macOS,
  Windows, Linux jobs)
- `installer_windows.iss` — Inno Setup script with HKCU CSV
  association and Start-Menu group
