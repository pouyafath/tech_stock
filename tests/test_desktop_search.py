import pytest

tkinter = pytest.importorskip("tkinter")

from src.desktop_app import find_search_offsets


def test_find_search_offsets_is_case_insensitive() -> None:
    matches, truncated = find_search_offsets("AMD, amd, AmD", "amd")

    assert matches == [(0, 3), (5, 8), (10, 13)]
    assert truncated is False


def test_find_search_offsets_caps_broad_matches() -> None:
    matches, truncated = find_search_offsets("a " * 10, "a", limit=3)

    assert matches == [(0, 1), (2, 3), (4, 5)]
    assert truncated is True


def test_find_search_offsets_handles_no_match() -> None:
    matches, truncated = find_search_offsets("NVDA and CRM", "amd")

    assert matches == []
    assert truncated is False
