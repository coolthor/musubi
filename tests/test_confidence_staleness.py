"""Tests for confidence + staleness features.

Covers:
- Frontmatter parsing of confidence, verified_by, superseded_by
- Referenced path extraction from note body
- Staleness check comparing referenced file mtime to note mtime
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


# --- Referenced path extraction -------------------------------------------

def test_extract_referenced_paths_absolute():
    from musubi.builder import _extract_referenced_paths
    text = """
    See `/Users/coolthor/BPSTracker/CLAUDE.md` for details.
    Also /home/user/foo/bar.md is relevant.
    """
    paths = _extract_referenced_paths(text)
    assert "/Users/coolthor/BPSTracker/CLAUDE.md" in paths
    assert "/home/user/foo/bar.md" in paths


def test_extract_referenced_paths_home_anchored():
    from musubi.builder import _extract_referenced_paths
    text = "Reference ~/ai-muninn-docs/experience-2026-04-14.md and more."
    paths = _extract_referenced_paths(text)
    assert "~/ai-muninn-docs/experience-2026-04-14.md" in paths


def test_extract_referenced_paths_ignores_urls():
    from musubi.builder import _extract_referenced_paths
    text = "Check https://example.com/path/to/thing and http://foo.com/bar/baz."
    paths = _extract_referenced_paths(text)
    # URL path fragments should NOT be captured as filesystem paths
    assert not any("example.com" in p or "foo.com" in p for p in paths)
    assert not any(p.startswith("/path/to/thing") for p in paths)


def test_extract_referenced_paths_dedupes():
    from musubi.builder import _extract_referenced_paths
    text = "/tmp/foo.log appears twice: /tmp/foo.log"
    paths = _extract_referenced_paths(text)
    assert paths.count("/tmp/foo.log") == 1


def test_extract_referenced_paths_requires_two_segments():
    from musubi.builder import _extract_referenced_paths
    # `/tmp` alone is too short — require at least one nested component
    text = "Just /tmp or ~/x"
    paths = _extract_referenced_paths(text)
    assert "/tmp" not in paths
    assert "~/x" not in paths


# --- Frontmatter → node attrs -------------------------------------------

def test_frontmatter_propagates_confidence(tmp_path: Path):
    from musubi.builder import _read_fs_documents
    note = tmp_path / "notes" / "sample.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\n"
        "title: Sample\n"
        "confidence: verified\n"
        "verified_by: \"trajectory exit_status check\"\n"
        "---\n"
        "body content\n"
    )
    docs = _read_fs_documents(tmp_path)
    assert len(docs) == 1
    assert docs[0]["confidence"] == "verified"
    assert docs[0]["verified_by"] == "trajectory exit_status check"


def test_frontmatter_confidence_absent_is_none(tmp_path: Path):
    from musubi.builder import _read_fs_documents
    note = tmp_path / "notes" / "no_confidence.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntitle: Plain\n---\njust body\n")
    docs = _read_fs_documents(tmp_path)
    assert docs[0].get("confidence") is None


def test_frontmatter_superseded_by(tmp_path: Path):
    from musubi.builder import _read_fs_documents
    note = tmp_path / "n" / "x.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\n"
        "confidence: superseded\n"
        "superseded_by: project_swe_bench_local.md\n"
        "---\n"
        "old content\n"
    )
    docs = _read_fs_documents(tmp_path)
    assert docs[0]["confidence"] == "superseded"
    assert docs[0]["superseded_by"] == "project_swe_bench_local.md"


# --- Referenced paths stored on doc -------------------------------------

def test_referenced_paths_on_doc(tmp_path: Path):
    from musubi.builder import _read_fs_documents
    note = tmp_path / "n" / "ref.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntitle: Ref\n---\n"
        "This references /Users/coolthor/BPSTracker/CLAUDE.md heavily.\n"
    )
    docs = _read_fs_documents(tmp_path)
    assert "/Users/coolthor/BPSTracker/CLAUDE.md" in docs[0]["referenced_paths"]


# --- Staleness at query time --------------------------------------------

def test_staleness_check_detects_newer_reference(tmp_path: Path):
    from musubi.staleness import compute_staleness

    ref = tmp_path / "referenced.md"
    ref.write_text("hello")
    # Note was written BEFORE the referenced file was last modified
    node_mtime = time.time() - 3600  # 1 hour ago
    # Touch the referenced file to NOW
    now = time.time()
    os.utime(ref, (now, now))

    stale = compute_staleness(
        node_modified_at=node_mtime,
        referenced_paths=[str(ref)],
    )
    assert stale["stale"] is True
    assert str(ref) in stale["newer_refs"]


def test_staleness_check_no_change(tmp_path: Path):
    from musubi.staleness import compute_staleness

    ref = tmp_path / "referenced.md"
    ref.write_text("hello")
    # Note written AFTER the ref was last modified
    ref_mtime = ref.stat().st_mtime
    node_mtime = ref_mtime + 3600  # 1 hour newer than ref

    stale = compute_staleness(
        node_modified_at=node_mtime,
        referenced_paths=[str(ref)],
    )
    assert stale["stale"] is False


def test_staleness_ignores_missing_files(tmp_path: Path):
    from musubi.staleness import compute_staleness

    stale = compute_staleness(
        node_modified_at=time.time(),
        referenced_paths=["/nonexistent/path/that/does/not/exist.md"],
    )
    assert stale["stale"] is False
    assert stale["newer_refs"] == []


def test_staleness_ignores_directories(tmp_path: Path):
    """Directories shouldn't trigger staleness — only regular file mtimes matter."""
    from musubi.staleness import compute_staleness

    d = tmp_path / "subdir"
    d.mkdir()
    # Directory mtime will be "now" — but we shouldn't flag as stale
    result = compute_staleness(
        node_modified_at=time.time() - 3600,
        referenced_paths=[str(d)],
    )
    assert result["stale"] is False


def test_staleness_ignores_devices():
    """/dev/null etc. shouldn't trigger staleness."""
    from musubi.staleness import compute_staleness
    result = compute_staleness(
        node_modified_at=time.time() - 86400,
        referenced_paths=["/dev/null"],
    )
    assert result["stale"] is False


def test_staleness_expands_home_anchored(tmp_path: Path, monkeypatch):
    from musubi.staleness import compute_staleness

    # Make ~ resolve to tmp_path
    monkeypatch.setenv("HOME", str(tmp_path))

    ref = tmp_path / "ref.md"
    ref.write_text("x")
    now = time.time()
    os.utime(ref, (now, now))

    stale = compute_staleness(
        node_modified_at=now - 3600,
        referenced_paths=["~/ref.md"],
    )
    assert stale["stale"] is True
