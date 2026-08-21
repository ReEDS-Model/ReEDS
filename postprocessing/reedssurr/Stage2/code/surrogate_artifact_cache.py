"""Process-wide cache for trained surrogate artifacts.

Bokeh executes the dashboard script separately for every browser session, but
normal imported Python modules are shared by all sessions in the server
process.  Keeping the cache here therefore prevents every connected user from
loading another copy of the same large model files into memory.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from surrogate_predict import load_artifact


@lru_cache(maxsize=32)
def _load_versioned(path: str, mtime_ns: int, size: int) -> dict:
    """Load one immutable file version.

    ``mtime_ns`` and ``size`` are part of the cache key so replacing an
    artifact on disk automatically creates a fresh cache entry.
    """
    del mtime_ns, size
    return load_artifact(path)


def load_artifact_cached(path: str | Path) -> dict:
    """Return a process-wide cached artifact for ``path``."""
    resolved = Path(path).resolve()
    stat = resolved.stat()
    return _load_versioned(str(resolved), stat.st_mtime_ns, stat.st_size)


def clear_artifact_cache() -> None:
    """Clear all cached artifacts, primarily for tests and maintenance."""
    _load_versioned.cache_clear()
