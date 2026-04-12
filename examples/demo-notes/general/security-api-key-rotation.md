---
title: "API Key Rotation: The Checklist You'll Forget"
date: "2026-03-05"
tags: ["security", "api key", "deploy", "monitoring"]
---

## When to Rotate

- Key appears in a commit (even if reverted — it's in git history forever)
- Team member leaves
- Suspicious activity in logs
- Every 90 days as a hygiene practice

## Rotation Checklist

1. Generate new key in the provider dashboard
2. Update all deployment environments (staging, prod, CI)
3. Update `.env` files on all servers
4. Verify new key works (health check endpoint)
5. Revoke old key in the provider dashboard
6. Check logs for 401 errors (something still using old key)
7. Update any hardcoded references in documentation

## The Mistake Everyone Makes

Rotating the key but forgetting to revoke the old one. Now you have two
valid keys, and the compromised one still works. Always revoke within
24 hours of deploying the new key.
