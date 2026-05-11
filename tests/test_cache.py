from src import cache


def test_cached_can_skip_writing_values(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return []

    first = cache.cached("news", "empty", 3600, loader, should_cache=lambda value: bool(value))
    second = cache.cached("news", "empty", 3600, loader, should_cache=lambda value: bool(value))

    assert first == []
    assert second == []
    assert calls["n"] == 2
    assert not list(tmp_path.rglob("*.pkl"))


def test_cached_ignores_existing_value_that_predicate_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    cache.cached("news", "maybe_empty", 3600, lambda: [], should_cache=lambda value: True)

    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [{"title": "fresh"}]

    value = cache.cached(
        "news",
        "maybe_empty",
        3600,
        loader,
        should_cache=lambda articles: bool(articles),
    )

    assert value == [{"title": "fresh"}]
    assert calls["n"] == 1
