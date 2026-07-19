"""Shared fixtures.

Sizes throughout the suite are deliberately distinct powers-of-ten-ish values
so that a wrong total identifies *which* file was miscounted, not just that
the number is off.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def write(path: Path, nbytes: int) -> Path:
    """Create *path* (and parents) containing exactly *nbytes* bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * nbytes)
    return path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small fixture tree with known sizes.

        root/
          a.txt                 1000
          big/
            b.bin              20000
            node_modules/
              junk.bin        300000
          empty/
          deep/
            l1/
              l2/
                deep.bin        5000

    Totals: root = 326000, big = 320000, deep = 5000, empty = 0.
    """
    root = tmp_path / "root"
    write(root / "a.txt", 1000)
    write(root / "big" / "b.bin", 20000)
    write(root / "big" / "node_modules" / "junk.bin", 300000)
    write(root / "deep" / "l1" / "l2" / "deep.bin", 5000)
    (root / "empty").mkdir(parents=True, exist_ok=True)
    return root


# Total bytes in the `tree` fixture, and per-subtree breakdowns.
TREE_TOTAL = 326000
BIG_TOTAL = 320000
NODE_MODULES_TOTAL = 300000
DEEP_TOTAL = 5000


def find_child(node, name: str):
    """Return the direct child of *node* named *name*, or None."""
    for child in node.children:
        if child.name == name:
            return child
    return None


def _supports_symlinks() -> bool:
    """True if this process can actually create a directory symlink.

    A runtime capability probe, not a platform check: Windows can do this
    under Developer Mode or elevation, and some Linux filesystems cannot.
    Probed once at import; the result drives the `needs_symlinks` marker.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dst = Path(tmp) / "dst"
        src.mkdir()
        try:
            os.symlink(src, dst, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


SYMLINKS_SUPPORTED = _supports_symlinks()

needs_symlinks = pytest.mark.skipif(
    not SYMLINKS_SUPPORTED,
    reason="this process cannot create symlinks "
           "(Windows needs Developer Mode or elevation)",
)
