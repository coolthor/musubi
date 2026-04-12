---
title: "System Prompts That Actually Work"
date: "2026-02-10"
tags: ["prompt engineering", "agent", "claude", "chatgpt"]
---

## The Structure That Works

1. **Role** (1 sentence): "You are a senior Python developer."
2. **Context** (2-3 sentences): what the user is working on, key constraints.
3. **Rules** (bullet list): explicit do's and don'ts.
4. **Output format** (if needed): JSON schema, markdown template, etc.

## What Doesn't Work

- **Too long**: after ~2000 tokens of system prompt, models start
  ignoring parts of it. Keep it under 1000 tokens.
- **Contradictory rules**: "be concise" + "explain thoroughly" → the
  model picks one randomly per turn.
- **Negative-only rules**: "don't do X, don't do Y" without saying
  what *to* do. Give positive examples.

## Testing

Vary the system prompt slightly between test runs. If the output changes
dramatically from a minor wording change, the prompt is fragile — the
model is pattern-matching on phrasing rather than understanding intent.
