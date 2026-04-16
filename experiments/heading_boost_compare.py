"""Compare graph neighbors before/after heading-boost.

Builds two graphs:
  1. Baseline — current default (no heading boost)
  2. Experimental — with MUSUBI_HEADING_BOOST=1

Then for each query doc, shows top-5 neighbors side-by-side so we can
eyeball whether the boosted version surfaces MORE-related notes.

Usage:
    uv run --with networkx --with numpy --with scikit-learn \\
        python experiments/heading_boost_compare.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


BASELINE_PATH = Path("/tmp/musubi-baseline.json")
BOOSTED_PATH = Path("/tmp/musubi-boosted.json")

QUERIES = [
    # (resolve-hint, reason-to-look)
    ("redis-singleton-churn", "known BPS-API perf note"),
    ("project-musubi-roadmap", "musubi self-reference"),
    ("gx10-vllm", "vLLM on GB10 (multi-candidate)"),
    ("swe-bench-local", "SWE-bench mainline"),
    ("bps-api-patterns", "BPSTracker patterns reference"),
]


def build_to(path: Path, heading_boost: bool) -> dict[str, Any]:
    from dataclasses import replace
    from musubi.builder import build
    from musubi.config import load_config

    cfg = replace(load_config(), graph_path=path)

    if heading_boost:
        os.environ["MUSUBI_HEADING_BOOST"] = "1"
    else:
        os.environ.pop("MUSUBI_HEADING_BOOST", None)

    return build(cfg, verbose=False)


def load_graph(path: Path):
    from musubi.graph import Graph
    return Graph.load(path)


def top5(g, query: str) -> list[tuple[str, float, list[str]]]:
    ids = g.resolve(query)
    if not ids:
        return []
    nid = ids[0]
    nbrs = g.neighbors_of(nid, limit=5)
    out = []
    for nbr in nbrs:
        n = g.id_to_node.get(nbr["id"], {})
        out.append((
            n.get("path", "?"),
            nbr.get("weight", 0),
            nbr.get("shared_concepts", [])[:3],
        ))
    return out


def main() -> int:
    print("Building baseline graph...")
    baseline_stats = build_to(BASELINE_PATH, heading_boost=False)
    print(f"  {baseline_stats}")

    print("\nBuilding heading-boosted graph...")
    boosted_stats = build_to(BOOSTED_PATH, heading_boost=True)
    print(f"  {boosted_stats}")

    g_base = load_graph(BASELINE_PATH)
    g_boost = load_graph(BOOSTED_PATH)

    print("\n" + "=" * 70)
    print(f"Edge count: baseline={baseline_stats['edges']}  boosted={boosted_stats['edges']}")
    print(f"Delta:      {boosted_stats['edges'] - baseline_stats['edges']:+d}")

    # Per-query side-by-side top-5
    for query, reason in QUERIES:
        ids = g_base.resolve(query)
        if not ids:
            print(f"\n\n### {query}  ({reason})")
            print("  <no match>")
            continue

        nid = ids[0]
        anchor = g_base.id_to_node[nid]
        print(f"\n\n### {query}  ({reason})")
        print(f"    anchor: {anchor.get('path')}")
        print()
        print(f"{'BASELINE':<45}  |  {'HEADING-BOOST':<45}")
        print("-" * 95)

        base = top5(g_base, query)
        boost = top5(g_boost, query)
        for i in range(5):
            b = base[i] if i < len(base) else None
            x = boost[i] if i < len(boost) else None
            b_str = f"{b[1]:5.1f} {os.path.basename(b[0])[:36]:<36}" if b else "—"
            x_str = f"{x[1]:5.1f} {os.path.basename(x[0])[:36]:<36}" if x else "—"
            marker = "  " if (b and x and b[0] == x[0]) else "≠ "
            print(f"{marker}{b_str}  |  {x_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
