from __future__ import annotations

from typing import Any


_ARTIFACT_LANES = {
    "task_prompt": "input",
    "task_interpretation": "decision",
    "schema_version": "schema",
    "schema_reference": "schema",
    "task_extraction": "extraction",
    "coverage_report": "decision",
    "schema_gap": "schema",
    "schema_requirement": "schema",
    "schema_candidate": "schema",
    "schema_review": "decision",
    "task_event": "decision",
    "task_run": "outcome",
}


def build_task_trace(task: dict[str, object], artifacts: list[dict[str, object]]) -> dict[str, object]:
    task_id = str(task["task_id"])
    interpretation = dict(task.get("interpretation") or {})
    run = dict(task.get("run") or {})
    schema_versions = [dict(item) for item in task.get("schema_versions", [])]

    flow_nodes = [_artifact_to_node(index, artifact) for index, artifact in enumerate(artifacts)]
    flow_edges = _build_flow_edges(flow_nodes)
    decision_tree = _build_decision_tree(task, artifacts)

    return {
        "task_id": task_id,
        "summary": {
            "prompt": task.get("prompt"),
            "resolved_subject": interpretation.get("resolved_subject"),
            "family": interpretation.get("family"),
            "status": run.get("status"),
            "reason": run.get("reason"),
            "attempts": run.get("attempts"),
            "schema_rounds": run.get("schema_rounds"),
        },
        "schema_lineage": [_schema_lineage_item(schema, index) for index, schema in enumerate(schema_versions)],
        "flowchart": {"nodes": flow_nodes, "edges": flow_edges},
        "decision_tree": decision_tree,
    }


def _artifact_to_node(index: int, artifact: dict[str, object]) -> dict[str, object]:
    artifact_type = str(artifact["artifact_type"])
    artifact_id = str(artifact["artifact_id"])
    payload = dict(artifact["payload"])
    title, subtitle, details, tone = _artifact_summary(artifact_type, payload)
    return {
        "id": artifact_id,
        "index": index,
        "artifact_type": artifact_type,
        "lane": _ARTIFACT_LANES.get(artifact_type, "decision"),
        "title": title,
        "subtitle": subtitle,
        "details": details,
        "tone": tone,
    }


