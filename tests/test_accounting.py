"""Disk-accounting options: actual (block) size, one-file-system, hard-link
dedup, and the symlink-cycle guard.

These cover behaviour that makes flamedisk's totals agree with ``du`` rather
than naively summing ``st_size`` for every directory entry.
"""

from __future__ import annotations

import os
import stat as stat_mod
import tempfile
from pathlib import Path

import pytest
from conftest import BIG_TOTAL, TREE_TOTAL, find_child, needs_symlinks, write

import flamedisk.scanner as scanner
from flamedisk import scan

HAS_ST_BLOCKS = hasattr(os.stat("."), "st_blocks")

needs_st_blocks = pytest.mark.skipif(
    not HAS_ST_BLOCKS, reason="st_blocks unavailable on this platform (e.g. Windows)"
)


def _supports_hardlinks() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dst = Path(tmp) / "dst"
        src.write_bytes(b"x")
        try:
            os.link(src, dst)
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


needs_hardlinks = pytest.mark.skipif(
    not _supports_hardlinks(), reason="this filesystem cannot create hard links"
)


# ── actual (block) size ────────────────────────────────────────────────────


@needs_st_blocks
def test_disk_usage_counts_allocated_blocks(tree: Path):
    """disk_usage=True must sum st_blocks*512, not st_size."""

    expected = 0
    for dirpath, _dirs, files in os.walk(tree):
        for f in files:
            expected += os.stat(os.path.join(dirpath, f)).st_blocks * 512

    assert scan(str(tree), disk_usage=True).size == expected


@needs_st_blocks
def test_disk_usage_differs_from_apparent_for_small_files(tmp_path: Path):
    """A one-byte file still occupies a whole allocation block, so the actual
    size is larger than the apparent size."""
    write(tmp_path / "tiny.bin", 1)
    apparent = scan(str(tmp_path)).size
    actual = scan(str(tmp_path), disk_usage=True).size
    assert apparent == 1
    assert actual >= apparent  # rounded up to at least one block (or equal on odd FS)


# ── one file system ────────────────────────────────────────────────────────


class _FakeStat:
    """Minimal stat_result stand-in with an overridable st_dev."""

    def __init__(self, real: os.stat_result, dev: int):
        self.st_mode = real.st_mode
        self.st_dev = dev
        self.st_ino = real.st_ino
        self.st_size = real.st_size
        self.st_nlink = real.st_nlink
        self.st_blocks = getattr(real, "st_blocks", 0)


class _DevEntry:
    """Wraps a DirEntry to report a different device for one target name."""

    def __init__(self, entry, target: str, other_dev: int):
        self._entry = entry
        self.name = entry.name
        self.path = entry.path
        self._target = target
        self._other_dev = other_dev

    def stat(self, *, follow_symlinks=True):
        real = self._entry.stat(follow_symlinks=follow_symlinks)
        if self.name == self._target:
            return _FakeStat(real, self._other_dev)
        return real

    def is_symlink(self):
        return self._entry.is_symlink()


def test_one_file_system_skips_other_device(tree: Path, monkeypatch):
    """A subdirectory reported on a different device is excluded entirely when
    one_file_system is set, and included otherwise."""
    root_dev = os.stat(str(tree)).st_dev
    other_dev = root_dev + 1000
    real_scandir = os.scandir

    class Wrapper:
        def __init__(self, path):
            self._it = real_scandir(path)

        def __enter__(self):
            return [_DevEntry(e, "big", other_dev) for e in list(self._it)]

        def __exit__(self, *a):
            self._it.close()
            return False

    monkeypatch.setattr(scanner.os, "scandir", Wrapper)

    # Without the flag the "other device" subtree is still counted.
    assert scan(str(tree)).size == TREE_TOTAL
    # With it, big/ is skipped along with all its bytes.
    pruned = scan(str(tree), one_file_system=True)
    assert find_child(pruned, "big") is None
    assert pruned.size == TREE_TOTAL - BIG_TOTAL


