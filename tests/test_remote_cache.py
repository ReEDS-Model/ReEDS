import os
import time
import hashlib

import pandas as pd
import pytest

import reeds.remote as remote


def _hash_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


@pytest.fixture
def sample_file(tmp_path):
    fpath = tmp_path / "sample.bin"
    fpath.write_bytes(b"a" * 1024)
    return fpath


def _spy_on_get_md5sum(monkeypatch):
    """Wrap remote.get_md5sum so tests can assert whether it was (not) called."""
    calls = []
    real_get_md5sum = remote.get_md5sum

    def spy(filepath):
        calls.append(filepath)
        return real_get_md5sum(filepath)

    monkeypatch.setattr(remote, 'get_md5sum', spy)
    return calls


def test_cache_miss_computes_and_stores_entry(sample_file):
    """First hash of a file computes the MD5 and stores a full cache entry."""
    cache = {}
    md5 = remote._cached_md5sum(sample_file, cache)
    stat = sample_file.stat()
    assert md5 == _hash_bytes(sample_file.read_bytes())
    assert cache[str(sample_file)] == {
        'size': stat.st_size,
        'mtime_ns': stat.st_mtime_ns,
        'ino': stat.st_ino,
        'md5': md5,
    }


def test_cache_hit_skips_rehash(sample_file, monkeypatch):
    """An up-to-date cache returns the stored MD5 without calling get_md5sum again."""
    cache = {}
    # populate cache
    remote._cached_md5sum(sample_file, cache)

    calls = _spy_on_get_md5sum(monkeypatch)
    md5 = remote._cached_md5sum(sample_file, cache)

    assert md5 == _hash_bytes(sample_file.read_bytes())
    # get_md5sum was never called: served from cache
    assert calls == []


def test_cache_invalidated_by_mtime_change(sample_file, monkeypatch):
    """Changing a file's content and mtime invalidates its cache entry."""
    cache = {}
    remote._cached_md5sum(sample_file, cache)

    # Change both content and mtime
    sample_file.write_bytes(b"b" * 1024)
    new_time = time.time() + 5
    os.utime(sample_file, (new_time, new_time))

    calls = _spy_on_get_md5sum(monkeypatch)
    md5 = remote._cached_md5sum(sample_file, cache)

    assert md5 == _hash_bytes(sample_file.read_bytes())
    # cache correctly invalidated and re-hashed
    assert calls == [sample_file]


def test_cache_invalidated_by_inode_change_with_same_size_and_mtime(tmp_path):
    """Replacing a file's inode invalidates the cache even if size and mtime are unchanged."""
    fpath = tmp_path / "sample.bin"
    fpath.write_bytes(b"a" * 1024)
    cache = {}
    md5_before = remote._cached_md5sum(fpath, cache)
    stat_before = fpath.stat()

    # Simulate a file being atomically replaced (e.g. re-downloaded) in a way
    # that happens to preserve size and mtime -- this changes the inode, which
    # the cache must catch even though size/mtime alone would look unchanged.
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"b" * 1024)
    os.replace(replacement, fpath)
    os.utime(fpath, ns=(stat_before.st_mtime_ns, stat_before.st_mtime_ns))

    if fpath.stat().st_ino == stat_before.st_ino:
        pytest.skip("filesystem reused the same inode on replace; nothing to test")

    md5_after = remote._cached_md5sum(fpath, cache)
    assert md5_after != md5_before
    assert md5_after == _hash_bytes(fpath.read_bytes())


def test_download_remote_files_recovers_from_corrupt_cache(tmp_path, monkeypatch, capsys):
    """A corrupt cache file is reported and rebuilt instead of crashing the run."""
    cache_path = tmp_path / '.remote_files_cache.json'
    cache_path.write_text('{not valid json')
    monkeypatch.setattr(remote, 'CACHE_PATH', cache_path)
    monkeypatch.setattr(
        remote, 'get_remote_filemap',
        lambda: pd.DataFrame({'inputs_path': pd.Series(dtype=object)}),
    )

    # should not raise despite the corrupt cache
    remote.download_remote_files()

    assert 'rebuilding checksum cache' in capsys.readouterr().out.lower()
    # a fresh, valid cache file was written back out
    assert cache_path.is_file()
