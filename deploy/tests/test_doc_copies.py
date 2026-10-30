"""Verbatim copies of repo files in docs/*.md stay identical to the files (spec 2026-10-31, 4.4)."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUIDE = "docs/LITELLM_IMPLEMENTATION_GUIDE.md"
GUIDE_COPIES = {"deploy/litellm/config.yaml", "deploy/compose.yaml", "deploy/compose.vm.yaml", "docs/opencode.example.json"}
# The marker line, then the fence opening on the very next line, then the copy.
COPY = re.compile(r"^<!-- salinan: (?P<path>\S+) -->\n```[a-z]*\n(?P<body>.*?)^```$", re.M | re.S)
DOCS = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "docs").glob("*.md"))


def _copies(doc: str) -> list[tuple[str, str]]:
    return [(m["path"], m["body"]) for m in COPY.finditer((REPO / doc).read_text(encoding="utf-8"))]


def test_guide_carries_every_copy():
    assert {path for path, _ in _copies(GUIDE)} == GUIDE_COPIES


def test_pre_commit_runs_unit_for_docs_only_commits():
    # Otherwise a docs-only commit can leave a copy stale until someone touches deploy/.
    hook = (REPO / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    trigger = re.search(r"grep -qE '([^']+)'; then\n\tmake -s unit", hook)[1]
    assert [p for p in (GUIDE, "docs/opencode.example.json") if not re.search(trigger, p)] == []


@pytest.mark.parametrize("doc", DOCS)
def test_copies_match_their_files(doc):
    stale = [path for path, body in _copies(doc) if body != (REPO / path).read_text(encoding="utf-8")]
    assert stale == [], f"{doc}: salinan berbeda dari file aslinya; salin ulang isinya"
