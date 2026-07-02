"""Musubi MCP server (stdio transport).

Exposes musubi as first-class MCP tools, on par with qmd.

Tools:
  - search: hybrid qmd keyword + graph neighbor boost
  - neighbors: find docs related to a given doc
  - cold: list orphan/stale docs (archive candidates)
  - stats: graph summary
  - orient: compact corpus orientation map for agents
  - map: exhaustive corpus map (optionally truncated)
  - health: knowledge-base health audit

Launch via: `musubi mcp` (stdio transport for Claude Code).
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from musubi.config import load_config
from musubi.graph import Graph
from musubi.mapgen import generate_map, generate_orient
from musubi.search import DIRECT_KIND, expand_qmd_hits
from musubi.staleness import compute_staleness


def _format_node(node: dict[str, Any]) -> dict[str, Any]:
    """Compact node representation for JSON output.

    Includes confidence + staleness flags when present so callers can tell
    at a glance whether a hit is trustworthy or needs verification.
    """
    out: dict[str, Any] = {
        "id": node.get("id"),
        "collection": node.get("collection", "?"),
        "title": node.get("title", "?"),
        "path": node.get("path", "?"),
    }
    for key in ("confidence", "verified_by", "superseded_by"):
        val = node.get(key)
        if val:
            out[key] = val

    stale_info = compute_staleness(
        node.get("modified_at"),
        node.get("referenced_paths") or [],
    )
    if stale_info["stale"]:
        out["stale"] = True
        out["stale_refs"] = stale_info["newer_refs"]

    return out


def _load_graph() -> tuple[Graph | None, str | None]:
    """Load the graph, return (graph, error_msg)."""
    try:
        cfg = load_config()
        if not cfg.graph_path.exists():
            return None, f"Graph not built yet. Run `musubi build` first."
        g = Graph.load(cfg.graph_path)
        return g, None
    except Exception as e:
        return None, f"Failed to load graph: {e}"


def _hybrid_search(query: str, limit: int = 10) -> dict[str, Any]:
    """Call qmd search then expand via graph neighbors."""
    g, err = _load_graph()
    if err:
        return {"error": err, "hits": []}

    cfg = load_config()
    try:
        result = subprocess.run(
            [cfg.qmd_bin, "search", query, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"error": f"qmd call failed: {e}", "hits": []}

    if result.returncode != 0:
        return {"error": f"qmd exit {result.returncode}: {result.stderr[:200]}", "hits": []}

    try:
        hits = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "qmd did not return JSON", "raw": result.stdout[:500], "hits": []}

    if not isinstance(hits, list):
        hits = hits.get("results", []) if isinstance(hits, dict) else []

    ranked, skipped = expand_qmd_hits(g, hits, query=query, limit=limit)

    results = []
    direct_count = 0
    for hit in ranked:
        n = g.id_to_node.get(hit.node_id, {})
        if hit.kind == DIRECT_KIND:
            direct_count += 1
        results.append({
            **_format_node(n),
            "score": round(hit.score, 4),
            "kind": hit.kind,
        })

    return {
        "query": query,
        "hits": results,
        "skipped_qmd_hits": skipped,
        "summary": f"{direct_count} direct hits + {len(ranked) - direct_count} graph neighbors",
    }


def _neighbors(query: str, limit: int = 10) -> dict[str, Any]:
    """Find graph neighbors of a doc matching the query."""
    g, err = _load_graph()
    if err:
        return {"error": err, "neighbors": []}

    nid = Graph.match_qmd_uri(query, g.path_to_id, g.collection_path_to_id)
    if nid is None:
        # Try as title/partial match
        for path, node_id in g.path_to_id.items():
            if query.lower() in path.lower():
                nid = node_id
                break

    if nid is None:
        return {"error": f"No doc matched '{query}'", "neighbors": []}

    anchor = g.id_to_node.get(nid, {})
    raw_neighbors = g.neighbors_of(nid, limit=limit)

    neighbors = []
    for nbr in raw_neighbors:
        n_node = g.id_to_node.get(nbr["id"], {})
        neighbors.append({
            **_format_node(n_node),
            "weight": nbr.get("weight", 0),
            "shared_concepts": nbr.get("shared_concepts", []),
        })

    return {
        "anchor": _format_node(anchor),
        "neighbors": neighbors,
    }


def _cold(limit: int = 20) -> dict[str, Any]:
    """List cold/orphan docs — archive candidates."""
    g, err = _load_graph()
    if err:
        return {"error": err, "cold": []}

    cold_nodes = []
    for nid, node in g.id_to_node.items():
        degree = len(list(g.neighbors_of(nid, limit=100)))
        if degree == 0:
            cold_nodes.append({**_format_node(node), "degree": 0})
        elif degree <= 2:
            cold_nodes.append({**_format_node(node), "degree": degree})

    cold_nodes.sort(key=lambda x: x["degree"])
    return {
        "cold": cold_nodes[:limit],
        "total_cold": len(cold_nodes),
        "note": "degree=0 = orphan (safe to archive). degree=1-2 = weakly connected.",
    }


def _stats() -> dict[str, Any]:
    """Graph summary."""
    g, err = _load_graph()
    if err:
        return {"error": err}

    n_nodes = len(g.id_to_node)
    n_edges = sum(len(list(g.neighbors_of(nid, limit=10000))) for nid in g.id_to_node) // 2

    collections: dict[str, int] = {}
    for node in g.id_to_node.values():
        coll = node.get("collection", "?")
        collections[coll] = collections.get(coll, 0) + 1

    return {
        "nodes": n_nodes,
        "edges": n_edges,
        "collections": collections,
    }


def _orient(
    by: str = "collection",
    limit_per_group: int = 8,
    max_groups: int = 20,
) -> dict[str, Any]:
    """Compact orientation map for agents."""
    g, err = _load_graph()
    if err:
        return {"error": err}
    return {
        "format": "markdown",
        "orient": generate_orient(
            g,
            by=by,
            limit_per_group=limit_per_group,
            max_groups=max_groups,
        ),
    }


def _map(by: str = "collection", max_chars: int = 50_000) -> dict[str, Any]:
    """Full map; truncate by default so MCP callers do not flood context."""
    g, err = _load_graph()
    if err:
        return {"error": err}
    text = generate_map(g, by=by)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rstrip() + "\n\n... truncated; call with a larger max_chars or use `orient`.\n"
    return {
        "format": "markdown",
        "map": text,
        "chars": len(text),
        "truncated": truncated,
    }


def _health(limit: int = 40) -> dict[str, Any]:
    """Knowledge-base health audit."""
    from musubi import health

    g, err = _load_graph()
    if err:
        return {"error": err}
    findings = health.check(g)
    return {
        "summary": {
            "total": findings["total"],
            "connected": findings["connected"],
            "coverage": findings["coverage"],
            "orphan_count": len(findings["orphans"]),
            "hub_count": len(findings["hubs"]),
            "dangling_count": len(findings["dangling"]),
            "duplicate_count": len(findings.get("duplicates") or []),
        },
        "hubs": findings["hubs"][:limit],
        "suggested_stop_concepts": findings.get("suggested_stop_concepts", [])[:limit],
        "dangling_by_kind": findings.get("dangling_by_kind", {}),
        "dangling": findings["dangling"][:limit],
        "duplicates": [
            [
                _format_node(node)
                for node in group
            ]
            for group in (findings.get("duplicates") or [])[:limit]
        ],
        "orphans": [_format_node(node) for node in findings["orphans"][:limit]],
    }


def build_server() -> Server:
    server = Server("musubi")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search",
                description=(
                    "Hybrid search: qmd keyword match + musubi graph neighbor boost. "
                    "Returns direct hits (★) and related docs surfaced by graph neighbors (+). "
                    "Use this for 'find past experience' queries — surfaces related notes you'd miss with keyword-only search."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "limit": {"type": "integer", "default": 10, "description": "Max results (default 10)."},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="neighbors",
                description=(
                    "Find graph neighbors of a specific doc — docs that share concepts via musubi's knowledge graph. "
                    "Use this when you already have a doc and want to find related ones without knowing keywords."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "File path or doc title fragment."},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="cold",
                description=(
                    "List orphan or weakly-connected docs — candidates for archiving or cleanup. "
                    "degree=0 means no graph connections (safe to archive)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 20},
                    },
                },
            ),
            Tool(
                name="stats",
                description="Graph summary: node count, edge count, per-collection breakdown.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="orient",
                description=(
                    "Compact orientation map for agents. Use this first when you need a fast overview "
                    "of the corpus without reading the exhaustive `map` output."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "by": {
                            "type": "string",
                            "enum": ["collection", "tag", "concept"],
                            "default": "collection",
                        },
                        "limit_per_group": {"type": "integer", "default": 8},
                        "max_groups": {"type": "integer", "default": 20},
                    },
                },
            ),
            Tool(
                name="map",
                description=(
                    "Exhaustive markdown map of the corpus. Can be large; prefer `orient` unless "
                    "you need every note."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "by": {
                            "type": "string",
                            "enum": ["collection", "tag", "concept"],
                            "default": "collection",
                        },
                        "max_chars": {"type": "integer", "default": 50000},
                    },
                },
            ),
            Tool(
                name="health",
                description=(
                    "Knowledge-base health audit: orphans, hub concepts, dangling file refs, "
                    "and duplicate/mirrored notes."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 40},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "search":
            result = _hybrid_search(arguments["query"], arguments.get("limit", 10))
        elif name == "neighbors":
            result = _neighbors(arguments["query"], arguments.get("limit", 10))
        elif name == "cold":
            result = _cold(arguments.get("limit", 20))
        elif name == "stats":
            result = _stats()
        elif name == "orient":
            result = _orient(
                arguments.get("by", "collection"),
                arguments.get("limit_per_group", 8),
                arguments.get("max_groups", 20),
            )
        elif name == "map":
            result = _map(arguments.get("by", "collection"), arguments.get("max_chars", 50_000))
        elif name == "health":
            result = _health(arguments.get("limit", 40))
        else:
            result = {"error": f"unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    return server


def run() -> int:
    """Entry point — stdio MCP server."""
    import asyncio

    async def _run():
        server = build_server()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    try:
        asyncio.run(_run())
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"musubi mcp server error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
