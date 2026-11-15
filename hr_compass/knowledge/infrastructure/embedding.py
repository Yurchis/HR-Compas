"""Embeddings with a persistent cache: every chunk is embedded once.

`CachingEmbedder` keys vectors by sha256(model + text): a re-run embeds nothing, a changed text or another model
is embedded again, identical texts (archived copies, one offer template) once. Search queries are embedded without
the cache. The model ([embeddings].provider):

- local: fastembed (ONNX on CPU, no API key), downloaded on first use into [embeddings].models_dir;
- openrouter: the OpenRouter /embeddings endpoint (e.g. openai/text-embedding-3-large); the API key is needed, and
  the text of every chunk is sent to the provider once, when it is indexed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from functools import cached_property
from pathlib import Path
from typing import Protocol

from hr_compass.shared.logging import kv
from hr_compass.shared.openrouter import OpenRouterClient
from hr_compass.shared.settings import Settings

logger = logging.getLogger(__name__)


class VectorModel(Protocol):
    def embed(self, texts: list[str], batch_size: int) -> list[list[float]]: ...


class FastEmbedModel:
    def __init__(self, name: str, models_dir: Path) -> None:
        self.name, self._models_dir = name, models_dir

    @cached_property
    def _model(self):
        from fastembed import TextEmbedding

        started = time.perf_counter()
        logger.info("loading embedding model %s", self.name, extra=kv(models_dir=str(self._models_dir)))
        model = TextEmbedding(self.name, cache_dir=str(self._models_dir))
        logger.info("embedding model loaded", extra=kv(ms=round((time.perf_counter() - started) * 1000)))
        return model

    def embed(self, texts: list[str], batch_size: int) -> list[list[float]]:
        return [[float(x) for x in vector] for vector in self._model.embed(texts, batch_size=batch_size)]


class OpenRouterEmbeddingModel:
    """A VectorModel over the OpenRouter /embeddings endpoint: `batch_size` texts per request, the project's client
    (timeouts, retries, logged tokens and cost). Synchronous: every call runs its own event loop, which is fine in
    the CLI and in the worker thread the chat searches in."""

    def __init__(self, settings: Settings, model: str, dim: int) -> None:
        self._settings, self.name, self._dim = settings, model, dim

    def embed(self, texts: list[str], batch_size: int) -> list[list[float]]:
        return asyncio.run(self._embed(texts, batch_size)) if texts else []

    async def _embed(self, texts: list[str], batch_size: int) -> list[list[float]]:
        vectors: list[list[float]] = []
        cost = 0.0
        async with OpenRouterClient(self._settings) as client:
            for start in range(0, len(texts), batch_size):
                result = await client.embed(texts[start:start + batch_size], model=self.name)
                vectors += [list(v) for v in result.vectors]
                cost += result.cost_usd or 0.0
        if vectors and len(vectors[0]) != self._dim:
            raise ValueError(f"{self.name} returns {len(vectors[0])}-dim vectors, [embeddings].dim is {self._dim}")
        logger.info("openrouter embeddings", extra=kv(model=self.name, texts=len(texts), cost=round(cost, 6)))
        return vectors


class VectorCache:
    """{key: vector} in one JSON file, read once, written atomically (an interrupted run never corrupts it)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._vectors: dict[str, list[float]] | None = None

    @property
    def vectors(self) -> dict[str, list[float]]:
        if self._vectors is None:
            self._vectors = {}
            if self.path.exists():
                try:
                    self._vectors = json.loads(self.path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:  # disposable: rebuild it
                    logger.warning("embedding cache unreadable, starting an empty one: %s", exc)
            logger.info("embedding cache loaded", extra=kv(vectors=len(self._vectors), file=self.path.name))
        return self._vectors

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.vectors), encoding="utf-8")
        os.replace(tmp, self.path)


class CachingEmbedder:
    """The Embedder port: vectors in input order; only texts missing from the cache reach the model."""

    def __init__(self, model: VectorModel, model_name: str, cache: VectorCache, batch_size: int = 64) -> None:
        self._model, self.model_name, self._cache, self._batch_size = model, model_name, cache, batch_size
        self.last_missing = 0   # how many vectors the last call computed (identical texts count once)

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_name}\n{text}".encode()).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._cache.vectors
        keys = [self.key(text) for text in texts]
        missing = {key: text for key, text in zip(keys, texts, strict=True) if key not in vectors}
        self.last_missing = len(missing)
        logger.info("embed", extra=kv(texts=len(texts), unique=len(set(keys)), to_embed=len(missing)))
        if missing:
            started = time.perf_counter()
            for key, vector in zip(missing, self._model.embed(list(missing.values()), self._batch_size), strict=True):
                vectors[key] = vector
            self._cache.save()
            logger.info("embedded", extra=kv(count=len(missing), ms=round((time.perf_counter() - started) * 1000),
                                             cached=len(vectors)))
        return [vectors[key] for key in keys]

    def embed_query(self, text: str) -> list[float]:
        [vector] = self._model.embed([text], self._batch_size)
        return vector
