# Musubi 結び

**Tie your markdown notes together — without leaving markdown.**

<p align="center">
  <img src="assets/demo-graph.png" alt="Musubi demo knowledge graph" width="100%">
</p>

```bash
$ musubi neighbors "vllm"

◇ [inference] Ollama vs vLLM: Same Model, 30% Speed Gap on GPU
  id=12  degree=5  concepts=15

  · w=7   [inference] Quantization Format Cheat Sheet: FP8, NVFP4, GGUF, AWQ, GPTQ
      shared: gotcha, gpu, vllm, inference
  · w=5   [devops] Docker GPU OOM: Why Your Container Crashes After 2 Hours
      shared: gpu, vram, vllm, inference
  · w=3   [inference] MoE vs Dense: Why Bandwidth Decides Everything
      shared: gpu, tok/s, throughput
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
| `musubi init` | Interactive setup — try the demo or point at your notes |
| `musubi build --source <dir>` | Build the graph from your notes directory |
| `musubi stats` | "How big is my knowledge graph? What are the hubs?" |
| `musubi neighbors <doc>` | "What other notes are related to this one?" |
| `musubi cold` | "Which notes have gone stale and lost connections?" |
| `musubi search <query>` | Search + show graph-expanded neighbors |
| `musubi benchmark` | Measure how many tokens musubi saves you ([details](#measure-your-token-savings)) |

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

## Numbers

The included demo notes (20 docs across 5 domains) build instantly.
Real-world corpora of 400+ docs build in under 30 seconds:

| Metric | Demo (20 docs) | Production (400 docs) |
|--------|---------------|----------------------|
| Concept edges | 17 | 13,915 |
| Isolated nodes | 7 (35%) | 0 (0%) |
| Build time | 0.7s | 24s |
| Graph file size | 8 KB | 1 MB |
| Read-side query | < 100ms | < 200ms |

The 35% isolation rate in the demo drops to 0% in production because
larger corpora have more concept overlap — and with qmd mode, the
embedding fallback catches the rest.

The default concept dictionary ships 180+ generic tech terms. You add
your own domain vocabulary in a plain text file (see
[Customizing concepts](#customizing-concepts)).

---

## Install

Requires **Python 3.11+**. No other external tools needed.

**One-liner** (if you have [uv](https://docs.astral.sh/uv/)):

```bash
uvx --from git+https://github.com/coolthor/musubi musubi init
```

This downloads, installs, and launches the setup wizard in one shot.

**Or install permanently:**

```bash
git clone https://github.com/coolthor/musubi.git
cd musubi
uv tool install .           # or: pip install .

musubi init                 # interactive setup wizard
```

The setup wizard checks your environment, lets you try the bundled demo
or point at your own notes, and walks you through custom concepts and
cron setup — all in under a minute.

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
  nodes:     20
  edges:     17
    · concept: 17
  isolated:  7 (35.0%)
  avg deg:   1.7
  hub node:  deg=5  [inference] Ollama vs vLLM: Same Model, 30% Speed Gap on GPU

  collections:
    inference          5
    agents             4
    devops             4
    webdev             4
    general            3

  top concepts:
    vllm                      5 docs
    agent                     4 docs
    inference                 4 docs
    gpu                       4 docs
    git                       4 docs
```

### Example output: `musubi neighbors`

```
◇ [inference] Ollama vs vLLM: Same Model, 30% Speed Gap on GPU
  id=12  degree=5  concepts=15

  · w=7   [inference] Quantization Format Cheat Sheet: FP8, NVFP4, GGUF, AWQ, GPTQ
      shared: gotcha, gpu, vllm, inference
  · w=5   [devops] Docker GPU OOM: Why Your Container Crashes After 2 Hours
      shared: gpu, vram, vllm, inference
  · w=3   [inference] MoE vs Dense: Why Bandwidth Decides Everything
      shared: gpu, tok/s, throughput
```

Notice how **Docker GPU OOM** (a devops note) surfaces as a neighbor of
a benchmark note — they share `gpu`, `vram`, `vllm`, and `inference`.
Keyword search for "benchmark" would never return a devops debugging note.

### Example output: `musubi cold`

```
◇ Cold nodes (top 5)
  score = 0.5·(1/deg) + 0.2·(1/concepts) + 0.3·(days/180)

  score   deg   days   label
  0.567   0     0      ❄ [webdev] React Server Components: Three Gotchas
  0.567   0     0      ❄ [devops] PostgreSQL Autovacuum Deadlock
  0.550   0     0      ❄ [agents] Tool Calling Patterns: When the Model Gets It Wrong
  0.540   0     0      ❄ [agents] Agent Memory: File-Based vs Database-Backed
  0.525   0     0      ❄ [webdev] Next.js i18n: hreflang x-default Splits Rankings
```

The ❄ marker flags isolated nodes (degree = 0). These docs don't share
enough concepts with anything else — either they need richer vocabulary,
or they're genuinely standalone topics.

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

## Try it yourself (demo)

The repo includes 20 demo notes across 5 domains. Build and explore
in 30 seconds:

```bash
git clone https://github.com/coolthor/musubi.git
cd musubi
uv tool install .
musubi build --source examples/demo-notes/
musubi stats
musubi neighbors "vllm"
musubi cold
```

The [interactive graph visualization](assets/demo-graph.html) can be
opened in any browser after building.

---

## Use it on your own notes

Done with the demo? Here's how to switch to your actual notes.

### Step 1: Point at your notes directory

