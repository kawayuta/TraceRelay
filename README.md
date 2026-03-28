# SchemaLedger

Task-first, self-evolving schema runtime for local LLM workflows.

SchemaLedger is a local-first system that lets an LLM:

- interpret a task,
- decide the schema family,
- generate or reuse a schema,
- extract structured information,
- detect when the schema is insufficient,
- add new keys and relations,
- re-run extraction until the task is filled or the loop limit is reached.

Every step is persisted as lineage, projected into PostgreSQL, browsable in Flask, and exposed through MCP.

## What Makes It Strong

- Schema does not have to be fixed up front. The runtime can expand fields and relations during the task.
- The runtime is traceable. Interpretation, extraction, coverage, schema gaps, schema candidates, reviews, and final status are all persisted as artifacts.
- Memory is built into the same runtime, not bolted on separately. Prior tasks, subject memory, profile memory, and extraction snapshots can be recalled into later tasks.
- The same core logic backs Web, PostgreSQL, and MCP. You are not maintaining three different products with drift.
- It runs local-first with LM Studio, PostgreSQL, and FastMCP. That is useful when privacy, controllability, and inspectability matter more than closed hosted pipelines.
- The active runtime is LLM-first. There is no heuristic family fallback in the execution path.

## Why It Is Better Than Static Extraction

- Static extractors break when the requested structure changes. SchemaLedger can add keys and relations as the task evolves.
- Ordinary structured extraction returns a payload. SchemaLedger returns a payload plus the reasoning trace that explains why the structure changed.
- Plain vector memory helps recall facts. SchemaLedger ties memory to task lineage, schema versions, and coverage outcomes.
- Most tool wrappers hide failures. SchemaLedger records failures as first-class artifacts so you can inspect them in Web and MCP.

## Current Working Stack

- LLM runtime: LM Studio
- Structured extraction: `POST /v1/chat/completions`
- Embeddings: LM Studio `/v1/embeddings`
- Artifact store: JSONL
- Projection: PostgreSQL
- Web: Flask
- MCP: official Python `FastMCP`

Live-verified in this repository:

- PostgreSQL default DSN: `postgresql://postgres:postgres@127.0.0.1:55432/schemaledger_fresh`
- MCP transport: `sse` on `127.0.0.1:5063`
- Web UI: `127.0.0.1:5080`
- LM Studio model used in live runs: `qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine`
- LM Studio embedding model used in live runs: `text-embedding-nomic-embed-text-v1.5`

## Public Docs

- [Public Overview](./docs/PUBLIC_OVERVIEW.md)
- [Architecture](./docs/ARCHITECTURE.md)

## Core Flow

```mermaid
flowchart TD
    A[Prompt] --> B[Prompt Memory Recall]
    B --> C[LLM Task Interpretation]
    C --> D[Subject Memory Recall]
    D --> E{Existing Schema?}
    E -->|No| F[LLM Initial Schema]
    E -->|Yes| G[Reuse Latest Schema]
    F --> H[LLM Extraction]
    G --> H
    H --> I[Coverage Evaluation]
    I -->|Complete| J[Persist Artifacts]
    I -->|Missing Values| K[Re-extract]
    K --> H
    I -->|Missing Structure| L[LLM Schema Evolution]
    L --> M[Apply New Schema Version]
    M --> H
    J --> N[PostgreSQL Projection]
    N --> O[Flask UI]
    N --> P[MCP Tools and Resources]
    J --> Q[Memory Documents and Profiles]
```

## Execution Tree

```text
Task Run
├─ Prompt
│  ├─ raw prompt
│  ├─ locale
│  └─ caller / user_id
├─ Memory Recall
│  ├─ user profile memory
│  ├─ prior prompt memories
│  └─ prior related tasks
├─ Interpretation
│  ├─ intent
│  ├─ resolved_subject
│  ├─ family
│  ├─ requested_fields
│  └─ requested_relations
├─ Subject Recall
│  ├─ subject memory
│  ├─ task memory context
│  └─ prior extraction snapshots
├─ Schema
│  ├─ latest schema reuse
│  └─ or LLM-generated initial schema
├─ Extraction Loop
│  ├─ extraction attempt
│  ├─ coverage report
│  ├─ re-extract if values are missing
│  └─ evolve schema if structure is missing
├─ Persistence
│  ├─ artifact lineage in JSONL
│  ├─ memory documents
│  ├─ user profiles
│  └─ PostgreSQL projection
└─ Surfaces
   ├─ Flask task trace and memory UI
   ├─ MCP tools / resources / prompts
   └─ repository and API access
```

## Quick Start

### 1. Install Dependencies

```bash
uv sync
```

### 2. Start PostgreSQL

```bash
docker compose up -d
```

This starts PostgreSQL 16 on `127.0.0.1:55432` and creates the `schemaledger_fresh` database.

