---
title: "Ollama vs vLLM: Same Model, 30% Speed Gap on GPU"
date: "2026-03-20"
tags: ["ollama", "vllm", "benchmark", "inference", "gpu"]
---

## Setup

Ran the same Qwen 35B model on both Ollama and vLLM on identical hardware.
Measured tok/s for decode, TTFT, and throughput under batch=1.

## Results

| Metric | Ollama | vLLM |
|--------|--------|------|
| Decode tok/s | 36 | 47 |
| TTFT | 0.8s | 0.12s |

vLLM is ~30% faster for decode and 6x faster for TTFT. The gap comes from
vLLM's continuous batching, CUDA graph compilation, and prefix caching.

## When to Use Each

- **Ollama**: quick model testing, development, multiple small models in memory
- **vLLM**: production serving, high throughput, when latency matters

## Gotcha

Ollama silently splits models across CPU and GPU when VRAM is tight. Check
`ollama ps` — if GPU% < 100, you're hitting CPU bandwidth, not GPU bandwidth.
