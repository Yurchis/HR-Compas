"""CachingEmbedder: vectors in order, cached by sha256(model + text), a re-run embeds nothing."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import ClassVar

import pytest

from hr_compass.knowledge.infrastructure.embedding import (
    CachingEmbedder,
    FastEmbedModel,
    OpenRouterEmbeddingModel,
    VectorCache,
)
from hr_compass.shared.openrouter import Embeddings
from hr_compass.shared.settings import EmbeddingsConfig, Settings


class CountingModel:
    """A VectorModel: [len(text)] * 3, and the texts it was asked to embed."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str], batch_size: int) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t))] * 3 for t in texts]


@pytest.fixture
def model() -> CountingModel:
    return CountingModel()


def embedder(model: CountingModel, path: Path, name: str = "m") -> CachingEmbedder:
    return CachingEmbedder(model, name, VectorCache(path))


def test_vectors_come_back_in_input_order_as_float_lists(model, tmp_path):
    e = embedder(model, tmp_path / "c.json")

    vectors = e.embed(["a", "bbb"])

    assert [v[0] for v in vectors] == [1.0, 3.0] and all(type(v[0]) is float for v in vectors)
    assert e.last_missing == 2


def test_a_second_run_embeds_nothing_even_in_a_new_process(model, tmp_path):
    first = embedder(model, tmp_path / "c.json").embed(["Can I work from home?", "Remote work is allowed."])

    second_embedder = embedder(model, tmp_path / "c.json")   # a fresh cache object: read from disk
    second = second_embedder.embed(["Remote work is allowed.", "Can I work from home?"])

    assert second_embedder.last_missing == 0 and len(model.calls) == 1
    assert second == first[::-1]


def test_only_new_texts_are_embedded_and_duplicates_once(model, tmp_path):
    e = embedder(model, tmp_path / "c.json")
    e.embed(["old"])

    vectors = e.embed(["old", "new", "new"])

    assert model.calls[-1] == ["new"] and e.last_missing == 1 and vectors[1] == vectors[2]


def test_the_key_depends_on_the_model(model, tmp_path):
    a, b = embedder(model, tmp_path / "c.json", "a"), embedder(model, tmp_path / "c.json", "b")
    assert a.key("x") != b.key("x")
    a.embed(["x"])

    b.embed(["x"])

    assert b.last_missing == 1


def test_a_broken_cache_file_is_rebuilt(model, tmp_path, caplog):
    path = tmp_path / "c.json"
    path.write_text("{not json", encoding="utf-8")
    e = embedder(model, path)

    with caplog.at_level(logging.WARNING, logger="hr_compass"):
        e.embed(["x"])

    assert "unreadable" in caplog.text and list(json.loads(path.read_text(encoding="utf-8"))) == [e.key("x")]


def test_a_query_is_embedded_by_the_same_model_but_never_cached(model, tmp_path):
    e = embedder(model, tmp_path / "c.json")
    e.embed(["document"])

    assert e.embed_query("how many days?") == [14.0] * 3
    assert e.embed_query("how many days?") == [14.0] * 3
    assert json.loads((tmp_path / "c.json").read_text(encoding="utf-8")).keys() == {e.key("document")}
    assert model.calls[-2:] == [["how many days?"], ["how many days?"]]   # no cache: the model both times


class FakeEmbeddingsClient:
    """Stands in for OpenRouterClient: 2-dim vectors, records the batches."""

    batches: ClassVar[list[list[str]]] = []

    def __init__(self, settings) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def embed(self, texts, *, model):
        FakeEmbeddingsClient.batches.append(list(texts))
        return Embeddings(vectors=tuple((float(len(t)), 1.0) for t in texts), model=model, tokens=len(texts),
                          cost_usd=0.000001)


def test_the_openrouter_model_batches_requests_and_checks_the_dimension(monkeypatch):
    monkeypatch.setattr("hr_compass.knowledge.infrastructure.embedding.OpenRouterClient", FakeEmbeddingsClient)
    FakeEmbeddingsClient.batches = []
    model = OpenRouterEmbeddingModel(Settings(api_key="k"), "openai/text-embedding-3-large", dim=2)

    vectors = model.embed(["a", "bb", "ccc"], batch_size=2)

    assert vectors == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]] and FakeEmbeddingsClient.batches == [["a", "bb"], ["ccc"]]
    assert model.embed([], batch_size=2) == []
    with pytest.raises(ValueError, match=re.escape("2-dim vectors, [embeddings].dim is 3072")):
        OpenRouterEmbeddingModel(Settings(api_key="k"), "openai/text-embedding-3-large", dim=3072).embed(["a"], 2)


def test_the_cache_is_written_atomically(model, tmp_path):
    embedder(model, tmp_path / "c.json").embed(["x"])

    assert (tmp_path / "c.json").exists() and not (tmp_path / "c.tmp").exists()


def _downloaded(name: str) -> bool:
    return any(EmbeddingsConfig().models_dir.glob(f"models--*{name}*"))


@pytest.mark.skipif(not _downloaded("paraphrase-multilingual"), reason="the embedding model is not downloaded yet")
def test_the_real_model_puts_similar_texts_closer(tmp_path):
    import numpy as np

    cfg = EmbeddingsConfig()
    e = CachingEmbedder(FastEmbedModel(cfg.model, cfg.models_dir), cfg.model, VectorCache(tmp_path / "c.json"))

    a, b, c = (np.asarray(v) for v in e.embed(["Скільки днів відпустки на рік?",
                                               "Employees get 24 days of paid vacation a year.",
                                               "Batteries are charged in the charging room."]))

    def cos(x, y):
        return float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y)))

    assert len(a) == cfg.dim and cos(a, b) > cos(a, c)
