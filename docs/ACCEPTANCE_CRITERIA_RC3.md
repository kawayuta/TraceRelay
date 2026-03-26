# RC3 Acceptance Criteria

## A. Prompt interpretation
- [ ] Google business prompt resolves to subject `Google`
- [ ] Macross prompt resolves to subject `Macross`
- [ ] Japanese policy prompt resolves to a compact policy subject, not the full sentence
- [ ] Incident prompt resolves to an incident-like subject or target system, not the full sentence

## B. Family selection
- [ ] Google business prompt -> `organization`
- [ ] Macross media prompt -> `media_work`
- [ ] population policy prompt -> `policy`
- [ ] API outage prompt -> `system_incident`
- [ ] TSMC/NVIDIA dependency prompt -> `relationship` or `supply_chain_relation`

## C. Extraction semantics
- [ ] extraction payload is non-empty
- [ ] extraction status is not falsely marked success when required values are null-only
- [ ] value deficiency triggers re-extract path

## D. Schema evolution-required case
At least one live prompt must produce:
- [ ] `new_version != null`
- [ ] `signals > 0`
- [ ] `gap != null`
- [ ] `requirement != null`
- [ ] `candidate != null`
- [ ] `review != null`
- [ ] `event != null`

## E. PostgreSQL / Flask
- [ ] `db apply-schema` passes
- [ ] `db reindex-workspace` is idempotent
- [ ] `/api/tasks` returns at least one task
- [ ] `/api/tasks/<id>/coverage` returns non-empty task coverage
- [ ] `/api/schema/*` routes remain stable

## F. MCP
- [ ] `mcp describe`
- [ ] `mcp tools`
- [ ] `mcp resources`
- [ ] `mcp prompts`

## G. Release gate
`2.0.0` should not be tagged until:
- all A and B are green
- at least one D case is green in a live environment
- E and F are green in the same tree
