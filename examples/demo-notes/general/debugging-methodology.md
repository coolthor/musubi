---
title: "Debugging: Bisect Before You Theorize"
date: "2026-01-20"
tags: ["debugging", "methodology"]
---

## The Anti-Pattern

1. See error
2. Form a theory ("it's probably the database connection")
3. Spend 2 hours investigating the theory
4. Theory was wrong
5. Repeat with a new theory

## The Better Way

1. See error
2. Find the smallest reproduction
3. Binary search (bisect) for the commit/config/input that introduced it
4. Once isolated, the fix is usually obvious

## Git Bisect Cheat Sheet

```bash
git bisect start
git bisect bad              # current commit is broken
git bisect good v1.2.0      # this version worked
# git checks out a middle commit — test it, then:
git bisect good             # or: git bisect bad
# repeat until it finds the exact commit
git bisect reset
```

## Key Takeaway

Theories are cheap. Evidence is expensive. Bisect gives you evidence
faster than theorizing.
