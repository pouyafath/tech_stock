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


def test_cached_disabled_bypasses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return "result"

    v1 = cache.cached("ns", "key", 3600, loader, enabled=False)
    v2 = cache.cached("ns", "key", 3600, loader, enabled=False)
    assert v1 == "result"
    assert calls["n"] == 2  # no cache, called twice


def test_cached_hits_on_fresh_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return "value"

    v1 = cache.cached("ns2", "key1", 3600, loader)
    v2 = cache.cached("ns2", "key1", 3600, loader)  # should hit
    assert v1 == "value"
    assert v2 == "value"
    assert calls["n"] == 1


def test_clear_cache_removes_pkl_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.cached("ns3", "key1", 3600, lambda: "x")
    assert list(tmp_path.rglob("*.pkl"))
    cache.clear_cache("ns3")
    assert not list(tmp_path.rglob("*.pkl"))


def test_clear_cache_all_namespaces(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.cached("nsA", "key1", 3600, lambda: "a")
    cache.cached("nsB", "key1", 3600, lambda: "b")
    cache.clear_cache()
    assert not list(tmp_path.rglob("*.pkl"))


def test_cached_handles_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    # Write a fresh but corrupt .pkl
    import hashlib

    raw = b"ns4:key1"
    digest = hashlib.sha1(raw).hexdigest()[:16]
    path = tmp_path / "ns4" / f"{digest}.pkl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not valid pickle data")

    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return "recovered"

    # corrupt file should cause cache miss → loader is called
    result = cache.cached("ns4", "key1", 3600, loader)
    assert result == "recovered"
    assert calls["n"] == 1
