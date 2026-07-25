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
* Sorting is deferred to after all children are collected, and is keyed on
  ``(-size, name)`` so equal-sized entries have a stable, reproducible order
  rather than following filesystem iteration order.

Size accounting
---------------
By default a file contributes its *apparent* size (``st_size``). With
``disk_usage=True`` it contributes its *allocated* size (``st_blocks * 512``),
matching plain ``du``; on platforms where ``st_blocks`` is unavailable (notably
Windows) this transparently falls back to the apparent size.

``one_file_system=True`` skips directories that live on a different device than
the scan root (like ``du -x``), so scanning ``/`` does not wander into
``/proc``, ``/sys``, or network mounts.

``dedup_links=True`` counts a hard-linked file only once (like ``du``): the
first occurrence in a deterministic largest-first traversal keeps its size and
every later link is treated as zero bytes, so totals are not inflated by files
that share storage. Hard-link data comes from ``st_ino``/``st_dev``; entries
without a real inode number (Windows ``scandir`` reports ``st_ino == 0``) are
never deduplicated, so the total is at worst as high as the un-deduplicated one.

When ``follow_symlinks=True`` the scanner tracks the ``(st_dev, st_ino)`` of
every directory on the current path and refuses to re-enter one, so a symlink
cycle can no longer cause infinite recursion.
"""

from __future__ import annotations

import os
import stat
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field


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
        dev:      Device id, recorded only for hard-link candidates (files with
                  a link count above one) when ``dedup_links`` is requested.
        ino:      Inode number, recorded under the same conditions as ``dev``.
        nlink:    Hard-link count, recorded under the same conditions as ``dev``.

    ``dev``/``ino``/``nlink`` are transient scan bookkeeping used by hard-link
    deduplication; they are never serialised (see :meth:`to_dict`).
    """

    name: str
    path: str
    size: int = 0
    children: list[Node] = field(default_factory=list)
    is_dir: bool = False
    error: str | None = None
    dev: int = 0
    ino: int = 0
    nlink: int = 0

    def to_dict(self) -> dict:
        """Return a compact JSON-serialisable representation.

        ``path`` and ``error`` are omitted when absent to keep payload small.
        ``children`` is omitted for leaf nodes. The hard-link bookkeeping
        fields (``dev``/``ino``/``nlink``) are never included.
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


@dataclass(frozen=True)
class _Opts:
    """Immutable bundle of scan options threaded through the recursion.

    Passing one frozen object keeps ``_scan_dir``/``_scan_dir_sync`` signatures
    readable and guarantees every level of the walk sees identical settings.
    """

    max_depth: int
    min_size: int
    follow_symlinks: bool
    exclude_set: frozenset[str]
    disk_usage: bool
    one_file_system: bool
    root_dev: int
    track_links: bool


def scan(
    root: str,
    *,
    max_depth: int = 0,
    min_size: int = 0,
    follow_symlinks: bool = False,
    exclude: list[str] | None = None,
    workers: int = 0,
    disk_usage: bool = False,
    one_file_system: bool = False,
    dedup_links: bool = False,
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
        follow_symlinks: Follow symlinks to directories. Symlink cycles are
                         detected and skipped rather than recursed into.
        exclude:         Entry *names* to skip entirely.
        workers:         Thread-pool size. 0 = ``min(32, os.cpu_count()*4)``
                         (I/O-bound, so more threads than CPUs helps).
        disk_usage:      Measure allocated blocks (``st_blocks * 512``) instead
                         of apparent size (``st_size``), matching ``du``. Falls
                         back to apparent size where ``st_blocks`` is missing.
        one_file_system: Do not descend into directories on a different device
                         than *root* (like ``du -x``).
        dedup_links:     Count each hard-linked inode only once.

    Returns:
        Node: Root node with ``size`` = total bytes under *root*.
    """
    root = os.path.abspath(root)
    exclude_set = frozenset(exclude or [])

    if workers <= 0:
        workers = min(32, (os.cpu_count() or 1) * 4)

    root_name = os.path.basename(root) or root

    try:
        st = os.stat(root)
    except OSError as exc:
        return Node(name=root_name, path=root, size=0, error=str(exc))

    if not stat.S_ISDIR(st.st_mode):
        return Node(name=root_name, path=root, size=_entry_size(st, disk_usage))

    opts = _Opts(
        max_depth=max_depth,
        min_size=min_size,
        follow_symlinks=follow_symlinks,
        exclude_set=exclude_set,
        disk_usage=disk_usage,
        one_file_system=one_file_system,
        root_dev=st.st_dev,
        track_links=dedup_links,
    )

    root_key = (st.st_dev, st.st_ino)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        root_node = _scan_dir(root, root_name, 0, frozenset({root_key}), opts, pool)

    if dedup_links:
        _dedup_hardlinks(root_node)

    return root_node


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _entry_size(st: os.stat_result, disk_usage: bool) -> int:
    """Bytes attributed to a single entry.

    With *disk_usage*, use the allocated block count (``st_blocks`` counts
    512-byte blocks by definition, regardless of the filesystem's own block
    size). ``st_blocks`` is absent on some platforms (Windows); fall back to
    the apparent size there.
    """
    if disk_usage:
        blocks = getattr(st, "st_blocks", None)
        if blocks is not None:
            return blocks * 512
    return st.st_size


