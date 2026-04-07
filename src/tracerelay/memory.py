from __future__ import annotations

import re
import hashlib
from collections import Counter
from dataclasses import asdict
from typing import Any

from .embeddings import TextEmbedder, cosine_similarity, embedder_from_env
from .evolution.ids import next_id
from .models import (
    ArtifactRecord,
    ExtractionResult,
    MemoryDocument,
    MemoryHit,
    TaskInterpretation,
    TaskMemoryContext,
    TaskSpec,
    UserProfile,
)


def normalize_subject(text: str) -> str:
    lowered = text.strip().lower()
    normalized = re.sub(r"[^0-9a-zA-Z\u3040-\u30ff\u3400-\u9fff]+", "_", lowered)
    normalized = normalized.strip("_")
    if not normalized:
        return "unknown"
    if len(normalized) > 120:
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        normalized = f"{normalized[:96].rstrip('_')}_{digest}"
    return normalized


class ArtifactMemoryStore:
    def __init__(self, artifact_store: Any, embedder: TextEmbedder | None = None) -> None:
        self.artifact_store = artifact_store
        self.embedder = embedder or embedder_from_env()

    def build_context(
        self,
        spec: TaskSpec,
        interpretation: TaskInterpretation | None = None,
        *,
        exclude_task_id: str | None = None,
        top_k: int = 3,
    ) -> TaskMemoryContext:
        user_id = resolve_user_id(spec)
        profile = self.build_user_profile(user_id)
        prompt_hits = self.search(
            spec.prompt,
            user_id=user_id,
            exclude_task_id=exclude_task_id,
            top_k=top_k,
        )
        subject_hits: tuple[MemoryHit, ...] = ()
        if interpretation is not None:
            subject_aliases = {
                interpretation.resolved_subject,
                *interpretation.subject_candidates,
                *interpretation.subject_aliases,
                *(participant.subject for participant in interpretation.subject_participants),
                *(alias for participant in interpretation.subject_participants for alias in participant.aliases),
            }
            subject_hits = self.search(
                _subject_query(interpretation),
                user_id=user_id,
                subject_key=interpretation.scope_key or normalize_subject(interpretation.resolved_subject),
                subject_aliases=tuple(subject_aliases),
                family=interpretation.family,
                exclude_task_id=exclude_task_id,
                top_k=top_k,
            )
        context_lines = _context_lines(profile, prompt_hits, subject_hits)
        return TaskMemoryContext(
            user_id=user_id,
            profile=profile,
            prompt_hits=prompt_hits,
            subject_hits=subject_hits,
            context_text="\n".join(context_lines),
        )

    def search(
        self,
        query: str,
        *,
        user_id: str | None = None,
        subject_key: str | None = None,
        subject_aliases: tuple[str, ...] | None = None,
        family: str | None = None,
        exclude_task_id: str | None = None,
        kinds: tuple[str, ...] | None = None,
        top_k: int = 5,
    ) -> tuple[MemoryHit, ...]:
        query_vector = self.embedder.embed(query)
        query_algorithm = getattr(self.embedder, "algorithm", "hash_vector_v1")
        documents = list(self.all_memory_documents())
        normalized_aliases = {
            normalize_subject(alias)
            for alias in (subject_aliases or ())
            if str(alias).strip()
        }
        if subject_key:
            exact_subject_documents = [
                document for document in documents if document.subject_key == subject_key
            ]
            alias_documents = [
                document for document in documents if _document_subject_aliases(document).intersection(normalized_aliases)
            ]
            if exact_subject_documents or alias_documents:
                deduped: dict[str, MemoryDocument] = {}
                for document in exact_subject_documents + alias_documents:
                    deduped[document.memory_id] = document
                documents = list(deduped.values())
        results: list[MemoryHit] = []
        for document in documents:
            if exclude_task_id is not None and document.source_task_id == exclude_task_id:
                continue
            if kinds is not None and document.kind not in kinds:
                continue
            if document.algorithm != query_algorithm:
                continue
            score = cosine_similarity(list(query_vector), list(document.vector))
            if user_id is not None and document.user_id == user_id:
                score += 0.05
            if subject_key and document.subject_key == subject_key:
                score += 0.35
            elif normalized_aliases and _document_subject_aliases(document).intersection(normalized_aliases):
                score += 0.12
            if family and document.family == family:
                score += 0.1
            if document.kind == "extraction_summary":
                score += 0.05
            if score <= 0:
                continue
            results.append(
                MemoryHit(
                    memory_id=document.memory_id,
                    source_task_id=document.source_task_id,
                    kind=document.kind,
                    user_id=document.user_id,
                    subject=document.subject,
                    subject_key=document.subject_key,
                    family=document.family,
                    text=document.text,
                    score=round(score, 6),
                    metadata=dict(document.metadata),
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return tuple(results[:top_k])

    def all_memory_documents(self) -> tuple[MemoryDocument, ...]:
        documents: list[MemoryDocument] = []
        for artifact in self.artifact_store.all_artifacts():
            if artifact.artifact_type != "memory_document":
                continue
            payload = artifact.payload
            vector = tuple(float(value) for value in payload.get("vector", []))
            documents.append(
                MemoryDocument(
                    memory_id=str(payload["memory_id"]),
                    source_task_id=str(payload["source_task_id"]),
                    kind=str(payload["kind"]),
                    user_id=str(payload["user_id"]),
                    subject=str(payload.get("subject", "")),
                    subject_key=str(payload.get("subject_key", "")),
                    family=str(payload.get("family", "")),
                    text=str(payload.get("text", "")),
                    algorithm=str(payload.get("algorithm", "hash_vector_v1")),
                    vector=vector,
                    metadata=dict(payload.get("metadata", {})),
                )
            )
        return tuple(documents)

    def latest_user_profile(self, user_id: str) -> UserProfile | None:
        profiles = [
            self._profile_from_payload(artifact.payload)
            for artifact in self.artifact_store.all_artifacts()
            if artifact.artifact_type == "user_profile" and artifact.payload.get("user_id") == user_id
        ]
        if not profiles:
            return None
        return profiles[-1]

    def build_user_profile(self, user_id: str) -> UserProfile | None:
        task_summaries = _task_summaries_for_user(self.artifact_store.all_artifacts(), user_id)
        if not task_summaries:
            return None
        locale = next(
            (
                summary.get("locale")
                for summary in reversed(task_summaries)
                if summary.get("locale") not in {None, "", "auto"}
            ),
            "auto",
        )
        family_counter = Counter(
            str(summary.get("family", ""))
            for summary in task_summaries
            if summary.get("family")
        )
        field_counter = Counter()
        relation_counter = Counter()
        recent_subjects: list[str] = []
        for summary in task_summaries:
            recent_subjects.append(str(summary.get("resolved_subject", "")))
            field_counter.update(str(item) for item in summary.get("requested_fields", ()) if item)
            relation_counter.update(str(item) for item in summary.get("requested_relations", ()) if item)
        recent_subjects = [subject for subject in recent_subjects if subject][-5:]
        families = tuple(name for name, _ in family_counter.most_common(5))
        fields = tuple(name for name, _ in field_counter.most_common(8))
        relations = tuple(name for name, _ in relation_counter.most_common(8))
        summary = (
            f"user={user_id}; locale={locale}; families={', '.join(families) or 'n/a'}; "
            f"recent_subjects={', '.join(recent_subjects) or 'n/a'}; "
            f"fields={', '.join(fields) or 'n/a'}; relations={', '.join(relations) or 'n/a'}"
        )
        return UserProfile(
            profile_id=next_id("profile"),
            user_id=user_id,
            preferred_locale=locale,
            family_preferences=families,
            recent_subjects=tuple(recent_subjects),
            requested_fields=fields,
            requested_relations=relations,
            summary=summary,
        )

    def append_task_context(self, task_id: str, context: TaskMemoryContext) -> None:
        payload = {
            "user_id": context.user_id,
            "profile": None if context.profile is None else asdict(context.profile),
            "prompt_hits": [asdict(hit) for hit in context.prompt_hits],
            "subject_hits": [asdict(hit) for hit in context.subject_hits],
            "context_text": context.context_text,
        }
        self.artifact_store.append(
            ArtifactRecord(
                artifact_id=next_id("artifact"),
                task_id=task_id,
                artifact_type="task_memory_context",
                payload=payload,
            )
        )

    def learn_from_task(
        self,
        task_id: str,
        spec: TaskSpec,
        interpretation: TaskInterpretation,
        extraction: ExtractionResult,
    ) -> tuple[MemoryDocument, ...]:
        user_id = resolve_user_id(spec)
        documents = (
            self._memory_document(
                task_id=task_id,
                kind="prompt_summary",
                user_id=user_id,
                subject=interpretation.resolved_subject,
                subject_key=interpretation.scope_key or normalize_subject(interpretation.resolved_subject),
                family=interpretation.family,
                text=_prompt_memory_text(spec, interpretation),
                metadata={
                    "requested_fields": list(interpretation.requested_fields),
                    "requested_relations": list(interpretation.requested_relations),
                    "subject_aliases": list(interpretation.subject_aliases),
                    "participant_subject_keys": [participant.subject_key for participant in interpretation.subject_participants],
                    "subject_topology": interpretation.subject_topology,
                    "branch_strategy": interpretation.branch_strategy,
                    "parent_task_id": spec.parent_task_id or "",
                    "root_task_id": spec.root_task_id or "",
                },
            ),
            self._memory_document(
                task_id=task_id,
                kind="extraction_summary",
                user_id=user_id,
                subject=interpretation.resolved_subject,
                subject_key=interpretation.scope_key or normalize_subject(interpretation.resolved_subject),
                family=interpretation.family,
                text=_extraction_memory_text(interpretation, extraction),
                metadata={
                    "status": extraction.status,
                    "provider_metadata": dict(extraction.provider_metadata),
                    "subject_aliases": list(interpretation.subject_aliases),
                    "participant_subject_keys": [participant.subject_key for participant in interpretation.subject_participants],
                    "subject_topology": interpretation.subject_topology,
                    "branch_strategy": interpretation.branch_strategy,
                    "scope_key": interpretation.scope_key,
                },
            ),
        )
        for document in documents:
            self.artifact_store.append(
                ArtifactRecord(
                    artifact_id=next_id("artifact"),
                    task_id=task_id,
                    artifact_type="memory_document",
                    payload=asdict(document),
                )
            )
        profile = self.build_user_profile(user_id)
        if profile is not None:
            self.artifact_store.append(
                ArtifactRecord(
                    artifact_id=next_id("artifact"),
                    task_id=task_id,
                    artifact_type="user_profile",
                    payload=asdict(profile),
                )
            )
        return documents

    def _memory_document(
        self,
        *,
        task_id: str,
        kind: str,
        user_id: str,
        subject: str,
        subject_key: str | None = None,
        family: str,
        text: str,
        metadata: dict[str, Any],
    ) -> MemoryDocument:
        return MemoryDocument(
            memory_id=next_id("memory"),
            source_task_id=task_id,
            kind=kind,
            user_id=user_id,
            subject=subject,
            subject_key=subject_key or normalize_subject(subject),
            family=family,
            text=text,
            algorithm=getattr(self.embedder, "algorithm", "hash_vector_v1"),
            vector=self.embedder.embed(text),
            metadata=metadata,
        )

    def _profile_from_payload(self, payload: dict[str, object]) -> UserProfile:
        return UserProfile(
            profile_id=str(payload["profile_id"]),
            user_id=str(payload["user_id"]),
            preferred_locale=str(payload.get("preferred_locale", "auto")),
            family_preferences=tuple(str(item) for item in payload.get("family_preferences", [])),
            recent_subjects=tuple(str(item) for item in payload.get("recent_subjects", [])),
            requested_fields=tuple(str(item) for item in payload.get("requested_fields", [])),
            requested_relations=tuple(str(item) for item in payload.get("requested_relations", [])),
            summary=str(payload.get("summary", "")),
        )


def resolve_user_id(spec: TaskSpec) -> str:
    if spec.user_id and spec.user_id.strip():
        return spec.user_id.strip()
    caller = (spec.caller or "").strip()
    if caller and caller != "user":
        return caller
    return "default"

def _subject_query(interpretation: TaskInterpretation) -> str:
    return " ".join(
        part
        for part in (
            interpretation.resolved_subject,
            interpretation.family,
            " ".join(interpretation.requested_fields),
            " ".join(interpretation.requested_relations),
        )
        if part
    )


def _context_lines(
    profile: UserProfile | None,
    prompt_hits: tuple[MemoryHit, ...],
    subject_hits: tuple[MemoryHit, ...],
) -> list[str]:
    lines: list[str] = []
    if profile is not None:
        lines.append(f"user_profile: {profile.summary}")
    for index, hit in enumerate(prompt_hits, start=1):
        lines.append(f"prior_prompt_memory_{index}: {hit.text}")
    for index, hit in enumerate(subject_hits, start=1):
        lines.append(f"subject_memory_{index}: {hit.text}")
    return lines


def _prompt_memory_text(spec: TaskSpec, interpretation: TaskInterpretation) -> str:
    return (
        f"Prompt: {spec.prompt}\n"
        f"Subject: {interpretation.resolved_subject}\n"
        f"Family: {interpretation.family}\n"
        f"Requested fields: {', '.join(interpretation.requested_fields) or 'n/a'}\n"
        f"Requested relations: {', '.join(interpretation.requested_relations) or 'n/a'}"
    )


def _extraction_memory_text(interpretation: TaskInterpretation, extraction: ExtractionResult) -> str:
    facts = _fact_lines_from_payload(extraction.payload)
    payload_text = "; ".join(facts[:6]) if facts else "no extracted facts"
    return (
        f"Learned about {interpretation.resolved_subject} as {interpretation.family}.\n"
        f"Extraction status: {extraction.status}\n"
        f"Facts: {payload_text}"
    )


def _fact_lines_from_payload(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in payload.items():
        if key in {"family", "schema", "prompt", "locale", "status", "reason"}:
            continue
        lines.append(f"{key}: {_summarize_value(value)}")
    return lines


def _summarize_value(value: object) -> str:
    if isinstance(value, dict):
        items = list(value.items())[:4]
        return ", ".join(f"{key}={_summarize_value(val)}" for key, val in items)
    if isinstance(value, list):
        return ", ".join(_summarize_value(item) for item in value[:4])
    return str(value)


def _document_subject_aliases(document: MemoryDocument) -> set[str]:
    aliases = {document.subject_key}
    aliases.update(
        normalize_subject(str(alias))
        for alias in document.metadata.get("subject_aliases", [])
        if str(alias).strip()
    )
    aliases.update(
        normalize_subject(str(alias))
        for alias in document.metadata.get("participant_subject_keys", [])
        if str(alias).strip()
    )
    return {alias for alias in aliases if alias and alias != "unknown"}


def _task_summaries_for_user(artifacts: tuple[ArtifactRecord, ...], user_id: str) -> list[dict[str, object]]:
    task_data: dict[str, dict[str, object]] = {}
    task_order: list[str] = []
    for artifact in artifacts:
        summary = task_data.setdefault(artifact.task_id, {})
        if artifact.task_id not in task_order:
            task_order.append(artifact.task_id)
        if artifact.artifact_type == "task_prompt":
            summary["user_id"] = artifact.payload.get("user_id") or artifact.payload.get("caller") or "default"
            summary["locale"] = artifact.payload.get("locale")
        elif artifact.artifact_type == "task_interpretation":
            summary["resolved_subject"] = artifact.payload.get("resolved_subject")
            summary["family"] = artifact.payload.get("family")
            summary["requested_fields"] = tuple(artifact.payload.get("requested_fields", []))
            summary["requested_relations"] = tuple(artifact.payload.get("requested_relations", []))
    results: list[dict[str, object]] = []
    for task_id in task_order:
        summary = task_data[task_id]
        if str(summary.get("user_id", "user")) != user_id:
            continue
        results.append(summary)
    return results