### 3. Set LM Studio Environment

```bash
export SCHEMALEDGER_LM_STUDIO_BASE_URL=http://127.0.0.1:1234
export SCHEMALEDGER_LM_STUDIO_MODEL=qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine
export SCHEMALEDGER_LM_STUDIO_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
```

### 4. Start the Web UI

```bash
uv run python -m schemaledger.web.server --host 127.0.0.1 --port 5080
```

Open:

- `http://127.0.0.1:5080/tasks`
- `http://127.0.0.1:5080/memory`

### 5. Start the MCP Server

```bash
uv run python -m schemaledger.mcp \
  --transport sse \
  --workspace ./workspace \
  --host 127.0.0.1 \
  --port 5063
```

This exposes the live MCP server on:

- `http://127.0.0.1:5063/sse`

## LM Studio Setup

### LM Studio Chat

The Chat UI path is live-verified.

Use this `mcp.json` entry:

```json
{
  "mcpServers": {
    "schemaledger": {
      "url": "http://127.0.0.1:5063/sse"
    }
  }
}
```

In LM Studio Chat, you can then ask for things like:

- `Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して`
- `ASPIヘリウムプロジェクトのスキーマを進化させて`
- `前回のGoogleの調査結果を踏まえて、事業セグメントと主要リスクを深掘りして`

### LM Studio API

The native LM Studio REST chat endpoint is:

- `POST /api/v1/chat`

The OpenAI-compatible structured-output endpoint is:

- `POST /v1/chat/completions`

Important: Chat UI MCP usage is verified. API-side MCP usage may require LM Studio plugin permission settings depending on your local server configuration.

## Public Surfaces

### Flask Pages

- `/tasks` - task list
- `/tasks/<task_id>` - flowchart and decision trace
- `/memory` - memory dashboard
- `/memory/profile/<profile_id>` - profile memory
- `/memory/subjects/<subject>` - subject memory
- `/memory/tasks/<task_id>` - task memory context

### Flask APIs

- `/api/tasks`
- `/api/tasks/<task_id>`
- `/api/tasks/<task_id>/coverage`
- `/api/tasks/<task_id>/schema`
- `/api/tasks/<task_id>/events`
- `/api/tasks/<task_id>/trace`
- `/api/memory/search?q=<query>`
- `/api/memory/profile`
- `/api/memory/subjects/<subject>`
- `/api/memory/tasks/<task_id>`

### MCP Tools

- `task_evolve`
- `task_trace`
- `schema_status`
- `schema_apply`
- `artifact_read`
- `artifact_search`
- `memory_search`
- `memory_profile`
- `subject_memory`
- `task_memory_context`

### MCP Resources

- `schemaledger://tasks`
- `schemaledger://tasks/{task_id}`
- `schemaledger://tasks/{task_id}/coverage`
- `schemaledger://tasks/{task_id}/schema`
- `schemaledger://tasks/{task_id}/events`
- `schemaledger://tasks/{task_id}/trace`
- `schemaledger://memory/profile`
- `schemaledger://memory/profile/{profile_id}`
- `schemaledger://memory/subjects/{subject}`
- `schemaledger://memory/tasks/{task_id}`
- `schemaledger://memory/search/{query}`

## Memory Model

SchemaLedger currently supports:

- vector-style search over prior tasks and learned facts,
- per-profile memory,
- subject memory,
- task memory context,
- automatic retrieval of prior extraction results into later tasks,
- subject-level recall such as “what did we learn about ASPI last time?”.

The active embedding backend is LM Studio embeddings when available. Offline fallback remains available for development, but live runs use real embeddings.

## Persistence Model

The system persists:

- task prompts,
- task interpretations,
- schema versions and references,
- extractions,
- coverage reports,
- schema gaps,
- schema requirements,
- schema candidates,
- reviews,
- task events,
- task runs,
- memory documents,
- task memory contexts,
- user profiles.

The JSONL artifact store is the write-ahead source of truth. PostgreSQL is the query and browse projection.

## Example Outcome

A live-verified Google run in this workspace produced:

- `resolved_subject=Google`
- `family=organization`
- `status=success`
- `reason=complete`
- `schema_version=2`
- `extraction_attempts=2`

It is visible through:

- Web task detail
- Web memory search
- PostgreSQL projection
- MCP `memory_search("Google")`

## Development

Run the test suite:

```bash
env PYTHONNOUSERSITE=1 uv run pytest -q
```

Current passing status in this workspace: `27 passed`.

## Status

This repository is no longer just a plan bundle. It contains a working runtime slice with:

- live LM Studio integration,
- schema evolution loops,
- JSONL persistence,
- PostgreSQL projection,
- Flask trace and memory UI,
- FastMCP server,
- live memory retrieval over embeddings.

It is still an experimental local system, but it is already useful as a transparent, inspectable, self-evolving structured research runtime.
