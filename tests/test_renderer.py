"""Renderer tests — payload encoding, escaping, and template integrity."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from flamedisk import Node, render_html, scan, write_html
from flamedisk.renderer import _encode_tree, _esc, _minify, render_html_gz

from conftest import TREE_TOTAL


def decode(root: Node) -> dict:
    return json.loads(_encode_tree(root))


# ── columnar payload ──────────────────────────────────────────────────────

def test_payload_arrays_are_parallel(tree: Path):
    p = decode(scan(str(tree)))
    assert len(p["N"]) == len(p["S"]) == len(p["C"])


def test_payload_root_is_index_zero(tree: Path):
    p = decode(scan(str(tree)))
    assert p["N"][0] == "root"
    assert p["S"][0] == TREE_TOTAL
    assert 0 in p["D"]


def test_payload_sizes_sum_correctly(tree: Path):
    """Every directory's size equals the sum of its children's sizes."""
    p = decode(scan(str(tree)))
    for idx, kids in enumerate(p["C"]):
        if kids:
            assert p["S"][idx] == sum(p["S"][k] for k in kids), f"node {p['N'][idx]}"


def test_payload_dir_set_matches_children(tree: Path):
    p = decode(scan(str(tree)))
    dirs = set(p["D"])
    for idx, kids in enumerate(p["C"]):
        if kids:
            assert idx in dirs, f"{p['N'][idx]} has children but is not marked a dir"


def test_payload_node_count_matches_tree(tree: Path):
    root = scan(str(tree))

    def count(n: Node) -> int:
        return 1 + sum(count(c) for c in n.children)

    assert len(decode(root)["N"]) == count(root)


def test_payload_path_only_on_root(tree: Path):
    p = decode(scan(str(tree)))
    assert p["P"] == str(tree.resolve()) or p["P"].endswith("root")


def test_payload_omits_empty_optional_keys():
    p = decode(Node(name="x", path="", size=1))
    assert "P" not in p
    assert "E" not in p


def test_payload_includes_errors():
    root = Node(name="r", path="/r", size=0, is_dir=True)
    root.children.append(Node(name="bad", path="", size=0, error="denied"))
    p = decode(root)
    assert p["E"] == {"1": "denied"}


def test_payload_error_ids_index_the_name_array():
    """E keys must be valid node ids, or the report cannot resolve paths."""
    root = Node(name="r", path="/r", size=0, is_dir=True)
    root.children.append(Node(name="ok", path="", size=5))
    root.children.append(Node(name="bad", path="", size=0, error="denied"))
    p = decode(root)
    for key in p["E"]:
        assert 0 <= int(key) < len(p["N"])
    assert p["N"][int(next(iter(p["E"])))] == "bad"


def test_payload_is_compact_json(tree: Path):
    """No whitespace padding — separators are (',', ':')."""
    raw = _encode_tree(scan(str(tree)))
    assert ", " not in raw and '": ' not in raw


# ── HTML output ───────────────────────────────────────────────────────────

def test_render_substitutes_placeholders(tree: Path):
    html = render_html(scan(str(tree)), "My Title")
    assert "__DATA__" not in html
    assert "__TITLE__" not in html
    assert "My Title" in html


def test_render_is_self_contained(tree: Path):
    """No external fetches — the report must work offline from one file."""
    html = render_html(scan(str(tree)))
    assert "<script src=" not in html
    assert "<link rel=\"stylesheet\"" not in html
    assert "http://" not in html.replace("http://www.w3.org", "")


def test_default_title_uses_root_path(tree: Path):
    html = render_html(scan(str(tree)))
    assert "flamedisk" in html


def test_title_is_html_escaped(tree: Path):
    html = render_html(scan(str(tree)), '<script>alert("x")</script>')
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_esc_covers_all_five_entities():
    assert _esc('<a href="x">&</a>') == "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;"


def test_write_html_roundtrip(tree: Path, tmp_path: Path):
    out = tmp_path / "report.html"
    write_html(scan(str(tree)), str(out), "T")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<") and "T" in text


def test_write_html_handles_unicode(tmp_path: Path):
    root = Node(name="café ☕", path="/café ☕", size=1, is_dir=True)
    out = tmp_path / "u.html"
    write_html(root, str(out))
    assert "café ☕" in out.read_text(encoding="utf-8")


def test_render_html_gz_roundtrips(tree: Path):
    root = scan(str(tree))
    gz = render_html_gz(root)
    assert gzip.decompress(gz).decode("utf-8") == render_html(root)
    assert len(gz) < len(render_html(root).encode("utf-8"))


# ── minifier ──────────────────────────────────────────────────────────────

def test_minify_strips_block_comments():
    assert "gone" not in _minify("a { /* gone */ color: red }")


def test_minify_collapses_runs_of_spaces():
    assert "  " not in _minify("<div>    x    </div>")


def test_minify_preserves_placeholders():
    """The placeholders must survive minification or render_html breaks."""
    out = _minify("<title>__TITLE__</title><script>const D=__DATA__;</script>")
    assert "__TITLE__" in out and "__DATA__" in out


def test_template_renders_the_error_banner_markup():
    """The template must contain the surfaces that display E, or errors stay
    silently invisible the way they were before this was wired up."""
    from flamedisk import renderer

    text = Path(renderer.__file__).with_name("template.html").read_text(encoding="utf-8")
    assert "ERRORS" in text, "error list is never reconstructed"
    assert 'id="errb"' in text, "no error banner element"
    assert "ewarn" in text, "no per-row error marker"


def test_legend_guards_against_overflow_placeholders():
    """Regression (JS-side, asserted structurally): updateLegend iterates
    BFS items that include `{node:null}` overflow placeholders. Dereferencing
    them threw, aborting renderIcicle before updatePB() ran and blanking the
    breadcrumb, size counter, and legend on any tree with sub-pixel entries."""
    from flamedisk import renderer

    text = Path(renderer.__file__).with_name("template.html").read_text(encoding="utf-8")
    legend = text[text.index("function updateLegend") :]
    legend = legend[: legend.index("\n}")]
    assert "if(!node) continue" in legend, "null-node guard missing from updateLegend"


def test_errors_reach_the_rendered_html():
    root = Node(name="r", path="/r", size=0, is_dir=True)
    root.children.append(Node(name="locked", path="", size=0, error="Permission denied"))
    html = render_html(root)
    assert "Permission denied" in html


def test_error_free_report_has_no_error_payload(tree: Path):
    """The zero-error case must not gain an E key or the banner would show."""
    assert '"E"' not in _encode_tree(scan(str(tree)))


def test_template_ships_with_package():
    from flamedisk import renderer

    template = Path(renderer.__file__).with_name("template.html")
    assert template.is_file()
    text = template.read_text(encoding="utf-8")
    assert "__DATA__" in text and "__TITLE__" in text


# ── deep trees ────────────────────────────────────────────────────────────

def test_encodes_a_deep_chain():
    """_encode_tree recurses; make sure a realistically deep tree survives."""
    root = Node(name="d0", path="/d0", size=1, is_dir=True)
    node = root
    for i in range(1, 200):
        child = Node(name=f"d{i}", path="", size=1, is_dir=True)
        node.children.append(child)
        node = child
    p = decode(root)
    assert len(p["N"]) == 200


@pytest.mark.parametrize("size", [0, 1, 2**31, 2**53 + 1])
def test_large_and_zero_sizes_survive_json(size: int):
    p = decode(Node(name="f", path="", size=size))
    assert p["S"][0] == size
