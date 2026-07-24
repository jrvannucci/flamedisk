"""
Filesystem scanner — walks a directory tree and returns a :class:`Node` tree
with cumulative byte sizes.

Performance notes
-----------------
* Uses ``os.scandir`` exclusively — ``DirEntry`` stat results are cached by
  the OS so we call ``.stat()`` once per entry rather than ``os.lstat`` +
  a second ``stat``.
* Uses ``concurrent.futures.ThreadPoolExecutor`` for parallel subtree scanning.
  I/O-bound directory walks release the GIL on the syscall, so threads give
  genuine speedup proportional to storage concurrency (SSDs / network FS).
  Only direct children of the root are dispatched to the pool; all deeper
  recursion runs synchronously inside each worker (``_scan_dir_sync``).  This
  prevents the deadlock that previously occurred when all threads blocked on
  ``fut.result()`` waiting for grandchild tasks that could never start because
  the pool was already at capacity.
* Single correct iterative post-order DFS (no double-scan bug from 0.4.0).
* ``_dir_size_fast`` is iterative, not recursive, avoiding Python stack limits
  on deep trees.
* Per-entry stat: one ``entry.stat()`` call per entry; ``st_mode`` is used for
  both dir and symlink detection, avoiding ``entry.is_dir()`` +
  ``entry.is_symlink()`` double-call.
* Sorting is deferred to after all children are collected.
"""

