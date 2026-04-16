"""Musubi CLI entry point.

Subcommands
-----------
  musubi stats                     print graph summary
  musubi neighbors <query>         show graph neighbors of a doc
  musubi cold [--limit N]          list isolated / stale docs
  musubi search <query>            hybrid qmd-keyword + graph-expand search
  musubi path <query>              resolve a query to node id + path (debug)
  musubi build                     rebuild the graph from the qmd index
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from musubi import __version__
from musubi.config import Config, load_config
from musubi.graph import Graph

ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "red": "\033[31m",
    "magenta": "\033[35m",
}
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text: str, color: str) -> str:
    if not USE_COLOR:
        return text
    return f"{ANSI[color]}{text}{ANSI['reset']}"


_CONFIDENCE_COLORS = {
    "verified": "green",
    "hypothesis": "yellow",
    "superseded": "red",
}


def _node_label(node: dict[str, Any]) -> str:
    coll = node.get("collection", "?")
    title = node.get("title", "?")
    path = node.get("path", "?")

    badges: list[str] = []
    conf = node.get("confidence")
    if conf:
        mark = {"verified": "✓", "hypothesis": "?", "superseded": "⚠"}.get(conf, "")
        color = _CONFIDENCE_COLORS.get(conf, "dim")
        badges.append(c(f"[{conf} {mark}]".rstrip(" ]") + "]", color))

    from musubi.staleness import compute_staleness
    stale_info = compute_staleness(
        node.get("modified_at"),
        node.get("referenced_paths") or [],
    )
    if stale_info["stale"]:
        n = len(stale_info["newer_refs"])
        badges.append(c(f"⚠ stale ({n} src newer)", "yellow"))

    badge_str = (" " + " ".join(badges)) if badges else ""
    return f"[{coll}] {title}{badge_str}  {c(path, 'dim')}"


def _is_stale(cfg: Config) -> bool:
    """Check if the graph is older than source data or older than 24 hours.

    Checks three sources of freshness:
    1. Graph age (> 24h = stale)
    2. qmd sqlite index mtime (re-indexed since last build = stale)
    3. MUSUBI_WATCH_DIRS directories (any .md newer than graph = stale)

    MUSUBI_WATCH_DIRS is a colon-separated list of directories to monitor
    for new/modified .md files. Useful for auto-memory directories or other
    note sources that aren't tracked by qmd.
    """
    if not cfg.graph_path.exists():
        return True

    graph_mtime = cfg.graph_path.stat().st_mtime
    graph_age_h = (datetime.now(timezone.utc).timestamp() - graph_mtime) / 3600

    if graph_age_h > 24:
        return True
    if cfg.qmd_db.exists() and cfg.qmd_db.stat().st_mtime > graph_mtime:
        return True

    # Check the original source directory (stored in graph metadata).
    # This handles filesystem-mode users who don't have qmd.
    # Only read the first 1KB to extract "source" without parsing the full graph.
    from pathlib import Path as _P
    try:
        head = cfg.graph_path.read_text(encoding="utf-8")[:1024]
        import re as _re
        m = _re.search(r'"source"\s*:\s*"([^"]+)"', head)
        src = m.group(1) if m else ""
        if src and src != "qmd":
            src_dir = _P(os.path.expanduser(src))
            if src_dir.is_dir():
                for md in src_dir.rglob("*.md"):
                    if md.stat().st_mtime > graph_mtime:
                        return True
    except Exception:
        pass

    # Check additional watched directories
    watch_dirs = os.environ.get("MUSUBI_WATCH_DIRS", "")
    for d in watch_dirs.split(":"):
        d = d.strip()
        if not d:
            continue
        watch = _P(os.path.expanduser(d))
        if not watch.is_dir():
            continue
        for md in watch.rglob("*.md"):
            if md.stat().st_mtime > graph_mtime:
                return True

    return False


def _auto_rebuild_if_stale(cfg: Config) -> None:
    """Automatically rebuild the graph if it's stale.

    This replaces the need for cron — the graph stays fresh lazily.
    Rebuild only happens when you actually query, not on a schedule.
    """
    if not _is_stale(cfg):
        return

    age_str = ""
    if cfg.graph_path.exists():
        age_h = (datetime.now(timezone.utc).timestamp() - cfg.graph_path.stat().st_mtime) / 3600
        age_str = f" ({age_h:.0f}h old)" if age_h < 48 else f" ({age_h / 24:.0f}d old)"

    # Read the original source from graph metadata so we rebuild from
    # the same place (filesystem dir vs qmd).
    source_dir = None
    try:
        import re as _re
        head = cfg.graph_path.read_text(encoding="utf-8")[:1024]
        m = _re.search(r'"source"\s*:\s*"([^"]+)"', head)
        src = m.group(1) if m else ""
        if src and src != "qmd":
            from pathlib import Path as _P
            candidate = _P(os.path.expanduser(src))
            if candidate.is_dir():
                source_dir = candidate
    except Exception:
        pass

    source_label = str(source_dir) if source_dir else "qmd"
    print(
        c(f"  ↻ graph is stale{age_str}, auto-rebuilding from {source_label}...", "yellow"),
        file=sys.stderr,
    )

    from musubi.builder import build as do_build

    try:
        summary = do_build(cfg, source=source_dir, verbose=False)
        n = summary["nodes"]
        e = summary["concept_edges"] + summary.get("embedding_edges", 0)
        print(
            c(f"  ✓ rebuilt: {n} docs, {e} edges", "green"),
            file=sys.stderr,
        )
    except Exception as ex:
        print(
            c(f"  ⚠️ auto-rebuild failed: {ex}. Using stale graph.", "yellow"),
            file=sys.stderr,
        )


def _load_graph_or_exit(cfg: Config) -> Graph:
    _auto_rebuild_if_stale(cfg)
    try:
        g = Graph.load(cfg.graph_path)
    except (FileNotFoundError, ValueError) as e:
        print(c(str(e), "red"), file=sys.stderr)
        sys.exit(1)
    return g


# ---------- commands ----------


def cmd_stats(args: argparse.Namespace, cfg: Config) -> int:
    g = _load_graph_or_exit(cfg)

    coll_counts: dict[str, int] = defaultdict(int)
    concept_counter: Counter[str] = Counter()
    etype_counter: Counter[str] = Counter()
    for n in g.nodes:
        coll_counts[n.get("collection", "?")] += 1
        for con in n.get("concepts", []):
            concept_counter[con] += 1
    for e in g.edges:
        etype_counter[e.get("edge_type", "?")] += 1

    degree_sum = sum(g.degree.values())
    iso = sum(1 for nid in g.id_to_node if g.deg(nid) == 0)
    avg_deg = degree_sum / max(len(g.nodes), 1)
    hub_id = max(g.id_to_node, key=lambda nid: g.deg(nid)) if g.id_to_node else None

    print(c("◇ Musubi — Graph Stats", "cyan"))
    print()
    print(f"  version:   {__version__}")
    print(f"  nodes:     {len(g.nodes)}")
    print(f"  edges:     {len(g.edges)}")
    for et, cnt in sorted(etype_counter.items()):
        print(f"    · {et}: {cnt}")
    print(f"  isolated:  {iso} ({100 * iso / max(len(g.nodes), 1):.1f}%)")
    print(f"  avg deg:   {avg_deg:.1f}")
    if hub_id is not None:
        hub = g.id_to_node[hub_id]
        print(f"  hub node:  deg={g.deg(hub_id)}  {_node_label(hub)}")
    print()
    print(c("  collections:", "dim"))
    for coll, cnt in sorted(coll_counts.items(), key=lambda x: -x[1]):
        print(f"    {coll:<18} {cnt}")
    print()
    print(c("  top concepts:", "dim"))
    for con, cnt in concept_counter.most_common(15):
        print(f"    {con:<25} {cnt} docs")

    if cfg.graph_path.exists():
        mtime = datetime.fromtimestamp(cfg.graph_path.stat().st_mtime, tz=timezone.utc)
        age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        print()
        print(
            c(
                f"  graph file: {cfg.graph_path.name} "
                f"({age_h:.1f}h old, {mtime:%Y-%m-%d %H:%M UTC})",
                "dim",
            )
        )
    return 0


def cmd_neighbors(args: argparse.Namespace, cfg: Config) -> int:
    g = _load_graph_or_exit(cfg)
    matches = g.resolve(args.query)
    if not matches:
        print(c(f"No doc matched: {args.query}", "red"), file=sys.stderr)
        return 1
    if len(matches) > 1 and not args.all:
        print(
            c(
                f"{len(matches)} docs matched. Showing neighbors for first; "
                f"pass --all to show all matches.",
                "yellow",
            ),
            file=sys.stderr,
        )
        for nid in matches[:5]:
            print(
                c(f"  · {nid}  {_node_label(g.id_to_node[nid])}", "dim"),
                file=sys.stderr,
            )
        matches = matches[:1]

    for source_id in matches:
        source = g.id_to_node[source_id]
        print()
        print(c(f"◇ {_node_label(source)}", "cyan"))
        print(
            c(
                f"  id={source_id}  degree={g.deg(source_id)}  "
                f"concepts={source.get('concept_count', 0)}",
                "dim",
            )
        )

        nbrs = g.neighbors_of(source_id, limit=args.limit)
        if not nbrs:
            print(c("  (no neighbors — isolated node)", "yellow"))
            continue

        for e in nbrs:
            nid = e["id"]
            n = g.id_to_node.get(nid, {})
            w = e.get("weight", 0)
            etype = e.get("edge_type", "?")
            shared = ", ".join(e.get("shared_concepts", [])[:4]) or "—"
            marker = "⚡" if etype == "embedding" else "·"
            print(f"  {marker} w={w:<4} {_node_label(n)}")
            print(f"      {c('shared:', 'dim')} {shared}")
    return 0


def cmd_cold(args: argparse.Namespace, cfg: Config) -> int:
    g = _load_graph_or_exit(cfg)
    now = datetime.now(timezone.utc)

    scored: list[tuple[float, Any, dict[str, Any], int, int]] = []
    for nid, node in g.id_to_node.items():
        deg = g.deg(nid)
        cc = node.get("concept_count", 0)

        days = 9999
        m = node.get("modified_at")
        if m:
            try:
                dt = datetime.fromisoformat(m.replace("Z", "+00:00"))
                days = max(0, (now - dt).days)
            except (ValueError, AttributeError):
                pass

        deg_score = 1.0 / (deg + 1)
        cc_score = 1.0 / (cc + 1)
        stale_score = min(days / 180, 1.0)
        cold_score = deg_score * 0.5 + cc_score * 0.2 + stale_score * 0.3

        scored.append((cold_score, nid, node, deg, days))

    scored.sort(reverse=True)

    print(c(f"◇ Cold nodes (top {args.limit})", "cyan"))
    print(c("  score = 0.5·(1/deg) + 0.2·(1/concepts) + 0.3·(days/180)", "dim"))
    print()
    print(f"  {'score':<7} {'deg':<5} {'days':<6} label")
    for score, nid, node, deg, days in scored[: args.limit]:
        marker = c("❄", "cyan") if deg == 0 else " "
        print(f"  {score:<7.3f} {deg:<5} {days:<6} {marker} {_node_label(node)}")

    iso_count = sum(1 for _, _, _, d, _ in scored if d == 0)
    print()
    print(
        c(
            f"  isolated (degree=0): {iso_count} / {len(scored)} total docs",
            "dim",
        )
    )
    return 0


def cmd_search(args: argparse.Namespace, cfg: Config) -> int:
    g = _load_graph_or_exit(cfg)

    try:
        result = subprocess.run(
            [cfg.qmd_bin, "search", args.query, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        print(
            c(
                f"qmd binary '{cfg.qmd_bin}' not found. "
                f"Set MUSUBI_QMD_BIN or install @tobilu/qmd.",
                "red",
            ),
            file=sys.stderr,
        )
        return 1
    except subprocess.TimeoutExpired:
        print(c("qmd search timed out", "red"), file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(
            c(f"qmd search failed (exit {result.returncode})", "red"),
            file=sys.stderr,
        )
        print(result.stderr, file=sys.stderr)
        return 1

    try:
        hits = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(
            c("qmd did not return JSON. Raw output:", "yellow"),
            file=sys.stderr,
        )
        print(result.stdout)
        return 0

    if not isinstance(hits, list):
        hits = hits.get("results", []) if isinstance(hits, dict) else []

    base_ids: list[tuple[Any, float]] = []
    skipped = 0
    for rank, hit in enumerate(hits[: args.limit]):
        file_field = hit.get("file") or hit.get("path") or ""
        nid = Graph.match_qmd_uri(file_field, g.path_to_id)
        if nid is None:
            skipped += 1
            continue
        base_ids.append((nid, 1.0 / (rank + 1)))

    if skipped:
        print(
            c(f"  ({skipped} qmd hit(s) skipped — not in graph or ambiguous basename)", "dim"),
            file=sys.stderr,
        )

    expanded: dict[Any, float] = {}
    for nid, base in base_ids:
        expanded[nid] = expanded.get(nid, 0.0) + base
        for nbr in g.neighbors_of(nid, limit=2):
            nbr_id = nbr["id"]
            boost = base * 0.3 * (nbr.get("weight", 1) / 10)
            expanded[nbr_id] = expanded.get(nbr_id, 0.0) + boost

    if not expanded:
        print(
            c(
                "Graph expansion found no matches. Raw qmd results (first 5):",
                "yellow",
            )
        )
        print(json.dumps(hits[:5], indent=2, ensure_ascii=False))
        return 0

    ranked = sorted(expanded.items(), key=lambda kv: kv[1], reverse=True)[: args.limit]
    base_set = {nid for nid, _ in base_ids}

    print(c(f"◇ Musubi search: {args.query}", "cyan"))
    print()
    for nid, score in ranked:
        n = g.id_to_node.get(nid, {})
        marker = c("★", "yellow") if nid in base_set else c("+", "green")
        print(f"  {marker} {score:.3f}  {_node_label(n)}")
    print()
    print(c("  ★ = direct hit    + = graph neighbor boost", "dim"))
    return 0


def cmd_path(args: argparse.Namespace, cfg: Config) -> int:
    g = _load_graph_or_exit(cfg)
    matches = g.resolve(args.query)
    if not matches:
        print(c(f"No doc matched: {args.query}", "red"), file=sys.stderr)
        return 1
    for nid in matches:
        n = g.id_to_node[nid]
        print(f"{nid}\t{n.get('collection', '?')}\t{n.get('path', '?')}")
    return 0


def cmd_init(args: argparse.Namespace, _cfg: Config | None) -> int:
    from musubi.init_wizard import run_init
    return run_init()


def cmd_benchmark(args: argparse.Namespace, _cfg: Config | None) -> int:
    """Run the token saving benchmark using the experiment script."""
    import importlib.resources
    from pathlib import Path as _Path

    # Find the experiment script
    exp_script = None
    # 1. Check bundled package data (pip/uv install)
    try:
        pkg_path = _Path(str(importlib.resources.files("musubi") / "benchmark" / "run_experiment.py"))
        if pkg_path.exists():
            exp_script = pkg_path
    except (TypeError, FileNotFoundError):
        pass
    # 2. Check relative to source tree (development / editable install)
    if exp_script is None:
        dev = _Path(__file__).parent.parent.parent / "experiments" / "token-saving" / "run_experiment.py"
        if dev.exists():
            exp_script = dev

    if exp_script is None:
        print(c("Experiment script not found.", "red"), file=sys.stderr)
        print(c("Clone the repo and run from the project directory:", "dim"), file=sys.stderr)
        print("  python experiments/token-saving/run_experiment.py", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(exp_script)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.task:
        cmd.extend(["--task", args.task])
    if args.model:
        cmd.extend(["--model", args.model])
    if getattr(args, "tasks", None):
        cmd.extend(["--tasks", args.tasks])
    if getattr(args, "notes", None):
        cmd.extend(["--notes", args.notes])

    import subprocess as sp
    return sp.run(cmd).returncode


def cmd_build(args: argparse.Namespace, cfg: Config) -> int:
    from pathlib import Path as _Path

    from musubi import builder  # lazy — this is the heavy import path

    source = _Path(args.source) if getattr(args, "source", None) else None
    started = datetime.now(timezone.utc)
    log_path = cfg.log_dir / "build.log"
    cfg.ensure_dirs()

    print(c("◇ Building musubi graph...", "cyan"))
    if source:
        print(c(f"  source:    {source} (filesystem mode)", "dim"))
    else:
        print(c(f"  source:    {cfg.qmd_db} (qmd sqlite)", "dim"))
    print(c(f"  output:    {cfg.graph_path}", "dim"))
    if cfg.concepts_file:
        print(c(f"  concepts:  default + {cfg.concepts_file}", "dim"))
    else:
        print(c("  concepts:  default only (no user extension)", "dim"))

    try:
        summary = builder.build(cfg, source=source, verbose=True)
    except FileNotFoundError as e:
        print(c(str(e), "red"), file=sys.stderr)
        return 2
    except Exception as e:
        print(c(f"build failed: {type(e).__name__}: {e}", "red"), file=sys.stderr)
        return 2

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(c(f"  ✓ done in {elapsed:.1f}s", "green"))

    with log_path.open("a") as log:
        log.write(f"{started.isoformat()} {json.dumps(summary)} {elapsed:.1f}s\n")
    return 0


# ---------- argparse ----------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="musubi",
        description=(
            "Musubi (結び) — a knowledge-graph companion for flat-file markdown "
            "note systems. Ties your notes together."
        ),
    )
    p.add_argument("--version", action="version", version=f"musubi {__version__}")

    sub = p.add_subparsers(dest="command")

    ps = sub.add_parser("stats", help="graph metrics summary")
    ps.set_defaults(func=cmd_stats)

    pn = sub.add_parser("neighbors", help="list graph neighbors of a doc")
    pn.add_argument("query", help="doc id, path, or title substring")
    pn.add_argument("--limit", type=int, default=8)
    pn.add_argument("--all", action="store_true", help="if ambiguous, show all matches")
    pn.set_defaults(func=cmd_neighbors)

    pc = sub.add_parser("cold", help="list cold/isolated docs")
    pc.add_argument("--limit", type=int, default=15)
    pc.set_defaults(func=cmd_cold)

    psearch = sub.add_parser("search", help="hybrid qmd keyword + graph search")
    psearch.add_argument("query")
    psearch.add_argument("--limit", type=int, default=10)
    psearch.set_defaults(func=cmd_search)

    pp = sub.add_parser("path", help="resolve query to node id + path (debug)")
    pp.add_argument("query")
    pp.set_defaults(func=cmd_path)

    pb = sub.add_parser(
        "build",
        help="rebuild graph from qmd index or a directory of markdown files",
    )
    pb.add_argument(
        "--source",
        metavar="DIR",
        help=(
            "path to a directory of *.md/*.mdx files (filesystem mode). "
            "If omitted, reads from the qmd SQLite index at $MUSUBI_QMD_DB."
        ),
    )
    pb.set_defaults(func=cmd_build)

    pi = sub.add_parser("init", help="interactive setup wizard (demo → your notes)")
    pi.set_defaults(func=cmd_init)

    pbench = sub.add_parser(
        "benchmark",
        help="measure token savings vs grep-only search (requires ANTHROPIC_API_KEY)",
    )
    pbench.add_argument("--task", help="run a single task by id")
    pbench.add_argument("--dry-run", action="store_true", help="preview tasks without API calls")
    pbench.add_argument("--model", default="claude-sonnet-4-5", help="model to use")
    pbench.add_argument("--tasks", help="path to custom tasks.json (default: bundled demo tasks)")
    pbench.add_argument("--notes", help="path to notes directory (default: bundled demo notes)")
    pbench.set_defaults(func=cmd_benchmark)

    pmcp = sub.add_parser("mcp", help="start MCP server (stdio transport)")
    pmcp.set_defaults(func=lambda args, cfg: _run_mcp())

    args = p.parse_args(argv)
    if not getattr(args, "command", None):
        p.print_help()
        return 1

    # init doesn't need a pre-existing graph or config
    if args.command == "init":
        return args.func(args, None)

    # mcp loads config on-demand inside the server
    if args.command == "mcp":
        return args.func(args, None)

    cfg = load_config()
    return args.func(args, cfg)


def _run_mcp() -> int:
    """Lazy import so mcp package is only required when actually running the server."""
    try:
        from musubi.mcp_server import run
    except ImportError as e:
        print(c(f"MCP server requires the 'mcp' package: {e}", "red"), file=sys.stderr)
        print(c("Install with: pipx install mcp  (or) pip install mcp", "yellow"), file=sys.stderr)
        return 1
    return run()


if __name__ == "__main__":
    sys.exit(main())
