from pathlib import Path

from src import ui_support


def test_save_api_key_updates_existing_file(tmp_path: Path, monkeypatch) -> None:
    api_file = tmp_path / "API_KEYS.txt"
    api_file.write_text("# keys\nANTHROPIC_API_KEY=old\n", encoding="utf-8")
    monkeypatch.setattr(ui_support, "api_key_search_paths", lambda: [api_file])

    path = ui_support.save_api_key("ANTHROPIC_API_KEY", "new-key")

    assert path == api_file
    assert "ANTHROPIC_API_KEY=new-key" in api_file.read_text(encoding="utf-8")


def test_save_api_key_adds_new_key_to_existing_file(tmp_path: Path, monkeypatch) -> None:
    api_file = tmp_path / "API_KEYS.txt"
    api_file.write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    monkeypatch.setattr(ui_support, "api_key_search_paths", lambda: [api_file])

    ui_support.save_api_key("FINNHUB_API_KEY", "finnhub-test")

    content = api_file.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-test" in content
    assert "FINNHUB_API_KEY=finnhub-test" in content


def test_save_api_key_collapses_duplicate_key_lines(tmp_path: Path, monkeypatch) -> None:
    api_file = tmp_path / "API_KEYS.txt"
    api_file.write_text("POLYGON_API_KEY=old\nPOLYGON_API_KEY=older\n", encoding="utf-8")
    monkeypatch.setattr(ui_support, "api_key_search_paths", lambda: [api_file])

    ui_support.save_api_key("POLYGON_API_KEY", "new")

    assert api_file.read_text(encoding="utf-8").splitlines() == ["POLYGON_API_KEY=new"]


def test_delete_api_key_removes_from_all_discovered_files(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "API_KEYS.txt"
    second = tmp_path / ".env"
    first.write_text("FINNHUB_API_KEY=one\nPOLYGON_API_KEY=polygon\n", encoding="utf-8")
    second.write_text("FINNHUB_API_KEY=two\n", encoding="utf-8")
    monkeypatch.setattr(ui_support, "api_key_search_paths", lambda: [first, second])
    monkeypatch.setenv("FINNHUB_API_KEY", "one")

    touched = ui_support.delete_api_key("FINNHUB_API_KEY")

    assert touched == [first, second]
    assert "FINNHUB_API_KEY" not in first.read_text(encoding="utf-8")
    assert "POLYGON_API_KEY=polygon" in first.read_text(encoding="utf-8")
    assert "FINNHUB_API_KEY" not in second.read_text(encoding="utf-8")
