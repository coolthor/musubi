"""Graph builder — reads markdown documents and produces a NetworkX graph.

Two source modes:

1. **qmd SQLite** (default) — reads from the ``@tobilu/qmd`` index at
   ``$MUSUBI_QMD_DB``. Gets content, metadata, and embeddings in one
   shot. Embeddings enable a fallback for isolated nodes (Phase 2).
2. **Filesystem** (``musubi build --source /path/to/notes``) — recursively
   reads ``*.md`` / ``*.mdx`` from a directory. No external tool needed.
   Parses YAML frontmatter for title/date/tags. No embedding fallback
   (concept edges only), but isolation rate is typically < 3%.

The graph build strategy:

1. **Concept co-occurrence edges** — for each concept, connect every pair
   of documents that both mention it. Cap at ``concept_weight >= 2`` to
   avoid noise from single-concept overlaps.
2. **Embedding fallback for isolates** (qmd mode only) — any node left
   with degree 0 after step 1 gets up to 3 nearest-neighbor edges from
   the qmd vector index. Brings isolation rate from ~35% down to 0%.

Runtime cost on a 400-doc corpus: ~15-25 seconds on an M-series Mac.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from musubi.concepts import DEFAULT_PATH_CONCEPTS, load_concepts
from musubi.config import Config


# ---------------------------------------------------------------------------
# Frontmatter parser (stdlib-only, no pyyaml dependency)
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract YAML-ish frontmatter from markdown text.

    Returns (metadata_dict, body_without_frontmatter). Only handles flat
    key: value pairs — enough for title, date, description, tags. Does
    NOT handle nested YAML, arrays, or multiline values.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in fm_block.splitlines():
        colon = line.find(":")
        if colon > 0:
            key = line[:colon].strip().lower()
            val = line[colon + 1 :].strip().strip('"').strip("'")
            if key and val:
                meta[key] = val
    return meta, body


# ---------------------------------------------------------------------------
# Source: filesystem (no external dependencies)
# ---------------------------------------------------------------------------


MAX_FILE_BYTES = 1_000_000  # 1 MB — skip files larger than this


def _read_fs_documents(root: Path) -> list[dict[str, Any]]:
    """Recursively read *.md / *.mdx from a directory tree.

    Each document gets a synthetic integer id and a collection name derived
    from the first subdirectory under root (or "default" if files live at
    root level). Files larger than 1 MB are skipped with a warning.
    """
    docs: list[dict[str, Any]] = []
    md_files = sorted(root.rglob("*.md")) + sorted(root.rglob("*.mdx"))
    for idx, filepath in enumerate(md_files):
        rel = filepath.relative_to(root)
        parts = rel.parts
        collection = parts[0] if len(parts) > 1 else "default"

        stat = filepath.stat()
        if stat.st_size > MAX_FILE_BYTES:
            print(f"  skipping {rel} ({stat.st_size / 1e6:.1f} MB > 1 MB limit)")
            continue

        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        try:
            text = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"  skipping {rel} (not valid UTF-8)")
            continue
        meta, body = _parse_frontmatter(text)

        title = meta.get("title") or filepath.stem
        docs.append({
            "id": idx,
            "collection": collection,
            "path": str(rel),
            "title": title,
            "modified_at": modified_at,
            "_content": body,  # carry content in-memory (no sqlite)
            "_meta": meta,
        })
    return docs


# ---------------------------------------------------------------------------
# Source: qmd SQLite index
# ---------------------------------------------------------------------------


def _read_md_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Read all active markdown/mdx docs from the qmd index."""
    cur = conn.execute(
        """
        SELECT d.id, d.collection, d.path, d.title, d.hash, d.modified_at
        FROM documents d
        WHERE d.active = 1 AND (d.path LIKE '%.md' OR d.path LIKE '%.mdx')
        ORDER BY d.collection, d.path
        """
    )
    return [
        {
            "id": r[0],
            "collection": r[1],
            "path": r[2],
            "title": r[3] or os.path.basename(r[2]),
            "hash": r[4],
            "modified_at": r[5],
        }
        for r in cur
    ]


def _read_content(conn: sqlite3.Connection, doc_hash: str) -> str:
    cur = conn.execute("SELECT doc FROM content WHERE hash = ?", (doc_hash,))
    row = cur.fetchone()
    return row[0] if row else ""


