"""Test doubles passed in explicitly (no module globals to monkeypatch): they implement the same ports as the real
infrastructure."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel

from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.knowledge.domain.retrieval import Hit, Query, tokenize
from hr_compass.shared.llm import LLMError, LLMResult
from hr_compass.shared.openrouter import Completion

DIM = 8


def chunk(chunk_id: str = "Policies/vacation.pdf#0", text: str = "24 days of paid vacation a year.", *,
          section: str = "", access: Iterable[str] = ("all_employees",), country: str | None = None,
          title: str = "Paid Vacation", effective: str | None = None) -> ChunkRecord:
    source, _, index = chunk_id.rpartition("#") if "#" in chunk_id else (chunk_id, "", "0")
    return ChunkRecord(chunk_id=chunk_id, source=source, title=title, section=section, access=tuple(access),
                       doc_hash=f"{abs(hash(source)):064d}"[:64], chunk_index=int(index),
                       n_tokens=len(text.split()), text=text, pipeline_version="test", ingested_at="2026-11-15",
                       effective=effective, country=country)


class KeywordEmbedder:
    """A deterministic Embedder: a one-hot direction for the first keyword found, so the nearest chunk is
    predictable. Records every call."""

    def __init__(self, keywords: Iterable[str] = ("remote", "vacation", "disability", "fee")) -> None:
        self.keywords = list(keywords)
        self.calls: list[list[str]] = []
        self.last_missing = 0   # like CachingEmbedder: how many vectors the last call computed

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.01] * DIM
        lowered = text.lower()
        for axis, word in enumerate(self.keywords):
            if word in lowered or (word == "remote" and "home" in lowered):
                vector[axis] = 1.0
                break
        return vector


class OverlapReranker:
    """A Reranker: scores a text by how many query words it contains."""

    def __init__(self) -> None:
        self.calls = 0

    def scores(self, query: str, texts: list[str]) -> list[float]:
        self.calls += 1
        words = set(tokenize(query))
        return [float(len(words & set(tokenize(t)))) for t in texts]


class ListRetriever:
    """A Retriever over a fixed list: returns the chunks the query admits, in list order, with falling scores."""

    def __init__(self, chunks: list[ChunkRecord]) -> None:
        self.chunks, self.queries = chunks, []

    def search(self, query: Query) -> list[Hit]:
        self.queries.append(query)
        admitted = [c for c in self.chunks if query.admits(c)]
        return [Hit(c, 1.0 - i / 100) for i, c in enumerate(admitted[:query.k])]


def completion(text: str = "", prompt_tokens: int = 10, completion_tokens: int = 5, cost: float = 0.001) -> Completion:
    return Completion(text=text, model="m", finish_reason="stop", prompt_tokens=prompt_tokens,
                      completion_tokens=completion_tokens, cost_usd=cost)


Reply = BaseModel | Exception | Callable[[list[dict[str, str]]], BaseModel]


class FakeGenerator:
    """The async Generator port of AskQuestion: replies by output model name, in order; records the calls.

        FakeGenerator(Intake=[intake], RagAnswer=[answer])
    A reply may be an exception (raised) or a function of the messages."""

    def __init__(self, **replies: list[Reply]) -> None:
        self.replies = {name: list(items) for name, items in replies.items()}
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def generate(self, messages: list[dict[str, str]], *, output_model: type[BaseModel]) -> LLMResult:
        name = output_model.__name__
        self.calls.append((name, messages))
        queue = self.replies.get(name)
        if not queue:
            raise LLMError([f"m: no fake reply for {name}"])
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        parsed = reply(messages) if callable(reply) and not isinstance(reply, BaseModel) else reply
        return LLMResult(completion(parsed.model_dump_json()), parsed, "m")

    def calls_of(self, name: str) -> list[list[dict[str, str]]]:
        return [messages for model, messages in self.calls if model == name]


class FakeChat:
    """The sync ChatModel port of the judge: prepared replies, records what it was asked."""

    def __init__(self, replies: Iterable[str] = ()) -> None:
        self.replies, self.asked = list(replies), []

    def chat(self, messages: list[dict], schema: dict | None = None) -> str:
        self.asked.append({"messages": messages, "schema": schema})
        return self.replies.pop(0)


def as_dicts(hits: list[Hit]) -> list[dict[str, Any]]:
    return [{"chunk_id": h.chunk.chunk_id, "score": h.score} for h in hits]
