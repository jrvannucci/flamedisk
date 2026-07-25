# Changelog

## 1.0.0 — 2026-07-25

Initial public release.

- Interactive, self-contained HTML disk-usage report with a flame graph, expandable file tree, and sortable list view.
- `flamedisk` CLI: depth limits, minimum-size filtering, name exclusion, symlink handling, JSON output, and configurable worker threads.
- Python API: `scan`, `write_html`, `render_html`, and the `Node` tree type.
- No runtime dependencies beyond the standard library. Supports Python 3.9–3.13 on Linux, macOS, and Windows.
