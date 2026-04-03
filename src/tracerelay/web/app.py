from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import re
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template, request

from ..action_planning import (
    build_information_gap_analysis,
    build_next_step_plan,
    build_search_query_plan,
)
from .repository import TaskBrowseRepository, _memory_record_matches_subject, _normalize_subject_key

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3040-\u30ff\u4e00-\u9fff]+")


def create_app(repository: TaskBrowseRepository) -> Flask:
    app = Flask(__name__)

    @app.context_processor
    def inject_shell() -> dict[str, object]:
        return {"app_shell": build_app_shell(repository)}

    @app.get("/")
    @app.get("/tasks")
    def tasks_page() -> object:
        dashboard = build_task_dashboard(repository)
        return render_template("task_list.html", tasks=dashboard["tasks"], dashboard=dashboard)

    @app.get("/tasks/<task_id>")
    def task_trace_page(task_id: str) -> object:
        try:
            task = repository.get_task(task_id)
            trace = repository.get_task_trace(task_id)
        except KeyError:
            abort(404)
        memory_panel = build_task_trace_memory_panel(repository, task_id, trace)
        operator_view = build_trace_operator_view(task, memory_panel=memory_panel)
        return render_template(
            "task_trace.html",
            trace=trace,
            memory_panel=memory_panel,
            operator_view=operator_view,
        )

    @app.get("/memory")
    @app.get("/memory/search")
    def memory_dashboard() -> object:
        query = request.args.get("q", "").strip()
        subject_scope = request.args.get("subject", "").strip()
        memory = build_workspace_profile_memory(repository)
        memory["search_query"] = query
        memory["subject_scope"] = subject_scope
        if query or subject_scope:
            search_result = build_memory_search(repository, query, limit=8, subject_scope=subject_scope)
            memory["blocks"].append(
                {
                    "title": "Vector Search Results",
                    "description": f"Top {len(search_result['results'])} matches using {search_result['strategy']}.",
                    "lines": [
                        f"query: {search_result['query'] or 'n/a'}",
                        f"subject scope: {search_result['subject_scope'] or 'none'}",
                        f"limit: {search_result['limit']}",
                        f"strategy: {search_result['strategy']}",
                    ],
                    "cards": [
                        _memory_task_card(result, href=f"/memory/tasks/{result['task_id']}")
                        for result in search_result["results"]
                    ],
                }
            )
        return render_template("memory_view.html", memory=memory)

    @app.get("/memory/profile")
    @app.get("/memory/profile/<profile_id>")
    def memory_profile_page(profile_id: str = "workspace") -> object:
        return render_template(
            "memory_view.html",
            memory=build_workspace_profile_memory(repository, profile_id=profile_id),
        )

    @app.get("/memory/subjects/<path:subject>")
    def memory_subject_page(subject: str) -> object:
        return render_template(
            "memory_view.html",
            memory=build_subject_memory(repository, subject),
        )

    @app.get("/memory/tasks/<task_id>")
    def memory_task_page(task_id: str) -> object:
        try:
            memory = build_task_memory_context(repository, task_id)
        except KeyError:
            abort(404)
        return render_template("memory_view.html", memory=memory)

    @app.get("/api/tasks")
    def list_tasks() -> object:
        return jsonify(repository.list_tasks())

    @app.get("/api/tasks/<task_id>")
    def get_task(task_id: str) -> object:
        try:
            return jsonify(repository.get_task(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/coverage")
    def get_task_coverage(task_id: str) -> object:
        try:
            return jsonify(repository.get_task_coverage(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/schema")
    def get_task_schema(task_id: str) -> object:
        try:
            return jsonify(repository.get_task_schema(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/events")
    def get_task_events(task_id: str) -> object:
        try:
            return jsonify(repository.get_task_events(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/trace")
    def get_task_trace(task_id: str) -> object:
        try:
            return jsonify(repository.get_task_trace(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/gaps")
    def get_task_gaps(task_id: str) -> object:
        try:
            return jsonify(build_information_gap_analysis(repository, task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/queries")
    def get_task_queries(task_id: str) -> object:
        try:
            limit = _bounded_limit(request.args.get("limit", "5"), default=5, maximum=10)
            return jsonify(build_search_query_plan(repository, task_id, limit=limit))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/next-step")
    def get_task_next_step(task_id: str) -> object:
        try:
            limit = _bounded_limit(request.args.get("limit", "5"), default=5, maximum=10)
            return jsonify(build_next_step_plan(repository, task_id, limit=limit))
        except KeyError:
            abort(404)

    @app.get("/api/memory/search")
    def api_memory_search() -> object:
        query = request.args.get("q", "").strip()
        subject_scope = request.args.get("subject", "").strip()
        limit = _bounded_limit(request.args.get("limit", "8"))
        return jsonify(build_memory_search(repository, query, limit=limit, subject_scope=subject_scope))

    @app.get("/api/memory/profile")
    @app.get("/api/memory/profile/<profile_id>")
    def api_memory_profile(profile_id: str = "workspace") -> object:
        return jsonify(build_workspace_profile_memory(repository, profile_id=profile_id))

    @app.get("/api/memory/subjects/<path:subject>")
    def api_memory_subject(subject: str) -> object:
        return jsonify(build_subject_memory(repository, subject))

    @app.get("/api/memory/tasks/<task_id>")
    def api_memory_task(task_id: str) -> object:
        try:
            return jsonify(build_task_memory_context(repository, task_id))
        except KeyError:
            abort(404)

    return app


def build_memory_search(
    repository: TaskBrowseRepository,
    query: str,
    limit: int = 8,
    subject_scope: str | None = None,
) -> dict[str, object]:
    query = query.strip()
    subject_scope = (subject_scope or "").strip() or None
    effective_query = query or (subject_scope or "")
    normalized_subject_scope = _normalize_subject_key(subject_scope) if subject_scope else None
    summaries = {str(item.get("task_id", "")): item for item in repository.list_tasks()}
    ranked_records = (
        repository.search_memory(
            effective_query,
            limit=max(limit * 4, limit),
            subject_key=normalized_subject_scope,
        )
        if effective_query
        else []
    )
    best_by_task: dict[str, dict[str, object]] = {}
    for record in ranked_records:
        task_id = str(record.get("task_id", ""))
        if not task_id:
            continue
        current = best_by_task.get(task_id)
        if current is None or float(record.get("score", 0.0)) > float(current.get("score", 0.0)):
            best_by_task[task_id] = record
    records = sorted(
        best_by_task.values(),
        key=lambda item: (-float(item.get("score", 0.0)), str(item.get("task_id", "")), str(item.get("artifact_id", ""))),
    )[:limit]
    results: list[dict[str, object]] = []
    strategy = "hash_vector_v1"

    for record in records:
        task_id = str(record.get("task_id", ""))
        summary = summaries.get(task_id)
        if not task_id or summary is None:
            continue
        try:
            task = repository.get_task(task_id)
            artifacts = list(repository.read_artifacts(task_id))
        except KeyError:
            continue
        doc = _memory_document(task_id, summary, task, artifacts)
        snippets = _memory_snippets(doc, effective_query.casefold()) if effective_query else []
        embedding = dict(record.get("embedding", {}))
        if embedding.get("algorithm"):
            strategy = str(embedding.get("algorithm"))
        results.append(
            {
                "task_id": task_id,
                "prompt": doc["prompt"],
                "resolved_subject": doc["resolved_subject"],
                "family": doc["family"],
                "status": doc["status"],
                "reason": doc["reason"],
                "score": round(float(record.get("score", 0.0)), 4),
                "snippets": snippets,
                "href": f"/memory/tasks/{task_id}",
            }
        )

    return {
        "query": query,
        "effective_query": effective_query,
        "subject_scope": subject_scope,
        "limit": limit,
        "strategy": strategy,
        "results": results[:limit],
    }


def build_app_shell(repository: TaskBrowseRepository) -> dict[str, object]:
    tasks = repository.list_tasks()
    statuses = Counter(str(task.get("status", "") or "unknown") for task in tasks)
    memory_docs = len(repository.list_memory_documents())
    success_rate = round((statuses.get("success", 0) / len(tasks)) * 100) if tasks else 0
    families = len({str(task.get("family", "")).strip() for task in tasks if str(task.get("family", "")).strip()})
    return {
        "stats": [
            {"label": "runs", "value": len(tasks)},
            {"label": "success", "value": f"{success_rate}%"},
            {"label": "families", "value": families},
            {"label": "memory docs", "value": memory_docs},
        ],
        "status_counts": [
            {"label": "partial", "value": statuses.get("partial", 0)},
            {"label": "failed", "value": statuses.get("failed", 0)},
        ],
        "signals": [
            "Schema, memory, and retries stay visible in one operating surface.",
            "Memory remains scoped by subject, profile, and task stage.",
            "Failures and branch points stay readable before raw artifacts.",
        ],
    }


def build_task_dashboard(repository: TaskBrowseRepository) -> dict[str, object]:
    raw_tasks = repository.list_tasks()
    tasks: list[dict[str, object]] = []
    statuses: Counter[str] = Counter()
    families: Counter[str] = Counter()
    evolved = 0
    attempts_total = 0

    for task in raw_tasks:
        task_id = str(task.get("task_id", ""))
        try:
            detail = repository.get_task(task_id)
        except KeyError:
            detail = {}
        run = dict(detail.get("run") or {})
        schema_versions = list(detail.get("schema_versions") or [])
        extractions = list(detail.get("extractions") or [])
        coverages = list(detail.get("coverage_reports") or [])
        latest_coverage = dict(coverages[-1]) if coverages else {}
        latest_extraction = dict(extractions[-1]) if extractions else {}
        attempts = int(run.get("attempts") or len(extractions) or 0)
        schema_rounds = int(run.get("schema_rounds") or max(len(schema_versions) - 1, 0))
        active_schema = dict(schema_versions[-1]) if schema_versions else {}
        is_evolved = schema_rounds > 0 or len(schema_versions) > 1
        if is_evolved:
            evolved += 1
        status = str(task.get("status", "") or "unknown")
        family = str(task.get("family", "") or "")
        statuses[status] += 1
        if family:
            families[family] += 1
        attempts_total += attempts
        dominant_issue = str(latest_coverage.get("dominant_issue") or "none")
        next_action = _task_next_action(run, latest_coverage)
        queue_state = _queue_state(status, dominant_issue)
        tasks.append(
            {
                **task,
                "latest_processed_label": _format_processed_at(str(task.get("latest_processed_at", "") or "")),
                "attempts": attempts,
                "schema_rounds": schema_rounds,
                "schema_version": active_schema.get("version"),
                "is_evolved": is_evolved,
                "prompt_preview": _truncate(str(task.get("prompt", "")), 120),
                "dominant_issue": dominant_issue,
                "issue_preview": _coverage_preview(latest_coverage),
                "next_action": next_action,
                "queue_state": queue_state,
                "schema_code": _pretty_json(_schema_code_view(active_schema)) if active_schema else "{}",
                "latest_key_preview": sorted(dict(latest_extraction.get("payload") or {}).keys())[:8],
                "branch_summary": _branch_summary_text(run, latest_coverage),
                "search_text": " ".join(
                    [
                        str(task.get("prompt", "")),
                        str(task.get("resolved_subject", "")),
                        family,
                        status,
                        str(task.get("reason", "")),
                        dominant_issue,
                        _coverage_preview(latest_coverage),
                    ]
                ).casefold(),
            }
        )

    tasks.sort(
        key=lambda item: (
            str(item.get("latest_processed_at", "")),
            str(item.get("task_id", "")),
        ),
        reverse=True,
    )
    memory_docs = len(repository.list_memory_documents())
    average_attempts = round(attempts_total / len(tasks), 1) if tasks else 0.0
    success_rate = round((statuses.get("success", 0) / len(tasks)) * 100) if tasks else 0
    return {
        "tasks": tasks,
        "stats": [
            {"label": "task runs", "value": len(tasks)},
            {"label": "need review", "value": statuses.get("partial", 0) + statuses.get("failed", 0)},
            {"label": "schema-evolved", "value": evolved},
            {"label": "memory docs", "value": memory_docs},
            {"label": "success rate", "value": f"{success_rate}%"},
        ],
        "status_breakdown": [
            {"label": "success", "value": statuses.get("success", 0)},
            {"label": "partial", "value": statuses.get("partial", 0)},
            {"label": "failed", "value": statuses.get("failed", 0)},
            {"label": "avg attempts", "value": average_attempts},
        ],
        "signals": [
            {
                "title": "Recent first",
                "text": "The queue stays sorted by the latest processed run so fresh work rises to the top.",
            },
            {
                "title": "Trace second",
                "text": "Every row should tell you the branch reason before you open the trace.",
            },
            {
                "title": "Evidence third",
                "text": "Schema changes and recalled memory stay separate from the raw ledger.",
            },
        ],
        "filters": {
            "statuses": sorted(status for status in statuses if status and status != "unknown"),
            "families": sorted(family for family in families if family),
        },
    }


def build_task_trace_memory_panel(
    repository: TaskBrowseRepository,
    task_id: str,
    trace: dict[str, object],
) -> dict[str, object] | None:
    try:
        memory_context = repository.get_task_memory_context(task_id)
    except KeyError:
        return None

    payload = dict(memory_context.get("payload", {}))
    resolved_subject = str(trace.get("summary", {}).get("resolved_subject", "") or payload.get("resolved_subject", ""))
    subject_summary = repository.get_subject_memory(resolved_subject) if resolved_subject else None

    return {
        "summary": str(memory_context.get("summary", "")),
        "profile_key": str(memory_context.get("profile_key", "")),
        "subject_key": str(memory_context.get("subject_key", "")),
        "family": str(memory_context.get("family", "")),
        "task_shape": str(payload.get("task_shape", "")),
        "intent": str(payload.get("intent", "")),
        "schema_version": payload.get("schema_version"),
        "schema_id": str(payload.get("schema_id", "")),
        "facts": _memory_fact_lines(payload),
        "task_href": f"/memory/tasks/{task_id}",
        "subject_href": f"/memory/subjects/{quote(resolved_subject, safe='')}" if resolved_subject else "",
        "related_documents": len(subject_summary.get("memory_documents", [])) if subject_summary else 0,
        "related_contexts": len(subject_summary.get("task_memory_contexts", [])) if subject_summary else 0,
        "related_profiles": len(subject_summary.get("profiles", [])) if subject_summary else 0,
        "evidence": _memory_evidence_items(task_id, subject_summary),
        "context_code": _pretty_json(
            {
                "profile_key": memory_context.get("profile_key"),
                "subject_key": memory_context.get("subject_key"),
                "family": memory_context.get("family"),
                "summary": memory_context.get("summary"),
                "payload": payload,
            }
        ),
    }


def build_trace_operator_view(
    task: dict[str, object],
    *,
    memory_panel: dict[str, object] | None = None,
) -> dict[str, object]:
    interpretation = dict(task.get("interpretation") or {})
    run = dict(task.get("run") or {})
    extractions = list(task.get("extractions") or [])
    coverages = list(task.get("coverage_reports") or [])
    schema_versions = list(task.get("schema_versions") or [])
    latest_coverage = dict(coverages[-1]) if coverages else {}
    latest_schema = dict(schema_versions[-1]) if schema_versions else {}
    latest_extraction = dict(extractions[-1]) if extractions else {}

    attempts: list[dict[str, object]] = []
    for index, extraction in enumerate(extractions, start=1):
        payload = dict(extraction.get("payload") or {})
        coverage = dict(coverages[index - 1]) if index - 1 < len(coverages) else {}
        attempts.append(
            {
                "attempt": int(extraction.get("attempt") or index),
                "status": str(extraction.get("status") or "unknown"),
                "schema_version": extraction.get("schema_version"),
                "returned_keys": len(payload),
                "reason": str(run.get("reason") or "n/a"),
                "key_preview": sorted(payload.keys())[:4],
                "dominant_issue": str(coverage.get("dominant_issue") or "none"),
                "missing_values": [str(item) for item in coverage.get("missing_values", [])][:3],
                "missing_fields": [str(item) for item in coverage.get("missing_fields", [])][:3],
                "missing_relations": [str(item) for item in coverage.get("missing_relations", [])][:3],
                "next_action": _attempt_next_action(index, extraction, coverage, run, len(extractions)),
                "payload_code": _pretty_json(payload),
                "coverage_code": _pretty_json(coverage),
                "missing_preview": _coverage_preview(coverage) or "none",
            }
        )

    schema_deltas: list[dict[str, object]] = []
    previous_schema: dict[str, object] | None = None
    for schema in schema_versions:
        current = dict(schema)
        schema_deltas.append(_schema_delta(previous_schema, current))
        previous_schema = current

    dominant_issue = str(latest_coverage.get("dominant_issue") or "none")
    summary_badges = [
        {"label": "status", "value": str(run.get("status") or "unknown")},
        {"label": "reason", "value": str(run.get("reason") or "n/a")},
        {"label": "dominant issue", "value": dominant_issue},
        {"label": "family", "value": str(interpretation.get("family") or "n/a")},
    ]
    if memory_panel:
        summary_badges.append({"label": "memory profile", "value": str(memory_panel.get("profile_key") or "workspace")})

    top_cards = [
        {
            "label": "Outcome",
            "value": f"{run.get('status') or 'unknown'} / {run.get('reason') or 'n/a'}",
            "tone": _tone_for_status(str(run.get("status") or "unknown")),
            "note": "Final state",
        },
        {
            "label": "Branch",
            "value": dominant_issue.replace("_", " "),
            "tone": "schema" if dominant_issue == "schema" else "warning" if dominant_issue == "values" else "neutral",
            "note": _coverage_preview(latest_coverage) or "No open gap",
        },
        {
            "label": "Schema",
            "value": f"v{latest_schema.get('version', 'n/a')}",
            "tone": "schema",
            "note": f"{len(schema_versions)} version(s), {run.get('schema_rounds') or 0} round(s)",
        },
        {
            "label": "Memory",
            "value": str(memory_panel.get("subject_key") or "n/a") if memory_panel else "n/a",
            "tone": "memory",
            "note": f"{memory_panel.get('related_documents', 0)} related memory doc(s)" if memory_panel else "No recall context",
        },
    ]

    return {
        "summary_badges": summary_badges,
        "top_cards": top_cards,
        "why_it_branched": _why_it_branched(run, latest_coverage, latest_schema),
        "attempts": attempts,
        "schema_deltas": schema_deltas,
        "schema_versions": [
            {
                "version": schema.get("version"),
                "family": schema.get("family"),
                "schema_id": schema.get("schema_id"),
                "code": _pretty_json(_schema_code_view(schema)),
            }
            for schema in schema_versions
        ],
        "active_schema_code": _pretty_json(_schema_code_view(latest_schema)) if latest_schema else "{}",
        "latest_payload_code": _pretty_json(dict(latest_extraction.get("payload") or {})) if latest_extraction else "{}",
        "has_schema_evolution": len(schema_versions) > 1,
        "has_memory_evidence": bool(memory_panel and memory_panel.get("evidence")),
    }


def build_workspace_profile_memory(repository: TaskBrowseRepository, profile_id: str = "workspace") -> dict[str, object]:
    if profile_id != "workspace":
        profile = repository.get_user_profile(profile_id)
        docs = repository.list_memory_documents(profile_key=profile_id)
        payload = dict(profile.get("payload", {}))
        top_subjects = list(payload.get("top_subjects", []))
        top_families = list(payload.get("top_families", []))
        top_fields = list(payload.get("top_requested_fields", []))
        top_relations = list(payload.get("top_requested_relations", []))
        subject_cards = [
            {
                "href": f"/memory/subjects/{quote(subject, safe='')}",
                "title": subject,
                "subtitle": "Recalled from this profile",
                "chips": [{"label": "profile", "value": profile_id}],
                "score": None,
                "snippets": [],
            }
            for subject in top_subjects[:6]
        ]
        recent_cards = _unique_task_cards(docs, limit=6)
        return {
            "kind": "profile",
            "profile_id": profile_id,
            "title": f"User Profile Memory: {profile_id}",
            "subtitle": "Per-profile memory aggregated from prior task runs and extractions.",
            "stats": [
                {"label": "tasks", "value": payload.get("task_count", 0)},
                {"label": "families", "value": len(top_families)},
                {"label": "subjects", "value": len(top_subjects)},
                {"label": "fields", "value": len(top_fields)},
            ],
            "search_query": "",
            "blocks": [
                {
                    "title": "Profile Summary",
                    "description": "Auto-aggregated preferences and recall cues for this profile.",
                    "lines": [
                        str(payload.get("summary", profile.get("summary", ""))),
                        f"preferred locale: {payload.get('preferred_locale', 'auto')}",
                        f"top families: {', '.join(top_families) or 'n/a'}",
                        f"top subjects: {', '.join(top_subjects) or 'n/a'}",
                    ],
                },
                {
                    "title": "Requested Fields",
                    "description": "Fields this profile asks for frequently.",
                    "chips": [{"label": item, "value": "field"} for item in top_fields[:10]],
                },
                {
                    "title": "Requested Relations",
                    "description": "Relations this profile asks for frequently.",
                    "chips": [{"label": item, "value": "relation"} for item in top_relations[:10]],
                },
                {
                    "title": "Subject Recall",
                    "description": "Subjects most associated with this profile.",
                    "cards": subject_cards,
                },
                {
                    "title": "Recent Task Memory",
                    "description": "Task memories associated with this profile.",
                    "cards": recent_cards,
                },
            ],
        }

    docs = _collect_memory_documents(repository)
    families = Counter(doc["family"] for doc in docs if doc["family"])
    subjects = Counter(doc["resolved_subject"] for doc in docs if doc["resolved_subject"])
    statuses = Counter(doc["status"] for doc in docs if doc["status"])
    locales = Counter(doc["locale"] for doc in docs if doc["locale"])
    learned_keys = Counter()
    for doc in docs:
        learned_keys.update(doc["learned_keys"])

    recent_cards = _unique_task_cards(reversed(docs), limit=5)
    subject_cards = [
        {
            "href": f"/memory/subjects/{quote(subject, safe='')}",
            "title": subject,
            "subtitle": f"{count} related tasks",
            "chips": [{"label": "tasks", "value": count}],
            "score": None,
            "snippets": [],
        }
        for subject, count in subjects.most_common(6)
    ]
    family_chips = [{"label": family, "value": count} for family, count in families.most_common(6)]
    key_chips = [{"label": key, "value": count} for key, count in learned_keys.most_common(10)]
    summary_lines = [
        f"tasks recorded: {len(docs)}",
        f"successes: {statuses.get('success', 0)}",
        f"partials: {statuses.get('partial', 0)}",
        f"failures: {statuses.get('failed', 0)}",
        f"top family: {families.most_common(1)[0][0] if families else 'n/a'}",
        f"top subject: {subjects.most_common(1)[0][0] if subjects else 'n/a'}",
        f"top locale: {locales.most_common(1)[0][0] if locales else 'n/a'}",
    ]
    profile_cards = [
        {
            "href": f"/memory/profile/{quote(str(profile.get('profile_key', 'workspace')), safe='')}",
            "title": str(profile.get("profile_key", "workspace")),
            "subtitle": str(profile.get("summary", "")),
            "chips": [
                {"label": "tasks", "value": dict(profile.get("payload", {})).get("task_count", 0)},
            ],
            "score": None,
            "snippets": [],
        }
        for profile in repository.list_user_profiles()[:8]
    ]
    blocks = [
        {
            "title": "Workspace Summary",
            "description": "Workspace-scoped memory snapshot across all saved profiles and task lineage.",
            "lines": summary_lines,
        },
        {
            "title": "Saved Profiles",
            "description": "Per-profile memory snapshots available for direct recall.",
            "cards": profile_cards,
        },
        {
            "title": "Frequent Families",
            "description": "Families that recur in this workspace.",
            "chips": family_chips,
        },
        {
            "title": "Learned Keys",
            "description": "Field and relation names repeatedly extracted across tasks.",
            "chips": key_chips,
        },
        {
            "title": "Subject Memory",
            "description": "Open a subject to recall prior extractions and learned facts.",
            "cards": subject_cards,
        },
        {
            "title": "Recent Task Memory",
            "description": "Most recent task contexts available for recall.",
            "cards": recent_cards,
        },
    ]
    return {
        "kind": "profile",
        "profile_id": profile_id,
        "title": "Workspace Profile Memory",
        "subtitle": "Aggregated workspace memory built from prior task runs and extractions.",
        "stats": [
            {"label": "tasks", "value": len(docs)},
            {"label": "families", "value": len(families)},
            {"label": "subjects", "value": len(subjects)},
            {"label": "keys", "value": len(learned_keys)},
        ],
        "search_query": "",
        "blocks": blocks,
    }


def build_subject_memory(repository: TaskBrowseRepository, subject: str, limit: int = 6) -> dict[str, object]:
    docs = _collect_memory_documents(repository)
    normalized = subject.casefold().strip()
    normalized_subject_key = _normalize_subject_key(subject)
    search_bundle = build_memory_search(repository, subject, limit=limit, subject_scope=subject)
    exact_matches = [
        doc
        for doc in docs
        if normalized_subject_key and _memory_record_matches_subject(doc, normalized_subject_key)
    ]
    search_results = search_bundle["results"]
    related_docs = [
        doc
        for doc in _task_docs_from_search_results(search_results, docs)
        if normalized_subject_key and _memory_record_matches_subject(doc, normalized_subject_key)
    ]
    if not related_docs and not exact_matches:
        related_docs = _task_docs_from_search_results(search_results, docs)
    if not exact_matches:
        exact_matches = related_docs

    learned_facts = _aggregate_learned_facts(exact_matches)
    related_cards = [_memory_task_card(doc, href=f"/memory/tasks/{doc['task_id']}") for doc in related_docs[:limit]]
    summary_lines = [
        f"matched tasks: {len(exact_matches)}",
        f"retrieval strategy: {search_bundle['strategy']}",
        f"subject key: {subject}",
    ]
    if exact_matches:
        summary_lines.append(f"latest family: {exact_matches[-1]['family'] or 'n/a'}")
        summary_lines.append(f"latest status: {exact_matches[-1]['status'] or 'n/a'}")
    else:
        summary_lines.append("no direct matches yet")
    return {
        "kind": "subject",
        "subject": subject,
        "title": f"Subject Memory: {subject}",
        "subtitle": "Prior learnings auto-aggregated from related task runs.",
        "stats": [
            {"label": "matches", "value": len(exact_matches)},
            {"label": "facts", "value": len(learned_facts)},
            {"label": "related", "value": len(related_cards)},
        ],
        "search_query": subject,
        "subject_scope": subject,
        "blocks": [
            {
                "title": "Recall Context",
                "description": "What the workspace has already learned about this subject.",
                "lines": summary_lines,
            },
            {
                "title": "Learned Facts",
                "description": "Latest extraction keys and values from matching tasks.",
                "lines": learned_facts or ["No learned facts recorded yet."],
            },
            {
                "title": "Related Tasks",
                "description": "Tasks most relevant to this subject.",
                "cards": related_cards,
            },
        ],
        "related_tasks": related_docs[:limit],
        "learned_facts": learned_facts,
        "recall_context": "\n".join(summary_lines + learned_facts[:8]),
    }


def build_task_memory_context(repository: TaskBrowseRepository, task_id: str, limit: int = 6) -> dict[str, object]:
    task = repository.get_task(task_id)
    interpretation = dict(task.get("interpretation") or {})
    run = dict(task.get("run") or {})
    prompt = str(task.get("prompt") or "")
    subject = str(interpretation.get("resolved_subject") or "").strip()
    family = str(interpretation.get("family") or "")
    latest_schema = dict(task.get("schema_versions", [])[-1] if task.get("schema_versions") else {})
    latest_extraction = _latest_extraction(task)
    learned_facts = _learned_facts_from_task(task)
    query = subject or prompt
    search_results = (
        build_memory_search(repository, query, limit=limit, subject_scope=subject or None)["results"] if query else []
    )
    related_cards = [
        _memory_task_card(result, href=f"/memory/tasks/{result['task_id']}")
        for result in search_results
        if result["task_id"] != task_id
    ]
    recall_lines = [
        f"prompt: {prompt or 'n/a'}",
        f"resolved subject: {subject or 'n/a'}",
        f"family: {family or 'n/a'}",
        f"status: {run.get('status', '') or 'n/a'}",
        f"reason: {run.get('reason', '') or 'n/a'}",
        f"latest schema version: {latest_schema.get('version', 'n/a')}",
    ]
    if latest_extraction:
        recall_lines.append(f"latest extraction attempt: {latest_extraction.get('attempt', 'n/a')}")
    return {
        "kind": "task",
        "task_id": task_id,
        "title": subject or task_id,
        "subtitle": prompt or "Task memory context",
        "task_trace_url": f"/tasks/{task_id}",
        "stats": [
            {"label": "family", "value": family or "n/a"},
            {"label": "status", "value": run.get("status", "") or "n/a"},
            {"label": "facts", "value": len(learned_facts)},
            {"label": "related", "value": len(related_cards)},
        ],
        "search_query": query,
        "subject_scope": subject or None,
        "blocks": [
            {
                "title": "Task Snapshot",
                "description": "Current task identity and outcome.",
                "lines": recall_lines,
            },
            {
                "title": "Recall Context",
                "description": "What should be carried forward into the next task or follow-up prompt.",
                "lines": _task_recall_context(task, learned_facts),
            },
            {
                "title": "Learned Facts",
                "description": "Compact values extracted by the runtime.",
                "lines": learned_facts or ["No extracted facts recorded yet."],
            },
            {
                "title": "Related Tasks",
                "description": "Vector-search neighbors and subject peers.",
                "cards": related_cards,
            },
        ],
        "related_tasks": search_results,
        "learned_facts": learned_facts,
        "recall_context": "\n".join(_task_recall_context(task, learned_facts)),
        "latest_schema_version": latest_schema.get("version"),
        "latest_schema_id": latest_schema.get("schema_id"),
    }


def _collect_memory_documents(repository: TaskBrowseRepository) -> list[dict[str, object]]:
    docs: list[dict[str, object]] = []
    for summary in repository.list_tasks():
        task_id = str(summary.get("task_id", ""))
        if not task_id:
            continue
        try:
            task = repository.get_task(task_id)
            artifacts = list(repository.read_artifacts(task_id))
        except KeyError:
            continue
        docs.append(_memory_document(task_id, summary, task, artifacts))
    return docs


def _memory_document(
    task_id: str,
    summary: dict[str, object],
    task: dict[str, object],
    artifacts: list[dict[str, object]],
) -> dict[str, object]:
    interpretation = dict(task.get("interpretation") or {})
    run = dict(task.get("run") or {})
    extractions = [dict(item) for item in task.get("extractions", [])]
    latest_extraction = extractions[-1] if extractions else {}
    schema_versions = [dict(item) for item in task.get("schema_versions", [])]
    latest_schema = schema_versions[-1] if schema_versions else {}
    prompt_artifact = next((artifact for artifact in artifacts if artifact["artifact_type"] == "task_prompt"), {})
    locale = str(dict(prompt_artifact.get("payload", {})).get("locale", ""))
    learned_facts = _learned_facts_from_extraction(latest_extraction)
    learned_keys = list(dict.fromkeys(_learned_keys_from_extractions(extractions)))
    event_kinds = [str(event.get("kind", "")) for event in task.get("events", []) if event.get("kind")]
    text_parts = [
        str(task.get("prompt", "")),
        str(interpretation.get("resolved_subject", "")),
        str(interpretation.get("family", "")),
        str(run.get("status", "")),
        str(run.get("reason", "")),
        " ".join(learned_facts),
        " ".join(learned_keys),
        " ".join(event_kinds),
        str(latest_schema.get("rationale", "")),
    ]
    search_text = " ".join(part for part in text_parts if part)
    return {
        "task_id": task_id,
        "prompt": str(task.get("prompt", "")),
        "resolved_subject": str(interpretation.get("resolved_subject", "")),
        "family": str(interpretation.get("family", "")),
        "status": str(run.get("status", "")),
        "reason": str(run.get("reason", "")),
        "locale": locale,
        "learned_facts": learned_facts,
        "learned_keys": learned_keys,
        "search_text": search_text,
        "latest_schema_version": latest_schema.get("version"),
        "latest_schema_id": latest_schema.get("schema_id"),
        "summary": summary,
    }


def _task_docs_from_search_results(results: list[dict[str, object]], docs: list[dict[str, object]]) -> list[dict[str, object]]:
    by_id = {str(doc["task_id"]): doc for doc in docs}
    return [by_id[result["task_id"]] for result in results if str(result.get("task_id", "")) in by_id]


def _tokenize(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(text or "") if token.strip()]


def _memory_snippets(doc: dict[str, object], query_text: str) -> list[str]:
    tokens = set(_tokenize(query_text))
    snippets: list[str] = []
    prompt = str(doc.get("prompt", ""))
    subject = str(doc.get("resolved_subject", ""))
    family = str(doc.get("family", ""))
    if prompt:
        snippets.append(_truncate(prompt, 160))
    if subject and subject != prompt:
        snippets.append(f"subject: {subject}")
    if family:
        snippets.append(f"family: {family}")
    for fact in doc.get("learned_facts", []):
        text = str(fact)
        if any(token in text.casefold() for token in tokens) or not snippets:
            snippets.append(_truncate(text, 140))
        if len(snippets) >= 4:
            break
    return snippets[:4]


def _learned_keys_from_extractions(extractions: list[dict[str, object]]) -> list[str]:
    keys: list[str] = []
    for extraction in extractions:
        payload = dict(extraction.get("payload", {}))
        keys.extend(sorted(str(key) for key in payload.keys()))
    return keys


def _learned_facts_from_task(task: dict[str, object]) -> list[str]:
    facts: list[str] = []
    for extraction in task.get("extractions", []):
        facts.extend(_learned_facts_from_extraction(dict(extraction)))
    return list(dict.fromkeys(facts))


def _learned_facts_from_extraction(extraction: dict[str, object]) -> list[str]:
    payload = dict(extraction.get("payload", {}))
    if not payload:
        return []
    facts: list[str] = []
    for key, value in payload.items():
        facts.append(f"{key}: {_summarize_value(value)}")
    return facts


def _aggregate_learned_facts(tasks: list[dict[str, object]]) -> list[str]:
    facts: list[str] = []
    for task in tasks:
        if task.get("learned_facts"):
            facts.extend(str(item) for item in task.get("learned_facts", []))
            continue
        facts.extend(_learned_facts_from_task(task))
    return list(dict.fromkeys(facts))


def _latest_extraction(task: dict[str, object]) -> dict[str, object]:
    extractions = [dict(item) for item in task.get("extractions", [])]
    return extractions[-1] if extractions else {}


def _task_recall_context(task: dict[str, object], learned_facts: list[str]) -> list[str]:
    interpretation = dict(task.get("interpretation") or {})
    run = dict(task.get("run") or {})
    schema_versions = [dict(item) for item in task.get("schema_versions", [])]
    latest_schema = schema_versions[-1] if schema_versions else {}
    lines = [
        f"resolved_subject: {interpretation.get('resolved_subject', '') or 'n/a'}",
        f"family: {interpretation.get('family', '') or 'n/a'}",
        f"run status: {run.get('status', '') or 'n/a'} / {run.get('reason', '') or 'n/a'}",
        f"schema version: {latest_schema.get('version', 'n/a')}",
    ]
    lines.extend(learned_facts[:6])
    return _dedupe_lines(lines)


def _memory_task_card(doc: dict[str, object], href: str) -> dict[str, object]:
    chips = [
        {"label": "family", "value": doc.get("family") or "n/a"},
        {"label": "status", "value": doc.get("status") or "n/a"},
        {"label": "reason", "value": doc.get("reason") or "n/a"},
    ]
    if doc.get("latest_schema_version") is not None:
        chips.append({"label": "schema", "value": f"v{doc.get('latest_schema_version')}"})
    return {
        "href": href,
        "title": doc.get("resolved_subject") or doc.get("task_id"),
        "subtitle": doc.get("prompt") or "",
        "chips": chips,
        "score": doc.get("score"),
        "snippets": doc.get("snippets", []),
    }


def _memory_evidence_items(task_id: str, subject_summary: dict[str, object] | None, limit: int = 4) -> list[dict[str, object]]:
    if not subject_summary:
        return []
    evidence: list[dict[str, object]] = []
    for document in subject_summary.get("memory_documents", []):
        if str(document.get("task_id", "")) == task_id:
            continue
        evidence.append(
            {
                "task_id": str(document.get("task_id", "")),
                "memory_type": str(document.get("memory_type", "memory_document")),
                "summary": str(document.get("summary", "")),
                "href": f"/memory/tasks/{document.get('task_id', '')}",
            }
        )
        if len(evidence) >= limit:
            break
    return evidence


def _attempt_next_action(
    index: int,
    extraction: dict[str, object],
    coverage: dict[str, object],
    run: dict[str, object],
    total_attempts: int,
) -> str:
    dominant_issue = str(coverage.get("dominant_issue") or "none")
    if dominant_issue == "values":
        return "re-extract"
    if dominant_issue == "schema":
        return "evolve schema"
    if index == total_attempts:
        reason = str(run.get("reason") or "")
        if reason == "complete":
            return "complete"
        if reason:
            return reason.replace("_", " ")
    status = str(extraction.get("status") or "")
    return status or "continue"


def _queue_state(status: str, dominant_issue: str) -> str:
    if status == "failed":
        return "failed"
    if status == "partial":
        if dominant_issue == "schema":
            return "schema"
        if dominant_issue == "values":
            return "retry"
        return "partial"
    if status == "success":
        return "complete"
    return "neutral"


def _task_next_action(run: dict[str, object], coverage: dict[str, object]) -> str:
    dominant_issue = str(coverage.get("dominant_issue") or "none")
    reason = str(run.get("reason") or "")
    if dominant_issue == "schema":
        return "evolve schema"
    if dominant_issue == "values":
        return "retry extraction"
    if reason == "complete":
        return "stable"
    if reason:
        return reason.replace("_", " ")
    return "review"


def _branch_summary_text(run: dict[str, object], coverage: dict[str, object]) -> str:
    dominant_issue = str(coverage.get("dominant_issue") or "none")
    preview = _coverage_preview(coverage)
    if dominant_issue == "schema":
        return f"Schema gap: {preview or 'structure missing'}"
    if dominant_issue == "values":
        return f"Value gap: {preview or 'values missing'}"
    reason = str(run.get("reason") or "")
    if reason == "complete":
        return "Stable outcome"
    if reason:
        return reason.replace("_", " ")
    return "No open branch"


def _coverage_preview(coverage: dict[str, object]) -> str:
    missing_values = [str(item) for item in coverage.get("missing_values", [])]
    missing_fields = [str(item) for item in coverage.get("missing_fields", [])]
    missing_relations = [str(item) for item in coverage.get("missing_relations", [])]
    if missing_values:
        return ", ".join(missing_values[:2])
    if missing_fields:
        return ", ".join(missing_fields[:2])
    if missing_relations:
        return ", ".join(missing_relations[:2])
    return ""


def _format_processed_at(value: str) -> str:
    value = value.strip()
    if not value:
        return "n/a"
    try:
        normalized = value.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)
        return timestamp.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


def _tone_for_status(status: str) -> str:
    if status == "success":
        return "success"
    if status == "failed":
        return "failed"
    if status == "partial":
        return "warning"
    return "neutral"


def _schema_code_view(schema: dict[str, object]) -> dict[str, object]:
    return {
        "schema_id": schema.get("schema_id"),
        "family": schema.get("family"),
        "version": schema.get("version"),
        "required_fields": schema.get("required_fields", []),
        "optional_fields": schema.get("optional_fields", []),
        "relations": schema.get("relations", []),
        "rationale": schema.get("rationale", ""),
    }


def _why_it_branched(
    run: dict[str, object],
    coverage: dict[str, object],
    schema: dict[str, object],
) -> list[dict[str, str]]:
    dominant_issue = str(coverage.get("dominant_issue") or "none")
    missing_values = [str(item) for item in coverage.get("missing_values", [])]
    missing_fields = [str(item) for item in coverage.get("missing_fields", [])]
    missing_relations = [str(item) for item in coverage.get("missing_relations", [])]
    items = [
        {"label": "dominant issue", "value": dominant_issue},
        {"label": "missing values", "value": str(len(missing_values))},
        {"label": "missing fields", "value": str(len(missing_fields))},
        {"label": "missing relations", "value": str(len(missing_relations))},
        {"label": "active schema", "value": f"v{schema.get('version', 'n/a')}"},
        {"label": "next state", "value": str(run.get("reason") or "n/a").replace("_", " ")},
    ]
    if missing_values:
        items.append({"label": "values gap", "value": ", ".join(missing_values[:2])})
    elif missing_fields or missing_relations:
        structural = (missing_fields + missing_relations)[:2]
        items.append({"label": "structure gap", "value": ", ".join(structural)})
    return items


def _schema_delta(previous: dict[str, object] | None, current: dict[str, object]) -> dict[str, object]:
    previous_required = set(str(item) for item in (previous or {}).get("required_fields", []))
    previous_optional = set(str(item) for item in (previous or {}).get("optional_fields", []))
    previous_relations = set(str(item) for item in (previous or {}).get("relations", []))
    current_required = [str(item) for item in current.get("required_fields", [])]
    current_optional = [str(item) for item in current.get("optional_fields", [])]
    current_relations = [str(item) for item in current.get("relations", [])]
    return {
        "version": current.get("version"),
        "schema_id": str(current.get("schema_id", "")),
        "family": str(current.get("family", "")),
        "added_required": [item for item in current_required if item not in previous_required],
        "added_optional": [item for item in current_optional if item not in previous_optional],
        "added_relations": [item for item in current_relations if item not in previous_relations],
        "rationale": str(current.get("rationale", "")),
    }


def _memory_fact_lines(payload: dict[str, object], limit: int = 6) -> list[str]:
    extractions = payload.get("extractions", [])
    if not isinstance(extractions, list) or not extractions:
        return []
    latest = extractions[-1]
    if not isinstance(latest, dict):
        return []
    extraction_payload = latest.get("payload", {})
    if not isinstance(extraction_payload, dict):
        return []

    lines: list[str] = []
    for key, value in extraction_payload.items():
        preview = _preview_value(value)
        if not preview:
            continue
        lines.append(f"{key}: {preview}")
        if len(lines) >= limit:
            break
    return lines


def _preview_value(value: object) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value if len(value) <= 88 else value[:85] + "..."
    if isinstance(value, (bool, int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value[:3]:
            preview = _preview_value(item)
            if preview:
                parts.append(preview)
        if not parts:
            return ""
        text = ", ".join(parts)
        if len(value) > 3:
            text += f" +{len(value) - 3}"
        return text
    if isinstance(value, dict):
        parts = []
        for nested_key, nested_value in list(value.items())[:2]:
            preview = _preview_value(nested_value)
            if preview:
                parts.append(f"{nested_key}={preview}")
        return ", ".join(parts)
    return str(value)


def _unique_task_cards(documents, limit: int) -> list[dict[str, object]]:  # noqa: ANN001
    cards: list[dict[str, object]] = []
    seen: set[str] = set()
    for doc in documents:
        task_id = str(doc.get("task_id", ""))
        if not task_id or task_id in seen:
            continue
        seen.add(task_id)
        cards.append(_memory_task_card(doc, href=f"/memory/tasks/{task_id}"))
        if len(cards) >= limit:
            break
    return cards


def _summarize_value(value: object) -> str:
    if isinstance(value, dict):
        inner = ", ".join(f"{key}={_summarize_value(inner_value)}" for key, inner_value in list(value.items())[:4])
        return "{" + inner + ("..." if len(value) > 4 else "") + "}"
    if isinstance(value, (list, tuple, set)):
        items = [_summarize_value(item) for item in list(value)[:4]]
        if len(value) > 4:
            items.append("...")
        return "[" + ", ".join(items) + "]"
    return str(value)


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line and line not in seen:
            seen.add(line)
            result.append(line)
    return result


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _pretty_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)


def _bounded_limit(raw: str, default: int = 8, maximum: int = 20) -> int:
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(maximum, value))
