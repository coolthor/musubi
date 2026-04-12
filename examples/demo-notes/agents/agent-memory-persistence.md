---
title: "Agent Memory: File-Based vs Database-Backed"
date: "2026-04-01"
tags: ["agent", "memory", "sqlite", "architecture"]
---

## The Tradeoff

| Approach | Pros | Cons |
|----------|------|------|
| File-based (MEMORY.md) | Human-readable, git-friendly, portable | No structured query, grows without bound |
| SQLite | Fast search (FTS5), structured, queryable | Opaque, not human-editable, migration pain |
| Vector DB (ChromaDB, etc.) | Semantic search, handles fuzzy recall | Heavy dependency, overkill for < 10K docs |

## Recommendation

Start with file-based. When you hit 200+ memory entries and search
becomes slow, migrate to SQLite with FTS5. Don't jump to vector DBs
unless you need semantic recall across 10K+ entries.

## Key Insight

The hard part of agent memory isn't storage — it's **what to remember
and what to forget**. A memory system that never prunes is just a log
file. Build decay or explicit deletion into the design from day one.