def _read_embeddings(conn: sqlite3.Connection, doc_hashes: set[str]) -> dict[str, Any]:
    """Read embeddings for specified hashes, averaged per hash.

    Only imports numpy when actually called — keeps `musubi build` as the
    only command that pays the numpy import cost.
    """
    import numpy as np  # lazy

    DIM = 768
    rowid_map: dict[int, tuple[str, int, int]] = {}
    try:
        cur = conn.execute(
            "SELECT rowid, id, chunk_id, chunk_offset FROM vectors_vec_rowids"
        )
    except sqlite3.OperationalError:
        # No vector index present; skip embedding fallback entirely
        return {}

    for rowid, hash_seq, chunk_id, chunk_offset in cur:
        parts = hash_seq.rsplit("_", 1)
        if len(parts) == 2 and parts[0] in doc_hashes:
            rowid_map[rowid] = (parts[0], chunk_id, chunk_offset)

    all_vectors: dict[int, Any] = {}
    try:
        cur = conn.execute("SELECT rowid, vectors FROM vectors_vec_vector_chunks00")
    except sqlite3.OperationalError:
        return {}

    for chunk_rowid, vec_bytes in cur:
        n_floats = len(vec_bytes) // 4
        n_vectors = n_floats // DIM
        if n_vectors == 0:
            continue
        all_floats = struct.unpack(f"{n_floats}f", vec_bytes)
        for i in range(n_vectors):
            vec = np.array(all_floats[i * DIM : (i + 1) * DIM], dtype=np.float32)
            if np.any(vec != 0):
                all_vectors[chunk_rowid * 1024 + i] = vec

    hash_vecs: dict[str, list[Any]] = defaultdict(list)
    for rowid, (doc_hash, chunk_id, chunk_offset) in rowid_map.items():
        vec_key = chunk_id * 1024 + chunk_offset
        if vec_key in all_vectors:
            hash_vecs[doc_hash].append(all_vectors[vec_key])

    result = {}
    for h, vecs in hash_vecs.items():
        avg = np.mean(vecs, axis=0)
        norm = np.linalg.norm(avg)
        if norm > 0:
            result[h] = avg / norm
    return result


def _extract_concepts(
    text: str,
    title: str,
    path: str,
    tech_terms: set[str],
    path_concepts: dict[str, set[str]],
) -> set[str]:
    combined = (title + " " + text).lower()
    found: set[str] = set()

    for term in tech_terms:
        pattern = r"(?:^|[\s\-_/,.(])" + re.escape(term) + r"(?:[\s\-_/,.):]|$)"
        if re.search(pattern, combined):
            found.add(term)

    path_lower = path.lower()
    for key, concepts in path_concepts.items():
        if key in path_lower:
            found.update(concepts)

    # H2 / H3 headings as weak concepts (h: prefix so we can filter them out
    # of top-concept reports while still using them for edge discovery).
    for match in re.finditer(r"^#{2,3}\s+(.+)$", text, re.MULTILINE):
        heading = re.sub(r"\*\*|`|#", "", match.group(1)).strip().lower()
        if 3 < len(heading) < 50:
            found.add(f"h:{heading}")

    return found


def _build_graph(docs, doc_concepts, hash_embeddings):
    """Assemble the hybrid concept+embedding graph."""
    import networkx as nx
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity

    G = nx.Graph()
    for doc in docs:
        concepts = sorted(
            c for c in doc_concepts.get(doc["id"], set()) if not c.startswith("h:")
        )
        G.add_node(
            doc["id"],
            collection=doc["collection"],
            path=doc["path"],
            title=doc["title"],
            modified_at=doc["modified_at"],
            concepts=concepts,
            concept_count=len(concepts),
        )

    # Phase 1 — concept co-occurrence
    concept_to_docs: dict[str, set[Any]] = defaultdict(set)
    for doc_id, concepts in doc_concepts.items():
        for c in concepts:
            if not c.startswith("h:"):
                concept_to_docs[c].add(doc_id)

    edge_data: dict[tuple[Any, Any], dict[str, Any]] = defaultdict(
        lambda: {"concept_weight": 0, "shared": []}
    )
    for concept, doc_ids in concept_to_docs.items():
        if len(doc_ids) < 2 or len(doc_ids) > 80:
            continue
        doc_list = list(doc_ids)
        for i in range(len(doc_list)):
            for j in range(i + 1, len(doc_list)):
                a = min(doc_list[i], doc_list[j])
                b = max(doc_list[i], doc_list[j])
                edge_data[(a, b)]["concept_weight"] += 1
                if len(edge_data[(a, b)]["shared"]) < 6:
                    edge_data[(a, b)]["shared"].append(concept)

    concept_edges = 0
    for (a, b), data in edge_data.items():
        if data["concept_weight"] >= 2:
            G.add_edge(
                a,
                b,
                weight=data["concept_weight"],
                shared_concepts=data["shared"],
                edge_type="concept",
            )
            concept_edges += 1

    # Phase 2 — embedding fallback for still-isolated nodes
    isolated = [n for n in G.nodes() if G.degree(n) == 0]
    embedding_edges = 0
    if isolated and hash_embeddings:
        id_to_hash = {d["id"]: d["hash"] for d in docs}
        valid_ids = []
        vecs = []
        for nid in G.nodes():
            h = id_to_hash.get(nid)
            if h and h in hash_embeddings:
                valid_ids.append(nid)
                vecs.append(hash_embeddings[h])
        if vecs:
            vec_matrix = np.array(vecs)
            isolated_set = set(isolated)
            for idx, nid in enumerate(valid_ids):
                if nid not in isolated_set:
                    continue
                sims = cosine_similarity([vec_matrix[idx]], vec_matrix)[0]
                top = np.argsort(sims)[::-1][1:4]
                for tidx in top:
                    neighbor_id = valid_ids[tidx]
                    sim = float(sims[tidx])
                    if sim > 0.5 and not G.has_edge(nid, neighbor_id):
                        G.add_edge(
                            nid,
                            neighbor_id,
                            weight=round(sim * 2, 2),
                            shared_concepts=[f"embedding:{sim:.2f}"],
                            edge_type="embedding",
                        )
                        embedding_edges += 1

    return G, concept_edges, embedding_edges


