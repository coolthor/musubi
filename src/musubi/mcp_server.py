"""Musubi MCP server (stdio transport).

Exposes musubi as first-class MCP tools, on par with qmd.

Tools:
  - search: hybrid qmd keyword + graph neighbor boost
  - neighbors: find docs related to a given doc
  - cold: list orphan/stale docs (archive candidates)
  - stats: graph summary

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

from musubi.cli import _clean_qmd_snippet
from musubi.config import load_config
from musubi.graph import Graph
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

    base_ids: list[tuple[Any, float]] = []
    id_to_snippet: dict[Any, str] = {}
    for rank, hit in enumerate(hits[:limit]):
        file_field = hit.get("file") or hit.get("path") or ""
        nid = Graph.match_qmd_uri(file_field, g.path_to_id)
        if nid is not None:
            base_ids.append((nid, 1.0 / (rank + 1)))
            snippet = hit.get("snippet")
            if snippet:
                id_to_snippet[nid] = _clean_qmd_snippet(snippet)

    expanded: dict[Any, float] = {}
    for nid, base in base_ids:
        expanded[nid] = expanded.get(nid, 0.0) + base
        for nbr in g.neighbors_of(nid, limit=2):
            nbr_id = nbr["id"]
            boost = base * 0.3 * (nbr.get("weight", 1) / 10)
            expanded[nbr_id] = expanded.get(nbr_id, 0.0) + boost

    base_set = {nid for nid, _ in base_ids}
    ranked = sorted(expanded.items(), key=lambda kv: kv[1], reverse=True)[:limit]

    results = []
    for nid, score in ranked:
        n = g.id_to_node.get(nid, {})
        is_direct = nid in base_set
        entry = {
            **_format_node(n),
            "score": round(score, 4),
            "kind": "direct" if is_direct else "neighbor",
        }
        # Attach qmd's query-aligned snippet only to direct hits. Graph
        # neighbors didn't match the query, so a snippet would fake
        # authority — model should call neighbors or read_file to verify.
        if is_direct:
            snip = id_to_snippet.get(nid)
            if snip:
                entry["snippet"] = snip
        results.append(entry)

    return {
        "query": query,
        "hits": results,
        "summary": f"{len(base_set)} direct hits + {len(ranked) - len(base_set)} graph neighbors",
    }


def _neighbors(query: str, limit: int = 10) -> dict[str, Any]:
    """Find graph neighbors of a doc matching the query."""
    g, err = _load_graph()
    if err:
        return {"error": err, "neighbors": []}

    nid = Graph.match_qmd_uri(query, g.path_to_id)
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
