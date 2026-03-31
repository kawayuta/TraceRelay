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
2. `analyze_information_gaps`
3. `plan_next_step`
4. `task_trace`
5. `schema_status`
6. `artifact_read`

## Rule

Prefer runtime evidence and lineage over a guessed narrative.
If the user wants to know what to do next, use `plan_next_step` instead of inventing a free-form action plan.
