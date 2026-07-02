from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


class FakeGraph:
    def __init__(self):
        self.id_to_node = {
            1: {
                "id": 1,
                "collection": "shared-memory",
                "path": "codex-ssd.md",
                "title": "Codex SSD Logging Version Notes",
            },
            2: {
                "id": 2,
                "collection": "claude-memory",
                "path": "codex-ssd.md",
                "title": "Codex SSD Logging Version Notes",
            },
            3: {
                "id": 3,
                "collection": "shared-memory",
                "path": "KB_MAP.md",
                "title": "KB_MAP — AI orientation map of the knowledge base",
            },
            4: {
                "id": 4,
                "collection": "shared-memory",
                "path": "codex-release-note.md",
                "title": "Codex Release Notes",
            },
        }
        self.path_to_id = {"codex-ssd.md": 1, "KB_MAP.md": 3, "codex-release-note.md": 4}
        self.collection_path_to_id = {
            f"{n['collection']}/{n['path']}": nid
            for nid, n in self.id_to_node.items()
        }
        self._neighbors: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        self._neighbors[2] = [
            {"id": 3, "weight": 500.0},
            {"id": 4, "weight": 120.0},
        ]

    def neighbors_of(self, node_id: Any, limit: int = 10):
        return self._neighbors.get(node_id, [])[:limit]

    @staticmethod
    def match_qmd_uri(file_field, path_to_id, collection_path_to_id=None):
        m = re.match(r"qmd://([^/]+)/(.+)$", file_field)
        if m and collection_path_to_id is not None:
            nid = collection_path_to_id.get(f"{m.group(1)}/{m.group(2)}")
            if nid is not None:
                return nid
        rel = m.group(2) if m else file_field
        return path_to_id.get(rel)


def test_direct_hit_stays_above_high_weight_neighbor():
    from musubi.search import expand_qmd_hits

    g = FakeGraph()
    hits, skipped = expand_qmd_hits(
        g,
        [{"file": "qmd://shared-memory/codex-ssd.md"}],
        query="Codex SSD logging",
        limit=3,
    )

    assert skipped == 0
    assert hits[0].kind == "direct"
    assert hits[0].node_id == 2  # canonical source beats shared-memory mirror
    assert [h.kind for h in hits[1:]] == ["neighbor", "neighbor"]


def test_meta_neighbor_is_downranked_below_real_neighbor():
    from musubi.search import expand_qmd_hits

    g = FakeGraph()
    hits, _ = expand_qmd_hits(
        g,
        [{"file": "qmd://shared-memory/codex-ssd.md"}],
        query="Codex SSD logging",
        limit=3,
    )

    neighbor_ids = [h.node_id for h in hits if h.kind == "neighbor"]
    assert neighbor_ids == [4, 3]


def test_explicit_meta_query_keeps_meta_priority():
    from musubi.search import expand_qmd_hits

    g = FakeGraph()
    hits, _ = expand_qmd_hits(
        g,
        [{"file": "qmd://shared-memory/KB_MAP.md"}],
        query="KB_MAP",
        limit=1,
    )

    assert hits[0].node_id == 3
    assert hits[0].kind == "direct"