from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Node:
    """A single file or directory in the scanned tree.

    Attributes:
        name:     Basename of the entry.
        path:     Absolute path (only populated on the root node; deeper
                  nodes omit this to reduce JSON payload).
        size:     Size in bytes. For directories this is the recursive sum
                  of all descendant file sizes.
        children: Child nodes, sorted largest-first. Empty for files.
        is_dir:   ``True`` if this entry is a directory.
        error:    Non-None if the entry could not be read.
    """

    name: str
    path: str
    size: int = 0
    children: List["Node"] = field(default_factory=list)
    is_dir: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Return a compact JSON-serialisable representation.

        ``path`` and ``error`` are omitted when absent to keep payload small.
        ``children`` is omitted for leaf nodes.
        """
        d: dict = {"n": self.name, "s": self.size}
        if self.is_dir:
            d["d"] = 1
        if self.path:
            d["p"] = self.path
        if self.error:
            d["e"] = self.error
        if self.children:
            d["c"] = [ch.to_dict() for ch in self.children]
        return d


def scan(
    root: str,
    *,
    max_depth: int = 0,
    min_size: int = 0,
    follow_symlinks: bool = False,
    exclude: Optional[List[str]] = None,
    workers: int = 0,
) -> Node:
    """Recursively scan *root* and return a :class:`Node` tree.

    Uses a thread pool to scan independent subtrees in parallel, which gives
    significant speedup on SSDs and network file systems (I/O-bound work
    releases the GIL).

    Args:
        root:            Path to scan.
        max_depth:       Max recursion depth (0 = unlimited).
        min_size:        Prune file leaves smaller than this many bytes.
                         Directories are never pruned.
        follow_symlinks: Follow symlinks to directories.
        exclude:         Entry *names* to skip entirely.
        workers:         Thread-pool size. 0 = ``min(32, os.cpu_count()*4)``
                         (I/O-bound, so more threads than CPUs helps).

    Returns:
        Node: Root node with ``size`` = total bytes under *root*.
    """
    root = os.path.abspath(root)
    exclude_set: set[str] = set(exclude or [])

    if workers <= 0:
        workers = min(32, (os.cpu_count() or 1) * 4)

    root_name = os.path.basename(root) or root

    try:
        st = os.stat(root)
    except OSError as exc:
        return Node(name=root_name, path=root, size=0, error=str(exc))

    if not stat.S_ISDIR(st.st_mode):
        return Node(name=root_name, path=root, size=st.st_size)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        root_node = _scan_dir(
            root,
            root_name,
            0,
            max_depth,
            min_size,
            follow_symlinks,
            exclude_set,
            pool,
        )

    return root_node


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _scan_dir(
    path: str,
    name: str,
    depth: int,
    max_depth: int,
    min_size: int,
    follow_symlinks: bool,
    exclude_set: set[str],
    pool: ThreadPoolExecutor,
) -> Node:
    """Scan a single directory, dispatching immediate children to the thread pool.

    Only the *direct* subdirectories of the root are submitted to the pool.
    Deeper recursion happens synchronously inside each worker thread via
    ``_scan_dir_sync``.  This avoids the thread-pool deadlock that occurs when
    every worker blocks on ``fut.result()`` waiting for grandchild tasks that
    can never start because the pool is already saturated.
    """
    node = Node(name=name, path=path if depth == 0 else "", is_dir=True)

    if max_depth and depth >= max_depth:
        node.size = _dir_size_fast(path, exclude_set)
        return node

    try:
        with os.scandir(path) as it:
            entries = list(it)
    except OSError as exc:
        # Any OSError, not just PermissionError: directories vanish mid-scan
        # (FileNotFoundError), turn out not to be directories
        # (NotADirectoryError), or fail on stale network handles.  Record the
        # error on this node and keep scanning the rest of the tree.
        node.error = str(exc)
        return node

    # Separate dirs (need recursion) from files (cheap inline)
    dir_futures: list[tuple[str, str, Future]] = []  # (entry_path, entry_name, future)

    for entry in entries:
        if entry.name in exclude_set:
            continue

        try:
            # One stat call; covers dir, symlink, and size.
            st = entry.stat(follow_symlinks=follow_symlinks)
            mode = st.st_mode
        except OSError as exc:
            # Keep the real message — "stat failed" told the user nothing about
            # whether this was a permissions problem, a broken link, or a race.
            node.children.append(Node(name=entry.name, path="", size=0, error=str(exc)))
            continue

        is_lnk = entry.is_symlink()
        is_dir = stat.S_ISDIR(mode)

        if is_lnk and not follow_symlinks:
            # Count symlink target size but don't descend.
            try:
                sz = entry.stat(follow_symlinks=False).st_size
            except OSError:
                sz = 0
            node.size += sz
            if sz >= min_size:
                node.children.append(Node(name=entry.name, path="", size=sz))
            continue

        if is_dir:
            # Submit each direct child subtree to the pool.  The worker calls
            # _scan_dir_sync (no further pool submissions) so threads never
            # block waiting for pool capacity — deadlock is impossible.
            fut = pool.submit(
                _scan_dir_sync,
                entry.path,
                entry.name,
                depth + 1,
                max_depth,
                min_size,
                follow_symlinks,
                exclude_set,
            )
            dir_futures.append((entry.path, entry.name, fut))
        else:
            sz = st.st_size
            node.size += sz
            if sz >= min_size:
                node.children.append(Node(name=entry.name, path="", size=sz))

    # Collect directory results.  A worker that dies unexpectedly must not
    # take the whole scan with it — record the failure on a stub node and
    # carry on with the remaining subtrees.
    for _ep, _en, fut in dir_futures:
        try:
            child = fut.result()
        except OSError as exc:
            child = Node(name=_en, path="", is_dir=True, error=str(exc))
        node.size += child.size
        node.children.append(child)

    node.children.sort(key=lambda n: n.size, reverse=True)
    return node


def _scan_dir_sync(
    path: str,
    name: str,
    depth: int,
    max_depth: int,
    min_size: int,
    follow_symlinks: bool,
    exclude_set: set[str],
) -> Node:
    """Recursively scan a directory without touching the thread pool.

    Called by worker threads (submitted from ``_scan_dir``).  All deeper
    recursion is synchronous so this function never blocks on external futures
    and cannot contribute to a pool deadlock.
    """
    node = Node(name=name, path="", is_dir=True)

    if max_depth and depth >= max_depth:
        node.size = _dir_size_fast(path, exclude_set)
        return node

    try:
        with os.scandir(path) as it:
            entries = list(it)
    except OSError as exc:
        node.error = str(exc)
        return node

    for entry in entries:
        if entry.name in exclude_set:
            continue

        try:
            st = entry.stat(follow_symlinks=follow_symlinks)
            mode = st.st_mode
        except OSError as exc:
            # Keep the real message — "stat failed" told the user nothing about
            # whether this was a permissions problem, a broken link, or a race.
            node.children.append(Node(name=entry.name, path="", size=0, error=str(exc)))
            continue

        is_lnk = entry.is_symlink()
        is_dir = stat.S_ISDIR(mode)

        if is_lnk and not follow_symlinks:
            try:
                sz = entry.stat(follow_symlinks=False).st_size
            except OSError:
                sz = 0
            node.size += sz
            if sz >= min_size:
                node.children.append(Node(name=entry.name, path="", size=sz))
            continue

        if is_dir:
            child = _scan_dir_sync(
                entry.path,
                entry.name,
                depth + 1,
                max_depth,
                min_size,
                follow_symlinks,
                exclude_set,
            )
            node.size += child.size
            node.children.append(child)
        else:
            sz = st.st_size
            node.size += sz
            if sz >= min_size:
                node.children.append(Node(name=entry.name, path="", size=sz))

    node.children.sort(key=lambda n: n.size, reverse=True)
    return node


def _dir_size_fast(path: str, exclude_set: set[str]) -> int:
    """Iterative byte-count with no Node allocation (used at max-depth cutoff).

    ``exclude_set`` is applied at every level, matching the behaviour of the
    full-tree walk.  Without it, excluded names below the depth cutoff would
    still be counted, making ``--depth`` and ``--exclude`` give wrong totals
    when combined.

    ``min_size`` is deliberately *not* applied: in the full walk it only prunes
    nodes from the returned tree, never from the accumulated byte total.
    """
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    if entry.name in exclude_set:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total
