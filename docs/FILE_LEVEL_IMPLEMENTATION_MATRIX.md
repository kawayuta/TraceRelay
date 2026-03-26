# File-Level Implementation Matrix

| File | Current role | Required rc3 change | Priority |
|---|---|---|---|
| `src/schemaledger/cli.py` | Entry points | Promote `task evolve --prompt` as primary command; keep `entity evolve` compatibility | P0 |
| `src/schemaledger/prompt_interpretation.py` | Partial heuristic interpretation | Switch to LLM-native structured interpretation with fallback rules | P0 |
| `src/schemaledger/family_resolution.py` | Conservative family choice | Use candidate scoring; make `document` last fallback | P0 |
| `src/schemaledger/family_bootstrap.py` | Minimal bootstrap | Add `policy`, `system_incident`, `relationship`, `franchise` | P0 |
| `src/schemaledger/coverage.py` | Generic missing-* reporting | Add task-specific dimensions and dominant issue logic | P0 |
| `src/schemaledger/coverage_dimensions.py` | Static coverage dimensions | Add domain packs for organization/media/policy/incident/relation | P1 |
| `src/schemaledger/extraction.py` | Prompt builder | Family-specific extraction contracts and re-extract prompts | P1 |
| `src/schemaledger/entity_flow.py` | Prompt-first flow | Add family correction, values-first retry, final status codes | P0 |
| `src/schemaledger/task_runtime.py` | Thin wrapper | Become canonical orchestrator for prompt-first flow | P0 |
| `src/schemaledger/llm.py` | Provider HTTP execution | Support structured task interpretation + bootstrap calls | P1 |
| `src/schemaledger/candidate_generation.py` | Additive-first candidate builder | Generate candidates only for schema deficits, not value deficits | P1 |
| `src/schemaledger/evolution/gaps.py` | Gap artifact | Ensure every requirement depends on a gap | P0 |
| `src/schemaledger/evolution/requirements.py` | Requirement artifact | Add back-reference to gap and candidate intent | P0 |
| `src/schemaledger/evolution/migrations.py` | Migration helper | Prefer re-extract before migration on additive schema updates | P1 |
| `src/schemaledger/indexer/loader.py` | DB projection | Project task runtime artifacts; keep idempotency | P0 |
| `src/schemaledger/sql/003_task_runtime.sql` | Not stable yet | Add task-first tables | P0 |
| `src/schemaledger/web/repository.py` | Existing schema browse | Add task-centric queries | P1 |
| `src/schemaledger/web/app.py` | Existing browse routes | Add `/api/tasks*` routes | P1 |
| `src/schemaledger/mcp/server.py` | Minimal MCP shell | Add task-first MCP tools/resources/prompts | P2 |
| `tests/test_prompt_interpretation.py` | Existing semantics tests | Add Japanese organization, policy, incident, relation prompts | P0 |
| `tests/test_entity_flow_semantics.py` | Existing entity flow tests | Add schema-evolution-required success cases | P0 |
| `tests/test_schema_evolution_required_case.py` | Partial | Expand to policy / incident / relation families | P1 |
| `tests/test_web_browse_contract.py` | Existing browse tests | Add `/api/tasks*` and task lineage assertions | P1 |