def build(
    cfg: Config,
    *,
    source: Path | None = None,
    verbose: bool = True,
) -> dict[str, int]:
    """Build the graph and save JSON.

    Parameters
    ----------
    cfg : Config
        Runtime configuration (paths, concepts file, etc.).
    source : Path | None
        If a directory path is given, reads markdown files directly from
        the filesystem (no qmd dependency). If ``None`` (default), reads
        from the configured qmd SQLite index.
    verbose : bool
        Print progress to stdout.

    Returns a small dict with summary counts so the CLI can print them.
    """
    import networkx as nx  # lazy import

    tech_terms = load_concepts(cfg.concepts_file)
    path_concepts = DEFAULT_PATH_CONCEPTS

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    hash_embeddings: dict[str, Any] = {}

    if source is not None:
        # ── Filesystem mode ──────────────────────────────────────────
        if not source.is_dir():
            raise FileNotFoundError(f"Source directory not found: {source}")
        log(f"Scanning directory: {source}")
        docs = _read_fs_documents(source)
        log(f"  {len(docs)} markdown documents")

        doc_concepts: dict[Any, set[str]] = {}
        for doc in docs:
            content = doc.pop("_content", "")
            doc.pop("_meta", None)
            doc_concepts[doc["id"]] = _extract_concepts(
                content, doc["title"], doc["path"], tech_terms, path_concepts
            )
        log("  (no embeddings — filesystem mode uses concept edges only)")
    else:
        # ── qmd SQLite mode ──────────────────────────────────────────
        if not cfg.qmd_db.exists():
            raise FileNotFoundError(
                f"qmd index not found at {cfg.qmd_db}.\n"
                f"Either install @tobilu/qmd and run `qmd update`, or use:\n"
                f"  musubi build --source /path/to/your/notes/"
            )
        log(f"Opening qmd index: {cfg.qmd_db}")
        conn = sqlite3.connect(cfg.qmd_db)
        try:
            docs = _read_md_documents(conn)
            log(f"  {len(docs)} markdown documents")

            doc_concepts = {}
            for doc in docs:
                content = _read_content(conn, doc["hash"])
                doc_concepts[doc["id"]] = _extract_concepts(
                    content, doc["title"], doc["path"], tech_terms, path_concepts
                )

            log("Reading embeddings (may take a moment)...")
            hash_embeddings = _read_embeddings(conn, {d["hash"] for d in docs})
            log(f"  {len(hash_embeddings)} embedded docs")
        finally:
            conn.close()

    log("Building hybrid graph...")
    G, n_concept, n_embed = _build_graph(docs, doc_concepts, hash_embeddings)
    iso = sum(1 for n in G.nodes() if G.degree(n) == 0)

    log(f"  concept edges: {n_concept}")
    if n_embed:
        log(f"  embedding edges (fallback): {n_embed}")
    log(f"  isolated: {iso}")
    log(f"  total: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    cfg.ensure_dirs()
    data = nx.node_link_data(G, edges="edges")
    data["graph"]["built_at"] = datetime.now(timezone.utc).isoformat()
    data["graph"]["version"] = "musubi-0.1"
    with cfg.graph_path.open("w") as f:
        json.dump(data, f, ensure_ascii=False)
    log(f"  wrote: {cfg.graph_path}")

    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "concept_edges": n_concept,
        "embedding_edges": n_embed,
        "isolated": iso,
    }
