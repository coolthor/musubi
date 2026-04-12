---
title: "Prefix Caching: Why TTFT Drops from 2s to 0.1s"
date: "2026-04-05"
tags: ["vllm", "inference", "prefix caching", "kv cache", "latency"]
---

## What It Does

Prefix caching stores the KV cache of common prompt prefixes (system
prompts, few-shot examples) across requests. When a new request shares
the same prefix, vLLM skips recomputing those tokens entirely.

## Impact

For a 2000-token system prompt:
- Without prefix cache: TTFT = 2.1s (must process all 2000 tokens)
- With prefix cache: TTFT = 0.12s (cache hit, skip straight to user input)

## When It Doesn't Help

- Every request has a unique prefix (no reuse)
- Very short system prompts (< 100 tokens) — savings are negligible
- High request diversity (cache eviction rate too high)

## vLLM Flag

```bash
--enable-prefix-caching
```

Zero downside. Always enable it unless you're benchmarking raw prefill speed.
