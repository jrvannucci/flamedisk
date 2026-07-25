"""Packaging-metadata invariants.

The version is declared dynamically in pyproject.toml, which means anything
reading ``project.version`` from that file gets a KeyError. That broke the docs
workflow once already; these tests catch a recurrence without needing CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flamedisk

REPO = Path(flamedisk.__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"

pytestmark = pytest.mark.skipif(
    not PYPROJECT.is_file(),
    reason="not running from a source checkout",
)


def read_pyproject() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def test_version_is_declared_dynamic():
    text = read_pyproject()
    assert 'dynamic = ["version"]' in text
    # The version is supplied by versioningit (derived from git tags), not from
    # a literal or an attr reference.
    assert "[tool.versioningit]" in text


def test_pyproject_has_no_literal_version():
    """A literal version key would silently shadow the dynamic one."""
    project = read_pyproject().split("[project]", 1)[1].split("\n[", 1)[0]
    assert not re.search(r"^version\s*=", project, re.M)


def test_version_looks_like_a_release():
    # versioningit yields a bare ``X.Y.Z`` when built exactly on a tag, and a
    # PEP 440 dev/post form (e.g. ``1.0.1.dev4+g1a2b3c4``) between tags. Both are
    # valid; require only the leading numeric release segment.
    assert re.match(r"\d+\.\d+\.\d+", flamedisk.__version__), flamedisk.__version__


def test_nothing_reads_project_version_from_pyproject():
    """Regression: build_docs.py read tomllib.load(...)["project"]["version"],
    which KeyErrors now that the version is dynamic. The publish workflow had
    the same bug. Both now read flamedisk/__init__.py instead."""
    self_path = Path(__file__).resolve()
    offenders = []
    for path in REPO.rglob("*"):
        if path.suffix not in {".py", ".yml", ".yaml"} or not path.is_file():
            continue
        if path.resolve() == self_path:
            continue  # this file contains the pattern it searches for
        if any(part in {"build", ".venv", ".git", "_site"} for part in path.parts):
            continue
        if path.name.endswith(".egg-info"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r'\["project"\]\s*\[\s*["\']version', text):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, f"these still read project.version from pyproject: {offenders}"


def test_build_docs_reads_version_from_package():
    """Regression: build_docs.py used to regex ``__version__`` out of
    flamedisk/__init__.py. Once versioningit removed that literal assignment,
    the regex matched nothing and the docs workflow failed. The script must now
    obtain the version by importing the package (single source of truth)."""
    script = REPO / ".github" / "scripts" / "build_docs.py"
    if not script.is_file():
        pytest.skip("docs build script not present")
    text = script.read_text(encoding="utf-8")
    assert "import flamedisk" in text
    assert "return flamedisk.__version__" in text
    # The fragile source-parsing regex must be gone.
    assert r"__version__\s*=" not in text


def test_readme_is_declared():
    """Without this the PyPI page renders with no description."""
    assert 'readme = "README.md"' in read_pyproject()


def test_project_urls_present():
    text = read_pyproject()
    assert "[project.urls]" in text
    for key in ("Homepage", "Repository", "Changelog"):
        assert re.search(rf"^{key}\s*=", text, re.M), f"missing {key} URL"


def test_repo_urls_agree_across_files():
    """pyproject and README must name the same GitHub repo.

    The repo was renamed once (JonVannucci -> cryocliff) and the URLs were left
    pointing at the old owner; GitHub redirected, so nothing visibly broke
    while the metadata quietly went stale. [project.urls] is baked into each
    PyPI release, so drift here is only noticed long after it matters.
    """
    pattern = re.compile(r"github\.com/([^/\s\"']+/[^/\s\"')]+?)(?:\.git)?(?=[/\s\"')]|$)")
    found = {}
    for name in ("pyproject.toml", "README.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        for slug in pattern.findall(text):
            found.setdefault(slug, []).append(name)
    assert found, "no GitHub URLs found at all"
    assert len(found) == 1, f"conflicting repo URLs: {found}"
