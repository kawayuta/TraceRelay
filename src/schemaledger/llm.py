from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from .models import CoverageReport, ExtractionResult, SchemaVersion, TaskInterpretation, TaskSpec


class StructuredLLM(Protocol):
    def interpret_task(self, spec: TaskSpec) -> dict[str, Any]:
        ...

    def build_initial_schema(self, interpretation: TaskInterpretation) -> dict[str, Any]:
        ...

    def evolve_schema(
        self,
        interpretation: TaskInterpretation,
        schema: SchemaVersion,
        coverage: CoverageReport,
        extraction: ExtractionResult,
    ) -> dict[str, Any]:
        ...

    def extract_task(
        self,
        family: str,
        interpretation: TaskInterpretation,
        schema: SchemaVersion,
        attempt: int,
    ) -> ExtractionResult:
        ...


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LMStudioConfig:
    base_url: str
    model: str
    timeout_s: float = 30.0


class LMStudioClient:
    def __init__(self, config: LMStudioConfig) -> None:
        self.config = config

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                },
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.config.base_url.rstrip('/')}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_s) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"LM Studio request failed: HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise LLMError(f"LM Studio request failed: {exc}") from exc
        try:
            message = raw["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LM Studio payload: {raw!r}") from exc
        candidates = _message_json_candidates(message)
        parse_errors: list[str] = []
        for source, candidate in candidates:
            try:
                return _parse_json_content(candidate)
            except json.JSONDecodeError as exc:
                parse_errors.append(f"{source}: {exc}")
        candidate_sources = ", ".join(source for source, _ in candidates) or "none"
        raise LLMError(
            "LM Studio did not return JSON content. "
            f"candidate_sources={candidate_sources}; parse_errors={parse_errors!r}; message={message!r}"
        )


class LMStudioStructuredLLM:
    def __init__(self, client: LMStudioClient) -> None:
        self.client = client

    def interpret_task(self, spec: TaskSpec) -> dict[str, Any]:
        return self.client.complete_json(
            system_prompt=(
                "TASK_INTERPRETATION\n"
                "Return JSON with keys: intent, resolved_subject, subject_candidates, "
                "family, family_rationale, requested_fields, requested_relations, "
                "scope_hints, task_shape, locale.\n"
                "Interpret 'family' as the abstract schema class, not the entity name.\n"
                "Use a short snake_case type label such as organization, media_work, policy, "
                "system_incident, relationship, franchise, supply_chain_relation.\n"
                "Never return a company name, person name, title, or subject string in family.\n"
                "requested_fields and requested_relations must be atomic snake_case schema keys.\n"
                "Use requested_fields for attributes directly attached to the subject.\n"
                "Use requested_relations for links to other entities or regions.\n"
                "For organization-like prompts, prefer relations for subsidiaries, competitors, "
                "executives-as-people, acquisitions-as-target-entities, and operating regions.\n"
                "You may use memory_context as prior context from earlier tasks, but do not let stale memory override the current prompt."
            ),
            schema_name="task_interpretation",
            schema=_task_interpretation_schema(),
            user_prompt=json.dumps(
                {
                    "prompt": spec.prompt,
                    "locale": spec.locale,
                    "requested_scope": list(spec.requested_scope),
                    "caller": spec.caller,
                    "user_id": spec.user_id,
                    "memory_context": spec.memory_context,
                },
                ensure_ascii=False,
            ),
        )

    def build_initial_schema(self, interpretation: TaskInterpretation) -> dict[str, Any]:
        return self.client.complete_json(
            system_prompt=(
                "INITIAL_SCHEMA\n"
                "Return JSON with keys: family, required_fields, optional_fields, relations, rationale.\n"
                "family must remain the same abstract schema class from the interpretation step.\n"
                "All fields and relations must be atomic snake_case keys.\n"
                "Create the narrowest viable schema for this task.\n"
                "Do not add speculative fields or relations that are not needed for the requested task.\n"
                "Use memory_context for prior learned details about the same subject when it helps narrow the schema."
            ),
            schema_name="initial_schema",
            schema=_schema_definition_schema(),
            user_prompt=json.dumps(
                {
                    "family": interpretation.family,
                    "resolved_subject": interpretation.resolved_subject,
                    "requested_fields": list(interpretation.requested_fields),
                    "requested_relations": list(interpretation.requested_relations),
                    "intent": interpretation.intent,
                    "memory_context": interpretation.memory_context,
                },
                ensure_ascii=False,
            ),
        )

    def evolve_schema(
        self,
        interpretation: TaskInterpretation,
        schema: SchemaVersion,
        coverage: CoverageReport,
        extraction: ExtractionResult,
    ) -> dict[str, Any]:
        return self.client.complete_json(
            system_prompt=(
                "EVOLVE_SCHEMA\n"
                "Return JSON with keys: family, required_fields, optional_fields, relations, rationale. "
                "Only propose additive changes.\n"
                "family must remain the same abstract schema class from the interpretation step.\n"
                "All fields and relations must be atomic snake_case keys.\n"
                "Only add keys that directly resolve the current missing_fields and missing_relations.\n"
                "Do not add unrelated enrichment fields, metadata fields, historical fields, or nice-to-have keys.\n"
                "If no schema change is needed, return the current schema unchanged.\n"
                "Use memory_context to reuse prior learned subject details before expanding the schema."
            ),
            schema_name="evolved_schema",
            schema=_schema_definition_schema(),
            user_prompt=json.dumps(
                {
                    "family": interpretation.family,
                    "resolved_subject": interpretation.resolved_subject,
                    "current_schema": {
                        "schema_id": schema.schema_id,
                        "version": schema.version,
                        "required_fields": list(schema.required_fields),
                        "optional_fields": list(schema.optional_fields),
                        "relations": list(schema.relations),
                    },
                    "coverage": {
                        "missing_values": list(coverage.missing_values),
                        "missing_fields": list(coverage.missing_fields),
                        "missing_relations": list(coverage.missing_relations),
                        "dominant_issue": coverage.dominant_issue,
                    },
                    "extraction_payload": extraction.payload,
                    "memory_context": interpretation.memory_context,
                },
                ensure_ascii=False,
            ),
        )

    def extract_task(
        self,
        family: str,
        interpretation: TaskInterpretation,
        schema: SchemaVersion,
        attempt: int,
    ) -> ExtractionResult:
        payload = self.client.complete_json(
            system_prompt=(
                "TASK_EXTRACTION\n"
                "Return JSON with keys: payload, status.\n"
                "Populate the payload using the provided schema keys exactly.\n"
                "payload must contain only domain keys from the schema.\n"
                "Do not echo request metadata such as family, attempt, resolved_subject, schema, scope_hints, or intent.\n"
                "Fill every required field and every relation key with the best available value.\n"
                "Use memory_context for previously learned facts about the same subject before leaving values empty."
            ),
            schema_name="task_extraction",
            schema=_task_extraction_schema(schema),
            user_prompt=json.dumps(
                {
                    "family": family,
                    "attempt": attempt,
                    "resolved_subject": interpretation.resolved_subject,
                    "schema": {
                        "schema_id": schema.schema_id,
                        "version": schema.version,
                        "required_fields": list(schema.required_fields),
                        "optional_fields": list(schema.optional_fields),
                        "relations": list(schema.relations),
                    },
                    "scope_hints": list(interpretation.scope_hints),
                    "intent": interpretation.intent,
                    "memory_context": interpretation.memory_context,
                },
                ensure_ascii=False,
            ),
        )
        return ExtractionResult(
            payload=dict(payload.get("payload", {})),
            status=str(payload.get("status", "success")),
            provider_metadata={
                "attempt": attempt,
                "provider": "lmstudio",
                "base_url": self.client.config.base_url,
                "model": self.client.config.model,
            },
        )


