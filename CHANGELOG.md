# Changelog

## Unreleased

- **Fix**: `--exclude` is now honoured below the `--depth` cutoff — previously excluded names were still counted toward directory totals once a subtree hit the depth limit, so `--depth N --exclude ...` reported wrong sizes
- **Fix**: a mid-scan `OSError` no longer aborts the whole scan — directories that vanish (`FileNotFoundError`), turn out not to be directories, or fail on stale network handles are now recorded on the node and the rest of the tree still scans. Previously only `PermissionError` was caught
- **Packaging**: added `readme`, `authors`, `dependencies`, and `[project.urls]` to `pyproject.toml` — the PyPI page previously rendered with no description or links
- **Packaging**: version is now single-sourced from `flamedisk.__version__` via `dynamic = ["version"]`, so `pyproject.toml` and `--version` can no longer drift
- **Fix**: the breadcrumb, header size counter, and flame-graph legend were silently blank on almost every real scan — `updateLegend` dereferenced the `node:null` overflow placeholders added in 0.7.1, throwing out of `renderIcicle` before `updatePB()` could run
- **Feature**: entries that could not be read are now visible in the report. A header banner shows the count and, on hover, the full path and OS error for each; unreadable rows in the tree panel carry a ⚠ marker; selecting one shows the error in the status bar. Previously these were encoded into the payload but never displayed, so a permission-denied directory was indistinguishable from an empty one and totals were silently understated
- **Fix**: per-entry stat failures now record the real OS error instead of the literal string `"stat failed"`
- **Packaging**: added the Python 3.13 classifier
- **Tests**: added a pytest suite (~125 tests) covering the scanner, renderer, CLI, and packaging metadata, including regression tests for each fix above
- **CI**: added a `Tests` workflow running pytest on Linux/macOS/Windows across Python 3.9–3.13, plus a `ruff` lint job
- **Cleanup**: removed two unused imports (`render_html` in `cli.py`, `as_completed` in `scanner.py`)

## 0.7.2

- **Fix**: size bars and `% total` column now always reflect each entry's share of the absolute scan root, in all views and at all nesting depths — previously bars in tree view used parent-relative sizing when directories were expanded

## 0.7.1

- **Fix**: list view percentage bars and `%` column now always show each entry's share of the root directory, not the immediate parent
- **Fix**: switching to list view no longer drops the root directory row
- **Fix**: sub-pixel nodes in the flame graph now render a muted overflow indicator showing the combined size of hidden entries, rather than leaving a gap
- **Fix**: flame graph rows now use absolute pixel positioning so pruning sub-pixel nodes does not misalign sibling rows
- **Docs**: added full documentation and screenshots

## 0.7.0

- **Feature**: flame graph now inverted — root anchors at the bottom, deeper levels grow upward
- **Feature**: clicking a directory in the flame graph zooms in-place, preserving original colours and depth levels; original view restored with Esc or ↺ Reset
- **Feature**: separate toolbar button groups for graph views and list view
- **Feature**: ↺ Reset button resets navigation, zoom, sort order, and search across all views
- **Feature**: list view sort buttons — Name, Size, Type
- **Performance**: BFS in flame graph now prunes sub-pixel subtrees early, reducing nodes visited by ~480× on large trees (112k → ~500 nodes visited per render)
- **Performance**: zoom dimming switched from O(n) recursive search per cell to O(1) Set lookup
- **Performance**: legend reuses BFS-collected nodes instead of a separate tree walk
- **Refactor**: HTML template extracted to `flamedisk/template.html` (included as package data)
- **Fix**: `.gitignore` no longer ignores `flamedisk/template.html`

## 0.6.0

- **Feature**: CLI prints elapsed scan time on completion line (e.g. `✓  /usr — 4.35 GB — 0.06s`)
- **Fix**: thread pool deadlock — `_scan_dir` no longer submits tasks to itself recursively; introduced `_scan_dir_sync` for pool workers to recurse synchronously

## 0.5.0

- **Feature**: flame graph (icicle chart) panel alongside the file tree
- **Feature**: zoom into subtrees by clicking; breadcrumb navigation
- **Feature**: colour-coded cells by file type and directory depth
- **Feature**: hover tooltips with size, percentage of parent, and child count
- **Feature**: search highlights matching entries across tree and flame views
- **Feature**: resizable split panel
- **Optimisation**: JSON payload switched to columnar encoding (parallel arrays) — ~7% smaller output files
