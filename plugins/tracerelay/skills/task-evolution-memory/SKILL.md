---
name: task-evolution-memory
description: Route ongoing research, prior-work continuation, schema drift inspection, and memory-backed follow-up tasks into TraceRelay automatically.
---

# Task Evolution And Memory

Use this skill for requests that sound like:

- "continue what we learned about ..."
- "structure this research"
- "pick up where we left off"
- "show why the last run retried"
- "reuse prior memory"
- "inspect schema changes"
- "use what we already know"
- "organize this subject before searching again"

## Preferred Tool Order

1. `structure_subject` for new structured runs or schema growth.
2. `continue_prior_work` when the user references prior work on the same subject.
3. `inspect_latest_changes` when the user wants to understand retries or schema evolution.
4. `plan_next_step` before any generic search or external action.
5. `analyze_information_gaps` to confirm whether the current gap is values or structure.
6. `prepare_search_queries` when you need grounded search terms instead of broad guesses.
7. `task_trace` when the user wants the full branching view.
8. `schema_status` when the user asks which keys or relations were added.

## Rule

When the request is obviously about structured continuation or runtime inspection, prefer TraceRelay MCP tools before free-form explanation.
Use TraceRelay's gap analysis and query planning before web search so learned facts and missing slots shape the next action.
