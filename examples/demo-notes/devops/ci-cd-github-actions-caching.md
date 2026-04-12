---
title: "GitHub Actions: Caching node_modules Properly"
date: "2026-01-15"
tags: ["ci/cd", "github actions", "deploy", "javascript"]
---

## Problem

Next.js builds taking 8+ minutes in CI because `npm install` downloads
everything from scratch every time.

## Fix

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.npm
    key: npm-${{ hashFiles('**/package-lock.json') }}
    restore-keys: npm-
```

This caches the npm download cache (not `node_modules` itself). Cache
hit rate: ~95% for repos that don't change dependencies often.

## Result

Build time: 8m → 2.5m. The npm install step goes from 90s to 5s on
cache hit.

## Gotcha

Don't cache `node_modules` directly — it can contain platform-specific
binaries (e.g., `esbuild`, `sharp`) that break when restored on a
different architecture. Cache the *download* cache, let npm handle
the install.
