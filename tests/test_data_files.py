from types import SimpleNamespace

from src import data_files
from src.updater import UpdateInfo

HOLDINGS_HEADER = "Symbol,Quantity,Market Price,Market Price Currency,Book Value (Market),Market Value,Market Unrealized Returns"


def test_save_and_load_data_file_defaults(monkeypatch, tmp_path):
    from src import main

    monkeypatch.setattr(main, "CONFIG_DIR", tmp_path / "config")
    holdings = tmp_path / "holdings-report-2026-06-13.csv"
    activities = tmp_path / "activities-export-2026-06-13.csv"

    path = data_files.save_data_file_defaults(holdings, activities, clear_missing=True)
    loaded = data_files.load_data_file_defaults()

    assert path == tmp_path / "config" / "data_files.json"
    assert loaded["holdings"] == str(holdings)
    assert loaded["activities"] == str(activities)


def test_selected_data_files_prefers_saved_existing_paths(monkeypatch, tmp_path):
    from src import main

    monkeypatch.setattr(main, "CONFIG_DIR", tmp_path / "config")
    saved = tmp_path / "holdings-report-2026-06-13.csv"
    saved.write_text(f"{HOLDINGS_HEADER}\nNVDA,1,100,USD,90,100,10\n", encoding="utf-8")
    data_files.save_data_file_defaults(saved, None, clear_missing=True)
    monkeypatch.setattr(main, "find_csv_by_date", lambda prefix: None)

    selected = data_files.selected_data_files()

    assert selected["holdings"] == saved


def test_pre_run_checklist_blocks_missing_key_and_sample_holdings(monkeypatch, tmp_path):
    from src import main

    sample = tmp_path / "holdings-report-sample.csv"
    sample.write_text(f"{HOLDINGS_HEADER}\nNVDA,1,100,USD,90,100,10\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(main, "_load_api_keys_from_file", lambda: None)
    monkeypatch.setattr(data_files, "check_for_update", lambda **_kwargs: UpdateInfo(current_version="1.30.0"))
    monkeypatch.setattr(
        data_files,
        "check_budget",
        lambda expected_cost_usd=0.0: SimpleNamespace(
            hard_block=False,
            soft_warn=False,
            message="Budget check passed.",
        ),
    )

    checklist = data_files.build_pre_run_checklist(holdings_csv=sample)

    assert checklist["can_run"] is False
    assert checklist["blocking_count"] >= 2
    assert any(row["check"] == "Anthropic API key" and row["blocking"] for row in checklist["rows"])
    assert any(row["check"] == "Holdings CSV" and row["blocking"] for row in checklist["rows"])


def test_pre_run_checklist_allows_dry_run_with_sample_without_key(monkeypatch, tmp_path):
    from src import main

    sample = tmp_path / "holdings-report-sample.csv"
    sample.write_text(f"{HOLDINGS_HEADER}\nNVDA,1,100,USD,90,100,10\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(main, "_load_api_keys_from_file", lambda: None)
    monkeypatch.setattr(data_files, "check_for_update", lambda **_kwargs: UpdateInfo(current_version="1.30.0"))
    monkeypatch.setattr(
        data_files,
        "check_budget",
        lambda expected_cost_usd=0.0: SimpleNamespace(
            hard_block=False,
            soft_warn=False,
            message="Budget check passed.",
        ),
    )

    checklist = data_files.build_pre_run_checklist(holdings_csv=sample, dry_run=True)

    assert checklist["can_run"] is True
    assert any(row["check"] == "Anthropic API key" and row["status"] == "SKIP" for row in checklist["rows"])
