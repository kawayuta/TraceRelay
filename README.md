# SchemaLedger

[![Codex Plugin](https://img.shields.io/badge/Codex%20Plugin-Supported-7C3AED)](#plugin-support)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code%20Plugin-Supported-7C3AED)](#plugin-support)
[![MCP Server](https://img.shields.io/badge/MCP%20Server-Supported-2563EB)](#integration-model)
[![LM Studio Client](https://img.shields.io/badge/LM%20Studio%20Client-Supported-10B981)](#lm-studio-support)
[![Ollama Backend](https://img.shields.io/badge/Ollama%20Backend-Supported-10B981)](#backend-support)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supported-336791?logo=postgresql&logoColor=white)](#current-working-stack)
[![Flask UI](https://img.shields.io/badge/Flask%20UI-Supported-F59E0B?logo=flask&logoColor=white)](#public-surfaces)

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

- Self-evolving structure: SchemaLedger starts with the schema you need now, then adds fields and relations only when the task proves they are required.
- Context-scoped memory: daily work, deep research, and coding investigations do not get dumped into one noisy global memory pool.
- Better search inputs: later searches are driven by missing fields, missing relations, evolved schema versions, and prior extracted facts.
- Relay memory across long tasks: each extraction round leaves behind structured outputs that the next round can reuse.
- Traceable decisions: interpretation, extraction, coverage, schema evolution, retries, and failures are persisted as lineage.
- Lower waste, fewer hallucinations: gap-directed retries reduce token burn, redundant prompting, malformed search, and unsupported guesses.
- Operational surfaces: the same runtime is exposed through Web, PostgreSQL, MCP, Codex, Claude Code, and LM Studio.
- Flexible deployment control: run locally with LM Studio or Ollama, use OpenAI-compatible APIs or Gemini APIs when needed, keep data in PostgreSQL, inspect everything in Flask, and avoid locking the runtime to a single hosted pipeline.

## Why It Is Better Than Static Extraction

- Fixed schema vs adaptive schema: static extraction breaks when the requested structure changes; SchemaLedger evolves the schema in the loop.
- One-shot payload vs iterative completion: static extraction gives you one pass; SchemaLedger retries against the latest schema until the task is filled or the loop ends.
- Generic recall vs task-aware memory: plain vector memory recalls nearby text; SchemaLedger recalls subject, profile, task, and schema-aware context.
- Opaque output vs inspectable lineage: static extraction returns a result; SchemaLedger shows how the result was formed, changed, and validated.
- Hidden failure vs operational trace: most wrappers hide search mistakes and retry failures; SchemaLedger records them as first-class artifacts in Web and MCP.

## Benchmark Snapshot

They show the comparison style that fits this product well and should be replaced with real evaluation data when a benchmark harness is ready.

### Task Success Rate

```text
Higher is better

SchemaLedger  [##########################################........] 84%
Claude Code   [#####################################.............] 74%
Codex         [###################################...............] 71%
```

### Broad Or Malformed Query Rate

```text
Lower is better

SchemaLedger  [######............................................] 12%
Claude Code   [############......................................] 24%
Codex         [##############....................................] 27%
```

### Unsupported Claim Rate

```text
Lower is better

SchemaLedger  [####..............................................]  8%
Claude Code   [########..........................................] 16%
Codex         [#########.........................................] 18%
```

### Average Tokens Per Successful Task

```text
Lower is better

SchemaLedger  [############################......................] 3800
Claude Code   [####################################..............] 4900
Codex         [######################################............] 5200
```

### Long-Task Context Forgetting Rate

```text
Lower is better

SchemaLedger  [#####.............................................] 10%
Claude Code   [###########.......................................] 22%
Codex         [#############.....................................] 26%
```

### What These Charts Are Meant To Show

- SchemaLedger should win when the task depends on evolving structure, not just one-shot prompting.
- Schema-aware memory recall should reduce broad search, malformed search, and repeated search loops.
- Gap-directed retries should lower wasted token spend relative to agents that have to rediscover task structure each turn.
- Context-scoped memory and relay-style structured outputs should reduce long-task forgetting as the task gets deeper and more iterative.
- Traceable schema evolution and memory formation should reduce unsupported claims by making missing facts and missing structure explicit.

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

- PostgreSQL default DSN: `postgresql://postgres:postgres@127.0.0.1:55432/schemaledger_fresh`
- Docker Compose MCP: `sse` on `127.0.0.1:5064`
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

- Codex and Claude Code use SchemaLedger as plugins.
- LM Studio uses SchemaLedger as an MCP client.
- Ollama is supported as a runtime and embedding backend, not as an MCP client in this repository.
- The MCP endpoint is always served by SchemaLedger itself.

## Plugin Support

Codex and Claude Code are supported as plugins.
LM Studio is not a plugin target here. It connects to the running SchemaLedger MCP server directly.

### Codex

Run:

```bash
bash ./scripts/install_codex_plugin.sh
```

It creates:

- `~/plugins/schemaledger`
- `~/.agents/plugins/marketplace.json`

### Claude Code

Run:

```bash
bash ./scripts/install_claude_code_plugin.sh
```

It installs:

- local marketplace: `schemaledger-local`
- plugin: `schemaledger`

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
SCHEMALEDGER_LLM_PROVIDER=lmstudio
SCHEMALEDGER_EMBEDDING_PROVIDER=
SCHEMALEDGER_LM_STUDIO_BASE_URL=http://127.0.0.1:1234
SCHEMALEDGER_LM_STUDIO_MODEL=qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine
SCHEMALEDGER_LM_STUDIO_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
```

#### Ollama For Both

Run Ollama locally on `http://127.0.0.1:11434`, make sure your selected chat and embedding models are already available, then set:

```bash
SCHEMALEDGER_LLM_PROVIDER=ollama
SCHEMALEDGER_EMBEDDING_PROVIDER=ollama
SCHEMALEDGER_OLLAMA_BASE_URL=http://127.0.0.1:11434
SCHEMALEDGER_OLLAMA_MODEL=qwen3:latest
SCHEMALEDGER_OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest
```

#### OpenAI For Structured Extraction And Embeddings

```bash
SCHEMALEDGER_LLM_PROVIDER=openai
SCHEMALEDGER_EMBEDDING_PROVIDER=openai
SCHEMALEDGER_OPENAI_API_KEY=YOUR_OPENAI_API_KEY
SCHEMALEDGER_OPENAI_MODEL=gpt-4.1-mini
SCHEMALEDGER_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

#### Gemini For Structured Extraction And Embeddings

```bash
SCHEMALEDGER_LLM_PROVIDER=gemini
SCHEMALEDGER_EMBEDDING_PROVIDER=gemini
SCHEMALEDGER_GEMINI_API_KEY=YOUR_GEMINI_API_KEY
SCHEMALEDGER_GEMINI_MODEL=gemini-2.5-flash
SCHEMALEDGER_GEMINI_EMBEDDING_MODEL=gemini-embedding-001
```

#### LM Studio Chat + OpenAI Embeddings

```bash
SCHEMALEDGER_LLM_PROVIDER=lmstudio
SCHEMALEDGER_EMBEDDING_PROVIDER=openai
SCHEMALEDGER_LM_STUDIO_BASE_URL=http://127.0.0.1:1234
SCHEMALEDGER_LM_STUDIO_MODEL=qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine
SCHEMALEDGER_OPENAI_API_KEY=YOUR_OPENAI_API_KEY
SCHEMALEDGER_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

#### LM Studio Chat + Gemini Embeddings

```bash
SCHEMALEDGER_LLM_PROVIDER=lmstudio
SCHEMALEDGER_EMBEDDING_PROVIDER=gemini
SCHEMALEDGER_LM_STUDIO_BASE_URL=http://127.0.0.1:1234
SCHEMALEDGER_LM_STUDIO_MODEL=qwen3.5-35b-a3b-uncensored-claude-opus-4.6-affine
SCHEMALEDGER_GEMINI_API_KEY=YOUR_GEMINI_API_KEY
SCHEMALEDGER_GEMINI_EMBEDDING_MODEL=gemini-embedding-001
```

If `SCHEMALEDGER_EMBEDDING_PROVIDER` is empty, SchemaLedger follows `SCHEMALEDGER_LLM_PROVIDER`.

### 3. Start PostgreSQL, Flask, And MCP With Docker Compose

```bash
docker compose up -d --build postgres web mcp
```

This starts:

- PostgreSQL 16 on `127.0.0.1:55432`
- Flask Web UI on `http://127.0.0.1:5080`
- MCP SSE on `http://127.0.0.1:5064/sse`

The web and MCP containers apply the SchemaLedger PostgreSQL schema on boot and reindex the local `./workspace/artifacts.jsonl` file if it exists.

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

LM Studio uses SchemaLedger through MCP, not through a plugin install.

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

### 8. Install The Claude Code Plugin

Claude Code support is provided as an official plugin install, separate from LM Studio's MCP connection.

Run:

```bash
bash ./scripts/install_claude_code_plugin.sh
```

This installs the `schemaledger` plugin from the local `schemaledger-local` marketplace.

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

## LM Studio Support

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

## Backend Support

- LM Studio can act as both an MCP client and a local LLM / embedding backend.
- Ollama is supported as a local LLM / embedding backend.
- OpenAI is supported as a structured extraction and embedding backend.
- Gemini is supported as a structured extraction and embedding backend.

### Ollama

SchemaLedger supports Ollama as the runtime/backend behind its own MCP server.

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

## Embedding Provider Setup

Embedding selection is fully env-driven.

- `SCHEMALEDGER_EMBEDDING_PROVIDER=lmstudio`
- `SCHEMALEDGER_EMBEDDING_PROVIDER=ollama`
- `SCHEMALEDGER_EMBEDDING_PROVIDER=openai`
- `SCHEMALEDGER_EMBEDDING_PROVIDER=gemini`
- `SCHEMALEDGER_EMBEDDING_PROVIDER=hash`

If `SCHEMALEDGER_EMBEDDING_PROVIDER` is unset, SchemaLedger follows `SCHEMALEDGER_LLM_PROVIDER` first, then falls back to whatever local backend is configured.

### OpenAI Embeddings

```bash
export SCHEMALEDGER_EMBEDDING_PROVIDER=openai
export SCHEMALEDGER_OPENAI_API_KEY=YOUR_OPENAI_API_KEY
export SCHEMALEDGER_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
export SCHEMALEDGER_OPENAI_BASE_URL=https://api.openai.com
```

### Gemini Embeddings

```bash
export SCHEMALEDGER_EMBEDDING_PROVIDER=gemini
export SCHEMALEDGER_GEMINI_API_KEY=YOUR_GEMINI_API_KEY
export SCHEMALEDGER_GEMINI_EMBEDDING_MODEL=gemini-embedding-001
export SCHEMALEDGER_GEMINI_BASE_URL=https://generativelanguage.googleapis.com
```

### Claude / Anthropic Note

`SCHEMALEDGER_EMBEDDING_PROVIDER=claude` or `anthropic` is intentionally rejected. Anthropic does not currently expose a direct embeddings API, so SchemaLedger fails fast instead of pretending to support it.

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
