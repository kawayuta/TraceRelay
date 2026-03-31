---
name: structure-this
description: Use TraceRelay when the user wants a subject organized into structured fields, relations, or a reusable profile before further search or reasoning.
---

# Structure This

Use this skill when the request sounds like:

- structure this
- organize this subject
- build a profile for this company
- map the facts and relationships
- turn this research into structured data

## Preferred Tool Order

1. `structure_subject`
2. `plan_next_step`
3. `analyze_information_gaps`
4. `schema_status`
5. `task_trace`

## Rule

When the user asks for structured understanding rather than a plain answer, use `structure_subject` first.
If the user then wants external search or follow-up work, use `plan_next_step` before inventing new queries.
