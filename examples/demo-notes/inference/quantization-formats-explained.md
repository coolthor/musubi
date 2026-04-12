---
title: "Quantization Format Cheat Sheet: FP8, NVFP4, GGUF, AWQ, GPTQ"
date: "2026-04-01"
tags: ["quantization", "fp8", "nvfp4", "gguf", "inference"]
---

## Quick Reference

| Format | Bits | Runtime | Best For |
|--------|------|---------|----------|
| BF16 | 16 | any | baseline, no quality loss |
| FP8 | 8 | vLLM, TRT-LLM | production serving on H100/GB10 |
| NVFP4 | 4 | vLLM 0.19+ | maximum throughput on NVIDIA |
| GGUF Q4_K_M | 4 | llama.cpp, Ollama | CPU/mixed inference, Mac |
| AWQ | 4 | vLLM | fast GPU inference |
| GPTQ | 4 | vLLM, exllamav2 | legacy, being replaced by AWQ |

## Key Insight

Quantization is a memory-bandwidth tradeoff, not a compute tradeoff.
On bandwidth-limited hardware (consumer GPUs, Apple Silicon), 4-bit
quantization nearly doubles throughput because you're moving half the
bytes through the memory bus per token.

## Gotcha

FP8 KV cache and FP8 weights are independent decisions. You can run
FP8 weights with BF16 KV cache (recommended) or vice versa. Don't
assume they're linked.
