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


def check(graph) -> dict[str, Any]:
    total = len(graph.id_to_node)
    orphans: list[dict[str, Any]] = []
    connected = 0
    concept_df: Counter[str] = Counter()
    dangling: list[tuple[str, str]] = []

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

    # hub concepts: present in a large share of all notes → low discriminative value
    hub_cut = max(8, int(total * 0.20))
    hubs = [(c, n) for c, n in concept_df.most_common(20) if n >= hub_cut]

    return {
        "total": total,
        "connected": connected,
        "coverage": (connected / total) if total else 0.0,
        "orphans": orphans,
        "hubs": hubs,
        "hub_cut": hub_cut,
        "dangling": dangling,
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
    out.append("")

    dangling = f["dangling"]
    out.append(f"③ DANGLING FILE REFS (note points at a path that no longer exists): {len(dangling)}")
    for title, ref in dangling[:limit]:
        out.append(f"    {title} → {ref}")
    if len(dangling) > limit:
        out.append(f"    … +{len(dangling)-limit} more")

    return "\n".join(out)
