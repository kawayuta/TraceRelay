from __future__ import annotations

from collections import Counter
import re
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template, request

from .repository import TaskBrowseRepository

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3040-\u30ff\u4e00-\u9fff]+")


def create_app(repository: TaskBrowseRepository) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    @app.get("/tasks")
    def tasks_page() -> object:
        return render_template("task_list.html", tasks=repository.list_tasks())

    @app.get("/tasks/<task_id>")
    def task_trace_page(task_id: str) -> object:
        try:
            trace = repository.get_task_trace(task_id)
        except KeyError:
            abort(404)
        return render_template("task_trace.html", trace=trace)

    @app.get("/memory")
    @app.get("/memory/search")
    def memory_dashboard() -> object:
        query = request.args.get("q", "").strip()
        memory = build_workspace_profile_memory(repository)
        memory["search_query"] = query
        if query:
            search_result = build_memory_search(repository, query, limit=8)
            memory["blocks"].append(
                {
                    "title": "Vector Search Results",
                    "description": f"Top {len(search_result['results'])} matches using {search_result['strategy']}.",
                    "lines": [
                        f"query: {query}",
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

    @app.get("/api/memory/search")
    def api_memory_search() -> object:
        query = request.args.get("q", "").strip()
        limit = _bounded_limit(request.args.get("limit", "8"))
        return jsonify(build_memory_search(repository, query, limit=limit))

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


def build_memory_search(repository: TaskBrowseRepository, query: str, limit: int = 8) -> dict[str, object]:
    query = query.strip()
    summaries = {str(item.get("task_id", "")): item for item in repository.list_tasks()}
    ranked_records = repository.search_memory(query, limit=max(limit * 4, limit))
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
        snippets = _memory_snippets(doc, query.casefold())
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
        "limit": limit,
        "strategy": strategy,
        "results": results[:limit],
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
    search_bundle = build_memory_search(repository, subject, limit=limit)
    exact_matches = [
        doc
        for doc in docs
        if normalized
        and (
            normalized in str(doc["resolved_subject"]).casefold()
            or normalized in str(doc["prompt"]).casefold()
            or normalized in str(doc["search_text"]).casefold()
        )
    ]
    search_results = search_bundle["results"]
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
    search_results = build_memory_search(repository, query, limit=limit)["results"] if query else []
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


def _bounded_limit(raw: str, default: int = 8, maximum: int = 20) -> int:
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(maximum, value))
