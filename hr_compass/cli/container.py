"""Composition root: the one place that knows which infrastructure implements which port.

Everything is built lazily and once per command, from Settings; nothing lives in module globals, so tests build
the same objects with fakes instead of monkeypatching modules.
"""

from __future__ import annotations

from functools import cached_property

from hr_compass.assistant.application.ask_question import AskQuestion, AssistantPrompts, Generator
from hr_compass.ingestion.application.ingest_documents import IngestDocuments
from hr_compass.ingestion.infrastructure.dataset_repo import DatasetRepository
from hr_compass.ingestion.infrastructure.extractors import SUPPORTED, extract
from hr_compass.knowledge.application.retrievers import configurations
from hr_compass.knowledge.application.search_service import SearchService
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.knowledge.domain.retrieval import Reranker, Retriever
from hr_compass.knowledge.infrastructure.bm25 import Bm25Retriever
from hr_compass.knowledge.infrastructure.embedding import (
    CachingEmbedder,
    FastEmbedModel,
    OpenRouterEmbeddingModel,
    VectorCache,
)
from hr_compass.knowledge.infrastructure.files import load_access_rules, load_chunks
from hr_compass.knowledge.infrastructure.qdrant_index import QdrantRetriever
from hr_compass.knowledge.infrastructure.rerankers import CrossEncoderReranker, OpenRouterReranker
from hr_compass.shared.prompts import load_prompt
from hr_compass.shared.settings import Settings
from hr_compass.shared.tokens import TiktokenTokenizer


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---------------------------------------------------------------- shared

    @cached_property
    def policy(self) -> AccessPolicy:
        return AccessPolicy(load_access_rules(self.settings.access.rules_file), self.settings.access.inherits)

    def user_groups(self, value: str | None) -> list[str]:
        """--groups "a,b" -> ["a", "b"]; nothing -> [access].default_groups."""
        if not value:
            return list(self.settings.access.default_groups)
        return [g.strip() for g in value.split(",") if g.strip()]

    @cached_property
    def chunk_tokenizer(self) -> TiktokenTokenizer:
        return TiktokenTokenizer(self.settings.ingest.tokenizer)

    # ---------------------------------------------------------------- ingestion

    def ingest(self, *, raw: bool = False) -> IngestDocuments:
        cfg = self.settings.ingest
        return IngestDocuments(DatasetRepository(cfg.output_dir), extract, SUPPORTED, self.policy,
                               self.chunk_tokenizer, chunk_tokens=cfg.chunk_tokens, countries=cfg.countries, raw=raw,
                               strategy=cfg.strategy, fixed_overlap=cfg.fixed_overlap)

    # ---------------------------------------------------------------- knowledge

    @cached_property
    def chunks(self) -> list[ChunkRecord]:
        return load_chunks(self.settings.ingest.output_dir)

    @cached_property
    def chunks_by_id(self) -> dict[str, ChunkRecord]:
        return {c.chunk_id: c for c in self.chunks}

    @cached_property
    def embedder(self) -> CachingEmbedder:
        cfg = self.settings.embeddings
        model = (OpenRouterEmbeddingModel(self.settings, cfg.model, cfg.dim) if cfg.provider == "openrouter"
                 else FastEmbedModel(cfg.model, cfg.models_dir))
        return CachingEmbedder(model, cfg.model, VectorCache(cfg.cache_file), cfg.batch_size)

    @cached_property
    def vector_index(self) -> QdrantRetriever:
        return QdrantRetriever(self.chunks, self.embedder, self.settings.embeddings.dim)

    @cached_property
    def reranker(self) -> Reranker:
        cfg = self.settings.search
        if cfg.reranker == "openrouter":
            return OpenRouterReranker(self.settings, cfg.openrouter_rerank_model)
        return CrossEncoderReranker(cfg.local_rerank_model, self.settings.embeddings.models_dir)

    @cached_property
    def search_configurations(self) -> dict[str, Retriever]:
        return configurations(self.vector_index, Bm25Retriever(self.chunks), self.reranker, self.settings.search)

    @cached_property
    def search(self) -> SearchService:
        cfg = self.settings.search
        return SearchService(self.search_configurations[cfg.mode], self.policy, cfg.k, cfg.mode)

    # ---------------------------------------------------------------- assistant

    def prompts(self, *, intake: bool | None = None) -> AssistantPrompts:
        rag = self.settings.rag
        use_intake = rag.intake if intake is None else intake
        return AssistantPrompts(answer=load_prompt(rag.prompt),
                                intake=load_prompt(rag.intake_prompt) if use_intake else None,
                                condense=load_prompt(rag.condense_prompt) if rag.condense else None)

    def ask_question(self, llm: Generator, *, intake: bool | None = None) -> AskQuestion:
        return AskQuestion(llm, self.search, self.prompts(intake=intake),
                           TiktokenTokenizer(self.settings.rag.context_tokenizer),
                           context_budget=self.settings.rag.context_budget)
