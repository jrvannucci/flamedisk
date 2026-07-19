"""CLI tests — size parsing, argument handling, and end-to-end invocation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest

from flamedisk.cli import _fmt, _parse_size, build_parser, main

from conftest import TREE_TOTAL


# ── _parse_size ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("0", 0),
        ("", 0),
        ("512", 512),
        ("1024", 1024),
        ("1B", 1),
        ("1KB", 1024),
        ("1kb", 1024),
        ("1K", 1024),
        ("1MB", 1024**2),
        ("1GB", 1024**3),
        ("1TB", 1024**4),
        ("1.5GB", int(1.5 * 1024**3)),
        ("0.5MB", 1024**2 // 2),
        ("  2MB  ", 2 * 1024**2),
    ],
)
def test_parse_size(text: str, expected: int):
    assert _parse_size(text) == expected


@pytest.mark.parametrize("bad", ["abc", "MB", "1.2.3GB", "12XB"])
def test_parse_size_rejects_garbage(bad: str):
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_size(bad)


def test_parse_size_prefers_longest_suffix():
    """'1KB' must not be read as '1K' + stray 'B', nor as bare bytes."""
    assert _parse_size("1KB") == 1024
    assert _parse_size("1B") == 1


# ── _fmt ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "nbytes,expected",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024**2, "1.0 MB"),
        (1024**3, "1.0 GB"),
        (1024**4, "1.0 TB"),
    ],
)
def test_fmt(nbytes: int, expected: str):
    assert _fmt(nbytes) == expected


def test_fmt_caps_at_tb():
    """Petabyte-scale input stays in TB rather than falling off the unit list."""
    assert _fmt(5 * 1024**5).endswith("TB")


# ── argument parsing ──────────────────────────────────────────────────────

def test_defaults():
    args = build_parser().parse_args([])
    assert args.path == "."
    assert args.depth == 0
    assert args.exclude == []
    assert args.min_size == "0"
    assert args.workers == 0
    assert not args.follow_symlinks
    assert not args.no_browser
    assert not args.json


def test_exclude_accepts_multiple_names():
    args = build_parser().parse_args(["--exclude", ".git", "node_modules"])
    assert args.exclude == [".git", "node_modules"]


def test_double_dash_separates_exclude_from_path():
    """Documented in the README; --exclude uses nargs='+' so this matters."""
    args = build_parser().parse_args(["--exclude", ".git", "--", "/my dir"])
    assert args.exclude == [".git"]
    assert args.path == "/my dir"


def test_path_with_spaces():
    assert build_parser().parse_args(["/home/My Documents"]).path == "/home/My Documents"


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert "flamedisk" in capsys.readouterr().out


# ── end-to-end ────────────────────────────────────────────────────────────

def test_main_writes_html(tree: Path, tmp_path: Path):
    out = tmp_path / "report.html"
    assert main([str(tree), "-o", str(out), "-q"]) == 0
    assert out.is_file()
    assert out.read_text(encoding="utf-8").lstrip().startswith("<")


def test_main_json_output(tree: Path, capsys):
    assert main([str(tree), "--json", "-q"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n"] == "root"
    assert payload["s"] == TREE_TOTAL


def test_main_json_respects_exclude(tree: Path, capsys):
    assert main([str(tree), "--json", "-q", "--exclude", "node_modules"]) == 0
    assert json.loads(capsys.readouterr().out)["s"] == TREE_TOTAL - 300000


def test_main_json_depth_and_exclude_agree(tree: Path, capsys):
    """End-to-end guard for the --depth/--exclude regression."""
    main([str(tree), "--json", "-q", "--exclude", "node_modules"])
    unlimited = json.loads(capsys.readouterr().out)["s"]
    main([str(tree), "--json", "-q", "--depth", "1", "--exclude", "node_modules"])
    limited = json.loads(capsys.readouterr().out)["s"]
    assert limited == unlimited


def test_default_output_goes_to_a_temp_file(tree: Path, monkeypatch):
    """`flamedisk <dir>` with no -o is the most common invocation; it writes to
    a temp file and opens it."""
    import flamedisk.cli as cli

    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))

    assert main([str(tree)]) == 0

    assert len(opened) == 1
    url = opened[0]
    assert url.startswith("file://")
    # Round-trip the URI properly: naive prefix-stripping drops the leading
    # slash on POSIX ("file:///tmp/x" -> "tmp/x").
    written = Path(url2pathname(urlparse(url).path))
    assert written.is_file(), f"temp report missing: {written}"
    assert written.suffix == ".html"
    assert "flamedisk_" in written.name
    assert written.read_text(encoding="utf-8").lstrip().startswith("<")
    written.unlink()


def test_default_output_respects_no_browser(tree: Path, monkeypatch):
    """-q still writes the temp file; it just does not open it."""
    import flamedisk.cli as cli

    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))
    created = []
    real_mkstemp = cli.tempfile.mkstemp

    def spy(*a, **kw):
        fd, path = real_mkstemp(*a, **kw)
        created.append(path)
        return fd, path

    monkeypatch.setattr(cli.tempfile, "mkstemp", spy)

    assert main([str(tree), "-q"]) == 0
    assert opened == []
    assert len(created) == 1
    assert Path(created[0]).is_file()
    Path(created[0]).unlink()


def test_main_rejects_a_file_path(tmp_path: Path):
    f = tmp_path / "notadir.txt"
    f.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        main([str(f), "-q"])
    assert exc.value.code != 0


def test_main_rejects_missing_path(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path / "nope"), "-q"])
    assert exc.value.code != 0


def test_no_browser_flag_suppresses_open(tree: Path, tmp_path: Path, monkeypatch):
    import flamedisk.cli as cli

    calls = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: calls.append(url))
    main([str(tree), "-o", str(tmp_path / "r.html"), "-q"])
    assert calls == []


def test_browser_opens_by_default(tree: Path, tmp_path: Path, monkeypatch):
    import flamedisk.cli as cli

    calls = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: calls.append(url))
    main([str(tree), "-o", str(tmp_path / "r.html")])
    assert len(calls) == 1
    assert calls[0].startswith("file://")


def test_custom_title_lands_in_html(tree: Path, tmp_path: Path):
    out = tmp_path / "r.html"
    main([str(tree), "-o", str(out), "-q", "--title", "Custom Report"])
    assert "Custom Report" in out.read_text(encoding="utf-8")


def test_min_size_flag_parsed_end_to_end(tree: Path, capsys):
    """Totals are unchanged by min_size; only the node list shrinks."""
    main([str(tree), "--json", "-q", "--min-size", "10KB"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["s"] == TREE_TOTAL
    assert "a.txt" not in [c["n"] for c in payload["c"]]
