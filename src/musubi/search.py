"""Shared hybrid-search ranking for CLI and MCP.

The important invariant: qmd direct hits are retrieval evidence; graph
neighbors are context expansion. A strong graph edge can make a neighbor useful,
but it must not outrank the direct evidence that found the topic.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

DIRECT_KIND = "direct"
NEIGHBOR_KIND = "neighbor"

_META_BASENAMES = {
    "kb_map.md",
    "kb-map.md",
    "log.md",
    "memory.md",
}
_META_TITLE_RE = re.compile(r"\b(kb[_ -]?map|memory\.md|orientation map)\b|^log\b", re.I)
_EXPLICIT_META_RE = re.compile(r"\b(kb[_ -]?map|memory\.md|orientation map)\b", re.I)

_COLLECTION_PRIORITY = {
    # shared-memory is a mirror in Thor's setup; prefer the canonical source
    # collection when the same note appears in both.
    "claude-memory": 0,
    "hermes-memory": 1,
    "shared-memory": 9,
}


@dataclass(frozen=True)
class SearchHit:
    node_id: Any
    score: float
    kind: str
    qmd_rank: int | None = None


def _node_key(node: dict[str, Any]) -> tuple[str, str] | None:
    """Return a stable duplicate key for mirrored notes.

    qmd mode stores the content hash on new graphs. Older graphs do not, so
    fall back to exact path + normalized title, which catches collection mirrors
    without collapsing unrelated notes that merely share a basename.
    """
    content_hash = (node.get("hash") or "").strip()
    if content_hash:
        return ("hash", content_hash)

    path = (node.get("path") or "").strip().lower()
    title = re.sub(r"\s+", " ", (node.get("title") or "").strip().lower())
    if path and title:
        return ("path-title", f"{path}\0{title}")
    return None


def _collection_rank(node: dict[str, Any]) -> tuple[int, str]:
    coll = node.get("collection") or ""
    return (_COLLECTION_PRIORITY.get(coll, 5), coll)


def _canonical_node_id(graph: Any, node_id: Any) -> Any:
    node = graph.id_to_node.get(node_id, {})
    key = _node_key(node)
    if key is None:
        return node_id

    candidates: list[tuple[tuple[int, str], str, Any]] = []
    for cand_id, cand in graph.id_to_node.items():
        if _node_key(cand) != key:
            continue
        candidates.append((_collection_rank(cand), cand.get("path", ""), cand_id))
    if not candidates:
        return node_id
    return min(candidates)[2]


def is_meta_doc(node: dict[str, Any]) -> bool:
    path = node.get("path") or ""
    title = node.get("title") or ""
    basename = os.path.basename(path).lower()
    return basename in _META_BASENAMES or bool(_META_TITLE_RE.search(title))


def canonical_node_ids(graph: Any) -> list[Any]:
    """Return one preferred node id per mirrored/duplicate note key."""
    seen: set[tuple[str, str]] = set()
    ids: list[Any] = []
    for node_id in graph.id_to_node:
        canonical_id = _canonical_node_id(graph, node_id)
        node = graph.id_to_node.get(canonical_id, {})
        key = _node_key(node) or ("id", str(canonical_id))
        if key in seen:
            continue
        seen.add(key)
        ids.append(canonical_id)
    return ids


def _meta_query(query: str) -> bool:
    return bool(_EXPLICIT_META_RE.search(query))


def _match_qmd_hit(graph: Any, file_field: str) -> Any | None:
    """Map qmd's file URI to a graph node, preserving collection when possible."""
    return graph.match_qmd_uri(
        file_field,
        graph.path_to_id,
        getattr(graph, "collection_path_to_id", None),
    )


def expand_qmd_hits(
    graph: Any,
    qmd_hits: list[dict[str, Any]],
    *,
    query: str,
    limit: int = 10,
    neighbor_limit: int = 2,
) -> tuple[list[SearchHit], int]:
    """Rank qmd direct hits plus graph neighbors.

    Returns ``(hits, skipped_count)``. Direct hits are always sorted before graph
    neighbors. Neighbor boosts are capped and meta-doc neighbors are downranked
    unless the user explicitly asked for a map/memory document.
    """
    direct: dict[Any, SearchHit] = {}
    skipped = 0
    explicit_meta = _meta_query(query)

    for rank, hit in enumerate(qmd_hits[:limit]):
        file_field = hit.get("file") or hit.get("path") or ""
        nid = _match_qmd_hit(graph, file_field)
        if nid is None:
            skipped += 1
            continue
        nid = _canonical_node_id(graph, nid)
        base = 1.0 / (rank + 1)
        prev = direct.get(nid)
        if prev is None or rank < (prev.qmd_rank or rank + 1):
            direct[nid] = SearchHit(nid, base, DIRECT_KIND, rank)

    neighbor_scores: dict[Any, float] = {}
    for nid, hit in direct.items():
        base = hit.score
        for nbr in graph.neighbors_of(nid, limit=neighbor_limit):
            nbr_id = _canonical_node_id(graph, nbr["id"])
            if nbr_id in direct:
                continue
            raw_boost = base * 0.3 * (nbr.get("weight", 1) / 10)
            boost = min(raw_boost, base * 0.25)
            nbr_node = graph.id_to_node.get(nbr_id, {})
            if is_meta_doc(nbr_node) and not explicit_meta:
                boost *= 0.15
            neighbor_scores[nbr_id] = neighbor_scores.get(nbr_id, 0.0) + boost

    neighbors = [
        SearchHit(nid, score, NEIGHBOR_KIND, None)
        for nid, score in neighbor_scores.items()
    ]

    def sort_key(hit: SearchHit) -> tuple[int, int, int, float, tuple[int, str], str]:
        node = graph.id_to_node.get(hit.node_id, {})
        kind_order = 0 if hit.kind == DIRECT_KIND else 1
        meta_order = 1 if is_meta_doc(node) and not explicit_meta else 0
        rank = hit.qmd_rank if hit.qmd_rank is not None else 999_999
        title = (node.get("title") or "").lower()
        return (kind_order, meta_order, rank, -hit.score, _collection_rank(node), title)

    ranked = sorted([*direct.values(), *neighbors], key=sort_key)

    # Defensive de-dupe: canonicalization should already merge mirrors, but keep
    # only the best ranked entry if an older graph lacks enough metadata.
    seen_keys: set[tuple[str, str]] = set()
    out: list[SearchHit] = []
    for hit in ranked:
        node = graph.id_to_node.get(hit.node_id, {})
        key = _node_key(node) or ("id", str(hit.node_id))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(hit)
        if len(out) >= limit:
            break

    return out, skipped