def _artifact_summary(
    artifact_type: str,
    payload: dict[str, object],
) -> tuple[str, str, list[str], str]:
    if artifact_type == "task_prompt":
        prompt = str(payload.get("prompt", ""))
        return "Prompt", _truncate(prompt, 180), _detail_lines([prompt]), "neutral"
    if artifact_type == "task_interpretation":
        requested_fields = [str(item) for item in payload.get("requested_fields", [])]
        requested_relations = [str(item) for item in payload.get("requested_relations", [])]
        details = [
            f"intent: {payload.get('intent', '')}",
            f"resolved_subject: {payload.get('resolved_subject', '')}",
            f"family rationale: {payload.get('family_rationale', '')}",
            f"requested fields: {_preview_list(requested_fields)}",
            f"requested relations: {_preview_list(requested_relations)}",
        ]
        subtitle = f"{payload.get('family', '')} for {payload.get('resolved_subject', '')}"
        return "Interpretation", subtitle, _detail_lines(details), "decision"
    if artifact_type in {"schema_version", "schema_reference"}:
        required_fields = [str(item) for item in payload.get("required_fields", [])]
        optional_fields = [str(item) for item in payload.get("optional_fields", [])]
        relations = [str(item) for item in payload.get("relations", [])]
        version = payload.get("version", "?")
        subtitle = f"{payload.get('family', '')} schema v{version}"
        details = [
            f"required: {_preview_list(required_fields)}",
            f"optional: {_preview_list(optional_fields)}",
            f"relations: {_preview_list(relations)}",
        ]
        title = "Schema Version" if artifact_type == "schema_version" else "Schema Reference"
        return title, subtitle, _detail_lines(details), "schema"
    if artifact_type == "task_extraction":
        payload_keys = sorted(dict(payload.get("payload", {})).keys())
        subtitle = f"attempt {payload.get('attempt', '?')} on schema v{payload.get('schema_version', '?')}"
        details = [
            f"status: {payload.get('status', '')}",
            f"keys returned: {_preview_list(payload_keys)}",
        ]
        return "Extraction", subtitle, _detail_lines(details), "extraction"
    if artifact_type == "coverage_report":
        missing_values = [str(item) for item in payload.get("missing_values", [])]
        missing_fields = [str(item) for item in payload.get("missing_fields", [])]
        missing_relations = [str(item) for item in payload.get("missing_relations", [])]
        dominant_issue = str(payload.get("dominant_issue", "none"))
        details = [
            f"missing values: {_preview_list(missing_values)}",
            f"missing fields: {_preview_list(missing_fields)}",
            f"missing relations: {_preview_list(missing_relations)}",
        ]
        tone = "success" if dominant_issue == "none" else "warning"
        return "Coverage Check", f"dominant issue: {dominant_issue}", _detail_lines(details), tone
    if artifact_type == "schema_gap":
        signals = [str(item) for item in payload.get("signals", [])]
        return "Schema Gap", _preview_list(signals), _detail_lines([f"signals: {_preview_list(signals)}"]), "warning"
    if artifact_type == "schema_requirement":
        summary = str(payload.get("summary", ""))
        return "Schema Requirement", _truncate(summary, 120), _detail_lines([summary]), "schema"
    if artifact_type == "schema_candidate":
        fields = [str(item) for item in payload.get("fields", [])]
        relations = [str(item) for item in payload.get("relations", [])]
        details = [
            f"additive fields: {_preview_list(fields)}",
            f"additive relations: {_preview_list(relations)}",
            f"rationale: {payload.get('rationale', '')}",
        ]
        return "Schema Candidate", "LLM additive proposal", _detail_lines(details), "schema"
    if artifact_type == "schema_review":
        disposition = str(payload.get("disposition", ""))
        notes = str(payload.get("notes", ""))
        return "Schema Review", disposition, _detail_lines([notes]), "decision"
    if artifact_type == "task_event":
        kind = str(payload.get("kind", ""))
        details = _event_details(payload)
        tone = "warning" if kind == "reextract_requested" else "decision"
        return "Task Event", kind, details, tone
    if artifact_type == "task_run":
        subtitle = f"{payload.get('status', '')} / {payload.get('reason', '')}"
        details = [
            f"attempts: {payload.get('attempts', '')}",
            f"schema rounds: {payload.get('schema_rounds', '')}",
            f"active schema version: {payload.get('schema_version', '')}",
        ]
        if payload.get("error"):
            details.append(f"error: {payload.get('error', '')}")
        tone = "success" if payload.get("status") == "success" else "warning"
        return "Outcome", subtitle, _detail_lines(details), tone
    return artifact_type, "", [], "neutral"


def _event_details(payload: dict[str, object]) -> list[str]:
    details = dict(payload.get("details", {}))
    lines: list[str] = []
    if "missing_values" in details:
        lines.append(f"missing values: {_preview_list(_to_str_list(details['missing_values']))}")
    if "fields" in details:
        lines.append(f"applied fields: {_preview_list(_to_str_list(details['fields']))}")
    if "relations" in details:
        lines.append(f"applied relations: {_preview_list(_to_str_list(details['relations']))}")
    if "schema_id" in details:
        lines.append(f"schema: {details['schema_id']} (v{details.get('version', '?')})")
    if not lines:
        lines.append(_truncate(str(details), 180))
    return _detail_lines(lines)


