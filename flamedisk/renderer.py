"""
Renders the disk-usage Node tree as a TreeSize-style interactive HTML page.

Optimisations vs v0.1
----------------------
* JSON payload uses single-char keys (``n/s/d/p/c/e``) — ~40% smaller.
* Paths are stored only on the root node; the browser reconstructs them.
* CSS and JS are minified at import time (strips comments + excess whitespace).
* ``gzip`` compression available via :func:`render_html_gz` for HTTP serving.

v0.2 visualisation improvements
---------------------------------
* Right panel replaced with a horizontal **icicle chart** (flame-graph layout):
  each depth level is a fixed-height row; width is proportional to size.
  Equal-sized siblings are clearly distinguishable via alternating hue shifts
  and depth-based brightness.
* Directories with identical sizes now get visually distinct colours.
* Hover tooltip shows full path, size, % of parent, and child count.
* Clicking an icicle cell drills down; Escape / ▲ Up goes back.
* Tree panel bar widths and % column now reflect proportion of *parent* rather
  than root, making deep comparisons easier.

v0.5 payload encoding
----------------------
The JSON payload is now **columnar** rather than nested-dict per node.
Four parallel arrays are emitted (indices are node IDs):

  N – name strings
  S – sizes as decimal integers
  D – set of node indices that are directories (sparse; absent = file)
  C – children arrays (list of child node-IDs for each node, empty = leaf)

The JS side reconstructs the tree at startup in O(n).  This saves ~8 % raw
bytes versus the v0.4 nested format for typical directory trees, and allows
future delta/varint encoding without changing the JS tree logic.

A ``--gzip`` CLI flag writes a self-decompressing HTML wrapper around a
base64-gzipped payload, yielding ~75 % size reduction for HTTP serving.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

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
    names:    list[str]       = []
    sizes:    list[int]       = []
    dirs:     list[int]       = []
    children: list[list[int]] = []
    errors:   dict[int, str]  = {}
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
        children.append([])          # placeholder; filled after recursion
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

def render_html(root: Node, title: Optional[str] = None) -> str:
    """Render *root* as a self-contained HTML string.

    Args:
        root:  Root :class:`~flamedisk.scanner.Node` returned by :func:`~flamedisk.scanner.scan`.
        title: Page ``<title>`` (defaults to ``"flamedisk — <path>"``).

    Returns:
        str: Complete HTML document, ready to write to a ``.html`` file.
    """
    title = title or f"flamedisk \u2014 {root.path}"
    data  = _encode_tree(root)
    return (
        _TEMPLATE
        .replace("__TITLE__", _esc(title))
        .replace("__DATA__", data)
    )


def render_html_gz(root: Node, title: Optional[str] = None) -> bytes:
    """Like :func:`render_html` but returns gzip-compressed bytes.

    Useful when serving the report over HTTP
    (set ``Content-Encoding: gzip``).
    """
    import gzip
    return gzip.compress(render_html(root, title).encode("utf-8"), compresslevel=9)


def write_html(root: Node, output: str, title: Optional[str] = None) -> None:
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
    return (str(s)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


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
_RAW_TEMPLATE = (Path(__file__).with_name("template.html")
                 .read_text(encoding="utf-8"))

_TEMPLATE = _minify(_RAW_TEMPLATE)
