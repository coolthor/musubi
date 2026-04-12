# Musubi 結び

**Tie your markdown notes together — without leaving markdown.**

```bash
$ musubi neighbors "fp8-kvcache-repetition"

◇ [infra] FP8 KV Cache Causes Infinite Repetition
  id=4821  degree=38  concepts=18

  · w=12  [infra] SM121 NVFP4 vLLM Garbage Output — Root Cause & Fix
      shared: vllm, quantization, kv cache, gpu
  · w=10  [infra] Gemma 4 26B-A4B NVFP4 on GX10 — vLLM 0.19
      shared: vllm, quantization, dgx spark, inference
  · w=8   [infra] vLLM FP8 KV Cache Upgrade — bf16 Fix
      shared: vllm, kv cache, fp8, gpu
```

You wrote a debugging note about FP8 KV cache six weeks ago. Today
you're fixing a different quantization issue. Keyword search won't find
the old note because the vocabulary is different. Musubi links them
through shared concepts — `quantization`, `kv cache`, `vllm` — so the
connection surfaces automatically.

---

## What it does

Musubi scans a directory of markdown files, extracts technical concepts
from each document, and builds a weighted graph of concept co-occurrence.
The result is a JSON graph you can query instantly from the command line:

| Command | What you get |
|---------|-------------|
| `musubi neighbors <doc>` | "What other notes are related to this one?" |
| `musubi cold` | "Which notes have gone stale and lost connections?" |
| `musubi search <query>` | "Search this topic + show graph-expanded neighbors" |
| `musubi stats` | "How big is my knowledge graph? What are the hubs?" |
| `musubi build --source <dir>` | "Rebuild the graph from my notes directory" |

No servers. No databases. No API keys. Just markdown files and a CLI.

---

## Why not...

| Tool | What it does | Why musubi is different |
|------|-------------|----------------------|
| **Obsidian Graph View** | Visual graph of `[[wikilinks]]` | Locked to Obsidian. Edges are manual (you write the links). No concept extraction, no cold detection, no CLI. Musubi works with any markdown files. |
| **LightRAG** | LLM-powered entity extraction → knowledge graph → RAG | Requires an LLM for every build ($$). Server setup. Designed for RAG pipelines, not personal note management. Musubi builds are deterministic, free, and take 24 seconds. |
| **Logseq / Roam** | Graph-based note apps with bidirectional linking | Proprietary formats. Manual linking. No automatic concept discovery. Musubi reads plain `.md` files — your existing ones, unmodified. |
| **Neo4j + scripts** | Full graph database | Requires a running Neo4j server. Overkill for personal notes. Musubi is a single `pip install` — the graph is a JSON file. |
| **Vector search alone** | Find similar documents by embedding distance | Similarity ≠ community. Two Python files are "similar" (both are code) but not intellectually related. Concept co-occurrence captures *topical* relationships, not surface-level text similarity. |

**Musubi's position:** it's a **companion**, not a replacement. Your
markdown files stay where they are. The graph is a pure derivative you
can delete and rebuild anytime. Zero lock-in.

---

## Numbers (real-world, not synthetic)

Built from a personal knowledge base of developer notes, experience
files, and technical blog articles:

| Metric | Value |
|--------|-------|
| Documents | 399 |
| Concept edges | 13,915 |
| Embedding fallback edges | 131 |
| Isolated nodes | 0 (0.0%) |
| Build time | 24 seconds (M-series Mac) |
| Graph file size | ~1 MB |
| Read-side query time | < 200ms |
| Concept dictionary | 180+ built-in terms, user-extensible |

The default concept dictionary covers LLM inference, web development,
DevOps, and AI tooling. You add your own domain vocabulary in a plain
text file.

---

## Install

Requires **Python 3.11+**. No other external tools needed.

```bash
pip install musubi          # from PyPI (coming soon)

# or from source:
git clone https://github.com/coolthor/musubi.git
cd musubi
uv tool install .           # or: pip install .
```

### Optional: qmd integration

If you use [`@tobilu/qmd`][qmd] (an on-device hybrid search CLI for
markdown), musubi can read its SQLite index directly:

- `musubi build` (no `--source`) reads from the qmd index, including
  embeddings for a better isolation fallback
- `musubi search` delegates keyword search to `qmd search --json` and
  expands results with graph neighbors

qmd is **not required**. Without it, use `musubi build --source <dir>`.

[qmd]: https://www.npmjs.com/package/@tobilu/qmd

---

## Quick start

```bash
# Build from a directory of markdown files
musubi build --source ~/my-notes/

# Explore
musubi stats                         # graph overview
musubi neighbors "some-doc-slug"     # what's connected to this?
musubi cold --limit 20               # what's gone stale?
```

### Example output: `musubi stats`