```bash
musubi build --source ~/path/to/your/notes/
```

Musubi recursively finds all `*.md` and `*.mdx` files. Subdirectories
become **collections** (shown as `[inference]`, `[devops]`, etc. in
output). If all files are at the root level, they go into a `default`
collection.

**Works with any markdown notes system** — Obsidian vaults, Logseq
directories, Dendron workspaces, or just a folder of `.md` files.

### Step 2: Check what you got

```bash
musubi stats       # how many nodes, edges, isolated docs?
musubi cold        # anything gone stale?
```

If `musubi cold` shows a lot of ❄ isolated nodes, your notes probably
use domain-specific vocabulary that isn't in the default concept
dictionary. That's normal — go to Step 3.

### Step 3: Add your vocabulary (optional but recommended)

Create a concepts file with terms specific to your work:

```bash
mkdir -p ~/.config/musubi

cat > ~/.config/musubi/concepts.txt << 'EOF'
# My domain vocabulary
# One term per line. Lines starting with # are comments.

# example: if you work in finance
black-scholes
portfolio rebalancing
sharpe ratio

# example: your internal tools
my-internal-api
staging-cluster
deployment-pipeline

# example: your tech stack
fastapi
celery
rabbitmq
EOF
```

Then rebuild:

```bash
musubi build --source ~/path/to/your/notes/
musubi stats    # edges and avg degree should increase
musubi cold     # fewer isolated nodes
```

**Tip:** Look at the `top concepts` in `musubi stats`. If the top
concepts are too generic (like "the", "api", "code"), they're acting as
stopwords and connecting everything to everything. Remove overly generic
terms from your concepts file. If important domain terms are missing,
add them.

### Step 4: Set up auto-rebuild (optional)

Once you're happy with the graph, schedule a weekly rebuild so it
stays fresh as you add new notes:

```cron
# every Sunday at 02:17: rebuild graph from latest notes
17 2 * * 0 musubi build --source ~/notes/ >> /tmp/musubi-weekly.log 2>&1
```

### Directory structure tips

```
# Good: subdirectories become meaningful collections
~/notes/
├── projects/          → [projects] collection
│   ├── api-redesign.md
│   └── mobile-app.md
├── debugging/         → [debugging] collection
│   ├── postgres-oom.md
│   └── redis-timeout.md
└── learning/          → [learning] collection
    ├── rust-ownership.md
    └── k8s-networking.md

# Also fine: flat directory → all in [default] collection
~/notes/
├── api-redesign.md
├── postgres-oom.md
└── rust-ownership.md
```

### Common questions

**Q: How many notes do I need for the graph to be useful?**
A: 30+. Below that, most notes are isolated. Above 100, you start
getting rich cross-domain connections that surprise you.

**Q: Can I point at multiple directories?**
A: Not yet in a single command. Workaround: symlink them under one
parent directory, or use [qmd](https://www.npmjs.com/package/@tobilu/qmd)
which supports multiple named collections.

**Q: Will it modify my markdown files?**
A: No. Musubi is strictly read-only. It reads your files, builds a
separate `graph.json`, and never touches the source.

---

## Weekly auto-rebuild

```cron
# every Sunday at 02:17: rebuild graph from latest notes
17 2 * * 0 musubi build --source ~/notes/ >> /tmp/musubi-weekly.log 2>&1
```

---

## Measure your token savings

Musubi itself uses **zero LLM tokens** — the graph is built with
deterministic regex matching, not LLM entity extraction. But does using
musubi save tokens when you *use* an LLM to search your notes?

The included benchmark answers this empirically:

```bash
# Preview the 10 test tasks (no API calls, no cost)
musubi benchmark --dry-run

# Full run — compares grep-only vs musubi-augmented retrieval
# Requires ANTHROPIC_API_KEY. Cost: ~$0.15 per run.
export ANTHROPIC_API_KEY=sk-ant-...
musubi benchmark
```

The benchmark runs each task twice — once with only `grep` + `cat`
(baseline), once with `musubi search` + `musubi neighbors` — and
measures total tokens consumed. Results go to
`experiments/token-saving/results/summary.md`.

### What it tests

| Task type | Count | What it measures |
|-----------|-------|-----------------|
| Direct lookup | 3 | Find a note when you know the topic |
| Cross-domain | 3 | Find notes across different collections — musubi's main advantage |
| Exploration | 2 | "Show me related notes" — only graph can do this |
| Health check | 2 | "What's stale?" — only musubi can answer |

### Why we test instead of claim

We don't put "saves 40% tokens" in the README without data. Run the
benchmark yourself and see your actual numbers. The experiment uses the
bundled demo notes (20 docs) so results are reproducible — anyone who
clones the repo gets the same test.

---

## Using with Claude Code

Add this to your project's `CLAUDE.md` or global instructions to make
Claude Code automatically use musubi when retrieving knowledge:

```markdown
### Retrieval workflow

1. Query your knowledge base: `qmd search "<topic>"` or `musubi search "<topic>"`
2. If a relevant doc is found, expand with graph neighbors:
   `musubi neighbors "<filename>" --limit 3`
3. Read the most relevant docs and proceed with the task.

Use `musubi search` when you want keyword hits + graph-expanded neighbors
in one shot. Use `musubi neighbors` after finding a specific doc to see
what's connected to it. Use `musubi cold` for periodic health checks.
```

No MCP server needed — Claude Code calls musubi via the shell, same as
`grep` or `git`.

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
