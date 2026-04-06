---
name: continue-prior-work
description: Use TraceRelay when the user wants to continue earlier research, analysis, investigation, or follow-up work without starting from scratch.
---

# Continue Prior Work

Use this skill when the request sounds like:

- continue this investigation
- pick up where we left off
- use what we learned last time
- don't start from scratch
- keep going on this subject
- continue the earlier analysis
- use the previous findings before searching again
- continue the company, policy, incident, or relationship analysis

## Preferred Tool Order

1. `continue_prior_work`
2. `plan_next_step`
3. `prepare_search_queries`
4. `task_trace`
5. `schema_status`
6. `artifact_read`

## Rule

If the user clearly expects continuity, prefer `continue_prior_work` before free-form reasoning.
If `continue_prior_work` returns `pending: true`, poll `task_status` with the returned `task_id` or `job_id` instead of restarting the run.
Before generic search, use `plan_next_step` and `prepare_search_queries` so the next move is driven by stored facts and open gaps.
