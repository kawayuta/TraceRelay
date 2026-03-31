# SchemaLedger

[![Codex Plugin](https://img.shields.io/badge/Codex%20Plugin-Supported-0F172A)](#codex-plugin)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20Ready-D97706)](#claude-code)
[![MCP](https://img.shields.io/badge/MCP-FastMCP-2563EB)](#mcp-tools)
[![LM Studio](https://img.shields.io/badge/LM%20Studio-Connected-10B981)](#lm-studio-setup)
[![Ollama](https://img.shields.io/badge/Ollama-Supported-111827)](#ollama-setup)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Projected-336791?logo=postgresql&logoColor=white)](#current-working-stack)
[![Flask UI](https://img.shields.io/badge/Flask-Trace%20UI-000000?logo=flask&logoColor=white)](#public-surfaces)

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
- It runs local-first with LM Studio or Ollama, PostgreSQL, and FastMCP. That is useful when privacy, controllability, and inspectability matter more than closed hosted pipelines.
- The active runtime is LLM-first. There is no heuristic family fallback in the execution path.

## Why It Is Better Than Static Extraction

- Static extractors break when the requested structure changes. SchemaLedger can add keys and relations as the task evolves.
- Ordinary structured extraction returns a payload. SchemaLedger returns a payload plus the reasoning trace that explains why the structure changed.
- Plain vector memory helps recall facts. SchemaLedger ties memory to task lineage, schema versions, and coverage outcomes.
- Most tool wrappers hide failures. SchemaLedger records failures as first-class artifacts so you can inspect them in Web and MCP.

## Current Working Stack

- LLM runtime: LM Studio or Ollama
- Structured extraction: LM Studio `POST /v1/chat/completions` or Ollama `POST /api/chat`
- Embeddings: LM Studio `POST /v1/embeddings` or Ollama `POST /api/embed`
- Artifact store: JSONL
- Projection: PostgreSQL
- Web: Flask
- MCP: official Python `FastMCP`

Live-verified in this repository:

- PostgreSQL default DSN: `postgresql://postgres:postgres@127.0.0.1:55432/schemaledger_fresh`
- Docker Compose MCP: `sse` on `127.0.0.1:5064`
- Web UI: `127.0.0.1:5080`
- LM Studio model used in live runs: `qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine`
- LM Studio embedding model used in live runs: `text-embedding-nomic-embed-text-v1.5`
- Ollama backend: supported through `SCHEMALEDGER_LLM_PROVIDER=ollama`

## Public Docs

- [Public Overview](./docs/PUBLIC_OVERVIEW.md)
- [Architecture](./docs/ARCHITECTURE.md)

## Codex Plugin

SchemaLedger now ships as a repo-local Codex plugin as well.

- Plugin root: `./plugins/schemaledger`
- Manifest: `./plugins/schemaledger/.codex-plugin/plugin.json`
- MCP config: `./plugins/schemaledger/.mcp.json`
- Marketplace entry: `./.agents/plugins/marketplace.json`

The plugin uses repo-local stdio MCP, not a separate hosted service. Codex can launch SchemaLedger directly through:

```bash
PYTHONPATH=../../src:../.. uv run --project ../.. python -m schemaledger.mcp \
  --workspace ../../workspace \
  --dsn postgresql://postgres:postgres@127.0.0.1:55432/schemaledger_fresh
```

with LM Studio and PostgreSQL injected through plugin-local environment variables. The same plugin config can be switched to Ollama by changing `SCHEMALEDGER_LLM_PROVIDER`, `SCHEMALEDGER_OLLAMA_MODEL`, and optional embedding env vars. For the main app stack, the default runtime path is still `docker compose`.

This repo already includes the local marketplace entry Codex expects:

- `./plugins/schemaledger/.codex-plugin/plugin.json`
- `./plugins/schemaledger/.mcp.json`
- `./.agents/plugins/marketplace.json`

To install the same plugin home-locally for Codex across repositories:

```bash
bash ./scripts/install_codex_plugin.sh
```

That creates:

- `~/plugins/schemaledger`
- `~/.agents/plugins/marketplace.json`

## Claude Code

SchemaLedger also supports Claude Code through MCP.

- Default Compose endpoint: `http://127.0.0.1:5064/sse`

With `docker compose up -d --build postgres web mcp` running, you can either:

- add a project-scoped root `.mcp.json`
- or install `schemaledger` into Claude Code user scope

For a user-scoped Claude Code install across repositories:

```bash
bash ./scripts/install_claude_code_mcp.sh
```

Manual equivalent:

```bash
claude mcp add --transport sse --scope user schemaledger http://127.0.0.1:5064/sse
```

That uses the official Claude Code CLI flow and registers:

- name: `schemaledger`
- transport: `sse`
- url: `http://127.0.0.1:5064/sse`

Useful commands:

```bash
claude mcp list
claude mcp get schemaledger
claude mcp remove schemaledger
```

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

### 1. Choose An LLM Backend

SchemaLedger now supports either LM Studio or Ollama for the MCP/runtime backend.

#### Option A. LM Studio

Run LM Studio locally on `http://127.0.0.1:1234` with:

- chat model: `qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine`
- embedding model: `text-embedding-nomic-embed-text-v1.5`

If you use custom values, export them before starting Compose:

```bash
export SCHEMALEDGER_LM_STUDIO_BASE_URL=http://127.0.0.1:1234
export SCHEMALEDGER_LM_STUDIO_MODEL=qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine
export SCHEMALEDGER_LM_STUDIO_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
```

#### Option B. Ollama

Run Ollama locally on `http://127.0.0.1:11434`, make sure your selected chat and embedding models are already available, then export:

```bash
export SCHEMALEDGER_LLM_PROVIDER=ollama
export SCHEMALEDGER_EMBEDDING_PROVIDER=ollama
export SCHEMALEDGER_OLLAMA_BASE_URL=http://127.0.0.1:11434
export SCHEMALEDGER_OLLAMA_MODEL=qwen3:latest
export SCHEMALEDGER_OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest
```

If you do not set `SCHEMALEDGER_EMBEDDING_PROVIDER`, it follows the active LLM provider by default.

### 2. Start PostgreSQL, Flask, And MCP With Docker Compose

```bash
docker compose up -d --build postgres web mcp
```

This starts:

- PostgreSQL 16 on `127.0.0.1:55432`
- Flask Web UI on `http://127.0.0.1:5080`
- MCP SSE on `http://127.0.0.1:5064/sse`

The web and MCP containers apply the SchemaLedger PostgreSQL schema on boot and reindex the local `./workspace/artifacts.jsonl` file if it exists.

### 3. Check Container Status

```bash
docker compose ps
```

### 4. Tail Web And MCP Logs

```bash
docker compose logs -f web mcp
```

### 5. Open The Web UI

Open:

- `http://127.0.0.1:5080/tasks`
- `http://127.0.0.1:5080/memory`

### 6. Connect LM Studio To The Compose MCP Server

Use this `mcp.json` entry:

```json
{
  "mcpServers": {
    "schemaledger": {
      "url": "http://127.0.0.1:5064/sse"
    }
  }
}
```

### 7. Connect Claude Code To The Compose MCP Server

Project-scoped support uses a root `.mcp.json` like this:

```json
{
  "mcpServers": {
    "schemaledger": {
      "type": "sse",
      "url": "${SCHEMALEDGER_CLAUDE_MCP_URL:-http://127.0.0.1:5064/sse}"
    }
  }
}
```

For cross-project user scope, run:

```bash
bash ./scripts/install_claude_code_mcp.sh
```

## Operations

```bash
docker compose logs -f web mcp
```

```bash
docker compose restart web mcp
```

```bash
docker compose down
```

```bash
docker compose down -v
```

Use `down -v` only when you intentionally want to drop the PostgreSQL volume as well.

## CLI

The short CLI name is `slg`.

- Correct: `slg`
- Not used: `sgl`

The containers use `slg` internally. If you need to invoke it manually in the docker-first workflow:

```bash
docker compose exec web slg db apply-schema --workspace /app/workspace --reindex
docker compose exec web slg --help
docker compose exec mcp slg --help
```

## LM Studio Setup

### LM Studio Chat

The Chat UI path is live-verified.

```json
{
  "mcpServers": {
    "schemaledger": {
      "url": "http://127.0.0.1:5064/sse"
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

## Ollama Setup

SchemaLedger supports Ollama as the runtime/backend behind MCP.

- chat backend: `POST /api/chat`
- embedding backend: `POST /api/embed`
- provider switch: `SCHEMALEDGER_LLM_PROVIDER=ollama`
- optional explicit embedding switch: `SCHEMALEDGER_EMBEDDING_PROVIDER=ollama`

With docker compose:

```bash
export SCHEMALEDGER_LLM_PROVIDER=ollama
export SCHEMALEDGER_EMBEDDING_PROVIDER=ollama
export SCHEMALEDGER_OLLAMA_BASE_URL=http://127.0.0.1:11434
export SCHEMALEDGER_OLLAMA_MODEL=qwen3:latest
export SCHEMALEDGER_OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest

docker compose up -d --build postgres web mcp
```

If you want LM Studio for chat but Ollama for embeddings, set only:

```bash
export SCHEMALEDGER_EMBEDDING_PROVIDER=ollama
export SCHEMALEDGER_OLLAMA_BASE_URL=http://127.0.0.1:11434
export SCHEMALEDGER_OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest
```

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

The active embedding backend can be LM Studio or Ollama. Offline hash fallback remains available for development when no live embedding provider is configured.

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

Current passing status in this workspace: `44 passed`.

## Status

This repository is no longer just a plan bundle. It contains a working runtime slice with:

- live LM Studio integration,
- Ollama-compatible MCP/runtime backend,
- schema evolution loops,
- JSONL persistence,
- PostgreSQL projection,
- Flask trace and memory UI,
- FastMCP server,
- live memory retrieval over embeddings.

It is still an experimental local system, but it is already useful as a transparent, inspectable, self-evolving structured research runtime.
