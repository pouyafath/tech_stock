"""
cache.py
Simple pickle-based cache for expensive network calls (yfinance, news).
Files stored under data/.cache/ (gitignored). Safe on corruption — treats any
read/unpickle error as a cache miss and re-runs the loader.
"""

import hashlib
import pickle
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / "data" / ".cache"


def _cache_key_to_filename(namespace: str, key: str) -> Path:
    """Hash the namespace+key into a safe filename."""
    raw = f"{namespace}:{key}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:16]
    return CACHE_DIR / namespace / f"{digest}.pkl"


def _is_fresh(path: Path, ttl_seconds: int) -> bool:
    """True if path exists and mtime is within ttl."""
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_seconds


def cached(
    namespace: str,
    key: str,
    ttl_seconds: int,
    loader: Callable[[], Any],
    enabled: bool = True,
) -> Any:
    """
    Return cached value if fresh, otherwise call loader() and cache the result.

    Args:
        namespace: logical grouping, e.g. "market_data", "news", "historical_price"
        key: unique identifier within namespace, e.g. "NVDA_10"
        ttl_seconds: freshness window
        loader: zero-arg callable producing the value
        enabled: set False to bypass cache entirely

    Safe on corruption: any pickle error is swallowed and treated as cache miss.
    """
    if not enabled:
        return loader()

    path = _cache_key_to_filename(namespace, key)

    # Try to read from cache first
    if _is_fresh(path, ttl_seconds):
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            # Cache is corrupt or unreadable — fall through to loader
            pass

    # Cache miss or stale — compute and store
    value = loader()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".pkl.tmp")
        with open(tmp, "wb") as f:
            pickle.dump(value, f)
        tmp.replace(path)  # atomic
    except Exception:
        # Cache write failed — not fatal, value is still returned
        pass

    return value


def clear_cache(namespace: str = None):
    """Delete cached entries. If namespace given, only clear that namespace."""
    target = CACHE_DIR / namespace if namespace else CACHE_DIR
    if not target.exists():
        return
    if target.is_file():
        target.unlink()
        return
    for f in target.rglob("*.pkl"):
        try:
            f.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    # Self-test
    counter = {"n": 0}

    def slow_loader():
        counter["n"] += 1
        return f"computed-{counter['n']}"

    clear_cache("selftest")
    v1 = cached("selftest", "key1", 60, slow_loader)
    v2 = cached("selftest", "key1", 60, slow_loader)  # should hit cache
    v3 = cached("selftest", "key2", 60, slow_loader)  # different key → miss
    assert v1 == v2, f"Cache hit failed: {v1} != {v2}"
    assert v3 != v1, f"Different key should miss cache"
    assert counter["n"] == 2, f"Expected 2 loader calls, got {counter['n']}"
    print("✓ cache.py self-test passed")
    clear_cache("selftest")