def llm_from_env() -> StructuredLLM | None:
    base_url = os.getenv("SCHEMALEDGER_LM_STUDIO_BASE_URL")
    model = os.getenv("SCHEMALEDGER_LM_STUDIO_MODEL")
    if not base_url or not model:
        return None
    return LMStudioStructuredLLM(
        LMStudioClient(
            LMStudioConfig(
                base_url=base_url,
                model=model,
                timeout_s=float(os.getenv("SCHEMALEDGER_LM_STUDIO_TIMEOUT", "30")),
            )
        )
    )


def _string_array_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
    }


def _task_interpretation_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {"type": "string"},
            "resolved_subject": {"type": "string"},
            "subject_candidates": _string_array_schema(),
            "family": {"type": "string"},
            "family_rationale": {"type": "string"},
            "requested_fields": _string_array_schema(),
            "requested_relations": _string_array_schema(),
            "scope_hints": _string_array_schema(),
            "task_shape": {"type": "string"},
            "locale": {"type": "string"},
        },
        "required": [
            "intent",
            "resolved_subject",
            "subject_candidates",
            "family",
            "family_rationale",
            "requested_fields",
            "requested_relations",
            "scope_hints",
            "task_shape",
            "locale",
        ],
    }


def _schema_definition_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "family": {"type": "string"},
            "required_fields": _string_array_schema(),
            "optional_fields": _string_array_schema(),
            "relations": _string_array_schema(),
            "rationale": {"type": "string"},
        },
        "required": ["family", "required_fields", "optional_fields", "relations", "rationale"],
    }


def _task_extraction_schema(schema: SchemaVersion) -> dict[str, Any]:
    keys = list(dict.fromkeys(schema.required_fields + schema.optional_fields + schema.relations))
    value_schema = {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
            {
                "type": "array",
                "items": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "number"},
                        {"type": "boolean"},
                        {"type": "null"},
                        {"type": "object", "additionalProperties": True},
                    ]
                },
            },
            {"type": "object", "additionalProperties": True},
        ]
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "payload": {
                "type": "object",
                "additionalProperties": False,
                "properties": {key: value_schema for key in keys},
                "required": keys,
            },
            "status": {"type": "string"},
        },
        "required": ["payload", "status"],
    }


def _parse_json_content(content: str) -> dict[str, Any]:
    candidates: list[str] = []
    stripped = content.strip()
    if stripped:
        candidates.append(stripped)

    without_think = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
    if without_think and without_think not in candidates:
        candidates.append(without_think)

    for source in list(candidates):
        fenced = _extract_fenced_json(source)
        if fenced and fenced not in candidates:
            candidates.append(fenced)

    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
        else:
            if isinstance(parsed, dict):
                return parsed
            raise json.JSONDecodeError("Expected JSON object", candidate, 0)

        extracted = _extract_json_object(candidate, decoder)
        if extracted is not None:
            return extracted

    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("Expected JSON object", content, 0)


def _message_json_candidates(message: Any) -> list[tuple[str, str]]:
    if not isinstance(message, dict):
        return []
    candidates: list[tuple[str, str]] = []
    for key in ("content", "reasoning_content"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append((key, value))
            continue
        if isinstance(value, list):
            text = "".join(
                str(part.get("text", ""))
                for part in value
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
            if text:
                candidates.append((key, text))
    return candidates


def _extract_fenced_json(content: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _extract_json_object(content: str, decoder: json.JSONDecoder) -> dict[str, Any] | None:
    for index, character in enumerate(content):
        if character not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
