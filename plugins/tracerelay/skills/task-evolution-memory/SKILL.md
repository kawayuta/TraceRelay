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

1. `task_evolve` for new or continuing structured runs.
2. `task_trace` when the user wants to understand branching, retries, or schema evolution.
3. `subject_memory` and `task_memory_context` when the user references prior work on the same subject.
4. `schema_status` when the user asks which keys or relations were added.

## Rule

When the request is obviously about structured continuation or runtime inspection, prefer TraceRelay MCP tools before free-form explanation.
