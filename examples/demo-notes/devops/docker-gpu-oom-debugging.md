---
title: "Docker GPU OOM: Why Your Container Crashes After 2 Hours"
date: "2026-03-10"
tags: ["docker", "gpu", "nvidia", "debugging", "inference"]
---

## Symptom

vLLM container runs fine for ~2 hours, then gets OOM-killed. nvidia-smi
shows GPU memory climbing steadily despite no increase in concurrent
requests.

## Root Cause

Another process (Ollama) was configured with `KEEP_ALIVE=2h`, holding
its model in GPU memory even when idle. After 2 hours, Ollama releases
the memory — but during those 2 hours, both processes compete for VRAM.

## Fix

Before starting vLLM, unload all Ollama models:

```bash
curl -X POST http://localhost:11434/api/generate \
  -d '{"model":"your-model","keep_alive":0}'
```

Or stop the Ollama service entirely: `systemctl stop ollama`

## Prevention

Never run two GPU-hungry inference servers on the same machine without
explicit memory budgeting. Use `--gpu-memory-utilization 0.85` in vLLM
to leave headroom.
