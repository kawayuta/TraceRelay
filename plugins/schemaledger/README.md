# SchemaLedger Codex Plugin

Repo-local Codex plugin wrapper for SchemaLedger.

This plugin wires the existing SchemaLedger MCP server into Codex through `.mcp.json` and exposes the same task evolution, trace, schema, and memory surfaces you already use through Web and LM Studio.

## Repo-Local Install

This repository already includes the files Codex expects for repo-local discovery:

- `./plugins/schemaledger/.codex-plugin/plugin.json`
- `./plugins/schemaledger/.mcp.json`
- `./.agents/plugins/marketplace.json`

Open Codex in the repository root and use the local marketplace entry for `schemaledger`.

If you want the plugin available outside this repository as well, run:

```bash
bash ./scripts/install_codex_plugin.sh
```

from the repo root. That installs a home-local copy at `~/plugins/schemaledger` and updates `~/.agents/plugins/marketplace.json`.

## Prerequisites

- `uv sync`
- `docker compose up -d --build postgres web mcp`
- either LM Studio on `http://127.0.0.1:1234`
- or Ollama on `http://127.0.0.1:11434`
- PostgreSQL from docker compose on `127.0.0.1:55432`

The checked-in plugin config defaults to LM Studio. To switch it to Ollama, edit `./plugins/schemaledger/.mcp.json` and set:

- `SCHEMALEDGER_LLM_PROVIDER=ollama`
- `SCHEMALEDGER_EMBEDDING_PROVIDER=ollama` if you want Ollama embeddings too
- `SCHEMALEDGER_OLLAMA_MODEL=<your chat model>`
- `SCHEMALEDGER_OLLAMA_EMBEDDING_MODEL=<your embedding model>`

## What The Plugin Starts

The plugin launches:

```bash
PYTHONPATH=../../src:../.. uv run --project ../.. python -m schemaledger.mcp \
  --workspace ../../workspace \
  --dsn postgresql://postgres:postgres@127.0.0.1:55432/schemaledger_fresh
```

using stdio transport from Codex, while PostgreSQL and the web surface stay on `docker compose`.

This avoids relying on a generated console script and keeps the plugin launch path aligned with the repo-local source tree.

## Core Plugin Surfaces

- MCP tools: `task_evolve`, `task_trace`, `schema_status`, `schema_apply`, `artifact_read`, `artifact_search`, `memory_search`, `memory_profile`, `subject_memory`, `task_memory_context`
- Memory-aware task evolution through the same runtime used by the Flask UI
- PostgreSQL-backed browse and trace data

## Suggested Prompts

- `Evolve a schema for this task and show the missing structure decisions`
- `Recall what we learned about ASPI and continue the extraction`
- `Show the latest Google task trace and related memory context`
