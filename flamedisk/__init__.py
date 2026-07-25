"""
flamedisk — flame-graph & treemap disk-usage visualiser.

Quick start::

    from flamedisk import scan, write_html

    tree = scan("/home/user", max_depth=5, exclude=[".git", "node_modules"])
    write_html(tree, "report.html")

The :func:`scan` function returns a :class:`~flamedisk.scanner.Node` tree
which can be rendered to a self-contained HTML file via :func:`write_html`,
or consumed programmatically as a plain dict via :meth:`~flamedisk.scanner.Node.to_dict`.
"""

from __future__ import annotations

from .renderer import render_html, write_html
from .scanner import Node, scan

__version__ = "1.0.0"
__all__ = ["scan", "Node", "render_html", "write_html", "__version__"]
