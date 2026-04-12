---
title: "Adding Client-Side Search to a Static Site with Pagefind"
date: "2026-03-01"
tags: ["pagefind", "next.js", "search", "seo", "javascript"]
---

## What Pagefind Does

Pagefind builds a static search index at build time from your HTML
output. The index ships as a few hundred KB of WASM + compressed data.
No server, no API, no runtime cost.

## Integration with Next.js

```bash
npx pagefind --site .next/server/app --glob '**/*.html'
cp -r .next/server/app/pagefind public/pagefind
```

Add to your build script in `package.json`. The search UI loads the
WASM file on first keystroke — zero impact on initial page load.

## Gotcha

Pagefind indexes the *rendered HTML*, not the source markdown. If your
content is behind client-side rendering (CSR), Pagefind won't see it.
Make sure critical content is server-rendered or statically generated.
