from __future__ import annotations

from typing import Any

from .web.repository import TaskBrowseRepository


def build_information_gap_analysis(repository: TaskBrowseRepository, task_id: str) -> dict[str, object]:
    task = repository.get_task(task_id)
    interpretation = dict(task.get("interpretation") or {})
    run = dict(task.get("run") or {})
    coverage = _latest_coverage(task)
    schema = _latest_schema(task)
    extraction = _latest_extraction(task)
    latest_branch_decision = dict(task.get("latest_branch_decision") or {})
    family_selection = dict(task.get("family_selection") or {})
    strategy_selection = dict(task.get("strategy_selection") or {})
    payload = dict(extraction.get("payload") or {})
    known_facts = _learned_facts_from_payload(payload)
    missing_values = _string_list(coverage.get("missing_values", []))
    missing_fields = _string_list(coverage.get("missing_fields", []))
    missing_relations = _string_list(coverage.get("missing_relations", []))
    requested_fields = _string_list(interpretation.get("requested_fields", []))
    requested_relations = _string_list(interpretation.get("requested_relations", []))
    schema_fields = _string_list(schema.get("required_fields", [])) + _string_list(schema.get("optional_fields", []))
    schema_relations = _string_list(schema.get("relations", []))
    subject = str(interpretation.get("resolved_subject") or "")
    family = str(interpretation.get("family") or "")
    dominant_issue = str(coverage.get("dominant_issue") or "none")

    return {
        "task_id": task_id,
        "prompt": str(task.get("prompt") or ""),
        "subject": subject,
        "family": family,
        "status": str(run.get("status") or ""),
        "reason": str(run.get("reason") or ""),
        "attempts": int(run.get("attempts") or len(task.get("extractions") or []) or 0),
        "schema_version": int(schema.get("version") or 0),
        "dominant_issue": dominant_issue,
        "selected_family": str(family_selection.get("chosen_family") or family or ""),
        "selected_strategy": str(
            strategy_selection.get("chosen_branch_type") or latest_branch_decision.get("chosen_branch_type") or ""
        ),
        "chosen_branch_type": str(latest_branch_decision.get("chosen_branch_type") or ""),
        "branch_completion_rate": latest_branch_decision.get("completion_rate"),
        "branch_rationale": str(latest_branch_decision.get("rationale") or ""),
        "strategy_rationale": str(strategy_selection.get("rationale") or latest_branch_decision.get("rationale") or ""),
        "branch_telemetry": dict(latest_branch_decision.get("telemetry") or {}),
        "missing_values": missing_values,
        "missing_fields": missing_fields,
        "missing_relations": missing_relations,
        "requested_fields": requested_fields,
        "requested_relations": requested_relations,
        "schema_fields": sorted(dict.fromkeys(schema_fields)),
        "schema_relations": sorted(dict.fromkeys(schema_relations)),
        "known_keys": sorted(payload.keys()),
        "known_facts": known_facts,
        "gap_summary": _gap_summary(dominant_issue, missing_values, missing_fields, missing_relations, run),
        "needs_external_search": dominant_issue in {"values", "schema"},
        "needs_schema_evolution": dominant_issue == "schema",
        "needs_reextract": dominant_issue == "values",
    }


def build_search_query_plan(
    repository: TaskBrowseRepository,
    task_id: str,
    *,
    limit: int = 5,
) -> dict[str, object]:
    analysis = build_information_gap_analysis(repository, task_id)
    subject = str(analysis.get("subject") or "subject").strip()
    family = str(analysis.get("family") or "").strip()
    prompt = str(analysis.get("prompt") or "").strip()
    focus_terms = _focus_terms(analysis)
    anchor_terms = _anchor_terms(analysis)
    scope_terms = _scope_terms(analysis)

    queries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(query: str, why: str) -> None:
        normalized = " ".join(query.split())
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        queries.append({"query": normalized, "why": why})

    focus_phrase = " ".join(_pretty_term(item) for item in focus_terms[:2]).strip()
    anchor_phrase = " ".join(anchor_terms[:2]).strip()
    scope_phrase = " ".join(scope_terms[:2]).strip()
    family_phrase = _pretty_term(family).strip()

    if focus_phrase:
        add(f"{subject} {focus_phrase}", "Search directly for the currently missing slots.")
        add(f"{subject} {focus_phrase} latest", "Bias toward recent facts for the missing slots.")
    if focus_phrase and anchor_phrase:
        add(
            f"{subject} {anchor_phrase} {focus_phrase}",
            "Keep the query grounded in facts already extracted before widening search.",
        )
    if focus_phrase and scope_phrase:
        add(
            f"{subject} {scope_phrase} {focus_phrase}",
            "Combine scope hints with the explicit gap so search stays narrow.",
        )
    if focus_phrase and family_phrase:
        add(
            f"{subject} {family_phrase} {focus_phrase}",
            "Reinforce the current family context while filling the missing slots.",
        )
    if not queries and prompt:
        add(f"{subject} {scope_phrase}".strip() or prompt, "Start from the task subject before broadening the search.")
    if not queries:
        add(subject, "Start with the resolved subject only and let TraceRelay structure the baseline.")

    return {
        "task_id": task_id,
        "subject": subject,
        "dominant_issue": analysis["dominant_issue"],
        "focus_terms": [_pretty_term(item) for item in focus_terms[:5]],
        "anchor_terms": anchor_terms[:5],
        "queries": queries[:limit],
    }


