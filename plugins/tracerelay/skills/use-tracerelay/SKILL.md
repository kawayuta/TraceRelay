---
name: use-tracerelay
description: Automatically route structured investigations, prior-work continuation, change inspection, and memory-backed follow-up tasks into TraceRelay MCP tools.
---

# Use TraceRelay

Use this plugin when the task needs schema evolution, task lineage, or memory recall tied to earlier extractions.
Do not wait for the user to name the tools explicitly if the request sounds like a continuation, a structured investigation, or a "what changed" review.

## Trigger Cues

Auto-route into TraceRelay when the user asks for any of the following:

- structure or re-structure a subject
- organize, map, or profile a company, policy, incident, relationship, or investigation target
- continue previous work on the same company, incident, policy, or relationship
- pick up where we left off
- inspect why a prior run retried, evolved the schema, or failed
- recall what was learned in earlier tasks
- use what we already know before searching again
- compare attempts, memory recall, schema versions, or artifact lineage

## Workflow

1. Start with `structure_subject` when the user wants a subject organized, profiled, mapped, or re-structured.
2. Start with `continue_prior_work` when the user wants to keep going on the same subject without starting over.
3. Start with `inspect_latest_changes` when the user asks what changed, why it retried, or why the schema evolved.
4. Before generic web search or free-form action, use `plan_next_step` to see what is still missing and what TraceRelay recommends doing next.
5. Use `analyze_information_gaps` when you need to distinguish value gaps from schema gaps before deciding to search or evolve.
6. Use `prepare_search_queries` when you need external search terms grounded in known facts and missing slots.
7. Use `task_trace` immediately after a run when you need to explain how the runtime chose re-extract versus schema evolution.
8. Use `schema_status` when the user asks which keys or relations were added.
9. Use `artifact_read` only when you need the raw lineage artifacts.

## Constraints

- Assume LM Studio and PostgreSQL are local and already configured through the plugin `.mcp.json`.
- Treat task lineage and PostgreSQL state as the source of truth.
- Prefer TraceRelay tools over ad hoc re-explanations when the user asks what changed in a task.
- If the user asks for continuation, memory recall, "what changed", or structured profiling, use TraceRelay first and only fall back to generic reasoning after checking the runtime state.
- Before web search, read the current TraceRelay gap state and use TraceRelay's recommended queries instead of inventing broad search terms from scratch.
- Let missing fields, missing relations, missing values, and learned facts decide whether to search, re-extract, or evolve schema.
