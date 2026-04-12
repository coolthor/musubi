---
title: "Git Worktrees: Work on Two Branches Without Stashing"
date: "2026-02-05"
tags: ["git", "workflow"]
---

## Problem

You're deep in a feature branch. An urgent bug report comes in. You need
to switch to main, but you have uncommitted work and don't want to stash.

## Solution

```bash
# Create a worktree for the hotfix — no stash needed
git worktree add ../hotfix-branch main
cd ../hotfix-branch
# fix the bug, commit, push
cd ../original-repo
git worktree remove ../hotfix-branch
```

## Why This Beats Stashing

- No risk of stash conflicts
- Both branches are checked out simultaneously
- You can diff between worktrees
- Claude Code and other AI tools can work on the worktree in isolation

## Gotcha

Worktrees share the same `.git` directory. Don't run destructive git
operations (reset --hard, clean -f) in one worktree without checking
the other.
