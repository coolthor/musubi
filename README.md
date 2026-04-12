# Musubi 結び

**A knowledge-graph companion for flat-file markdown note systems.**

Musubi (Japanese: *結び*, "to tie together") layers a knowledge graph on
top of a flat-file markdown notes system so you can ask questions like
*"what docs are adjacent to this one?"*, *"which notes have gone cold?"*,
and *"search this topic and include semantically related neighbors"* —
without migrating away from plain markdown.

It's designed as a companion to [`@tobilu/qmd`][qmd], but the graph format
is generic enough to plug into any notes system that exposes a SQLite
index over markdown documents with embeddings.

[qmd]: https://www.npmjs.com/package/@tobilu/qmd

---

## Why

Flat-file notes are great for portability and speed. They're bad at
**making implicit relationships visible**. Two notes about the same
gotcha, written six weeks apart, look like independent files to
BM25 keyword search and even to vector search — because vector search
gives you *similarity*, not *community*.

Musubi turns your notes into a graph:

- **Nodes** = markdown documents, with per-doc concept sets
- **Edges** = shared concepts (co-occurrence weighted by frequency),
  with an embedding fallback for docs that would otherwise be isolated
- **Communities** = automatically detected knowledge clusters

Then it gives you a handful of sharp read-side queries that let you
actually use that structure.

---

## Install

Requires **Python 3.11+**. No other external tools needed.

```bash
git clone https://github.com/coolthor/musubi.git
cd musubi
uv tool install .        # or: pip install .
```

This puts a `musubi` command on your PATH.

### Optional: qmd integration

If you use [`@tobilu/qmd`][qmd] (an on-device hybrid search tool for
markdown), musubi can read its SQLite index directly for richer results:

- `musubi build` without `--source` reads from the qmd index (includes
  embeddings for a better isolation fallback)
- `musubi search` delegates keyword search to `qmd search --json` and
  expands results with graph neighbors

qmd is **not required**. Without it, use `musubi build --source <dir>`
to build from a plain directory of markdown files.

---

## Quick start

```bash
# Option A: build from a directory of markdown files (no external tools)
musubi build --source ~/my-notes/

# Option B: build from a qmd SQLite index (if you have @tobilu/qmd)
musubi build

# Then explore
musubi stats
musubi neighbors "some-doc-slug"
musubi cold --limit 20
musubi search "your query here"     # requires qmd for keyword search
```

---

## Subcommands

| Command | What it does |
|---------|-------------|
| `musubi stats` | Graph size, top concepts per collection, hub node, graph freshness |
| `musubi neighbors <query>` | Top-N graph neighbors of a doc (weighted by shared concepts) |
| `musubi cold [--limit N]` | Docs with low degree + stale modification time. Inverse of "hot" |
| `musubi search <query>` | Hybrid: calls `qmd search --json` then boosts graph neighbors of each hit |
| `musubi path <query>` | Resolve a query (id / path / title substring) to node ids — debug |
| `musubi build [--source DIR]` | Rebuild graph from a directory or qmd index |

All queries accept:
- a numeric node id
- an exact relative path
- a path substring (case-insensitive)
- a title substring

---

## Architecture

```
┌──────────────────┐     musubi build      ┌──────────────────┐
│  qmd sqlite      │ ───────────────────▶  │  graph.json      │
│  (documents +    │  concepts + embeds    │  (node_link_data)│
│   content +      │                       │                  │
│   vectors)       │                       └──────────────────┘
└──────────────────┘                                 │
                                                     ▼
                                     ┌───────────────────────────┐
                                     │  read-side commands       │
                                     │  ─ stats                  │
                                     │  ─ neighbors              │
                                     │  ─ cold                   │
                                     │  ─ search (+ qmd)         │
                                     │  ─ path                   │
                                     └───────────────────────────┘
```

### Graph build strategy

1. **Concept extraction.** Every document is scanned against a dictionary
   of tech/dev terms (see [`concepts.py`](src/musubi/concepts.py)),
   producing a per-doc concept set. Users extend the dictionary via a
   plain text file (see [Customizing concepts](#customizing-concepts)).
2. **Concept co-occurrence edges.** For each concept, connect every pair
   of docs that mention it. Edges with `weight >= 2` are kept. This gives
   fast, interpretable edges — you can always see *why* two docs are
   linked (the shared concepts).
3. **Embedding fallback.** Any doc left with zero edges after step 2 gets
   up to 3 nearest-neighbor edges from the qmd vector index (cosine
   similarity > 0.5). This catches docs whose vocabulary doesn't overlap
   with the concept dictionary. Typical isolation rate after this: 0%.
4. **Serialize** to NetworkX `node_link_data` JSON at `$MUSUBI_GRAPH_PATH`.

### Read-side lookup

The `Graph` class in [`graph.py`](src/musubi/graph.py) loads the JSON
once, builds an adjacency map + path/title/id indexes, and answers
queries from memory. No networkx import on the read path, so
`musubi stats` runs in a few hundred milliseconds even on large graphs.

---

## Configuration

Musubi reads configuration entirely from environment variables — zero
hardcoded paths. All of these have sensible XDG-style defaults:

| Variable | Default | What it is |
|----------|---------|------------|
| `MUSUBI_GRAPH_PATH` | `$XDG_DATA_HOME/musubi/graph.json` | Serialized graph |
| `MUSUBI_QMD_DB` | `$XDG_CACHE_HOME/qmd/index.sqlite` | qmd SQLite index |
| `MUSUBI_QMD_BIN` | whatever `qmd` resolves to | qmd CLI binary |
| `MUSUBI_CONCEPTS_FILE` | `$XDG_CONFIG_HOME/musubi/concepts.txt` | Extra user concepts |
| `MUSUBI_LOG_DIR` | `$XDG_STATE_HOME/musubi` | Where `build` logs go |

---

## Customizing concepts

The default concept dictionary covers generic LLM infra + web dev +
agent/tooling terms. Your own domain vocabulary (internal product names,
team jargon, industry-specific terms) should go in a user concepts file:

```bash
# ~/.config/musubi/concepts.txt
# One term per line. Lines starting with # are ignored.

# product names
my-internal-tool
secretproduct

# domain vocabulary (e.g. options trading)
bull put spread
delta hedging
iv rank
```

Rebuild the graph after adding concepts:

```bash
musubi build
```

---

## Weekly auto-rebuild

Drop this in your crontab (or equivalent) to keep the graph fresh:

```cron
# every Sunday at 02:17 local: re-index qmd, rebuild graph
17 2 * * 0 qmd update && musubi build >> /tmp/musubi-weekly.log 2>&1
```

---

## Prior art & inspiration

- [LightRAG](https://github.com/HKUDS/LightRAG) — the concept of treating
  a note collection as a knowledge graph instead of a bag of vectors.
- [Obsidian graph view](https://help.obsidian.md/Plugins/Graph+view) —
  the visual intuition, minus the vendor lock-in.
- Graph community detection literature — Louvain, node centrality.

Musubi differs in that it **doesn't replace your notes system**. Your
markdown files stay where they are. The graph is a pure derivative — you
can delete it at any time and rebuild from the source.

---

## License

MIT. See [LICENSE](LICENSE).