def _dir_identity(path: str, st: os.stat_result, opts: _Opts) -> tuple[int, int]:
    """Return ``(st_dev, st_ino)`` for a directory, reliably.

    ``os.scandir`` does not populate ``st_dev``/``st_ino`` on every platform
    (Windows reports zeroes), which would defeat ``one_file_system`` and the
    symlink-cycle guard. When a feature needs the identity and ``scandir`` left
    it blank, fall back to a direct ``os.stat``. On Unix ``scandir`` already
    fills these in, so no extra syscall happens.
    """
    dev, ino = st.st_dev, st.st_ino
    if (opts.one_file_system or opts.follow_symlinks) and dev == 0:
        try:
            rst = os.stat(path, follow_symlinks=opts.follow_symlinks)
            dev, ino = rst.st_dev, rst.st_ino
        except OSError:
            pass
    return dev, ino


def _make_file_node(name: str, path: str, st: os.stat_result, opts: _Opts) -> Node:
    """Build a leaf node, recording hard-link identity when deduplicating.

    As with :func:`_dir_identity`, ``scandir`` may not report ``st_ino``/
    ``st_nlink`` (Windows), so when deduplicating we fall back to ``os.stat`` to
    learn whether a file is hard-linked. This costs an extra syscall per file
    only on platforms that need it, and only when ``dedup_links`` is set.
    """
    node = Node(name=name, path="", size=_entry_size(st, opts.disk_usage))
    if opts.track_links:
        dev, ino, nlink = st.st_dev, st.st_ino, st.st_nlink
        if ino == 0:
            try:
                rst = os.stat(path, follow_symlinks=opts.follow_symlinks)
                dev, ino, nlink = rst.st_dev, rst.st_ino, rst.st_nlink
            except OSError:
                ino = 0
        if nlink > 1 and ino:
            node.dev, node.ino, node.nlink = dev, ino, nlink
    return node


def _scan_dir(
    path: str,
    name: str,
    depth: int,
    ancestors: frozenset[tuple[int, int]],
    opts: _Opts,
    pool: ThreadPoolExecutor,
) -> Node:
    """Scan a single directory, dispatching immediate children to the thread pool.

    Only the *direct* subdirectories of the root are submitted to the pool.
    Deeper recursion happens synchronously inside each worker thread via
    ``_scan_dir_sync``.  This avoids the thread-pool deadlock that occurs when
    every worker blocks on ``fut.result()`` waiting for grandchild tasks that
    can never start because the pool is already saturated.

    *ancestors* is the set of ``(st_dev, st_ino)`` for every directory on the
    path from the root to here; it is used to break symlink cycles when
    following symlinks.
    """
    node = Node(name=name, path=path if depth == 0 else "", is_dir=True)

    if opts.max_depth and depth >= opts.max_depth:
        node.size = _dir_size_fast(
            path,
            opts.exclude_set,
            disk_usage=opts.disk_usage,
            one_file_system=opts.one_file_system,
            root_dev=opts.root_dev,
        )
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
    dir_futures: list[tuple[str, Future]] = []  # (entry_name, future)

    for entry in entries:
        if entry.name in opts.exclude_set:
            continue

        try:
            # One stat call; covers dir, symlink, size, device and inode.
            st = entry.stat(follow_symlinks=opts.follow_symlinks)
            mode = st.st_mode
        except OSError as exc:
            # Keep the real message — "stat failed" told the user nothing about
            # whether this was a permissions problem, a broken link, or a race.
            node.children.append(Node(name=entry.name, path="", size=0, error=str(exc)))
            continue

        is_lnk = entry.is_symlink()
        is_dir = stat.S_ISDIR(mode)

        if is_lnk and not opts.follow_symlinks:
            # Count symlink target size but don't descend.
            try:
                sz = _entry_size(entry.stat(follow_symlinks=False), opts.disk_usage)
            except OSError:
                sz = 0
            node.size += sz
            if sz >= opts.min_size:
                node.children.append(Node(name=entry.name, path="", size=sz))
            continue

        if is_dir:
            dev, ino = _dir_identity(entry.path, st, opts)
            if opts.one_file_system and dev and dev != opts.root_dev:
                continue
            key = (dev, ino)
            if opts.follow_symlinks and ino and key in ancestors:
                # Symlink cycle: this directory is already on our path.
                continue
            # Submit each direct child subtree to the pool.  The worker calls
            # _scan_dir_sync (no further pool submissions) so threads never
            # block waiting for pool capacity — deadlock is impossible.
            fut = pool.submit(
                _scan_dir_sync,
                entry.path,
                entry.name,
                depth + 1,
                ancestors | {key},
                opts,
            )
            dir_futures.append((entry.name, fut))
        else:
            node_child = _make_file_node(entry.name, entry.path, st, opts)
            node.size += node_child.size
            if node_child.size >= opts.min_size:
                node.children.append(node_child)

    # Collect directory results.  A worker that dies unexpectedly must not
    # take the whole scan with it — record the failure on a stub node and
    # carry on with the remaining subtrees.
    for _en, fut in dir_futures:
        try:
            child = fut.result()
        except OSError as exc:
            child = Node(name=_en, path="", is_dir=True, error=str(exc))
        node.size += child.size
        node.children.append(child)

    node.children.sort(key=lambda n: (-n.size, n.name))
    return node


