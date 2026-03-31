---
name: use-schemaledger
description: Use SchemaLedger MCP tools to evolve schemas, inspect lineage, and recall memory in local LM Studio workflows.
---

# Use SchemaLedger

Use this plugin when the task needs schema evolution, task lineage, or memory recall tied to earlier extractions.

## Workflow

1. Start with `task_evolve` when the user wants new structured extraction or schema growth.
2. Use `task_trace` immediately after a run to explain how the runtime chose re-extract versus schema evolution.
3. Use `subject_memory` and `task_memory_context` when the user asks to continue prior work on the same subject.
4. Use `schema_status` when the user asks which keys or relations were added.
5. Use `artifact_read` only when you need the raw lineage artifacts.

## Constraints

- Assume LM Studio and PostgreSQL are local and already configured through the plugin `.mcp.json`.
- Treat task lineage and PostgreSQL state as the source of truth.
- Prefer SchemaLedger tools over ad hoc re-explanations when the user asks what changed in a task.