```
◇ Musubi — Graph Stats

  version:   0.1.0
  nodes:     399
  edges:     14046
    · concept: 13915
    · embedding: 131
  isolated:  0 (0.0%)
  avg deg:   70.4
  hub node:  deg=224  [bpstracker-web] Blog SEO + Charts session

  top concepts:
    api                       172 docs
    agent                     89 docs
    session                   82 docs
    bps                       73 docs
    security                  59 docs
```

### Example output: `musubi cold`

```
◇ Cold nodes (top 5)
  score = 0.5·(1/deg) + 0.2·(1/concepts) + 0.3·(days/180)

  score   deg   days   label
  0.458   3     80     ❄ [book-podcast] courage
  0.455   3     78       [book-podcast] lychee
  0.433   3     65       [claude-code] Development Context
```

### Example output: `musubi search`

```
◇ Musubi search: gemma4 nvfp4

  ★ 1.000  [infra] Gemma 4 26B-A4B NVFP4 on GX10
  + 0.690  [infra] SM121 NVFP4 vLLM Garbage Output — Root Cause
  + 0.660  [infra] SM121 cuBLASLt → CUTLASS Migration

  ★ = direct hit    + = graph neighbor boost
```

The `+` results are notes that **keyword search alone would never
return** — they don't contain the search terms, but they're graph
neighbors of the direct hits.

---

## How it works

```
                    musubi build
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐
   │ ~/notes/   │ │ qmd sqlite │ │ concepts   │
   │ *.md files │ │ (optional) │ │ dictionary │
   └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
         │              │              │
         └──────────────┼──────────────┘
                        ▼
              ┌──────────────────┐
              │ concept          │
              │ extraction       │  regex matching against
              │ per document     │  180+ built-in terms
              └────────┬─────────┘  + your custom terms
                       ▼
              ┌──────────────────┐
              │ co-occurrence    │  if doc A and doc B both
              │ edge building    │  mention "vllm" + "kv cache"
              │                  │  → edge(A,B, weight=2)
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │ embedding        │  (qmd mode only)
              │ fallback for     │  cosine sim > 0.5 for
              │ isolated nodes   │  docs with 0 concept edges
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │ graph.json       │  NetworkX node_link_data
              │ (~1 MB)          │  stored at $MUSUBI_GRAPH_PATH
              └──────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       stats      neighbors      cold
       search        path
```

### Key design decisions

- **Concept extraction is deterministic.** No LLM in the build loop.
  Same input → same graph, every time. No API costs, no hallucinated
  entities, no rate limits.
- **Read path imports nothing heavy.** `musubi stats` and
  `musubi neighbors` load the JSON file and answer from memory. No
  networkx, no numpy on the read path. Fast cold starts.
- **Edges are interpretable.** Every edge carries its `shared_concepts`
  list, so you can always see *why* two docs are connected — not just
  that they are.

---

## Customizing concepts

The default dictionary covers generic tech terms. Add your own domain
vocabulary in a plain text file:

```bash
# ~/.config/musubi/concepts.txt
# One term per line. # for comments.

# your product names
my-internal-tool
secretproduct

# your domain (e.g. finance)
bull put spread
delta hedging
iv rank

# your hardware
dgx spark
gb10
```

Then rebuild: `musubi build --source ~/notes/`

The default + custom concepts are merged at build time. Your custom file
is never committed to the musubi repo.

---

## Configuration

All paths are overridable via environment variables. Sensible XDG
defaults mean you don't need to set anything:

| Variable | Default | What it is |
|----------|---------|------------|
| `MUSUBI_GRAPH_PATH` | `$XDG_DATA_HOME/musubi/graph.json` | Serialized graph |
| `MUSUBI_QMD_DB` | `$XDG_CACHE_HOME/qmd/index.sqlite` | qmd SQLite index |
| `MUSUBI_QMD_BIN` | `qmd` on PATH | qmd CLI binary |
| `MUSUBI_CONCEPTS_FILE` | `$XDG_CONFIG_HOME/musubi/concepts.txt` | Custom concept list |
| `MUSUBI_LOG_DIR` | `$XDG_STATE_HOME/musubi/` | Build logs |

---

## Weekly auto-rebuild

```cron
# every Sunday at 02:17: rebuild graph from latest notes
17 2 * * 0 musubi build --source ~/notes/ >> /tmp/musubi-weekly.log 2>&1
```

---

## Prior art

- [LightRAG](https://github.com/HKUDS/LightRAG) — LLM-powered knowledge
  graph + RAG. Musubi borrows the "treat notes as a graph" idea but
  replaces LLM extraction with deterministic concept matching.
- [Obsidian graph view](https://help.obsidian.md/Plugins/Graph+view) —
  the visual intuition. Musubi gives you the same structure as a CLI tool
  on plain markdown files.
- Louvain community detection, betweenness centrality — the graph theory
  behind `musubi cold` and community identification.

---

## License

MIT. See [LICENSE](LICENSE).