def _build_flow_edges(nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    for previous, current in zip(nodes, nodes[1:]):
        edges.append(
            {
                "from": previous["id"],
                "to": current["id"],
                "label": _edge_label(str(previous["artifact_type"]), str(current["artifact_type"]), previous, current),
            }
        )
    return edges


def _edge_label(
    previous_type: str,
    current_type: str,
    previous: dict[str, object],
    current: dict[str, object],
) -> str:
    if previous_type == "coverage_report" and current_type == "task_event":
        subtitle = str(current.get("subtitle", ""))
        if subtitle == "reextract_requested":
            return "values branch"
    if previous_type == "coverage_report" and current_type == "schema_gap":
        return "schema branch"
    if previous_type == "coverage_report" and current_type == "task_run":
        return "complete"
    if previous_type == "task_event" and current_type == "task_extraction":
        subtitle = str(previous.get("subtitle", ""))
        if subtitle == "reextract_requested":
            return "retry"
        if subtitle == "schema_version_applied":
            return "rerun on new schema"
    return ""


def _build_decision_tree(task: dict[str, object], artifacts: list[dict[str, object]]) -> dict[str, object]:
    interpretation = dict(task.get("interpretation") or {})
    run = dict(task.get("run") or {})

    root = {
        "title": "Task Decision Tree",
        "lines": [
            f"task_id: {task.get('task_id', '')}",
            f"final status: {run.get('status', '')} / {run.get('reason', '')}",
        ],
        "children": [
            {
                "title": "Prompt",
                "lines": _detail_lines([str(task.get("prompt", ""))]),
                "children": [],
            },
            {
                "title": "Interpretation",
                "lines": _detail_lines(
                    [
                        f"resolved_subject: {interpretation.get('resolved_subject', '')}",
                        f"family: {interpretation.get('family', '')}",
                        f"family rationale: {interpretation.get('family_rationale', '')}",
                    ]
                ),
                "children": [],
            },
            {
                "title": "Schema Lineage",
                "lines": [],
                "children": _schema_tree_nodes([dict(item) for item in task.get("schema_versions", [])]),
            },
            {
                "title": "Execution Loop",
                "lines": [],
                "children": _attempt_tree_nodes(artifacts, run),
            },
            {
                "title": "Outcome",
                "lines": _detail_lines(
                    [
                        f"status: {run.get('status', '')}",
                        f"reason: {run.get('reason', '')}",
                        f"attempts: {run.get('attempts', '')}",
                        f"schema rounds: {run.get('schema_rounds', '')}",
                    ]
                ),
                "children": [],
            },
        ],
    }
    return root


def _schema_tree_nodes(schema_versions: list[dict[str, object]]) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    for schema in schema_versions:
        nodes.append(
            {
                "title": f"Schema v{schema.get('version', '?')}",
                "lines": _detail_lines(
                    [
                        f"family: {schema.get('family', '')}",
                        f"required: {_preview_list(_to_str_list(schema.get('required_fields', [])))}",
                        f"optional: {_preview_list(_to_str_list(schema.get('optional_fields', [])))}",
                        f"relations: {_preview_list(_to_str_list(schema.get('relations', [])))}",
                    ]
                ),
                "children": [],
            }
        )
    return nodes


def _attempt_tree_nodes(artifacts: list[dict[str, object]], run: dict[str, object]) -> list[dict[str, object]]:
    attempts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for artifact in artifacts:
        artifact_type = str(artifact["artifact_type"])
        payload = dict(artifact["payload"])

        if artifact_type == "task_extraction":
            current = {
                "attempt": payload.get("attempt", len(attempts) + 1),
                "extraction": payload,
                "coverage": None,
                "events": [],
                "gap": None,
                "requirement": None,
                "candidate": None,
                "review": None,
                "schema": None,
            }
            attempts.append(current)
            continue

        if current is None:
            continue

        if artifact_type == "coverage_report":
            current["coverage"] = payload
        elif artifact_type == "task_event":
            current["events"].append(payload)
        elif artifact_type == "schema_gap":
            current["gap"] = payload
        elif artifact_type == "schema_requirement":
            current["requirement"] = payload
        elif artifact_type == "schema_candidate":
            current["candidate"] = payload
        elif artifact_type == "schema_review":
            current["review"] = payload
        elif artifact_type == "schema_version" and current.get("coverage", {}).get("dominant_issue") == "schema":
            current["schema"] = payload

    nodes: list[dict[str, object]] = []
    for attempt in attempts:
        extraction = dict(attempt["extraction"])
        coverage = dict(attempt["coverage"] or {})
        decision = _attempt_decision(attempt, run)
        children = [
            {
                "title": "Extraction",
                "lines": _detail_lines(
                    [
                        f"schema version: {extraction.get('schema_version', '')}",
                        f"status: {extraction.get('status', '')}",
                        f"keys returned: {_preview_list(sorted(dict(extraction.get('payload', {})).keys()))}",
                    ]
                ),
                "children": [],
            },
        ]

        if coverage:
            children.append(
                {
                    "title": "Coverage",
                    "lines": _detail_lines(
                        [
                            f"dominant issue: {coverage.get('dominant_issue', '')}",
                            f"missing values: {_preview_list(_to_str_list(coverage.get('missing_values', [])))}",
                            f"missing fields: {_preview_list(_to_str_list(coverage.get('missing_fields', [])))}",
                            f"missing relations: {_preview_list(_to_str_list(coverage.get('missing_relations', [])))}",
                        ]
                    ),
                    "children": [],
                }
            )

        decision_children: list[dict[str, object]] = []
        if attempt.get("gap") or attempt.get("requirement") or attempt.get("candidate") or attempt.get("review") or attempt.get("schema"):
            evolution_lines = []
            gap = dict(attempt["gap"] or {})
            requirement = dict(attempt["requirement"] or {})
            candidate = dict(attempt["candidate"] or {})
            review = dict(attempt["review"] or {})
            schema = dict(attempt["schema"] or {})
            if gap:
                evolution_lines.append(f"gap signals: {_preview_list(_to_str_list(gap.get('signals', [])))}")
            if requirement:
                evolution_lines.append(f"requirement: {requirement.get('summary', '')}")
            if candidate:
                evolution_lines.append(f"candidate fields: {_preview_list(_to_str_list(candidate.get('fields', [])))}")
                evolution_lines.append(f"candidate relations: {_preview_list(_to_str_list(candidate.get('relations', [])))}")
            if review:
                evolution_lines.append(f"review: {review.get('disposition', '')}")
            if schema:
                evolution_lines.append(f"applied schema version: {schema.get('version', '')}")
            decision_children.append(
                {
                    "title": "Schema Evolution",
                    "lines": _detail_lines(evolution_lines),
                    "children": [],
                }
            )

        event_nodes = []
        for event in attempt.get("events", []):
            event_nodes.append(
                {
                    "title": f"Event: {event.get('kind', '')}",
                    "lines": _event_details(event),
                    "children": [],
                }
            )
        decision_children.extend(event_nodes)

        children.append(
            {
                "title": "Decision",
                "lines": _detail_lines(decision),
                "children": decision_children,
            }
        )
        nodes.append(
            {
                "title": f"Attempt {attempt['attempt']}",
                "lines": [],
                "children": children,
            }
        )
    return nodes


def _attempt_decision(attempt: dict[str, Any], run: dict[str, object]) -> list[str]:
    extraction = dict(attempt["extraction"])
    coverage = dict(attempt["coverage"] or {})
    if extraction.get("status") == "failed":
        return ["provider execution failed", f"final reason: {run.get('reason', '')}"]

    dominant_issue = str(coverage.get("dominant_issue", "none"))
    if dominant_issue == "none":
        return ["coverage passed", "branch: complete"]
    if any(event.get("kind") == "reextract_requested" for event in attempt.get("events", [])):
        return ["missing values remained", "branch: re-extract with same schema"]
    if attempt.get("candidate") or attempt.get("gap"):
        return ["schema was insufficient for the requested scope", "branch: evolve schema and re-run extraction"]
    if dominant_issue == "values":
        return ["missing values remained", f"branch stopped with reason: {run.get('reason', '')}"]
    if dominant_issue == "schema":
        return ["schema was insufficient for the requested scope", f"branch stopped with reason: {run.get('reason', '')}"]
    return [f"branch stopped with reason: {run.get('reason', '')}"]


def _schema_lineage_item(schema: dict[str, object], index: int) -> dict[str, object]:
    return {
        "index": index,
        "schema_id": schema.get("schema_id"),
        "version": schema.get("version"),
        "family": schema.get("family"),
        "required_fields": _to_str_list(schema.get("required_fields", [])),
        "optional_fields": _to_str_list(schema.get("optional_fields", [])),
        "relations": _to_str_list(schema.get("relations", [])),
        "rationale": schema.get("rationale"),
    }


def _preview_list(values: list[str], limit: int = 5) -> str:
    if not values:
        return "none"
    if len(values) <= limit:
        return ", ".join(values)
    remaining = len(values) - limit
    return f"{', '.join(values[:limit])} +{remaining} more"


def _to_str_list(values: object) -> list[str]:
    if isinstance(values, (list, tuple)):
        return [str(item) for item in values]
    return []


def _detail_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line and line != "none"]


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
