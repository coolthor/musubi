# Token Saving Experiment

**Question:** How many tokens does Claude save when using musubi's
graph-augmented search vs plain keyword search for finding notes?

## Design

10 retrieval tasks on the bundled demo notes (20 docs), each run twice:

| Group | Available tools | Measures |
|-------|----------------|----------|
| **A — Baseline** | `grep` + `cat` (keyword search) | Tokens, rounds, tool calls |
| **B — Musubi** | `musubi search/neighbors/cold/stats` + `cat` | Same metrics |

### Task types (see `tasks.json`)

| Type | Count | What it tests |
|------|-------|---------------|
| `direct_lookup` | 3 | Find a note when you know the topic — baseline should do OK |
| `cross_domain` | 3 | Find notes across different collections — musubi's main advantage |
| `exploration` | 2 | "Show me related notes" — only musubi can do this directly |
| `health_check` | 2 | "What's stale?" — only musubi can answer |

### Hypothesis

- **Direct lookup:** musubi saves 20-40% (fewer rounds to find the right file)
- **Cross-domain:** musubi saves 50-70% (keyword search can't bridge domains)
- **Exploration / health:** musubi saves 80%+ (baseline literally can't do this)
- **Overall:** 30-50% token reduction

## Running

```bash
# 1. Build the graph from demo notes
musubi build --source examples/demo-notes/

# 2. Install the Anthropic SDK
pip install anthropic

# 3. Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Dry run (preview tasks, no API calls)
python experiments/token-saving/run_experiment.py --dry-run

# 5. Full run
python experiments/token-saving/run_experiment.py

# 6. Single task (for debugging)
python experiments/token-saving/run_experiment.py --task cross-1

# 7. One group only
python experiments/token-saving/run_experiment.py --group musubi
```

## Output

- `results/experiment-YYYY-MM-DD.json` — raw per-task token counts
- `results/summary.md` — comparison table with savings percentages

## Cost estimate

- 10 tasks × 2 groups × ~2000 tokens avg = ~40K tokens
- At Claude Sonnet rates: ~$0.15 per full run
- You can run `--task <id>` to test a single task first

## Reproduction

Everything uses the bundled demo notes (no private data). Anyone who
clones the repo can reproduce the results with their own API key.
