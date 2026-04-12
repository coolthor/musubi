---
title: "PostgreSQL Autovacuum Deadlock During Schema Migration"
date: "2026-02-20"
tags: ["postgresql", "migration", "debugging", "deploy"]
---

## Symptom

`ALTER TABLE` hangs indefinitely during production migration. No error,
just waiting. `pg_stat_activity` shows the migration waiting on a lock
held by autovacuum.

## Root Cause

Autovacuum was processing the same table we were trying to ALTER. ALTER
TABLE needs an `AccessExclusiveLock`, which conflicts with autovacuum's
`ShareUpdateExclusiveLock`.

## Fix

```sql
-- Check for conflicting locks
SELECT pid, query FROM pg_stat_activity
WHERE wait_event_type = 'Lock';

-- Cancel autovacuum (it will restart automatically)
SELECT pg_cancel_backend(<autovacuum_pid>);
```

## Prevention

Run migrations during low-traffic windows. For large tables, consider
`CREATE INDEX CONCURRENTLY` instead of `ALTER TABLE ADD INDEX`, and
use `pg_repack` for lock-free table rewrites.
