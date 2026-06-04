# Contributing to tech_stock

Thanks for being here. This document is the operating manual: what the
review bar is, how the test/lint/format flow works, what the design
tenets are. The friendly intro lives in [the README](README.md). The
deep technical map lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The release flow lives in [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).
User-facing behavior is documented in
[docs/USER_GUIDE.md](docs/USER_GUIDE.md) and common recovery steps live in
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## Quick start

```bash
git clone https://github.com/pouyafath/tech_stock.git
cd tech_stock

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Verify it works:

```bash
.venv/bin/python -m pytest -q                       # full suite
.venv/bin/ruff check src/ tests/ ui/ tools/         # lint
.venv/bin/ruff format --check src/ tests/ ui/ tools/ # format gate
```

All three must be green before you push.

---

## Design tenets

Every PR is reviewed against these. If your change conflicts with one,
explain why in the commit message — there's almost always a good reason
when it makes sense to break a tenet.

### 1. Never silently swallow exceptions

Every `except Exception:` either recovers explicitly with a structured
log event, or surfaces an error to the user. The v1.17 observability
pass removed 17 silent excepts from the API clients. Don't add new
ones.

```python
# Bad
try:
    data = json.loads(payload)
except Exception:
    return None

# Good
try:
    data = json.loads(payload)
except json.JSONDecodeError as exc:
    log_event("finnhub", "error", "json_decode", f"Decode failed: {exc}", {"endpoint": endpoint})
    return None
```

### 2. Additive schema

Adding a field to a dict / JSON output / function return is fine.
Renaming or removing one breaks downstream consumers (reports,
CSVs, the Learning tab, the Claude prompt, the GitHub Release CI).

If you must break a schema, bump a major version and mention it in
the CHANGELOG entry.

### 3. Tests with every feature

Every new module ships with a test file. The default verdict is "if
it isn't tested, it doesn't ship." The current bar is ≥ 60% coverage
for new code; ≥ 30% for `main.py`-style orchestration glue.

Run only the tests you care about during development:

```bash
.venv/bin/python -m pytest tests/test_backtester_calibration.py -v
.venv/bin/python -m pytest -k "calibration"
```

### 4. Production = default-safe

Opt-in by default. A misconfigured user should still get a working
app. Examples:

- `monthly_budget_usd` defaults to 0 (= no cap).
- Notification channels default ON but no-op when the OS backend is
  missing.
- The wizard is bypassed when `config/settings.json` already has
  recognised state — existing users see no change after upgrade.

### 5. Tools, not toys

Every UI surface should answer a real user question. Avoid features
that look impressive but don't change a decision.

Examples that earned their tab: **Diagnostics** answers "why is this
slow?", **Performance** answers "how am I doing?", **Learning**
answers "is my conviction calibrated?", **Schedule** answers "can I
forget about it?". If you can't write a one-sentence "this answers ⟨X⟩"
description, the tab probably isn't ready.

---

## Daily workflow

### Branch + commit

```bash
git checkout -b feat/your-feature
# work
.venv/bin/ruff format src/ tests/ ui/ tools/
.venv/bin/ruff check src/ tests/ ui/ tools/
.venv/bin/python -m pytest -q
git add ...
git commit -m "..."
git push -u origin feat/your-feature
```

### Commit message style

Used by every recent commit. The pattern is:

```
<type>(<scope>): <short summary>

<wide body explaining WHY, with bullets for individual changes>

Version bumped: X.Y.Z → A.B.C   (only on releases)

Co-Authored-By: ...
```

Where `type` is one of:

- `feat` — user-visible new feature
- `fix` — bug fix
- `chore` — formatting, deps, build
- `docs` — documentation only
- `refactor` — internal restructuring, no behaviour change
- `test` — test-only changes

`scope` is the area of the codebase (e.g. `ui`, `macos`, `learning`,
`backtester`, `v1.19`). Lowercase. Keep the summary ≤ 70 chars; put
detail in the body.

Real examples:

- `feat(ui): production-grade UI overhaul — v1.15.0`
- `fix(v1.19.1): close the v1.19 loose ends — CLI flags, workspace export, desktop wizard hook`
- `feat(learning): close the loop — per-horizon edge, risk-adjusted sizing, thesis-text drift, Learning tab (v1.16.0)`

### Pull-request review

1. Title: `<type>(<scope>): <short>` (same as the squashed commit
   message).
2. Description: what + why. Reference any issue (`closes #N`).
3. The CI tests gate must be green. CI runs `pytest + ruff` on
   macOS, Windows, and Linux.
4. PR review focuses on the design tenets above, schema impact, and
   whether the new tests actually cover the new code.

---

