# SchemaLedger 2.0.0rc3 Implementation Plan

This bundle contains the file-level implementation plan for the next RC.

The workspace now also includes a task-first runtime slice that implements:
- LLM-only prompt interpretation into structured task semantics,
- LLM-selected family generation without heuristic fallback,
- LLM-only extraction against the active schema,
- versioned schema persistence with additive schema evolution,
- automatic schema apply + re-extraction loops until the task is filled or the loop limit is reached.

The workspace also includes:
- LM Studio HTTP integration for task interpretation and extraction,
- a JSONL-backed persistent artifact store,
- PostgreSQL projection SQL plus reindex helpers,
- Flask task APIs over the persisted task lineage,
- a real FastMCP server surface for tools, resources, and prompts.

Local development is managed through `uv` with dependencies declared in `pyproject.toml`.
Runtime artifact, task, schema, and review identifiers are UUID-backed so multiple workspaces
can project into the same PostgreSQL database without `task_id` or `artifact_id` collisions.
PostgreSQL browse reads from an exact-match `task_artifact` projection instead of relying on
`task_id` prefixes or lexicographic ordering assumptions.
The default PostgreSQL DSN is `postgresql://postgres:postgres@127.0.0.1:55432/schemaledger_fresh`
unless `SCHEMALEDGER_POSTGRES_DSN` overrides it.

The MCP server runs from the official Python SDK (`mcp[cli]`) and can be started with:

```bash
uv run python -m schemaledger.mcp --transport streamable-http --workspace ./workspace
```

Goal: move from a prompt-first runtime that mostly routes prompts into existing conservative families
toward a task-first runtime that can:

1. interpret the prompt with LLM-native structured outputs,
2. propose family candidates instead of forcing a single heuristic family,
3. bootstrap missing families,
4. distinguish missing values from missing schema structure,
5. re-extract before evolving the schema when value coverage is the dominant issue,
6. evolve schemas only when fields or relations are actually missing,
7. project the whole task lineage into PostgreSQL and Flask browse/API,
8. expose the same runtime through MCP tools/resources/prompts.

This plan is derived from the recent live runs:
- "What kind of anime is Macross?" resolved correctly as `media_work`
- "Googleの事業内容について調査してほしい" resolved correctly only after semantics fixes
- policy / relationship / incident prompts still collapse into `document` or `organization`
- schema-evolution-required prompts currently return `new_version = null` too often

Use this bundle as the implementation checklist for `2.0.0rc3`.
