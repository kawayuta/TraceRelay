from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from urllib import parse, request
from urllib.error import HTTPError, URLError


class EmbeddingError(RuntimeError):
    pass


class TextEmbedder(Protocol):
    algorithm: str

    def embed(self, text: str) -> tuple[float, ...]:
        ...


@dataclass(frozen=True)
class LMStudioEmbeddingConfig:
    base_url: str
    model: str
    timeout_s: float = 30.0


@dataclass(frozen=True)
class OllamaEmbeddingConfig:
    base_url: str
    model: str
    timeout_s: float = 30.0


@dataclass(frozen=True)
class OpenAIEmbeddingConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com"
    timeout_s: float = 30.0


@dataclass(frozen=True)
class GeminiEmbeddingConfig:
    api_key: str
    model: str
    base_url: str = "https://generativelanguage.googleapis.com"
    timeout_s: float = 30.0


class HashingTextEmbedder:
    algorithm = "hash_vector_v1"

    def __init__(self, dimensions: int = 48) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        normalized = _normalize_for_embedding(text)
        grams = list(_token_grams(normalized)) + list(_char_ngrams(normalized))
        vector = [0.0] * self.dimensions
        for gram in grams:
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + min(len(gram), 12) / 12.0
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return tuple(vector)


class LMStudioTextEmbedder:
    algorithm = "lmstudio_embeddings_v1"

    def __init__(self, config: LMStudioEmbeddingConfig) -> None:
        self.config = config
        self._cache: dict[str, tuple[float, ...]] = {}

    def embed(self, text: str) -> tuple[float, ...]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        payload = {
            "model": self.config.model,
            "input": text,
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.config.base_url.rstrip('/')}/v1/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_s) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingError(f"LM Studio embeddings request failed: HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise EmbeddingError(f"LM Studio embeddings request failed: {exc}") from exc

        try:
            embedding = raw["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError(f"Unexpected LM Studio embeddings payload: {raw!r}") from exc

        vector = tuple(float(value) for value in embedding)
        self._cache[text] = vector
        return vector


class OllamaTextEmbedder:
    algorithm = "ollama_embeddings_v1"

    def __init__(self, config: OllamaEmbeddingConfig) -> None:
        self.config = config
        self._cache: dict[str, tuple[float, ...]] = {}

    def embed(self, text: str) -> tuple[float, ...]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        payload = {
            "model": self.config.model,
            "input": text,
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.config.base_url.rstrip('/')}/api/embed",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_s) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingError(f"Ollama embeddings request failed: HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise EmbeddingError(f"Ollama embeddings request failed: {exc}") from exc

        try:
            embedding = raw["embeddings"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError(f"Unexpected Ollama embeddings payload: {raw!r}") from exc

        vector = tuple(float(value) for value in embedding)
        self._cache[text] = vector
        return vector


class OpenAITextEmbedder:
    algorithm = "openai_embeddings_v1"

    def __init__(self, config: OpenAIEmbeddingConfig) -> None:
        self.config = config
        self._cache: dict[str, tuple[float, ...]] = {}

    def embed(self, text: str) -> tuple[float, ...]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        payload = {
            "model": self.config.model,
            "input": text,
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.config.base_url.rstrip('/')}/v1/embeddings",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_s) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingError(f"OpenAI embeddings request failed: HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise EmbeddingError(f"OpenAI embeddings request failed: {exc}") from exc

        try:
            embedding = raw["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError(f"Unexpected OpenAI embeddings payload: {raw!r}") from exc

        vector = tuple(float(value) for value in embedding)
        self._cache[text] = vector
        return vector


class GeminiTextEmbedder:
    algorithm = "gemini_embeddings_v1"

    def __init__(self, config: GeminiEmbeddingConfig) -> None:
        self.config = config
        self._cache: dict[str, tuple[float, ...]] = {}

    def embed(self, text: str) -> tuple[float, ...]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        model_name = _gemini_model_resource(self.config.model)
        payload = {
            "model": model_name,
            "content": {
                "parts": [{"text": text}],
            },
            "taskType": "RETRIEVAL_QUERY",
        }
        body = json.dumps(payload).encode("utf-8")
        query = parse.urlencode({"key": self.config.api_key})
        req = request.Request(
            url=f"{self.config.base_url.rstrip('/')}/v1beta/{model_name}:embedContent?{query}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_s) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingError(f"Gemini embeddings request failed: HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise EmbeddingError(f"Gemini embeddings request failed: {exc}") from exc

        try:
            embedding = raw["embedding"]["values"]
        except (KeyError, TypeError) as exc:
            raise EmbeddingError(f"Unexpected Gemini embeddings payload: {raw!r}") from exc

        vector = tuple(float(value) for value in embedding)
        self._cache[text] = vector
        return vector


def embedding_record(text: str, embedder: TextEmbedder | None = None) -> dict[str, object]:
    active = embedder or embedder_from_env()
    vector = list(active.embed(text))
    record: dict[str, object] = {
        "algorithm": active.algorithm,
        "dimensions": len(vector),
        "vector": vector,
    }
    model = getattr(active, "config", None)
    if model is not None:
        record["model"] = getattr(model, "model", "")
    return record


def embed_text(text: str, embedder: TextEmbedder | None = None) -> tuple[float, ...]:
    active = embedder or embedder_from_env()
    return active.embed(text)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(length))
    left_norm = math.sqrt(sum(value * value for value in left[:length]))
    right_norm = math.sqrt(sum(value * value for value in right[:length]))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def embedder_from_env() -> TextEmbedder:
    explicit_provider = os.getenv("SCHEMALEDGER_EMBEDDING_PROVIDER", "").strip().casefold()
    provider = _infer_embedding_provider_from_env()
    if provider == "hash":
        return _hash_embedder()
    if provider in {"anthropic", "claude"}:
        raise EmbeddingError(
            "Anthropic Claude does not currently expose a direct embeddings API. "
            "Use openai, gemini, ollama, lmstudio, or hash for SCHEMALEDGER_EMBEDDING_PROVIDER."
        )
    if provider == "openai":
        api_key = os.getenv("SCHEMALEDGER_OPENAI_API_KEY", "").strip()
        model = os.getenv("SCHEMALEDGER_OPENAI_EMBEDDING_MODEL", "").strip() or "text-embedding-3-small"
        base_url = os.getenv("SCHEMALEDGER_OPENAI_BASE_URL", "https://api.openai.com").strip()
        if not api_key:
            if explicit_provider == "openai":
                raise EmbeddingError("SCHEMALEDGER_OPENAI_API_KEY is required for openai embeddings")
            return _hash_embedder()
        return _openai_embedder(
            api_key,
            model,
            base_url,
            float(os.getenv("SCHEMALEDGER_OPENAI_TIMEOUT", "30")),
        )
    if provider == "gemini":
        api_key = os.getenv("SCHEMALEDGER_GEMINI_API_KEY", "").strip()
        model = os.getenv("SCHEMALEDGER_GEMINI_EMBEDDING_MODEL", "").strip() or "gemini-embedding-001"
        base_url = os.getenv("SCHEMALEDGER_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").strip()
        if not api_key:
            if explicit_provider == "gemini":
                raise EmbeddingError("SCHEMALEDGER_GEMINI_API_KEY is required for gemini embeddings")
            return _hash_embedder()
        return _gemini_embedder(
            api_key,
            model,
            base_url,
            float(os.getenv("SCHEMALEDGER_GEMINI_TIMEOUT", "30")),
        )
    if provider == "ollama":
        base_url = os.getenv("SCHEMALEDGER_OLLAMA_BASE_URL")
        if not base_url:
            return _hash_embedder()
        timeout_s = float(os.getenv("SCHEMALEDGER_OLLAMA_TIMEOUT", "30"))
        model = os.getenv("SCHEMALEDGER_OLLAMA_EMBEDDING_MODEL") or _detect_ollama_embedding_model(base_url, timeout_s)
        if not model:
            return _hash_embedder()
        return _ollama_embedder(base_url, model, timeout_s)

    base_url = os.getenv("SCHEMALEDGER_LM_STUDIO_BASE_URL")
    if not base_url:
        return _hash_embedder()
    timeout_s = float(os.getenv("SCHEMALEDGER_LM_STUDIO_TIMEOUT", "30"))
    model = os.getenv("SCHEMALEDGER_LM_STUDIO_EMBEDDING_MODEL") or _detect_lmstudio_embedding_model(base_url, timeout_s)
    if not model:
        return _hash_embedder()
    return _lmstudio_embedder(base_url, model, timeout_s)


def _infer_embedding_provider_from_env() -> str:
    provider = os.getenv("SCHEMALEDGER_EMBEDDING_PROVIDER", "").strip().casefold()
    if provider in {"lmstudio", "ollama", "openai", "gemini", "anthropic", "claude", "hash"}:
        return provider
    llm_provider = os.getenv("SCHEMALEDGER_LLM_PROVIDER", "").strip().casefold()
    if llm_provider in {"lmstudio", "ollama"}:
        return llm_provider
    if os.getenv("SCHEMALEDGER_OPENAI_API_KEY"):
        return "openai"
    if os.getenv("SCHEMALEDGER_GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("SCHEMALEDGER_LM_STUDIO_BASE_URL"):
        return "lmstudio"
    if os.getenv("SCHEMALEDGER_OLLAMA_BASE_URL"):
        return "ollama"
    return "hash"


@lru_cache(maxsize=1)
def _hash_embedder() -> HashingTextEmbedder:
    return HashingTextEmbedder()


@lru_cache(maxsize=8)
def _lmstudio_embedder(base_url: str, model: str, timeout_s: float) -> LMStudioTextEmbedder:
    return LMStudioTextEmbedder(LMStudioEmbeddingConfig(base_url=base_url, model=model, timeout_s=timeout_s))


@lru_cache(maxsize=8)
def _ollama_embedder(base_url: str, model: str, timeout_s: float) -> OllamaTextEmbedder:
    return OllamaTextEmbedder(OllamaEmbeddingConfig(base_url=base_url, model=model, timeout_s=timeout_s))


@lru_cache(maxsize=8)
def _openai_embedder(api_key: str, model: str, base_url: str, timeout_s: float) -> OpenAITextEmbedder:
    return OpenAITextEmbedder(
        OpenAIEmbeddingConfig(api_key=api_key, model=model, base_url=base_url, timeout_s=timeout_s)
    )


@lru_cache(maxsize=8)
def _gemini_embedder(api_key: str, model: str, base_url: str, timeout_s: float) -> GeminiTextEmbedder:
    return GeminiTextEmbedder(
        GeminiEmbeddingConfig(api_key=api_key, model=model, base_url=base_url, timeout_s=timeout_s)
    )


@lru_cache(maxsize=8)
def _detect_lmstudio_embedding_model(base_url: str, timeout_s: float) -> str | None:
    req = request.Request(
        url=f"{base_url.rstrip('/')}/v1/models",
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    models = raw.get("data", [])
    ranked: list[str] = []
    for item in models:
        model_id = str(item.get("id", ""))
        lowered = model_id.casefold()
        if any(token in lowered for token in ("embedding", "embed", "nomic", "bge", "e5", "gte")):
            ranked.append(model_id)
    return ranked[0] if ranked else None


@lru_cache(maxsize=8)
def _detect_ollama_embedding_model(base_url: str, timeout_s: float) -> str | None:
    req = request.Request(
        url=f"{base_url.rstrip('/')}/api/tags",
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    models = raw.get("models", [])
    ranked: list[str] = []
    for item in models:
        model_id = str(item.get("model") or item.get("name") or "")
        lowered = model_id.casefold()
        if any(token in lowered for token in ("embedding", "embed", "nomic", "bge", "e5", "gte")):
            ranked.append(model_id)
    return ranked[0] if ranked else None


def clear_embedding_caches() -> None:
    _hash_embedder.cache_clear()
    _lmstudio_embedder.cache_clear()
    _ollama_embedder.cache_clear()
    _openai_embedder.cache_clear()
    _gemini_embedder.cache_clear()
    _detect_lmstudio_embedding_model.cache_clear()
    _detect_ollama_embedding_model.cache_clear()


def _normalize_for_embedding(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _token_grams(text: str) -> list[str]:
    tokens = re.findall(r"[\w]+", text, flags=re.UNICODE)
    return [token for token in tokens if token]


def _char_ngrams(text: str, size: int = 3) -> list[str]:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < size:
        return [compact] if compact else []
    return [compact[index : index + size] for index in range(len(compact) - size + 1)]


def _gemini_model_resource(model: str) -> str:
    if model.startswith("models/"):
        return model
    return f"models/{model}"
