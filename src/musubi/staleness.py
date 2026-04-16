"""Staleness detection — compares note mtime against referenced file mtimes.

A note that references `/Users/coolthor/foo.md` is *potentially stale* if
`foo.md` was modified AFTER the note itself was last written. This doesn't
prove the note is wrong, but flags it for verification before trusting.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _to_epoch(value: Any) -> float | None:
    """Normalize an ISO timestamp or epoch float to an epoch float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            # Handle both naive and Z-suffixed ISO timestamps
            s = value.replace("Z", "+00:00")
            return datetime.fromisoformat(s).timestamp()
        except ValueError:
            return None
    return None


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path))


def compute_staleness(
    node_modified_at: Any,
    referenced_paths: list[str] | None,
) -> dict[str, Any]:
    """Check whether any referenced file is newer than the note itself.

    Returns ``{"stale": bool, "newer_refs": [paths]}``. Missing referenced
    files are silently ignored — we don't claim staleness based on files
    that no longer exist. A malformed ``node_modified_at`` disables the
    check (returns stale=False).
    """
    node_ts = _to_epoch(node_modified_at)
    if node_ts is None or not referenced_paths:
        return {"stale": False, "newer_refs": []}

    newer: list[str] = []
    for raw in referenced_paths:
        try:
            p = _expand(raw)
            if not p.is_file():
                # Skip directories, devices (/dev/null), and missing paths —
                # only regular-file mtimes are meaningful for "note is stale"
                continue
            if p.stat().st_mtime > node_ts:
                newer.append(raw)
        except (OSError, ValueError):
            continue

    return {"stale": bool(newer), "newer_refs": newer}
