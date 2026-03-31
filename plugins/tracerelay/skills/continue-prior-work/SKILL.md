---
name: continue-prior-work
description: Use TraceRelay when the user wants to continue earlier research, analysis, or investigation without starting from scratch.
---

# Continue Prior Work

Use this skill when the request sounds like:

- continue this investigation
- pick up where we left off
- use what we learned last time
- don't start from scratch
- continue the company, policy, incident, or relationship analysis

## Preferred Tool Order

1. `continue_prior_work`
2. `task_trace`
3. `schema_status`
4. `artifact_read`

## Rule

If the user clearly expects continuity, prefer `continue_prior_work` before free-form reasoning.
