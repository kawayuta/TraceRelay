# TraceRelay

[![Codex Plugin](https://img.shields.io/badge/Codex%20Plugin-Supported-7C3AED)](#plugin-support)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code%20Plugin-Supported-7C3AED)](#plugin-support)
[![MCP Server](https://img.shields.io/badge/MCP%20Server-Supported-2563EB)](#integration-model)
[![LM Studio Client](https://img.shields.io/badge/LM%20Studio%20Client-Supported-10B981)](#lm-studio-support)
[![Ollama Backend](https://img.shields.io/badge/Ollama%20Backend-Supported-10B981)](#backend-support)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supported-336791?logo=postgresql&logoColor=white)](#current-working-stack)
[![Flask UI](https://img.shields.io/badge/Flask%20UI-Supported-F59E0B?logo=flask&logoColor=white)](#public-surfaces)

Task-first, self-evolving schema runtime for local LLM workflows.

TraceRelay is a local-first system that lets an LLM:

- interpret a task,
- decide the schema family,
- generate or reuse a schema,
- extract structured information,
- detect when the schema is insufficient,
- add new keys and relations,
- re-run extraction until the task is filled or the loop limit is reached.

Every step is persisted as lineage, projected into PostgreSQL, browsable in Flask, and exposed through MCP.

## Benchmark Snapshot

### Normalized Comparison

![Benchmark Snapshot](./docs/images/benchmark-snapshot.svg)

### What These Charts Are Meant To Show

- The benchmark is shown as one normalized profile so the comparison reads as an overall product shape, not five disconnected charts.
- Higher is better across all axes in this view.
- Query Quality reflects the inverse of broad or malformed query rate.
- Claim Support reflects the inverse of unsupported claim rate.
- Token Efficiency reflects lower average tokens per successful task.
- Long-Task Recall reflects the inverse of long-task context forgetting rate.
- TraceRelay should win when the task depends on evolving structure, not just one-shot prompting.
- Schema-aware memory recall should reduce broad search, malformed search, and repeated search loops.
- Gap-directed retries should lower wasted token spend relative to agents that have to rediscover task structure each turn.
- Context-scoped memory and relay-style structured outputs should reduce long-task forgetting as the task gets deeper and more iterative.
- Traceable schema evolution and memory formation should reduce unsupported claims by making missing facts and missing structure explicit.

## Quick Start

```bash
cp .env.example .env
docker compose up -d --build postgres web mcp
docker compose logs -f web mcp
```

Then open:

- `http://127.0.0.1:5080/tasks`
- `http://127.0.0.1:5080/memory`

Default `.env.example` targets LM Studio. If you want Ollama or external embedding APIs, edit `.env` first. Full setup variants are in [Setup Details](#setup-details).

## What Makes It Strong

- Self-evolving structure: TraceRelay starts with the schema you need now, then adds fields and relations only when the task proves they are required.
- Context-scoped memory: daily work, deep research, and coding investigations do not get dumped into one noisy global memory pool.
- Better search inputs: later searches are driven by missing fields, missing relations, evolved schema versions, and prior extracted facts.
- Relay memory across long tasks: each extraction round leaves behind structured outputs that the next round can reuse.
- Shared memory across agents: Codex, Claude Code, LM Studio, and MCP clients can work against the same live memory and lineage instead of keeping isolated assistant-local recall.
- Traceable decisions: interpretation, extraction, coverage, schema evolution, retries, and failures are persisted as lineage.
- Lower waste, fewer hallucinations: gap-directed retries reduce token burn, redundant prompting, malformed search, and unsupported guesses.
- Operational surfaces: the same runtime is exposed through Web, PostgreSQL, MCP, Codex, Claude Code, and LM Studio.
- Flexible deployment control: run locally with LM Studio or Ollama, use OpenAI-compatible APIs or Gemini APIs when needed, keep data in PostgreSQL, inspect everything in Flask, and avoid locking the runtime to a single hosted pipeline.

## Why It Is Better Than Static Extraction

- Fixed schema vs adaptive schema: static extraction breaks when the requested structure changes; TraceRelay evolves the schema in the loop.
- One-shot payload vs iterative completion: static extraction gives you one pass; TraceRelay retries against the latest schema until the task is filled or the loop ends.
- Generic recall vs task-aware memory: plain vector memory recalls nearby text; TraceRelay recalls subject, profile, task, and schema-aware context.
- Opaque output vs inspectable lineage: static extraction returns a result; TraceRelay shows how the result was formed, changed, and validated.
- Hidden failure vs operational trace: most wrappers hide search mistakes and retry failures; TraceRelay records them as first-class artifacts in Web and MCP.

## Current Working Stack

- MCP server: official Python `FastMCP`
- Plugin targets: Codex, Claude Code
- MCP client support: LM Studio
- LLM runtime: LM Studio, Ollama, OpenAI, or Gemini
- Structured extraction: LM Studio `POST /v1/chat/completions`, Ollama `POST /api/chat`, OpenAI `POST /v1/chat/completions`, or Gemini `models.generateContent`
- Embeddings: LM Studio `POST /v1/embeddings`, Ollama `POST /api/embed`, OpenAI `POST /v1/embeddings`, or Gemini `models.embedContent`
- Artifact store: JSONL
- Projection: PostgreSQL
- Web: Flask

Live-verified in this repository:

- PostgreSQL default DSN: `postgresql://postgres:postgres@127.0.0.1:55432/tracerelay_fresh`
- Docker Compose MCP: HTTP `/mcp` on `127.0.0.1:5064`
- Web UI: `127.0.0.1:5080`
- LM Studio model used in live runs: `qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine`
- LM Studio embedding model used in live runs: `text-embedding-nomic-embed-text-v1.5`
- LLM backends: `lmstudio`, `ollama`, `openai`, `gemini`
- Embedding backends: `lmstudio`, `ollama`, `openai`, `gemini`, `hash`
- Configuration template: `.env.example`

## Public Docs

- [Public Overview](./docs/PUBLIC_OVERVIEW.md)
- [Architecture](./docs/ARCHITECTURE.md)

## Integration Model

- Codex and Claude Code use TraceRelay as plugins.
- LM Studio uses TraceRelay as an MCP client.
- Ollama is supported as a runtime and embedding backend, not as an MCP client in this repository.
- The MCP endpoint is always served by TraceRelay itself.

## Plugin Support

Codex and Claude Code are supported as plugins.
LM Studio is not a plugin target here. It connects to the running TraceRelay MCP server directly.
Plugin routing is more conservative than direct MCP use, so the plugin relies on TraceRelay-specific skills and MCP settings to decide when to auto-run tools.
Before using either plugin, start the docker stack so the shared MCP endpoint is live: `docker compose up -d --build postgres web mcp`.

### Codex

Run:

```bash
bash ./scripts/install_codex_plugin.sh
```

It creates:

- `~/plugins/tracerelay`
- `~/.agents/plugins/marketplace.json`

The installer reads `.env` automatically and bakes `TRACERELAY_PLUGIN_MCP_URL` into the generated plugin MCP config.
Codex expects the docker-compose MCP server to already be running and uses a dedicated plugin MCP config at `.codex-plugin/mcp.json`.
Rerun the installer after changing `.env` or plugin files so Codex picks up the latest TraceRelay behavior.

### Claude Code

Run:

```bash
bash ./scripts/install_claude_code_plugin.sh
```

It installs:

- local marketplace: `tracerelay-local`
- plugin: `tracerelay`

The installer refreshes the local `tracerelay` plugin state and is the safest way to apply `.env` or plugin changes.
Claude Code uses the root plugin `.mcp.json` in the official plugin layout and also expects the docker-compose MCP server to already be running.
If you change the plugin MCP URL, rerun the installer.

### Prompts That Route Well Through Plugins

These phrases tend to trigger TraceRelay tools reliably in plugin mode:

- "Continue what we learned about ASPI and extend the schema if needed."
- "Structure this subject and keep the TraceRelay lineage visible."
- "Use prior memory for Google and explain why the last run retried."
- "Inspect the latest TraceRelay task, schema changes, and recalled memory."

## Core Flow

```mermaid
flowchart TD
    subgraph Entry["Entry Paths"]
      A[Codex Plugin]
      B[Claude Code Plugin]
      C[LM Studio MCP Client]
      D[Direct Python Runtime]
      E[Flask UI and API]
    end

    A --> F[MCP HTTP client]
    B --> F
    C --> G[MCP HTTP client]
    F --> H[MCP server at slash mcp]
    G --> H
    D --> I[TaskRuntime.run_task]
    H -->|task_evolve| I

    I --> J[Prompt Memory Recall]
    J --> K[LLM Task Interpretation]
    K --> L[Subject Memory Recall]
    L --> M{Existing Schema?}
    M -->|No| N[LLM Initial Schema]
    M -->|Yes| O[Reuse Latest Schema]
    N --> P[LLM Extraction]
    O --> P
    P --> Q[Coverage Evaluation]
    Q -->|Missing Values| R[Re-extract]
    R --> P
    Q -->|Missing Structure| S[LLM Schema Evolution]
    S --> T[Apply New Schema Version]
    T --> P
    Q -->|Complete| U[Persist Artifact Lineage]

    V[LM Studio / Ollama / OpenAI / Gemini] --> K
    V --> N
    V --> P
    V --> S

    U --> W[Memory Documents, Task Contexts, User Profiles]
    U --> X[Project to PostgreSQL]
    X --> Y[Flask UI and API]
    X --> Z[MCP resources]
    E -->|read path| Y
    H -->|read path| Z
```

Notes:

- Codex and Claude Code enter through plugin-managed HTTP MCP.
- LM Studio enters through TraceRelay's MCP server over HTTP at `/mcp`.
- MCP `task_evolve` and direct Python usage both converge on the same `TaskRuntime`.
- Flask is a read surface over PostgreSQL projection, not a second runtime.
- Memory and lineage are shared across all of these surfaces once a run is persisted.

## Execution Tree

```text
TraceRelay Runtime
├─ Entry Paths
│  ├─ Codex plugin -> HTTP MCP
│  ├─ Claude Code plugin -> HTTP MCP
│  ├─ LM Studio -> HTTP MCP
│  └─ direct Python runtime
├─ Prompt
│  ├─ raw prompt
│  ├─ locale
│  └─ caller / user_id
├─ Prompt Recall
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
├─ Schema State
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
│  ├─ task memory contexts
│  ├─ user profiles
│  └─ PostgreSQL projection
└─ Shared Surfaces
   ├─ Flask task trace and memory UI
   ├─ MCP tools / resources / prompts
   ├─ PostgreSQL-backed repository and API access
   └─ live memory shared across agents and clients
```

## Setup Details

### 1. Create A Local `.env`

```bash
cp .env.example .env
```

`docker compose` reads `.env` automatically. The checked-in defaults target LM Studio for chat and embeddings.

### 2. Choose Your Runtime / Embedding Backend

Edit `.env` and pick one of these common setups.

#### Default: LM Studio For Both

Run LM Studio locally on `http://127.0.0.1:1234` with:

- chat model: `qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine`
- embedding model: `text-embedding-nomic-embed-text-v1.5`

```bash
TRACERELAY_LLM_PROVIDER=lmstudio
TRACERELAY_EMBEDDING_PROVIDER=
TRACERELAY_LM_STUDIO_BASE_URL=http://127.0.0.1:1234
TRACERELAY_LM_STUDIO_MODEL=qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine
TRACERELAY_LM_STUDIO_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
```

#### Ollama For Both

Run Ollama locally on `http://127.0.0.1:11434`, make sure your selected chat and embedding models are already available, then set:

```bash
TRACERELAY_LLM_PROVIDER=ollama
TRACERELAY_EMBEDDING_PROVIDER=ollama
TRACERELAY_OLLAMA_BASE_URL=http://127.0.0.1:11434
TRACERELAY_OLLAMA_MODEL=qwen3:latest
TRACERELAY_OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest
```

#### OpenAI For Structured Extraction And Embeddings

```bash
TRACERELAY_LLM_PROVIDER=openai
TRACERELAY_EMBEDDING_PROVIDER=openai
TRACERELAY_OPENAI_API_KEY=YOUR_OPENAI_API_KEY
TRACERELAY_OPENAI_MODEL=gpt-4.1-mini
TRACERELAY_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

#### Gemini For Structured Extraction And Embeddings

```bash
TRACERELAY_LLM_PROVIDER=gemini
TRACERELAY_EMBEDDING_PROVIDER=gemini
TRACERELAY_GEMINI_API_KEY=YOUR_GEMINI_API_KEY
TRACERELAY_GEMINI_MODEL=gemini-2.5-flash
TRACERELAY_GEMINI_EMBEDDING_MODEL=gemini-embedding-001
```

#### LM Studio Chat + OpenAI Embeddings

```bash
TRACERELAY_LLM_PROVIDER=lmstudio
TRACERELAY_EMBEDDING_PROVIDER=openai
TRACERELAY_LM_STUDIO_BASE_URL=http://127.0.0.1:1234
TRACERELAY_LM_STUDIO_MODEL=qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine
TRACERELAY_OPENAI_API_KEY=YOUR_OPENAI_API_KEY
TRACERELAY_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

#### LM Studio Chat + Gemini Embeddings

```bash
TRACERELAY_LLM_PROVIDER=lmstudio
TRACERELAY_EMBEDDING_PROVIDER=gemini
TRACERELAY_LM_STUDIO_BASE_URL=http://127.0.0.1:1234
TRACERELAY_LM_STUDIO_MODEL=qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine
TRACERELAY_GEMINI_API_KEY=YOUR_GEMINI_API_KEY
TRACERELAY_GEMINI_EMBEDDING_MODEL=gemini-embedding-001
```

If `TRACERELAY_EMBEDDING_PROVIDER` is empty, TraceRelay follows `TRACERELAY_LLM_PROVIDER`.

### 3. Start PostgreSQL, Flask, And MCP With Docker Compose

```bash
docker compose up -d --build postgres web mcp
```

This starts:

- PostgreSQL 16 on `127.0.0.1:55432`
- Flask Web UI on `http://127.0.0.1:5080`
- MCP HTTP on `http://127.0.0.1:5064/mcp`

The web and MCP containers apply the TraceRelay PostgreSQL schema on boot and reindex the local `./workspace/artifacts.jsonl` file if it exists.

### 4. Check Container Status

```bash
docker compose ps
```

### 5. Tail Web And MCP Logs

```bash
docker compose logs -f web mcp
```

### 6. Open The Web UI

Open:

- `http://127.0.0.1:5080/tasks`
- `http://127.0.0.1:5080/memory`

### 7. Connect LM Studio To The Compose MCP Server

LM Studio uses TraceRelay through MCP, not through a plugin install.

Use this `mcp.json` entry:

```json
{
  "mcpServers": {
    "TraceRelay": {
      "url": "http://127.0.0.1:5064/mcp"
    }
  }
}
```

### 8. Install The Claude Code Plugin

Claude Code support is provided as an official plugin install, separate from LM Studio's MCP connection.

Run:

```bash
bash ./scripts/install_claude_code_plugin.sh
```

This installs the `tracerelay` plugin from the local `tracerelay-local` marketplace.

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

The short CLI name is `trr`.

- Correct: `trr`
- Not used: `sgl`

The containers use `trr` internally. If you need to invoke it manually in the docker-first workflow:

```bash
docker compose exec web trr db apply-schema --workspace /app/workspace --reindex
docker compose exec web trr --help
docker compose exec mcp trr --help
```

## LM Studio Support

### LM Studio Chat

The Chat UI path is live-verified.

```json
{
  "mcpServers": {
    "TraceRelay": {
      "url": "http://127.0.0.1:5064/mcp"
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

## Backend Support

- LM Studio can act as both an MCP client and a local LLM / embedding backend.
- Ollama is supported as a local LLM / embedding backend.
- OpenAI is supported as a structured extraction and embedding backend.
- Gemini is supported as a structured extraction and embedding backend.

### Ollama

TraceRelay supports Ollama as the runtime/backend behind its own MCP server.

- chat backend: `POST /api/chat`
- embedding backend: `POST /api/embed`
- provider switch: `TRACERELAY_LLM_PROVIDER=ollama`
- optional explicit embedding switch: `TRACERELAY_EMBEDDING_PROVIDER=ollama`

With docker compose:

```bash
export TRACERELAY_LLM_PROVIDER=ollama
export TRACERELAY_EMBEDDING_PROVIDER=ollama
export TRACERELAY_OLLAMA_BASE_URL=http://127.0.0.1:11434
export TRACERELAY_OLLAMA_MODEL=qwen3:latest
export TRACERELAY_OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest

docker compose up -d --build postgres web mcp
```

If you want LM Studio for chat but Ollama for embeddings, set only:

```bash
export TRACERELAY_EMBEDDING_PROVIDER=ollama
export TRACERELAY_OLLAMA_BASE_URL=http://127.0.0.1:11434
export TRACERELAY_OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest
```

## Embedding Provider Setup

Embedding selection is fully env-driven.

- `TRACERELAY_EMBEDDING_PROVIDER=lmstudio`
- `TRACERELAY_EMBEDDING_PROVIDER=ollama`
- `TRACERELAY_EMBEDDING_PROVIDER=openai`
- `TRACERELAY_EMBEDDING_PROVIDER=gemini`
- `TRACERELAY_EMBEDDING_PROVIDER=hash`

If `TRACERELAY_EMBEDDING_PROVIDER` is unset, TraceRelay follows `TRACERELAY_LLM_PROVIDER` first, then falls back to whatever local backend is configured.

### OpenAI Embeddings

```bash
export TRACERELAY_EMBEDDING_PROVIDER=openai
export TRACERELAY_OPENAI_API_KEY=YOUR_OPENAI_API_KEY
export TRACERELAY_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
export TRACERELAY_OPENAI_BASE_URL=https://api.openai.com
```

### Gemini Embeddings

```bash
export TRACERELAY_EMBEDDING_PROVIDER=gemini
export TRACERELAY_GEMINI_API_KEY=YOUR_GEMINI_API_KEY
export TRACERELAY_GEMINI_EMBEDDING_MODEL=gemini-embedding-001
export TRACERELAY_GEMINI_BASE_URL=https://generativelanguage.googleapis.com
```

### Claude / Anthropic Note

`TRACERELAY_EMBEDDING_PROVIDER=claude` or `anthropic` is intentionally rejected. Anthropic does not currently expose a direct embeddings API, so TraceRelay fails fast instead of pretending to support it.

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

- `tracerelay://tasks`
- `tracerelay://tasks/{task_id}`
- `tracerelay://tasks/{task_id}/coverage`
- `tracerelay://tasks/{task_id}/schema`
- `tracerelay://tasks/{task_id}/events`
- `tracerelay://tasks/{task_id}/trace`
- `tracerelay://memory/profile`
- `tracerelay://memory/profile/{profile_id}`
- `tracerelay://memory/subjects/{subject}`
- `tracerelay://memory/tasks/{task_id}`
- `tracerelay://memory/search/{query}`

## Memory Model

TraceRelay currently supports:

- vector-style search over prior tasks and learned facts,
- per-profile memory,
- subject memory,
- task memory context,
- automatic retrieval of prior extraction results into later tasks,
- subject-level recall such as “what did we learn about ASPI last time?”.

The active embedding backend can be LM Studio, Ollama, OpenAI, Gemini, or the offline hash fallback.

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

A live-verified Google run produced:

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
