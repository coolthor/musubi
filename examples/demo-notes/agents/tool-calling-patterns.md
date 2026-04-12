---
title: "Tool Calling Patterns: When the Model Gets It Wrong"
date: "2026-03-20"
tags: ["tool calling", "agent", "prompt engineering", "debugging"]
---

## Common Failure Modes

### 1. Hallucinated parameters
The model invents a parameter name that doesn't exist in the schema.
Fix: make parameter names obvious and descriptive. `file_path` > `fp`.

### 2. Wrong tool selection
The model picks `search_web` when it should use `read_file`. Fix:
add a one-line description to each tool that disambiguates. "Search
the web for external information" vs "Read a file from the local
filesystem."

### 3. Infinite tool loops
The model calls the same tool repeatedly with the same arguments.
Fix: add a turn counter or a "this tool was already called with
these args" check in the orchestrator.

## Best Practice

Keep the tool list short (< 20 tools per conversation). If you need
more, use a toolset routing layer that selects a subset based on the
conversation topic.
