---
title: "Vercel Domain Redirects: 307 vs 308 and What Google Thinks"
date: "2026-04-10"
tags: ["vercel", "seo", "deploy", "canonical"]
---

## Problem

Vercel's default apex → www redirect uses 307 (temporary). Google sees
both `example.com` and `www.example.com` as separate sites and splits
ranking signal between them.

## Fix

In Vercel Dashboard → Domains, set the non-primary domain to use a
**308 permanent** redirect. Google will consolidate within 1-2 weeks.

## Also Check

- `robots.txt` sitemap URL — make sure it uses the primary domain
- All hardcoded URLs in metadata/OG tags — match the primary domain
- Google Search Console — submit sitemap under the primary domain

## Numbers

Before fix: homepage ranking at position 11.8 (apex) and 4.0 (www)
After fix: consolidated to position ~4 with full backlink equity.