def build_next_step_plan(
    repository: TaskBrowseRepository,
    task_id: str,
    *,
    limit: int = 5,
) -> dict[str, object]:
    analysis = build_information_gap_analysis(repository, task_id)
    query_plan = build_search_query_plan(repository, task_id, limit=limit)
    dominant_issue = str(analysis.get("dominant_issue") or "none")
    chosen_branch_type = str(analysis.get("chosen_branch_type") or "")
    status = str(analysis.get("status") or "")
    reason = str(analysis.get("reason") or "")

    pre_search_checks = [
        "Read task_memory_context so already extracted facts are reused before taking new actions.",
        "Read subject_memory to avoid repeating prior work on the same subject.",
        "Check analyze_information_gaps before searching so schema gaps and value gaps are not mixed together.",
    ]
    guardrails = [
        "Do not issue broad web searches before reviewing the missing fields, relations, or values.",
        "Do not evolve schema for plain missing values when the current schema already supports them.",
        "Do not ignore facts already stored in TraceRelay memory when preparing the next query.",
    ]

    if chosen_branch_type == "schema_evolution" or dominant_issue == "schema":
        recommended_tool = "continue_prior_work"
        actions = [
            _action(
                "Confirm the structural gap",
                "analyze_information_gaps",
                "Verify which fields or relations are missing before searching or evolving schema.",
            ),
            _action(
                "Prepare targeted search queries",
                "prepare_search_queries",
                "Use narrow search terms based on the explicit missing structure and known facts.",
            ),
            _action(
                "Continue the structured run",
                "continue_prior_work",
                "Bring new evidence back into TraceRelay so schema evolution and re-extraction stay traceable.",
            ),
        ]
    elif chosen_branch_type == "reextract" or dominant_issue == "values":
        recommended_tool = "continue_prior_work"
        actions = [
            _action(
                "Review what is already known",
                "task_memory_context",
                "Reuse prior extraction facts before searching again for missing values.",
            ),
            _action(
                "Prepare focused value queries",
                "prepare_search_queries",
                "Generate search phrases only for the values that are still missing.",
            ),
            _action(
                "Run the next structured pass",
                "continue_prior_work",
                "Use the retrieved evidence to refill missing values instead of widening the schema.",
            ),
        ]
    elif chosen_branch_type == "complete" or (status == "success" and reason == "complete"):
        recommended_tool = "inspect_latest_changes"
        actions = [
            _action(
                "Inspect the completed run",
                "inspect_latest_changes",
                "Review what changed before deciding whether another structured pass is necessary.",
            ),
            _action(
                "Only expand scope intentionally",
                "structure_subject",
                "Start a new structured pass only when you truly need new fields, relations, or a fresh scope.",
            ),
        ]
    else:
        recommended_tool = "inspect_latest_changes"
        actions = [
            _action(
                "Inspect the latest branch",
                "inspect_latest_changes",
                "Understand the current branch state before taking more actions.",
            ),
            _action(
                "Prepare the next search or follow-up",
                "plan_next_step",
                "Use TraceRelay's memory and gap state before free-form reasoning or search.",
            ),
        ]

    return {
        "task_id": task_id,
        "subject": analysis["subject"],
        "family": analysis["family"],
        "selected_family": analysis["selected_family"],
        "selected_strategy": analysis["selected_strategy"],
        "status": analysis["status"],
        "reason": analysis["reason"],
        "dominant_issue": dominant_issue,
        "chosen_branch_type": chosen_branch_type,
        "branch_rationale": analysis["branch_rationale"],
        "recommended_tool": recommended_tool,
        "pre_search_checks": pre_search_checks,
        "recommended_actions": actions,
        "recommended_queries": query_plan["queries"],
        "guardrails": guardrails,
        "gap_summary": analysis["gap_summary"],
    }


