#!/usr/bin/env python3
"""
Musubi Token Saving Experiment
==============================

Measures how many tokens Claude uses to complete note-retrieval tasks
under two conditions:

  A) Baseline — only grep/cat (simulates keyword search)
  B) Musubi   — musubi search/neighbors/cold/stats + cat

Uses the demo notes bundled with musubi (no private data) and the
Anthropic Python SDK for controlled API calls with tool use.

Prerequisites
-------------
  pip install anthropic
  musubi build --source <path-to-demo-notes>  # build the graph first

Usage
-----
  export ANTHROPIC_API_KEY=sk-ant-...
  python run_experiment.py                     # full run
  python run_experiment.py --task direct-1     # single task
  python run_experiment.py --group baseline    # baseline only
  python run_experiment.py --dry-run           # show tasks, don't call API

Output
------
  results/experiment-YYYY-MM-DD.json   — raw results
  results/summary.md                   — comparison table
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Demo notes live in two places depending on how the benchmark is invoked:
#   - Installed via `uv tool install musubi`: force-included at musubi/demo-notes
#   - Running from source checkout: examples/demo-notes at the repo root
_INSTALLED_NOTES = Path(__file__).parent.parent / "demo-notes"
_SOURCE_NOTES = Path(__file__).parent.parent.parent / "examples" / "demo-notes"
DEMO_NOTES = _INSTALLED_NOTES if _INSTALLED_NOTES.is_dir() else _SOURCE_NOTES
TASKS_FILE = Path(__file__).parent / "tasks.json"
RESULTS_DIR = Path(__file__).parent / "results"
_MODEL = "claude-sonnet-4-5"
MAX_TURNS = 10
# Defined as a mutable container so main() can update it without `global`
MODEL = _MODEL


def _update_model(m: str) -> None:
    global MODEL
    MODEL = m

# ---------- Tool definitions ----------

TOOLS_BASELINE = [
    {
        "name": "search_files",
        "description": "Search for files containing a keyword in the notes directory. Returns matching filenames.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "keyword or phrase to search for"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_files",
        "description": "List all markdown files in the notes directory.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Read the full content of a markdown file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "relative path like 'inference/vllm-fp8-kvcache-bug.md'"},
            },
            "required": ["path"],
        },
    },
]

TOOLS_MUSUBI = [
    {
        "name": "musubi_search",
        "description": (
            "Search notes. Returns one line per hit: `path\\tmarker score [badges]`. "
            "* = direct keyword hit, + = graph-neighbor boost. "
            "For a specific known note, the top * is almost always the answer — "
            "read it directly without calling neighbors. "
            "Only chain to `musubi_neighbors` when the user asks for related/surrounding context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "musubi_neighbors",
        "description": (
            "Graph neighbors of a document. ONLY use when the user explicitly wants "
            "related/surrounding notes (cross-domain, exploration). "
            "For simple lookup, `musubi_search` is enough."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc": {"type": "string", "description": "document path, id, or title substring"},
                "limit": {"type": "integer", "description": "max neighbors to return", "default": 5},
            },
            "required": ["doc"],
        },
    },
    {
        "name": "musubi_cold",
        "description": (
            "List orphan / weakly-connected docs — direct answer for 'which notes are "
            "isolated / candidates for archiving'. No other tool can answer this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "musubi_stats",
        "description": "Knowledge graph overview: node/edge counts, top concepts, hub nodes, collections.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Read the full content of a markdown file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "relative path like 'inference/vllm-fp8-kvcache-bug.md'"},
            },
            "required": ["path"],
        },
    },
]


# ---------- Tool execution ----------


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"Error: {e}"


def execute_tool(name: str, args: dict[str, Any], notes_dir: Path) -> str:
    """Execute a tool call and return the string result."""
    if name == "search_files":
        # `--` prevents option injection from query strings starting with `-`
        return _run(["grep", "-rl", "--include=*.md", "--", args["query"], str(notes_dir)])

    if name == "list_files":
        files = sorted(notes_dir.rglob("*.md"))
        return "\n".join(str(f.relative_to(notes_dir)) for f in files)

    if name == "read_file":
        path = (notes_dir / args["path"]).resolve()
        # Prevent path traversal (e.g. ../../.ssh/config)
        if not path.is_relative_to(notes_dir.resolve()):
            return f"Access denied: path escapes notes directory"
        if not path.exists():
            return f"File not found: {args['path']}"
        return path.read_text(encoding="utf-8", errors="replace")[:3000]

    if name == "musubi_search":
        return _run([
            "musubi", "search", args["query"],
            "--limit", "8", "--format", "compact",
        ])

    if name == "musubi_neighbors":
        limit = str(args.get("limit", 5))
        return _run([
            "musubi", "neighbors", args["doc"],
            "--limit", limit, "--format", "compact",
        ])

    if name == "musubi_cold":
        limit = str(args.get("limit", 10))
        return _run(["musubi", "cold", "--limit", limit])

    if name == "musubi_stats":
        return _run(["musubi", "stats"])

    return f"Unknown tool: {name}"


# ---------- Conversation runner ----------


def run_conversation(
    task: dict[str, Any],
    tools: list[dict[str, Any]],
    notes_dir: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run a multi-turn tool-use conversation for a single task.

    Returns a dict with token counts and conversation metadata.
    """
    try:
        import anthropic
    except ImportError:
        print("Error: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()

    system = (
        "You are helping a developer find relevant notes in their markdown knowledge base. "
        "Use the available tools to locate the information requested. "
        "When you've found the answer, respond with a brief summary of what you found "
        "and which file(s) are relevant. Be efficient — minimize unnecessary tool calls."
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": task["query"]},
    ]

    total_input = 0
    total_output = 0
    tool_calls = 0
    turns = 0

    if dry_run:
        return {
            "task_id": task["id"],
            "dry_run": True,
            "query": task["query"],
            "tools": [t["name"] for t in tools],
        }

    for _ in range(MAX_TURNS):
        turns += 1
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            tools=tools,
            messages=messages,
        )

        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        # Check if the model wants to use tools
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # Model is done — extract final text
            final_text = "".join(
                b.text for b in response.content if b.type == "text"
            )
            return {
                "task_id": task["id"],
                "task_type": task.get("type", "?"),
                "query": task["query"],
                "turns": turns,
                "tool_calls": tool_calls,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_input + total_output,
                "final_answer": final_text[:500],
                "stop_reason": response.stop_reason,
            }

        # Execute tool calls and build response
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in tool_use_blocks:
            tool_calls += 1
            result = execute_tool(block.name, block.input, notes_dir)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result[:4000],  # cap tool output
            })

        messages.append({"role": "user", "content": tool_results})

    # Hit max turns
    return {
        "task_id": task["id"],
        "task_type": task.get("type", "?"),
        "query": task["query"],
        "turns": turns,
        "tool_calls": tool_calls,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "final_answer": "(max turns reached)",
        "stop_reason": "max_turns",
    }