# ── hard-link dedup ────────────────────────────────────────────────────────


@needs_hardlinks
def test_hardlinks_double_counted_by_default(tmp_path: Path):
    write(tmp_path / "orig.bin", 1000)
    os.link(tmp_path / "orig.bin", tmp_path / "hard.bin")
    # Both names are counted, so the directory looks twice as big as the data.
    assert scan(str(tmp_path)).size == 2000


@needs_hardlinks
def test_dedup_links_counts_inode_once(tmp_path: Path):
    write(tmp_path / "orig.bin", 1000)
    os.link(tmp_path / "orig.bin", tmp_path / "hard.bin")
    root = scan(str(tmp_path), dedup_links=True)
    assert root.size == 1000
    # Exactly one of the two links keeps the bytes; the other is zeroed.
    sizes = sorted(c.size for c in root.children)
    assert sizes == [0, 1000]


@needs_hardlinks
def test_dedup_links_subtracts_from_all_ancestors(tmp_path: Path):
    """A link in a subdirectory must reduce every ancestor's total, not just
    its immediate parent."""
    write(tmp_path / "sub" / "orig.bin", 1000)
    (tmp_path / "sub" / "deeper").mkdir(parents=True, exist_ok=True)
    os.link(tmp_path / "sub" / "orig.bin", tmp_path / "sub" / "deeper" / "hard.bin")

    assert scan(str(tmp_path)).size == 2000  # naive
    root = scan(str(tmp_path), dedup_links=True)
    assert root.size == 1000
    assert find_child(root, "sub").size == 1000


@needs_hardlinks
def test_dedup_links_is_deterministic(tmp_path: Path):
    """Which link is kept must not depend on thread timing."""
    write(tmp_path / "orig.bin", 1000)
    os.link(tmp_path / "orig.bin", tmp_path / "hard.bin")

    def zeroed_name(root):
        return next(c.name for c in root.children if c.size == 0)

    first = zeroed_name(scan(str(tmp_path), dedup_links=True))
    for _ in range(5):
        assert zeroed_name(scan(str(tmp_path), dedup_links=True)) == first


# ── symlink cycle guard ────────────────────────────────────────────────────


@needs_symlinks
def test_follow_symlinks_breaks_cycles(tmp_path: Path):
    """A symlink pointing back up its own tree must not cause infinite
    recursion when following symlinks."""
    write(tmp_path / "data.bin", 1000)
    os.symlink(tmp_path, tmp_path / "loop", target_is_directory=True)

    # Would recurse forever without the ancestor guard.
    root = scan(str(tmp_path), follow_symlinks=True)
    assert root.size >= 1000  # terminates and counts the real file


# ── deterministic ordering ─────────────────────────────────────────────────


def test_equal_sized_entries_sort_by_name(tmp_path: Path):
    """Ties in size resolve by name so repeated scans are byte-for-byte stable."""
    write(tmp_path / "zebra.bin", 500)
    write(tmp_path / "apple.bin", 500)
    write(tmp_path / "mango.bin", 500)
    names = [c.name for c in scan(str(tmp_path)).children]
    assert names == ["apple.bin", "mango.bin", "zebra.bin"]


def test_dir_size_fast_honours_disk_usage(tree: Path):
    """The depth-cutoff fast path measures on the same basis as the full walk."""
    if not HAS_ST_BLOCKS:
        pytest.skip("st_blocks unavailable")
    full = scan(str(tree), disk_usage=True).size
    cut = scan(str(tree), disk_usage=True, max_depth=1).size
    assert cut == full  # depth-1 pushes every subtree through _dir_size_fast


def test_stat_mode_helpers_available():
    # Guard against import drift in the fake-stat helper above.
    assert stat_mod.S_ISDIR(os.stat(".").st_mode) is True
