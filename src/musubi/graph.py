"""Read-side graph operations: loading, indexing, queries.

The graph is stored as NetworkX `node_link_data` JSON. Each node has at
minimum: `id`, `path`, `title`, `collection`, `modified_at`, `concepts`,
`concept_count`. Each edge has: `source`, `target`, `weight`,
`shared_concepts`, `edge_type` (concept | embedding).

This module intentionally avoids any dependency on qmd, sqlite, or
networkx itself — pure stdlib. Keeps the query path fast (no import cost
from heavy ML libs) and lets us ship `musubi stats` / `musubi neighbors`
on machines that only need read access.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass
class Graph:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    id_to_node: dict[Any, dict[str, Any]]
    path_to_id: dict[str, Any]
    title_to_id: dict[str, Any]
    neighbors: dict[Any, list[dict[str, Any]]]
    degree: dict[Any, int]

    @classmethod
    def load(cls, path: Path) -> "Graph":
        if not path.exists():
            raise FileNotFoundError(
                f"Graph file not found: {path}\n"
                f"Run `musubi build` to create it, or set MUSUBI_GRAPH_PATH."
            )
        try:
            with path.open() as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Graph file is corrupted: {path}\n"
                f"  {e}\n"
                f"Delete it and rebuild: musubi build"
            ) from e

        nodes = raw.get("nodes", [])
        edges = raw.get("edges", [])

        id_to_node: dict[Any, dict[str, Any]] = {}
        path_to_id: dict[str, Any] = {}
        title_to_id: dict[str, Any] = {}
        for idx, n in enumerate(nodes):
            node_id = n.get("id", idx)
            id_to_node[node_id] = n
            if n.get("path"):
                path_to_id[n["path"]] = node_id
            if n.get("title"):
                title_to_id[n["title"]] = node_id

        neighbors: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        degree: dict[Any, int] = defaultdict(int)
        for e in edges:
            s, t = e.get("source"), e.get("target")
            if s is None or t is None:
                continue
            neighbors[s].append({"id": t, **e})
            neighbors[t].append({"id": s, **e})
            degree[s] += 1
            degree[t] += 1

        return cls(
            nodes=nodes,
            edges=edges,
            id_to_node=id_to_node,
            path_to_id=path_to_id,
            title_to_id=title_to_id,
            neighbors=dict(neighbors),
            degree=dict(degree),
        )

    # ---- lookup ----

    def resolve(self, query: str) -> list[Any]:
        """Resolve a query string to one or more doc node IDs.

        Priority: exact int id → exact path → exact basename → path suffix
        match → path substring → title substring. Each tier is tried only
        if the previous one returned nothing. Within a tier, all matches
        are returned (the caller decides how to handle ambiguity).
        """
        # 1. Exact numeric id
        if query.isdigit():
            nid = int(query)
            if nid in self.id_to_node:
                return [nid]

        # 2. Exact full path
        if query in self.path_to_id:
            return [self.path_to_id[query]]

        ql = query.lower()

        # 3. Exact basename match (e.g. "vllm-fp8-kvcache-bug.md")
        basename_hits = [
            nid for p, nid in self.path_to_id.items()
            if os.path.basename(p).lower() == ql
            or os.path.splitext(os.path.basename(p))[0].lower() == ql
        ]
        if basename_hits:
            return basename_hits

        # 4. Path ends with query (e.g. "inference/vllm-fp8" matches
        #    "inference/vllm-fp8-kvcache-bug.md" but NOT "other/vllm-fp8-note.md")
        suffix_hits = [nid for p, nid in self.path_to_id.items() if p.lower().endswith(ql)]
        if suffix_hits:
            return suffix_hits

        # 5. Path substring (broadest, may be ambiguous)
        path_hits = [nid for p, nid in self.path_to_id.items() if ql in p.lower()]
        if path_hits:
            return path_hits

        # 6. Title substring
        return [nid for t, nid in self.title_to_id.items() if ql in t.lower()]

    def neighbors_of(self, node_id: Any, limit: int = 10) -> list[dict[str, Any]]:
        nbrs = self.neighbors.get(node_id, [])
        return sorted(nbrs, key=lambda e: e.get("weight", 0), reverse=True)[:limit]

    def iter_nodes(self) -> Iterator[tuple[Any, dict[str, Any]]]:
        return iter(self.id_to_node.items())

    def deg(self, node_id: Any) -> int:
        return self.degree.get(node_id, 0)

    @staticmethod
    def match_qmd_uri(file_field: str, path_to_id: dict[str, Any]) -> Any | None:
        """Map a qmd-style ``qmd://<collection>/<path>`` URI to a node id.

        Falls back to basename match only if the match is **unique**. If
        multiple graph nodes share the same basename, returns ``None``
        rather than guessing (caller can log a warning).
        """
        import re

        m = re.match(r"qmd://[^/]+/(.+)$", file_field)
        rel = m.group(1) if m else file_field

        # 1. Exact relative-path match
        nid = path_to_id.get(rel)
        if nid is not None:
            return nid

        # 2. Unique basename match (skip if ambiguous)
        base = os.path.basename(rel)
        candidates = [gnid for gp, gnid in path_to_id.items() if os.path.basename(gp) == base]
        if len(candidates) == 1:
            return candidates[0]
        return None