# ---------- Report generation ----------


def generate_report(
    baseline_results: list[dict[str, Any]],
    musubi_results: list[dict[str, Any]],
) -> str:
    """Generate a markdown comparison report."""
    lines = [
        "# Musubi Token Saving Experiment — Results",
        "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"**Model:** {MODEL}",
        f"**Notes:** {len(baseline_results)} tasks on demo-notes (20 docs)",
        "",
        "## Per-Task Comparison",
        "",
        "| Task | Type | Baseline Tokens | Musubi Tokens | Savings | Baseline Calls | Musubi Calls |",
        "|------|------|---------------:|-------------:|--------:|---------------:|-------------:|",
    ]

    total_b, total_m = 0, 0
    for b, m in zip(baseline_results, musubi_results):
        bt = b.get("total_tokens", 0)
        mt = m.get("total_tokens", 0)
        total_b += bt
        total_m += mt
        savings = ((bt - mt) / bt * 100) if bt > 0 else 0
        lines.append(
            f"| {b['task_id']} | {b.get('task_type', '?')} | "
            f"{bt:,} | {mt:,} | {savings:+.1f}% | "
            f"{b.get('tool_calls', 0)} | {m.get('tool_calls', 0)} |"
        )

    overall = ((total_b - total_m) / total_b * 100) if total_b > 0 else 0
    lines += [
        "",
        "## Summary",
        "",
        f"| Metric | Baseline | Musubi | Difference |",
        f"|--------|--------:|------:|----------:|",
        f"| Total tokens | {total_b:,} | {total_m:,} | {overall:+.1f}% |",
        f"| Avg tokens/task | {total_b // max(len(baseline_results), 1):,} | {total_m // max(len(musubi_results), 1):,} | |",
        f"| Total tool calls | {sum(r.get('tool_calls', 0) for r in baseline_results)} | {sum(r.get('tool_calls', 0) for r in musubi_results)} | |",
        "",
        "## By Task Type",
        "",
    ]

    # Group by type
    types: dict[str, list[tuple[dict, dict]]] = {}
    for b, m in zip(baseline_results, musubi_results):
        t = b.get("task_type", "?")
        types.setdefault(t, []).append((b, m))

    for task_type, pairs in types.items():
        bt = sum(b.get("total_tokens", 0) for b, _ in pairs)
        mt = sum(m.get("total_tokens", 0) for _, m in pairs)
        savings = ((bt - mt) / bt * 100) if bt > 0 else 0
        lines.append(f"- **{task_type}**: {savings:+.1f}% ({bt:,} → {mt:,} tokens)")

    lines += [
        "",
        "## Reproduction",
        "",
        "```bash",
        "cd musubi",
        "musubi build --source examples/demo-notes/",
        "pip install anthropic",
        "export ANTHROPIC_API_KEY=sk-ant-...",
        "python experiments/token-saving/run_experiment.py",
        "```",
    ]

    return "\n".join(lines)