def build_subject_bootstrap_plan(subject: str, *, limit: int = 5) -> dict[str, object]:
    normalized_subject = " ".join(subject.split()).strip() or "subject"
    return {
        "found": False,
        "subject": normalized_subject,
        "recommended_tool": "structure_subject",
        "pre_search_checks": [
            "Start by creating a structured TraceRelay run before broad web search.",
            "Use the resolved subject as the base of every search phrase.",
        ],
        "recommended_actions": [
            _action(
                "Create the first structured run",
                "structure_subject",
                "Build the initial schema and task lineage before relying on ad hoc search.",
            ),
            _action(
                "Search only to establish the first fact base",
                "prepare_search_queries",
                "Use narrow subject-first queries so the initial run does not drift.",
            ),
        ],
        "recommended_queries": [
            {"query": normalized_subject, "why": "Use the resolved subject as the anchor query."},
            {
                "query": f"{normalized_subject} profile",
                "why": "Establish a baseline profile before adding more specific slots.",
            },
        ][:limit],
        "guardrails": [
            "Do not start with a broad, speculative query that ignores the subject anchor.",
            "Do not invent new schema keys until the first structured run shows a real structural gap.",
        ],
        "gap_summary": "No prior task found. Establish a structured baseline first.",
    }


def _action(title: str, tool: str, why: str) -> dict[str, str]:
    return {"title": title, "tool": tool, "why": why}


def _latest_coverage(task: dict[str, object]) -> dict[str, object]:
    reports = list(task.get("coverage_reports") or [])
    return dict(reports[-1]) if reports else {}


def _latest_schema(task: dict[str, object]) -> dict[str, object]:
    versions = list(task.get("schema_versions") or [])
    return dict(versions[-1]) if versions else {}


def _latest_extraction(task: dict[str, object]) -> dict[str, object]:
    extractions = list(task.get("extractions") or [])
    return dict(extractions[-1]) if extractions else {}


def _learned_facts_from_payload(payload: dict[str, Any], *, limit: int = 8) -> list[str]:
    facts: list[str] = []
    for key, value in payload.items():
        preview = _preview_value(value)
        if not preview:
            continue
        facts.append(f"{_pretty_term(str(key))}: {preview}")
        if len(facts) >= limit:
            break
    return facts


def _preview_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        return text[:120] + "..." if len(text) > 120 else text
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        items = [_preview_value(item) for item in value[:2]]
        items = [item for item in items if item]
        return ", ".join(items)
    if isinstance(value, dict):
        parts: list[str] = []
        for key, nested in list(value.items())[:2]:
            nested_preview = _preview_value(nested)
            if nested_preview:
                parts.append(f"{_pretty_term(str(key))}={nested_preview}")
        return ", ".join(parts)
    return str(value)


def _focus_terms(analysis: dict[str, object]) -> list[str]:
    for key in ("missing_values", "missing_fields", "missing_relations"):
        values = _string_list(analysis.get(key, []))
        if values:
            return values
    fallback = _string_list(analysis.get("requested_fields", [])) + _string_list(analysis.get("requested_relations", []))
    return list(dict.fromkeys(fallback))


def _anchor_terms(analysis: dict[str, object]) -> list[str]:
    anchors: list[str] = []
    for fact in _string_list(analysis.get("known_facts", [])):
        if ":" in fact:
            _, value = fact.split(":", 1)
            cleaned = " ".join(value.split()).strip()
            if cleaned and len(cleaned.split()) <= 6:
                anchors.append(cleaned)
    if not anchors:
        for key in _string_list(analysis.get("known_keys", [])):
            anchors.append(_pretty_term(key))
    return list(dict.fromkeys(item for item in anchors if item))


def _scope_terms(analysis: dict[str, object]) -> list[str]:
    requested = _string_list(analysis.get("requested_fields", [])) + _string_list(analysis.get("requested_relations", []))
    focus = set(_focus_terms(analysis))
    scope_terms = [_pretty_term(item) for item in requested if item not in focus]
    return list(dict.fromkeys(item for item in scope_terms if item))


def _gap_summary(
    dominant_issue: str,
    missing_values: list[str],
    missing_fields: list[str],
    missing_relations: list[str],
    run: dict[str, object],
) -> str:
    if dominant_issue == "schema":
        targets = missing_fields + missing_relations
        preview = ", ".join(_pretty_term(item) for item in targets[:2])
        return f"Schema gap: {preview or 'missing structure'}"
    if dominant_issue == "values":
        preview = ", ".join(_pretty_term(item) for item in missing_values[:2])
        return f"Value gap: {preview or 'missing values'}"
    reason = str(run.get("reason") or "")
    if reason == "complete":
        return "Complete with no open gap."
    if reason:
        return reason.replace("_", " ")
    return "No open gap."


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(item) for item in values if str(item).strip()]


def _pretty_term(value: str) -> str:
    return value.replace("_", " ").strip()
