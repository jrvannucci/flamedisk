# Changelog

## 1.1.0 — 2026-07-25

- **Feature**: `--actual-size` (`disk_usage=True`) measures allocated disk blocks (`st_blocks × 512`) instead of apparent file size, matching plain `du`. Falls back to apparent size where `st_blocks` is unavailable (Windows).
- **Feature**: `-x` / `--one-file-system` (`one_file_system=True`) skips directories on a different device than the scan root, like `du -x` — so scanning `/` no longer wanders into `/proc`, `/sys`, or network mounts.
- **Feature**: `--dedup-links` (`dedup_links=True`) counts each hard-linked inode only once, so shared storage is not double-counted. The first occurrence in a deterministic largest-first traversal keeps its bytes; later links count as zero.
- **Fix**: `--follow-symlinks` no longer risks infinite recursion — the scanner tracks the `(device, inode)` of every directory on the current path and refuses to re-enter one, breaking symlink cycles.
- **Fix**: equal-sized entries now sort by `(-size, name)` instead of filesystem iteration order, so repeated scans of the same tree produce byte-for-byte identical reports.
- All four options are opt-in and off by default, so existing behaviour is unchanged unless requested. On platforms where `os.scandir` omits identity fields (Windows), `--one-file-system` and `--dedup-links` fall back to a direct `os.stat` per entry so they still work.
- **Fix**: the docs site build read the version by regex-parsing `flamedisk/__init__.py`, which broke once versioningit removed the literal `__version__` assignment. It now imports the package version, and a regression test guards against a recurrence.

## 1.0.0 — 2026-07-25

Initial public release.

- Interactive, self-contained HTML disk-usage report with a flame graph, expandable file tree, and sortable list view.
- `flamedisk` CLI: depth limits, minimum-size filtering, name exclusion, symlink handling, JSON output, and configurable worker threads.
- Python API: `scan`, `write_html`, `render_html`, and the `Node` tree type.
- No runtime dependencies beyond the standard library. Supports Python 3.9–3.13 on Linux, macOS, and Windows.
