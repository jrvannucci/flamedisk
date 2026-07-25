"""
Command-line interface for flamedisk.

Entry point: ``flamedisk`` (installed by pip via ``project.scripts``).

Usage::

    flamedisk [path] [options]

Run ``flamedisk --help`` for the full option list.

Path handling
-------------
Paths that contain spaces must be quoted in the shell in the usual way::

    flamedisk "/home/user/My Documents"
    flamedisk '/var/log/some dir'

The ``--exclude`` option uses ``nargs="+"`` so it requires at least one name.
To pass a path *after* ``--exclude``, use ``--`` to end option parsing::

    flamedisk --exclude .git node_modules -- "/path with spaces"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from . import __version__
from .renderer import write_html
from .scanner import scan

# ── helpers ───────────────────────────────────────────────────────────────


def _fmt(n: int) -> str:
    """Human-readable byte count (e.g. ``1.23 GB``)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024  # type: ignore[assignment]
    return str(n)


def _parse_size(s: str) -> int:
    """Parse a human-readable size string into bytes.

    Accepts plain integers or strings suffixed with ``B``, ``KB``, ``MB``,
    ``GB``, or ``TB`` (case-insensitive). Fractional values are supported,
    e.g. ``1.5GB``.

    Args:
        s: Size string, e.g. ``"512KB"``, ``"1.5GB"``, ``"1048576"``.

    Returns:
        int: Number of bytes.

    Raises:
        argparse.ArgumentTypeError: If the string cannot be parsed.
    """
    s = s.strip()
    if not s or s == "0":
        return 0
    multipliers = {
        "tb": 1024**4,
        "gb": 1024**3,
        "mb": 1024**2,
        "kb": 1024,
        "b": 1,
        "t": 1024**4,
        "g": 1024**3,
        "m": 1024**2,
        "k": 1024,
    }
    lower = s.lower()
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if lower.endswith(suffix):
            try:
                return int(float(lower[: -len(suffix)]) * mult)
            except ValueError:
                pass
    try:
        return int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Cannot parse size: {s!r}")


# ── CLI ───────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser (exposed for Sphinx autodoc)."""
    p = argparse.ArgumentParser(
        prog="flamedisk",
        description="Flame-graph & treemap disk-usage visualiser.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  flamedisk /home/user                       # scan & open browser
  flamedisk "/home/My Documents" -o out.html # path with spaces
  flamedisk /var/log -o report.html          # save HTML, open browser
  flamedisk . --depth 4 --min-size 1MB       # limit depth & skip small files
  flamedisk / --exclude proc sys dev -q      # skip virtual FSes, no browser
  flamedisk --exclude .git -- "/path/My Dir" # exclude + spaced path via --
  flamedisk . --json | jq '.children[0]'     # raw JSON tree to stdout
""",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory). "
        "Quote paths that contain spaces: flamedisk '/my dir'",
    )
    p.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Write HTML output to FILE (default: a temp file).",
    )
    p.add_argument(
        "--depth",
        type=int,
        default=0,
        metavar="N",
        help="Maximum scan depth; 0 means unlimited (default: 0).",
    )
    p.add_argument(
        "--min-size",
        default="0",
        metavar="BYTES",
        help="Ignore files smaller than this, e.g. 1MB, 512KB (default: 0).",
    )
    p.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        metavar="NAME",
        # Changed from nargs="*" → nargs="+" so argparse does not greedily
        # consume a trailing positional (the path) as an exclude name.
        # Use -- to separate --exclude list from a spaced path, e.g.:
        #   flamedisk --exclude .git node_modules -- "/my dir"
        help="Entry names to skip, e.g. --exclude .git node_modules __pycache__ "
        "(use -- before path if the path follows: --exclude .git -- '/my dir')",
    )
    p.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symbolic links. Symlink cycles are detected and skipped.",
    )
    p.add_argument(
        "--actual-size",
        action="store_true",
        help="Measure allocated disk blocks instead of apparent file size, "
        "like plain du. Unix only; falls back to apparent size on Windows.",
    )
    p.add_argument(
        "-x",
        "--one-file-system",
        action="store_true",
        help="Skip directories on a different filesystem than the scan root "
        "(like du -x). Useful when scanning / to avoid /proc, /sys, and mounts.",
    )
    p.add_argument(
        "--dedup-links",
        action="store_true",
        help="Count hard-linked files only once, so shared storage is not "
        "double-counted (like du).",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=0,
        metavar="N",
        help="Thread-pool size for parallel scanning (default: auto = cpu_count×4, "
        "capped at 32). Increase for network/slow storage; lower for HDDs.",
    )
    p.add_argument(
        "-q",
        "--no-browser",
        action="store_true",
        help="Do not open a browser window after generating the report.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print the raw JSON tree to stdout instead of generating HTML.",
    )
    p.add_argument(
        "--title",
        metavar="TEXT",
        help="Custom HTML page title.",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"flamedisk {__version__}",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``flamedisk`` CLI.

    Args:
        argv: Argument list (defaults to :data:`sys.argv`).

    Returns:
        int: Exit code (0 on success).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    min_size = _parse_size(args.min_size)
    root_path = os.path.abspath(args.path)

    if not os.path.isdir(root_path):
        parser.error(f"Not a directory: {root_path!r}")

    print(f"⠿  Scanning {root_path} …", file=sys.stderr, flush=True)

    t0 = time.perf_counter()
    tree = scan(
        root_path,
        max_depth=args.depth,
        min_size=min_size,
        follow_symlinks=args.follow_symlinks,
        exclude=args.exclude,
        workers=args.workers,
        disk_usage=args.actual_size,
        one_file_system=args.one_file_system,
        dedup_links=args.dedup_links,
    )

    elapsed = time.perf_counter() - t0
    print(f"✓  {root_path} — {_fmt(tree.size)} — {elapsed:.2f}s", file=sys.stderr)

    if args.json:
        json.dump(tree.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    title = args.title or f"flamedisk — {root_path}"

    if args.output:
        out = args.output
        write_html(tree, out, title)
        print(f"✓  Saved → {out}", file=sys.stderr)
    else:
        fd, out = tempfile.mkstemp(suffix=".html", prefix="flamedisk_")
        os.close(fd)
        write_html(tree, out, title)

    if not args.no_browser:
        url = Path(out).as_uri()
        print(f"⠿  Opening {url}", file=sys.stderr)
        webbrowser.open(url)

    return 0


if __name__ == "__main__":
    sys.exit(main())
