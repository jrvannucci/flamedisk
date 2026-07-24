"""
Render a disk-usage :class:`~flamedisk.scanner.Node` tree as a self-contained,
interactive HTML report — a horizontal flame-graph (icicle chart) alongside a
sortable file tree.

The output is a single file with all CSS and JS inlined; it needs no server or
network access. Comments and redundant whitespace are stripped once at import
time (see :func:`_minify`).

Payload encoding
----------------
The node tree is serialised as a **columnar** JSON object rather than a nested
dict per node: several parallel arrays indexed by node id, which the browser
rebuilds into the tree in O(n) at startup.

  N – name strings
  S – sizes as decimal integers
  D – node ids that are directories (sparse; a missing id is a file)
  C – children arrays (list of child node ids; empty for leaves)
  P – path string, stored only for the root (index 0)
  E – {node id: error message} for entries that could not be read (usually empty)

:func:`render_html_gz` returns the same document gzip-compressed, for serving
over HTTP with a ``Content-Encoding: gzip`` header.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .scanner import Node

# ---------------------------------------------------------------------------
# Payload encoding
# ---------------------------------------------------------------------------


def _encode_tree(root: Node) -> str:
    """Serialise *root* as a compact columnar JSON string.

    Returns a JSON object with four parallel arrays keyed by single letters:

    * ``N`` – name strings (index = node id)
    * ``S`` – sizes as decimal integers
    * ``D`` – sorted list of node-ids that are directories (files are absent)
    * ``C`` – children arrays (list of child node-ids; ``[]`` for leaves)
    * ``P`` – path string, stored only for the root (index 0)
    * ``E`` – ``{node_id: error_string}`` for nodes that had errors (usually empty)
    """
    names: list[str] = []
    sizes: list[int] = []
    dirs: list[int] = []
    children: list[list[int]] = []
    errors: dict[int, str] = {}
    root_path = root.path or ""

    def _visit(node: Node) -> int:
        idx = len(names)
        # Reserve all slots before recursing so indices are stable.
        names.append(node.name)
        sizes.append(node.size)
        if node.is_dir:
            dirs.append(idx)
        if node.error:
            errors[idx] = node.error
        children.append([])  # placeholder; filled after recursion
        for child in node.children:
            children[idx].append(_visit(child))
        return idx

    _visit(root)

    payload: dict = {"N": names, "S": sizes, "D": dirs, "C": children}
    if root_path:
        payload["P"] = root_path
    if errors:
        payload["E"] = {str(k): v for k, v in errors.items()}

    return json.dumps(payload, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_html(root: Node, title: str | None = None) -> str:
    """Render *root* as a self-contained HTML string.

    Args:
        root:  Root :class:`~flamedisk.scanner.Node` returned by :func:`~flamedisk.scanner.scan`.
        title: Page ``<title>`` (defaults to ``"flamedisk — <path>"``).

    Returns:
        str: Complete HTML document, ready to write to a ``.html`` file.
    """
    title = title or f"flamedisk \u2014 {root.path}"
    data = _encode_tree(root)
    return _TEMPLATE.replace("__TITLE__", _esc(title)).replace("__DATA__", data)


def render_html_gz(root: Node, title: str | None = None) -> bytes:
    """Like :func:`render_html` but returns gzip-compressed bytes.

    Useful when serving the report over HTTP
    (set ``Content-Encoding: gzip``).
    """
    import gzip

    return gzip.compress(render_html(root, title).encode("utf-8"), compresslevel=9)


def write_html(root: Node, output: str, title: str | None = None) -> None:
    """Write the HTML report to *output*.

    Args:
        root:   Root node.
        output: Destination file path.
        title:  Optional page title.
    """
    Path(output).write_text(render_html(root, title), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _minify(html: str) -> str:
    """Strip CSS/JS comments and collapse redundant whitespace."""
    # Remove /* ... */ block comments (CSS)
    html = re.sub(r"/\*.*?\*/", "", html, flags=re.DOTALL)
    # Remove // line comments inside <script> blocks only
    html = re.sub(r"(?m)^[ \t]*//[^\n]*\n", "\n", html)
    # Collapse runs of spaces/tabs to a single space
    html = re.sub(r"[ \t]{2,}", " ", html)
    # Collapse multiple blank lines to one
    html = re.sub(r"\n[ \t]*\n[ \t]*\n", "\n\n", html)
    # Strip trailing space on lines
    html = re.sub(r"[ \t]+\n", "\n", html)
    return html.strip()


# ---------------------------------------------------------------------------
# HTML template
# NOTE: The JSON payload is now columnar (see _encode_tree above).
#   N = names[]   S = sizes[]   D = dir-index-set[]
#   C = children[][]   P = root path   E = {id: error}
#
# The JS rebuilds the nested node objects at startup in O(n) via _build().
# ---------------------------------------------------------------------------

# Template is loaded from template.html (alongside this file) and
# minified once at import time.
_RAW_TEMPLATE = Path(__file__).with_name("template.html").read_text(encoding="utf-8")

_TEMPLATE = _minify(_RAW_TEMPLATE)
