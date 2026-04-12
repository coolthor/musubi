---
title: "Next.js i18n: How hreflang x-default Splits Your SEO Rankings"
date: "2026-04-10"
tags: ["next.js", "seo", "hreflang", "canonical", "i18n"]
---

## Problem

Google indexed both `/blog/my-post` and `/en/blog/my-post` as separate
pages — same content, split ranking signal. The unprefixed URL had 4x
more impressions but 10x worse CTR.

## Root Cause

The i18n middleware auto-emitted an HTTP `Link` header with
`hreflang="x-default"` pointing at the unprefixed path. Google treated
it as a valid canonical URL even though it 307-redirected to `/en/`.

## Fix

1. Disable the middleware's auto alternate links
2. Add 308 permanent redirects for legacy unprefixed URLs
3. Declare x-default explicitly in page metadata pointing at `/en/`

## Key Takeaway

307 (temporary) redirects don't consolidate ranking signal. Use 308
(permanent) to tell Google to merge backlink equity. Always check
Google Search Console URL Inspection to see what Google *actually*
chose as canonical — it's often not what you declared.
