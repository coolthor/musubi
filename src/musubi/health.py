"""Knowledge-base health audit — what a graph is actually FOR.

A graph viz is eye-candy; the payoff of having the graph is surfacing structural
rot you can act on. `musubi health` reports, all from the existing graph (no ML,
no file re-reads except cheap existence checks):

  - orphans      — notes with zero graph links (concept-isolated; not woven in)
  - coverage     — % of notes that are connected to at least one other
  - hub concepts — concepts so common they connect everything (low signal)
  - dangling refs— filesystem paths a note references that no longer exist on disk

Stdlib only.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any

# Only treat a referenced path as a real local file (worth existence-checking)
# when it's home-anchored or under a real OS root. This skips site-relative web
# routes that look path-ish (e.g. "/videos/x.mp4", "/en/blog/foo") which are
# common in blog/content corpora and would otherwise dominate as false positives.
# Ephemeral roots (/tmp, /var, /private) are also skipped — scratch paths there
# are *expected* to vanish, so flagging them as "dangling" is noise, not signal.
_FS_PREFIXES = ("~", "/Users/", "/home/", "/opt/", "/srv/", "/mnt/", "/data/")


def _is_local_file_ref(ref: str) -> bool:
    return ref.startswith(_FS_PREFIXES)


def _classify_dangling_ref(ref: str) -> str:
    expanded = os.path.expanduser(ref)
    lower = expanded.lower()
    if any(part in lower for part in ("/models/", "/huggingface/", "/comfyui/", "/checkpoints/")):
        return "model-artifact"
    if expanded.startswith("/home/"):
        return "remote-linux-path"
    if expanded.startswith("/mnt/") or expanded.startswith("/data/"):
        return "mounted-storage"
    if expanded.startswith("/Users/") and "/Projects/" in expanded:
        return "local-project-file"
    return "local-missing"


def _dupe_key(node: dict[str, Any]) -> tuple[str, str] | None:
    content_hash = (node.get("hash") or "").strip()
    if content_hash:
        return ("hash", content_hash)
    path = (node.get("path") or "").strip().lower()
    title = re.sub(r"\s+", " ", (node.get("title") or "").strip().lower())
    if path and title:
        return ("path-title", f"{path}\0{title}")
    return None


def check(graph) -> dict[str, Any]:
    total = len(graph.id_to_node)
    orphans: list[dict[str, Any]] = []
    connected = 0
    concept_df: Counter[str] = Counter()
    dangling: list[tuple[str, str]] = []
    dangling_by_kind: Counter[str] = Counter()
    duplicate_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for nid, node in graph.id_to_node.items():
        deg = graph.deg(nid)
        if deg == 0:
            orphans.append(node)
        else:
            connected += 1
        for con in node.get("concepts", []):
            if not con.startswith("h:"):
                concept_df[con] += 1
        for ref in node.get("referenced_paths", []) or []:
            if not _is_local_file_ref(ref):
                continue
            if not os.path.exists(os.path.expanduser(ref)):
                dangling.append((node.get("title", "?"), ref))
                dangling_by_kind[_classify_dangling_ref(ref)] += 1

        key = _dupe_key(node)
        if key is not None:
            duplicate_groups.setdefault(key, []).append(node)

    # hub concepts: present in a large share of all notes → low discriminative value
    hub_cut = max(8, int(total * 0.20))
    hubs = [(c, n) for c, n in concept_df.most_common(20) if n >= hub_cut]
    duplicates = [
        nodes for nodes in duplicate_groups.values()
        if len(nodes) > 1
    ]
    duplicates.sort(
        key=lambda nodes: (
            0 if any(n.get("collection") == "shared-memory" for n in nodes) else 1,
            -(len(nodes)),
            (nodes[0].get("title") or "").lower(),
        )
    )

    return {
        "total": total,
        "connected": connected,
        "coverage": (connected / total) if total else 0.0,
        "orphans": orphans,
        "hubs": hubs,
        "hub_cut": hub_cut,
        "dangling": dangling,
        "dangling_by_kind": dict(dangling_by_kind),
        "duplicates": duplicates,
        "suggested_stop_concepts": [c for c, _ in hubs],
    }


def format_report(f: dict[str, Any], limit: int = 40) -> str:
    out: list[str] = []
    total = f["total"]
    pct = f["coverage"] * 100
    out.append(f"◇ KB health — {total} notes")
    out.append(f"  link coverage: {f['connected']}/{total} ({pct:.0f}%) connected to ≥1 other note")
    out.append("")

    orphans = f["orphans"]
    out.append(f"① ORPHANS (no graph links — not woven in): {len(orphans)}")
    for node in orphans[:limit]:
        out.append(f"    ❄ [{node.get('collection','?')}] {node.get('title','?')}  {node.get('path','')}")
    if len(orphans) > limit:
        out.append(f"    … +{len(orphans)-limit} more")
    out.append("")

    hubs = f["hubs"]
    out.append(f"② HUB CONCEPTS (in ≥{f['hub_cut']} notes — connect everything, low signal): {len(hubs)}")
    for con, n in hubs:
        out.append(f"    {con}  ({n} notes)")
    if hubs:
        out.append("    suggested stop-list candidates: " + ", ".join(f["suggested_stop_concepts"][:12]))
    out.append("")

    dangling = f["dangling"]
    out.append(f"③ DANGLING FILE REFS (note points at a path that no longer exists): {len(dangling)}")
    by_kind = f.get("dangling_by_kind") or {}
    if by_kind:
        kinds = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        out.append(f"    by kind: {kinds}")
    for title, ref in dangling[:limit]:
        out.append(f"    {title} → {ref}")
    if len(dangling) > limit:
        out.append(f"    … +{len(dangling)-limit} more")
    out.append("")

    duplicates = f.get("duplicates") or []
    out.append(f"④ DUPLICATE / MIRRORED NOTES (same hash or path+title): {len(duplicates)}")
    for group in duplicates[:limit]:
        title = group[0].get("title", "?")
        locs = ", ".join(
            f"[{node.get('collection','?')}] {node.get('path','')}"
            for node in sorted(group, key=lambda n: (n.get("collection", ""), n.get("path", "")))
        )
        out.append(f"    {title} → {locs}")
    if len(duplicates) > limit:
        out.append(f"    … +{len(duplicates)-limit} more")

    return "\n".join(out)