## Adding a new UI tab

The pattern is consistent across Streamlit and Tk Desktop:

1. **Data aggregator** in `src/ui_support.py` — a single function
   that returns a dict. Pure-ish, never raises, accumulates soft
   errors into an `errors` list.

   ```python
   def my_view() -> dict[str, Any]:
       out: dict[str, Any] = {"errors": []}
       try:
           ...
       except Exception as exc:
           out["errors"].append(f"my_view: {exc}")
       return out
   ```

2. **Streamlit render function** in `ui/streamlit_app.py`:

   ```python
   def _render_my_tab() -> None:
       view = my_view()
       if not view or view.get("error"):
           _html(empty_state("Nothing yet", "Generate a report first."))
           return
       ...
   ```

3. **Tk Desktop** counterpart in `src/desktop_app.py` with a
   `_build_my_tab` + `refresh_my_tab` pair; register the tab in
   `_build_tabs` and add a `_on_tab_changed` case so the data loads
   lazily.

4. **Shared visual language** — use `src/ui_theme.py` helpers
   (`action_badge`, `health_badge`, `empty_state`, `hero`,
   `metric_card`, `conviction_bar`, etc.) so the new tab matches the
   rest of the app.

5. **Tests**:
   - Unit-test the aggregator's shape + soft-error path.
   - Smoke-test the Streamlit module via `tools/smoke_streamlit.py`.
   - Add a Desktop syntax/parser test (we can't easily exercise Tk
     widgets in CI, but we verify the methods exist).

---

## Adding a new API source

Three required pieces:

1. **Client module** in `src/`. Pattern is `<source>_client.py`. Every
   client logs structured events on every error (HTTP 4xx, JSON
   decode, rate limit, cache failure):

   ```python
   from src.observability import log_event

   def _request(...):
       r = requests.get(...)
       if r.status_code >= 400:
           log_event("source_name", "error", f"http_{r.status_code}", ...)
           return None
       try:
           return r.json()
       except Exception as exc:
           log_event("source_name", "error", "json_decode", f"...: {exc}", ...)
           return None
   ```

2. **Cache layer** in `src/cache.py`. Set a reasonable TTL via the
   `cached(...)` helper rather than re-implementing cache logic.

3. **Health surface** — the source automatically appears in the
   Diagnostics tab once it's logging events. No extra wiring needed.

---

## Adding a new CLI flag

`src/main.py` already has the argparse setup. Add the flag, document
what it does in the help string, then handle it in the `main()`
function. **Always** test it with `tests/test_cli_flags.py` — the
test is a subprocess invocation of `python -m src.main --help` that
asserts your flag appears in the help output.

```python
parser.add_argument(
    "--my-flag",
    action="store_true",
    help="One-line description (will appear in --help).",
)
```

---

## Files you should never commit

- `.env`, `API_KEYS.txt` — secrets
- `data/recommendations_log/` — your portfolio history
- `data/decision_journal.json`, `data/thesis_log.json` — your decisions
- `data/cost_log.jsonl` — your spend
- `data/.cache/` — pickle cache
- `data/paper_portfolio.json` — simulated portfolio state
- `reports/`, `temporary_upload/`, `exports/`, `logs/`, `cache/`
- `dist/`, `build/`, `.venv/`
- `.claude/` artefacts

All of these are in `.gitignore`. If you add a new piece of writable
state, add the path there too.

---

## Areas where contributions are most welcome

- **Tax-account logic** — CAD-first defaults, TFSA / RRSP / RESP /
  Non-registered rules (TLH only fires on non-registered, US-withholding
  hint for TFSA holding US dividend stocks, etc.). The user data already
  has account-type from the Wealthsimple CSV; the model doesn't use it
  yet.
- **Email / Slack notification backends** — `src/notifications.py`
  already has the channel-gated dispatch. Add `EmailBackend` (SMTP)
  and `SlackBackend` (incoming webhook).
- **Async / parallel Phase 2 enrichment** — `src/enriched_data.py`
  currently does Phase 2 (Alpha Vantage) sequentially. A small
  `concurrent.futures` rewrite would speed reports by 5–15%.
- **PDF report export** — `src/report_generator.py` produces
  markdown. A `pypandoc`-style PDF path would be useful for sharing.
- **Mobile-responsive Streamlit** — CSS media queries + tab collapse.
- **Multi-portfolio support** — many users have a TFSA + RRSP at
  Wealthsimple. The portfolio_loader already reads multi-account
  CSVs but the rest of the pipeline assumes one portfolio.

---

## Questions

- Open an issue for architectural questions or proposed major changes.
- For small bug fixes, just send the PR.
- For style/formatting nits, run `ruff format` first.
