"""Scanner tests.

The scanner's whole job is producing correct byte totals, so most of these
assert on exact sizes against the `tree` fixture rather than on structure.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from flamedisk import Node, scan
from flamedisk.scanner import _dir_size_fast

from conftest import (
    BIG_TOTAL,
    DEEP_TOTAL,
    TREE_TOTAL,
    find_child,
    needs_symlinks,
    write,
)


# ── basic totals ──────────────────────────────────────────────────────────

def test_total_size(tree: Path):
    assert scan(str(tree)).size == TREE_TOTAL


def test_subtree_totals(tree: Path):
    root = scan(str(tree))
    assert find_child(root, "big").size == BIG_TOTAL
    assert find_child(root, "deep").size == DEEP_TOTAL
    assert find_child(root, "empty").size == 0
    assert find_child(root, "a.txt").size == 1000


def test_children_sorted_largest_first(tree: Path):
    root = scan(str(tree))
    sizes = [c.size for c in root.children]
    assert sizes == sorted(sizes, reverse=True)


def test_root_carries_path_children_do_not(tree: Path):
    root = scan(str(tree))
    assert root.path == os.path.abspath(str(tree))
    assert all(c.path == "" for c in root.children)


def test_dirs_flagged(tree: Path):
    root = scan(str(tree))
    assert root.is_dir
    assert find_child(root, "big").is_dir
    assert not find_child(root, "a.txt").is_dir


def test_empty_dir_is_a_childless_dir_node(tree: Path):
    empty = find_child(scan(str(tree)), "empty")
    assert empty.is_dir and empty.children == [] and empty.size == 0


def test_scan_nonexistent_path_returns_error_node(tmp_path: Path):
    node = scan(str(tmp_path / "does-not-exist"))
    assert node.error is not None
    assert node.size == 0


def test_scan_a_file_returns_single_node(tmp_path: Path):
    f = write(tmp_path / "lone.bin", 4321)
    node = scan(str(f))
    assert node.size == 4321
    assert not node.is_dir
    assert node.children == []


@pytest.mark.parametrize("workers", [1, 2, 8])
def test_worker_count_does_not_change_totals(tree: Path, workers: int):
    assert scan(str(tree), workers=workers).size == TREE_TOTAL


# ── exclude ───────────────────────────────────────────────────────────────

def test_exclude_top_level(tree: Path):
    root = scan(str(tree), exclude=["big"])
    assert root.size == TREE_TOTAL - BIG_TOTAL
    assert find_child(root, "big") is None


def test_exclude_applies_at_any_depth(tree: Path):
    """node_modules is nested two levels down, not at the root."""
    root = scan(str(tree), exclude=["node_modules"])
    assert root.size == TREE_TOTAL - 300000
    assert find_child(find_child(root, "big"), "node_modules") is None


# ── max_depth ─────────────────────────────────────────────────────────────

def test_depth_limit_truncates_tree_but_not_totals(tree: Path):
    """Nodes below the cutoff are dropped, but their bytes still count."""
    root = scan(str(tree), max_depth=1)
    assert root.size == TREE_TOTAL
    big = find_child(root, "big")
    assert big.size == BIG_TOTAL
    assert big.children == []


def test_depth_zero_is_unlimited(tree: Path):
    assert scan(str(tree), max_depth=0).size == scan(str(tree)).size


@pytest.mark.parametrize("depth", [1, 2, 3, 4, 99])
def test_total_is_depth_invariant(tree: Path, depth: int):
    assert scan(str(tree), max_depth=depth).size == TREE_TOTAL


# ── regression: exclude below the depth cutoff ────────────────────────────

@pytest.mark.parametrize("depth", [1, 2, 3])
def test_exclude_honoured_below_depth_cutoff(tree: Path, depth: int):
    """Regression: --depth used to disable --exclude for pruned subtrees.

    `_dir_size_fast` handled the max-depth cutoff but never received
    `exclude_set`, so excluded names were still counted toward the total.
    """
    root = scan(str(tree), max_depth=depth, exclude=["node_modules"])
    assert root.size == TREE_TOTAL - 300000


def test_exclude_result_matches_across_depths(tree: Path):
    """The excluded total must not depend on where the depth cutoff lands."""
    unlimited = scan(str(tree), exclude=["node_modules"]).size
    for depth in (1, 2, 3, 4):
        assert scan(str(tree), max_depth=depth, exclude=["node_modules"]).size == unlimited


def test_dir_size_fast_applies_exclude(tree: Path):
    assert _dir_size_fast(str(tree), set()) == TREE_TOTAL
    assert _dir_size_fast(str(tree), {"node_modules"}) == TREE_TOTAL - 300000
    assert _dir_size_fast(str(tree), {"big"}) == TREE_TOTAL - BIG_TOTAL


# ── min_size ──────────────────────────────────────────────────────────────

def test_min_size_prunes_nodes_but_not_totals(tree: Path):
    """min_size is a display filter: bytes are counted before the check."""
    root = scan(str(tree), min_size=10_000)
    assert root.size == TREE_TOTAL
    assert find_child(root, "a.txt") is None          # 1000 < 10000, pruned
    assert find_child(find_child(root, "big"), "b.bin") is not None  # 20000, kept


def test_min_size_does_not_prune_directories(tree: Path):
    """`empty` is 0 bytes but must survive any min_size."""
    root = scan(str(tree), min_size=1_000_000)
    assert find_child(root, "empty") is not None
    assert root.size == TREE_TOTAL


# ── regression: mid-scan OSError ──────────────────────────────────────────

@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError(2, "No such file or directory"),
        NotADirectoryError(20, "Not a directory"),
        PermissionError(13, "Permission denied"),
        OSError(5, "Input/output error"),
    ],
    ids=["missing", "not-a-dir", "denied", "io-error"],
)
def test_scandir_failure_does_not_abort_scan(tree: Path, monkeypatch, exc):
    """Regression: only PermissionError was caught, so any other OSError
    raised mid-walk propagated out of scan() and lost the entire result."""
    import flamedisk.scanner as scanner

    real_scandir = os.scandir

    def flaky(path):
        if os.path.basename(str(path)) == "big":
            raise exc
        return real_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", flaky)

    root = scan(str(tree))

    # The rest of the tree still scanned...
    assert find_child(root, "a.txt").size == 1000
    assert find_child(root, "deep").size == DEEP_TOTAL
    # ...and the failure is reported rather than silently dropped.
    big = find_child(root, "big")
    assert big is not None and big.error is not None
    assert root.size == TREE_TOTAL - BIG_TOTAL


def test_error_message_is_the_real_exception(tree: Path, monkeypatch):
    """Regression: entry-stat failures used to record the literal string
    "stat failed", which told the user nothing about the cause."""
    import flamedisk.scanner as scanner

    real_scandir = os.scandir

    class BadEntry:
        def __init__(self, entry):
            self.name = entry.name
            self.path = entry.path

        def stat(self, *a, **kw):
            raise PermissionError(13, "Permission denied")

        def is_symlink(self):
            return False

    class Wrapper:
        def __init__(self, path):
            self._it = real_scandir(path)

        def __enter__(self):
            return [BadEntry(e) if e.name == "a.txt" else e for e in self._it]

        def __exit__(self, *a):
            self._it.close()
            return False

    monkeypatch.setattr(scanner.os, "scandir", Wrapper)

    bad = find_child(scan(str(tree)), "a.txt")
    assert bad.error != "stat failed"
    assert "Permission denied" in bad.error


def test_errored_nodes_are_zero_sized(tree: Path, monkeypatch):
    """The report relies on this: errored entries contribute no bytes, which
    is why they cannot be surfaced in the size-proportional flame graph."""
    import flamedisk.scanner as scanner

    real_scandir = os.scandir

    def flaky(path):
        if os.path.basename(str(path)) == "big":
            raise PermissionError(13, "Permission denied")
        return real_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", flaky)

    def walk(n):
        if n.error is not None:
            assert n.size == 0, f"{n.name} has an error but non-zero size"
        for c in n.children:
            walk(c)

    walk(scan(str(tree)))


def test_worker_exception_does_not_abort_scan(tree: Path, monkeypatch):
    """The fut.result() guard: if a pool worker raises instead of returning a
    Node, the remaining subtrees must still be collected."""
    import flamedisk.scanner as scanner

    real_sync = scanner._scan_dir_sync

    def exploding(path, name, *a, **kw):
        if name == "big":
            raise OSError(5, "worker blew up")
        return real_sync(path, name, *a, **kw)

    monkeypatch.setattr(scanner, "_scan_dir_sync", exploding)

    root = scan(str(tree))
    big = find_child(root, "big")
    assert big is not None and big.error is not None
    assert "worker blew up" in big.error
    assert big.size == 0
    # Siblings survived.
    assert find_child(root, "deep").size == DEEP_TOTAL
    assert root.size == TREE_TOTAL - BIG_TOTAL


def test_deep_entry_stat_failure_is_recorded(tree: Path, monkeypatch):
    """Same as the shallow case but inside _scan_dir_sync, which is a separate
    code path from _scan_dir."""
    import flamedisk.scanner as scanner

    real_scandir = os.scandir

    class BadEntry:
        def __init__(self, entry):
            self.name = entry.name
            self.path = entry.path

        def stat(self, *a, **kw):
            raise OSError(13, "deep stat blocked")

        def is_symlink(self):
            return False

    class Wrapper:
        def __init__(self, path):
            self._path = path
            self._it = real_scandir(path)

        def __enter__(self):
            entries = list(self._it)
            # b.bin lives in root/big, reached via a pool worker (_scan_dir_sync)
            return [BadEntry(e) if e.name == "b.bin" else e for e in entries]

        def __exit__(self, *a):
            self._it.close()
            return False

    monkeypatch.setattr(scanner.os, "scandir", Wrapper)

    big = find_child(scan(str(tree)), "big")
    bad = find_child(big, "b.bin")
    assert bad is not None and bad.error is not None
    assert "deep stat blocked" in bad.error


def test_dir_size_fast_survives_unreadable_subdir(tree: Path, monkeypatch):
    """_dir_size_fast swallows OSError so a depth-limited scan still totals
    whatever it could read."""
    import flamedisk.scanner as scanner

    real_scandir = os.scandir

    def flaky(path):
        if os.path.basename(str(path)) == "node_modules":
            raise PermissionError(13, "Permission denied")
        return real_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", flaky)

    # depth=1 pushes root/big through _dir_size_fast, which then hits the
    # unreadable node_modules underneath it.
    root = scan(str(tree), max_depth=1)
    assert root.size == TREE_TOTAL - 300000


def test_root_scandir_failure_is_reported(tree: Path, monkeypatch):
    import flamedisk.scanner as scanner

    def always_fail(path):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(scanner.os, "scandir", always_fail)
    root = scan(str(tree))
    assert root.error is not None
    assert root.size == 0


def test_entry_stat_failure_is_recorded(tree: Path, monkeypatch):
    """A failing per-entry stat yields an error node, not a crash."""
    import flamedisk.scanner as scanner

    real_scandir = os.scandir

    class BadEntry:
        def __init__(self, entry):
            self._e = entry
            self.name = entry.name
            self.path = entry.path

        def stat(self, *a, **kw):
            raise OSError(13, "stat blocked")

        def is_symlink(self):
            return False

    class Wrapper:
        """Stands in for the os.scandir context manager, swapping one entry."""

        def __init__(self, path):
            self._it = real_scandir(path)

        def __enter__(self):
            return [BadEntry(e) if e.name == "a.txt" else e for e in self._it]

        def __exit__(self, *a):
            self._it.close()
            return False

    monkeypatch.setattr(scanner.os, "scandir", Wrapper)

    root = scan(str(tree))
    bad = find_child(root, "a.txt")
    assert bad is not None and bad.error is not None
    assert bad.size == 0
    # The rest of the tree is unaffected.
    assert find_child(root, "big").size == BIG_TOTAL


# ── symlinks ──────────────────────────────────────────────────────────────

@needs_symlinks
def test_symlinked_dir_not_descended_by_default(tmp_path: Path):
    target = tmp_path / "target"
    write(target / "payload.bin", 50_000)
    root = tmp_path / "root"
    root.mkdir()
    write(root / "real.bin", 7)
    os.symlink(target, root / "link", target_is_directory=True)

    scanned = scan(str(root))
    link = find_child(scanned, "link")
    # Present as a leaf, and the 50 KB behind it is not counted.
    assert link is not None
    assert link.children == []
    assert scanned.size < 50_000


@needs_symlinks
def test_nested_symlink_not_descended(tmp_path: Path):
    """Nested links go through _scan_dir_sync, a separate branch from the
    root-level handling in _scan_dir."""
    target = tmp_path / "target"
    write(target / "payload.bin", 50_000)
    root = tmp_path / "root"
    write(root / "sub" / "real.bin", 11)
    os.symlink(target, root / "sub" / "link", target_is_directory=True)

    sub = find_child(scan(str(root)), "sub")
    link = find_child(sub, "link")
    assert link is not None and link.children == []
    assert sub.size < 50_000


@needs_symlinks
def test_follow_symlinks_descends(tmp_path: Path):
    target = tmp_path / "target"
    write(target / "payload.bin", 50_000)
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(target, root / "link", target_is_directory=True)

    assert scan(str(root), follow_symlinks=True).size >= 50_000


# ── Node.to_dict ──────────────────────────────────────────────────────────

def test_to_dict_uses_compact_keys(tree: Path):
    d = scan(str(tree)).to_dict()
    assert d["n"] == "root"
    assert d["s"] == TREE_TOTAL
    assert d["d"] == 1
    assert "p" in d and "c" in d


def test_to_dict_omits_absent_fields():
    d = Node(name="f", path="", size=5).to_dict()
    assert d == {"n": "f", "s": 5}


def test_to_dict_includes_error():
    d = Node(name="f", path="", size=0, error="boom").to_dict()
    assert d["e"] == "boom"


def test_to_dict_is_json_serialisable(tree: Path):
    import json
    json.dumps(scan(str(tree)).to_dict())


# ── unicode / odd names ───────────────────────────────────────────────────

def test_unicode_and_spaced_names(tmp_path: Path):
    root = tmp_path / "root"
    write(root / "café ☕.txt", 100)
    write(root / "my dir" / "file.bin", 200)
    scanned = scan(str(root))
    assert scanned.size == 300
    assert {c.name for c in scanned.children} == {"café ☕.txt", "my dir"}