# ---------- Main ----------


def main() -> int:
    p = argparse.ArgumentParser(description="Musubi token saving experiment")
    p.add_argument("--task", help="run a single task by id")
    p.add_argument("--group", choices=["baseline", "musubi"], help="run only one group")
    p.add_argument("--dry-run", action="store_true", help="show tasks without calling API")
    p.add_argument("--notes", default=str(DEMO_NOTES), help="path to notes directory")
    p.add_argument("--tasks", default=str(TASKS_FILE),
                   help="path to tasks JSON file (default: demo tasks)")
    p.add_argument("--model", default=MODEL, help="Claude model to use")
    args = p.parse_args()

    # Update the module-level MODEL so run_conversation picks it up
    _update_model(args.model)
    notes_dir = Path(args.notes)
    tasks_path = Path(args.tasks)

    if not notes_dir.is_dir():
        print(f"Notes directory not found: {notes_dir}", file=sys.stderr)
        print("Run: musubi build --source examples/demo-notes/", file=sys.stderr)
        return 1

    if not tasks_path.is_file():
        print(f"Tasks file not found: {tasks_path}", file=sys.stderr)
        return 1

    with tasks_path.open() as f:
        tasks = json.load(f)

    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]
        if not tasks:
            print(f"Task not found: {args.task}", file=sys.stderr)
            return 1

    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run the experiment.", file=sys.stderr)
        print("Use --dry-run to preview tasks without API calls.", file=sys.stderr)
        return 1

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    baseline_results: list[dict[str, Any]] = []
    musubi_results: list[dict[str, Any]] = []

    for i, task in enumerate(tasks, 1):
        print(f"\n[{i}/{len(tasks)}] {task['id']}: {task['query'][:60]}...")

        if args.group != "musubi":
            print(f"  → baseline...", end=" ", flush=True)
            r = run_conversation(task, TOOLS_BASELINE, notes_dir, dry_run=args.dry_run)
            baseline_results.append(r)
            if not args.dry_run:
                print(f"{r['total_tokens']:,} tokens, {r['tool_calls']} calls")
            else:
                print("(dry run)")

        if args.group != "baseline":
            print(f"  → musubi...", end=" ", flush=True)
            r = run_conversation(task, TOOLS_MUSUBI, notes_dir, dry_run=args.dry_run)
            musubi_results.append(r)
            if not args.dry_run:
                print(f"{r['total_tokens']:,} tokens, {r['tool_calls']} calls")
            else:
                print("(dry run)")

        # Rate limiting
        if not args.dry_run:
            time.sleep(1)

    # Save results
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results_file = RESULTS_DIR / f"experiment-{timestamp}.json"
    with results_file.open("w") as f:
        json.dump({
            "meta": {
                "date": timestamp,
                "model": MODEL,
                "notes_dir": str(notes_dir),
                "num_tasks": len(tasks),
            },
            "baseline": baseline_results,
            "musubi": musubi_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nRaw results: {results_file}")

    # Generate report
    if baseline_results and musubi_results and not args.dry_run:
        report = generate_report(baseline_results, musubi_results)
        report_file = RESULTS_DIR / "summary.md"
        report_file.write_text(report, encoding="utf-8")
        print(f"Report: {report_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
