# Changelog

## Unreleased

- **CI**: pushing a release tag now also creates a GitHub Release, with notes pulled from this changelog's section for that version and the built wheel and sdist attached.

## 1.2.0 — 2026-07-25

- **Feature**: `--exclude` now accepts glob patterns. An entry containing `*`, `?`, or `[` is matched against each basename (e.g. `--exclude '*.log' '*.tmp'`); entries without glob characters still match names exactly, so existing usage is unchanged. Patterns apply at every depth, including below a `--depth` cutoff. Quote globs so the shell does not expand them.
- **Feature**: the CLI shows a live progress counter (entries scanned and running byte total) on an interactive terminal, updated as the scan runs. When stderr is redirected (a pipe, a file, CI) it falls back to the previous single static line, so logs stay clean.
- **API**: `scan()` gains an `on_progress` callback invoked periodically with `(entries_seen, bytes_seen)` running totals and once with the final totals.

## 1.1.1 — 2026-07-25

- **Fix**: `write_html` now creates missing parent directories, so `flamedisk -o new/dir/report.html` no longer fails when the directory does not exist yet.
- **Tooling**: added a `mypy --strict` type-check job to CI. The package ships a `py.typed` marker, so its signatures are now verified rather than merely promised.
- **Packaging**: removed the unused `rich` optional dependency; `mypy` is now part of the `dev` extra.

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
