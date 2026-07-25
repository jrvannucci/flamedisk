"""Glob exclude patterns and the live-progress callback."""

from __future__ import annotations

import io
import os
from pathlib import Path

from conftest import BIG_TOTAL, TREE_TOTAL, find_child

from flamedisk import scan
from flamedisk.cli import _progress_writer
from flamedisk.scanner import _is_glob

# ── glob excludes ──────────────────────────────────────────────────────────


def test_literal_exclude_still_exact(tree: Path):
    """A pattern with no glob characters matches the name exactly, as before."""
    root = scan(str(tree), exclude=["node_modules"])
    assert find_child(find_child(root, "big"), "node_modules") is None
    assert root.size == TREE_TOTAL - 300000


def test_glob_excludes_by_extension(tree: Path):
    """`*.bin` removes every .bin file at any depth, leaving only a.txt."""
    root = scan(str(tree), exclude=["*.bin"])
    assert root.size == 1000  # only a.txt survives
    assert find_child(root, "a.txt") is not None


def test_glob_excludes_directory_name(tree: Path):
    """A glob can match a directory, pruning its whole subtree."""
    root = scan(str(tree), exclude=["b*"])  # matches "big"
    assert find_child(root, "big") is None
    assert root.size == TREE_TOTAL - BIG_TOTAL


def test_mixed_literal_and_glob(tree: Path):
    root = scan(str(tree), exclude=["*.txt", "node_modules"])
    assert find_child(root, "a.txt") is None
    assert root.size == TREE_TOTAL - 1000 - 300000


def test_glob_applies_below_depth_cutoff(tree: Path):
    """The _dir_size_fast path (max_depth) must honour globs too, so a
    depth-limited total matches the full-walk total."""
    full = scan(str(tree), exclude=["*.bin"]).size
    cut = scan(str(tree), exclude=["*.bin"], max_depth=1).size
    assert cut == full == 1000


def test_is_glob_detection():
    assert _is_glob("*.log")
    assert _is_glob("file?.txt")
    assert _is_glob("cache[0-9]")
    assert not _is_glob("node_modules")
    assert not _is_glob(".git")


# ── progress callback ──────────────────────────────────────────────────────


def test_progress_final_totals(tree: Path):
    """The callback must fire and its final values must equal the real totals."""
    calls: list[tuple[int, int]] = []
    scan(str(tree), on_progress=lambda e, b: calls.append((e, b)))

    assert calls, "on_progress was never called"
    expected_entries = sum(len(dirs) + len(files) for _, dirs, files in os.walk(tree))
    assert calls[-1] == (expected_entries, TREE_TOTAL)


def test_progress_totals_monotonic(tree: Path):
    """Running totals never decrease."""
    calls: list[tuple[int, int]] = []
    scan(str(tree), on_progress=lambda e, b: calls.append((e, b)))
    entries = [e for e, _ in calls]
    nbytes = [b for _, b in calls]
    assert entries == sorted(entries)
    assert nbytes == sorted(nbytes)


def test_progress_omitted_is_fine(tree: Path):
    """No callback is the default and must not change the result."""
    assert scan(str(tree)).size == scan(str(tree), on_progress=None).size == TREE_TOTAL


def test_progress_writer_redraws_line():
    buf = io.StringIO()
    report = _progress_writer(buf)
    report(3, 2048)
    out = buf.getvalue()
    assert out.startswith("\r")
    assert "3 entries" in out
    assert "2.0 KB" in out
