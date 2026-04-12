---
title: "vLLM FP8 KV Cache Causes Output Repetition"
date: "2026-03-14"
tags: ["vllm", "fp8", "kv cache", "quantization", "inference"]
---

## Problem

After switching KV cache dtype from bf16 to fp8, the model starts producing
repetitive output after ~500 tokens. First 400 tokens are fine, then it
degrades into infinite loops of the same phrase.

## Root Cause

The fp8 KV cache quantization uses a per-head scale factor. When the scale
is miscalibrated (defaulting to 1.0), the accumulated quantization error
grows with sequence length until the attention distribution collapses.

## Solution

Switch back to `--kv-cache-dtype bf16`. The speed difference is marginal
(~3% slower) but output quality is dramatically better. If fp8 KV cache
is needed, ensure proper calibration data is provided.

## Key Takeaway

Never trust default quantization parameters for KV cache. Always validate
with long-context generation (1000+ tokens) before deploying.
