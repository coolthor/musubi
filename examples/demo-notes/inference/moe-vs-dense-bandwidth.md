---
title: "MoE vs Dense: Why Bandwidth Decides Everything"
date: "2026-03-25"
tags: ["moe", "dense", "inference", "gpu", "bandwidth"]
---

## The Rule

On bandwidth-limited hardware, **active parameter count** determines speed,
not total parameter count. A 26B MoE model with 4B active parameters runs
at roughly the same speed as a 4B dense model — because both move ~4B
params worth of bytes per token.

## Practical Example

| Model | Total | Active | tok/s (273 GB/s) |
|-------|-------|--------|-------------------|
| Gemma 4 31B Dense | 31B | 31B | 7 |
| Gemma 4 26B MoE | 26B | 4B | 52 |
| Gemma 4 E4B MoE | 9B | 4B | 50 |

The 26B MoE is **7x faster** than the 31B dense despite being nearly the
same total size. On memory-bandwidth-constrained hardware, always prefer
MoE over dense.

## When Dense Wins

On high-bandwidth hardware (H100 SXM, multi-GPU NVLink), the MoE routing
overhead starts to matter and dense models can match or beat MoE throughput.
