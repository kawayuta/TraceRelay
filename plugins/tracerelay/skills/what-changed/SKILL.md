---
name: what-changed
description: Use TraceRelay when the user asks what changed, why something retried, why structure evolved, or how the latest run differs from earlier attempts.
---

# What Changed

Use this skill when the request sounds like:

- what changed
- why did it retry
- why did the structure change
- what changed since the last run
- compare the latest attempt with the previous one

## Preferred Tool Order

1. `inspect_latest_changes`
2. `task_trace`
3. `schema_status`
4. `artifact_read`

## Rule

Prefer runtime evidence and lineage over a guessed narrative.
