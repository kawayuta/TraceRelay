# RC3 Implementation Tasks

## Why rc3 is needed

The runtime now proves that:
- real LM Studio execution works,
- prompt-first entry works,
- artifacts persist,
- PostgreSQL projection works,
- Flask browse/API works,
- organization and media_work prompts can succeed.

But the logs also show the main remaining weakness:

- schema-evolution-required prompts do **not** trigger schema evolution,
- policy / relation / incident prompts still collapse into fallback families,
- prompt interpretation is still partly heuristic,
- family selection is still too conservative,
- "document" still absorbs prompts that should bootstrap new families.

## rc3 objective

`2.0.0rc3` should make the runtime genuinely task-first:

```text
prompt
  -> task interpretation
  -> family candidates
  -> family bootstrap or reuse
  -> extraction
  -> coverage analysis
  -> if values missing: re-extract
  -> if fields/relations missing: schema evolve
  -> review/apply
  -> re-extract with new schema
  -> persist artifacts
  -> project to PostgreSQL
  -> browse through Flask
  -> expose through MCP
```

## Work packages

### WP1 — LLM-native task interpretation
Files:
- `src/schemaledger/prompt_interpretation.py`
- `src/schemaledger/task_runtime.py`
- `src/schemaledger/llm.py`

Implement:
- structured interpretation output with:
  - `intent`
  - `resolved_subject`
  - `subject_candidates`
  - `family_candidates`
  - `scope_hints`
  - `task_shape`
- multilingual prompt handling
- fewer direct keyword-only decisions
- fallback rules only after LLM interpretation fails

Acceptance:
- Google business prompt resolves to `Google`
- Macross prompt resolves to `Macross`
- policy prompt resolves to a policy-like subject, not the full sentence

### WP2 — Family candidate scoring and bootstrap
Files:
- `src/schemaledger/family_resolution.py`
- `src/schemaledger/family_bootstrap.py`
- `src/schemaledger/schema_guard.py`

Implement:
- `family_candidates[]` scoring
- family normalization
- bootstrap for:
  - `organization`
  - `media_work`
  - `franchise`
  - `policy`
  - `system_incident`
  - `relationship`
- `document` as true fallback, not default shortcut

Acceptance:
- policy prompt does not end in `document`
- incident prompt does not end in `organization`
- relation prompt does not end in single-entity `organization`

### WP3 — Coverage semantics
Files:
- `src/schemaledger/coverage.py`
- `src/schemaledger/coverage_dimensions.py`

Implement:
- task-specific required/preferred dimensions
- split output into:
  - `missing_values`
  - `missing_fields`
  - `missing_relations`
- `dominant_issue` computed explicitly

Acceptance:
- prompts with adequate fields but empty values produce `dominant_issue = values`
- prompts needing new relations produce `dominant_issue = schema`

### WP4 — Re-extract-first loop
Files:
- `src/schemaledger/entity_flow.py`
- `src/schemaledger/task_runtime.py`
- `src/schemaledger/extraction.py`

Implement:
- if `dominant_issue == values`, run re-extraction instead of schema candidate generation
- if `dominant_issue == schema`, generate additive schema candidates
- add statuses:
  - `success`
  - `partial`
  - `failed`
- add reasons:
  - `reextract_required`
  - `family_correction_required`
  - `schema_evolution_required`
  - `provider_execution_failed`

Acceptance:
- schema-evolution-required prompt can trigger candidate generation
- value-deficient prompt can trigger re-extract instead of candidate generation

### WP5 — Strict gap → requirement → candidate sequence
Files:
- `src/schemaledger/evolution/gaps.py`
- `src/schemaledger/evolution/requirements.py`
- `src/schemaledger/candidate_generation.py`

Implement:
- requirement creation must depend on a real gap artifact
- candidate creation must depend on a real requirement artifact
- no "requirement without gap"

Acceptance:
- every requirement has a gap id
- every candidate has a requirement id

### WP6 — PostgreSQL projection of task runtime
Files:
- `src/schemaledger/indexer/loader.py`
- `src/schemaledger/sql/003_task_runtime.sql`

Implement tables for:
- `task_prompt`
- `task_interpretation`
- `task_run`
- `schema_bootstrap`
- `task_extraction`
- `coverage_report`
- `task_schema_candidate_map`

Acceptance:
- task-first artifacts are visible in DB
- reindex remains idempotent

### WP7 — Flask task-first browse/API
Files:
- `src/schemaledger/web/repository.py`
- `src/schemaledger/web/app.py`

Add routes:
- `/api/tasks`
- `/api/tasks/<id>`
- `/api/tasks/<id>/coverage`
- `/api/tasks/<id>/schema`
- `/api/tasks/<id>/events`

Acceptance:
- from one task id, the user can trace:
  - prompt
  - interpretation
  - family choice
  - extraction
  - coverage
  - gap
  - candidate
  - review
  - event

### WP8 — MCP surface
Files:
- `src/schemaledger/mcp/server.py`
- `src/schemaledger/mcp/tools.py`
- `src/schemaledger/mcp/resources.py`
- `src/schemaledger/mcp/prompts.py`

Expose:
- tools:
  - `task_evolve`
  - `schema_status`
  - `schema_apply`
  - `artifact_read`
  - `artifact_search`
- resources:
  - task artifacts
  - family/version records
  - candidates/events
- prompts:
  - `investigate_subject`
  - `compare_subjects`
  - `analyze_policy`
  - `analyze_incident`

Acceptance:
- `mcp describe/tools/resources/prompts` works
- task-first runtime is externally discoverable

## Recommended delivery order

1. WP1
2. WP2
3. WP3
4. WP4
5. WP5
6. WP6
7. WP7
8. WP8