def _scan_dir_sync(
    path: str,
    name: str,
    depth: int,
    ancestors: frozenset[tuple[int, int]],
    opts: _Opts,
) -> Node:
    """Recursively scan a directory without touching the thread pool.

    Called by worker threads (submitted from ``_scan_dir``).  All deeper
    recursion is synchronous so this function never blocks on external futures
    and cannot contribute to a pool deadlock.
    """
    node = Node(name=name, path="", is_dir=True)

    if opts.max_depth and depth >= opts.max_depth:
        node.size = _dir_size_fast(
            path,
            opts.exclude_set,
            disk_usage=opts.disk_usage,
            one_file_system=opts.one_file_system,
            root_dev=opts.root_dev,
        )
        return node

    try:
        with os.scandir(path) as it:
            entries = list(it)
    except OSError as exc:
        node.error = str(exc)
        return node

    for entry in entries:
        if entry.name in opts.exclude_set:
            continue

        try:
            st = entry.stat(follow_symlinks=opts.follow_symlinks)
            mode = st.st_mode
        except OSError as exc:
            # Keep the real message — "stat failed" told the user nothing about
            # whether this was a permissions problem, a broken link, or a race.
            node.children.append(Node(name=entry.name, path="", size=0, error=str(exc)))
            continue

        is_lnk = entry.is_symlink()
        is_dir = stat.S_ISDIR(mode)

        if is_lnk and not opts.follow_symlinks:
            try:
                sz = _entry_size(entry.stat(follow_symlinks=False), opts.disk_usage)
            except OSError:
                sz = 0
            node.size += sz
            if sz >= opts.min_size:
                node.children.append(Node(name=entry.name, path="", size=sz))
            continue

        if is_dir:
            dev, ino = _dir_identity(entry.path, st, opts)
            if opts.one_file_system and dev and dev != opts.root_dev:
                continue
            key = (dev, ino)
            if opts.follow_symlinks and ino and key in ancestors:
                continue
            child = _scan_dir_sync(
                entry.path,
                entry.name,
                depth + 1,
                ancestors | {key},
                opts,
            )
            node.size += child.size
            node.children.append(child)
        else:
            node_child = _make_file_node(entry.name, entry.path, st, opts)
            node.size += node_child.size
            if node_child.size >= opts.min_size:
                node.children.append(node_child)

    node.children.sort(key=lambda n: (-n.size, n.name))
    return node


def _dir_size_fast(
    path: str,
    exclude_set,
    *,
    disk_usage: bool = False,
    one_file_system: bool = False,
    root_dev: int = 0,
) -> int:
    """Iterative byte-count with no Node allocation (used at max-depth cutoff).

    ``exclude_set`` is applied at every level, matching the behaviour of the
    full-tree walk.  Without it, excluded names below the depth cutoff would
    still be counted, making ``--depth`` and ``--exclude`` give wrong totals
    when combined.

    ``one_file_system`` and ``disk_usage`` are honoured here too, so the total
    below the cutoff is measured on the same basis as the rest of the tree.
    Hard-link dedup is *not* applied below the cutoff: there are no nodes to
    deduplicate, so those bytes are counted as-is.

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
                        st = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(st.st_mode):
                            if one_file_system and st.st_dev != root_dev:
                                continue
                            stack.append(entry.path)
                        else:
                            total += _entry_size(st, disk_usage)
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def _dedup_hardlinks(root: Node) -> None:
    """Zero out repeated hard links in place so totals count each inode once.

    Walks the tree largest-first (the order the nodes are already sorted in, so
    "first seen" is deterministic and independent of thread timing). The first
    node for a given ``(dev, ino)`` keeps its size; each later node is set to
    zero and its bytes are subtracted from every ancestor directory, which
    keeps directory totals consistent even when ``min_size`` pruned other
    siblings or a subtree was measured at the depth cutoff.

    Directory sizes are only ever *reduced*, so a final re-sort restores the
    largest-first invariant the renderer relies on.
    """
    seen: set[tuple[int, int]] = set()

    def visit(node: Node, ancestors: list[Node]) -> None:
        if node.is_dir:
            child_ancestors = ancestors + [node]
            for child in node.children:
                visit(child, child_ancestors)
            return
        if node.ino and node.nlink > 1:
            key = (node.dev, node.ino)
            if key in seen:
                dupe = node.size
                node.size = 0
                for ancestor in ancestors:
                    ancestor.size -= dupe
            else:
                seen.add(key)

    visit(root, [])
    _resort(root)


def _resort(node: Node) -> None:
    """Re-establish the ``(-size, name)`` ordering after dedup changed sizes."""
    if not node.children:
        return
    for child in node.children:
        _resort(child)
    node.children.sort(key=lambda n: (-n.size, n.name))
