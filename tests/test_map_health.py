"""Tests for `musubi map` and `musubi health`.

Builds a tiny graph from a temp directory (filesystem mode) and checks that:
- builder now carries frontmatter `description` / `tags` onto nodes
- map renders titles + descriptions, grouped by collection
- health reports coverage, orphans list, and dangling filesystem refs
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _build(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    (notes / "projects").mkdir(parents=True)
    (notes / "refs").mkdir(parents=True)

    (notes / "projects" / "alpha.md").write_text(
        "---\ntitle: Alpha Project\ndescription: the alpha orientation note\ntags: core\n---\n"
        "Alpha works with vllm and nvfp4 and quantization.\n",
        encoding="utf-8",
    )
    (notes / "projects" / "beta.md").write_text(
        "---\ntitle: Beta Project\ndescription: beta builds on vllm quantization\n---\n"
        "Beta also uses vllm and nvfp4 quantization heavily.\n",
        encoding="utf-8",
    )
    # references a path that does not exist -> dangling
    (notes / "refs" / "gamma.md").write_text(
        "---\ntitle: Gamma\ndescription: points at a missing file\n---\n"
        "See ~/musubi_missing_xyz_123/note.md for context.\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MUSUBI_GRAPH_PATH", str(tmp_path / "graph.json"))
    monkeypatch.setenv("MUSUBI_QMD_DB", str(tmp_path / "none.sqlite"))
    monkeypatch.delenv("MUSUBI_CONCEPTS", raising=False)

    from musubi.config import load_config
    from musubi.builder import build
    from musubi.graph import Graph

    cfg = load_config()
    build(cfg, source=notes, verbose=False)
    return Graph.load(cfg.graph_path)


def test_builder_carries_description(tmp_path, monkeypatch):
    g = _build(tmp_path, monkeypatch)
    descs = [n.get("description") for n in g.id_to_node.values()]
    assert "the alpha orientation note" in descs


def test_map_renders_titles_and_descriptions(tmp_path, monkeypatch):
    from musubi.mapgen import generate_map

    g = _build(tmp_path, monkeypatch)
    md = generate_map(g, by="collection")
    assert "Alpha Project" in md
    assert "the alpha orientation note" in md
    assert "## projects" in md          # grouped by first-level dir = collection


def test_map_concept_fallback_when_no_description(tmp_path, monkeypatch):
    from musubi.mapgen import generate_map

    g = _build(tmp_path, monkeypatch)
    # a node without description should still get a "concepts:" aboutness line
    md = generate_map(g)
    assert "concepts:" in md or "the alpha orientation note" in md


def test_health_reports_coverage_and_dangling(tmp_path, monkeypatch):
    from musubi import health

    g = _build(tmp_path, monkeypatch)
    f = health.check(g)
    assert f["total"] == 3
    assert 0.0 <= f["coverage"] <= 1.0
    assert isinstance(f["orphans"], list)
    # gamma references a missing file -> must be flagged dangling
    dangling_refs = [ref for _, ref in f["dangling"]]
    assert any("musubi_missing_xyz_123" in r for r in dangling_refs)
    report = health.format_report(f)
    assert "KB health" in report
