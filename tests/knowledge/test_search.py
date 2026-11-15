"""Vector index, BM25, RRF, rerank, the four configurations and SearchService; access and country everywhere."""

from __future__ import annotations

import logging

import pytest

from hr_compass.knowledge.application.retrievers import HybridRetriever, RerankingRetriever, configurations
from hr_compass.knowledge.application.search_service import SearchService
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.retrieval import Hit, Query, rrf
from hr_compass.knowledge.infrastructure.bm25 import Bm25Retriever
from hr_compass.knowledge.infrastructure.embedding import CachingEmbedder, FastEmbedModel, VectorCache
from hr_compass.knowledge.infrastructure.qdrant_index import QdrantRetriever
from hr_compass.knowledge.infrastructure.rerankers import CrossEncoderReranker
from hr_compass.shared.settings import EmbeddingsConfig, SearchConfig
from tests.fakes import DIM, KeywordEmbedder, ListRetriever, OverlapReranker, chunk

CHUNKS = [
    chunk("handbook#0", "Employees may work from home up to two days per week.",
          section="2-5. Remote Work/Telecommuting", country="USA"),
    chunk("handbook#1", "Full-time employees accrue 15 vacation days per year.", section="3-3. Paid Vacations",
          country="USA"),
    chunk("handbook#2", "File the claim on form DB-450 within 30 days.", section="Short-Term Disability",
          country="USA"),
    chunk("contract#0", "The contractor is paid a monthly fee of 5000 USD.", section="Fees", access=("hr",)),
    chunk("ua-vacation#0", "Employees in Ukraine get 24 calendar days of vacation.", section="Paid Vacation",
          country="UA"),
    chunk("draft#0", "A draft nobody may read about remote work.", access=()),
]
POLICY = AccessPolicy({}, {"hr": ("all_employees",)})


def ids(hits: list[Hit]) -> list[str]:
    return [h.chunk.chunk_id for h in hits]


def q(text: str, groups=("all_employees",), k: int = 5, country: str | None = None) -> Query:
    return Query(text, POLICY.expand(groups), k, country)


@pytest.fixture(scope="module")
def vector() -> QdrantRetriever:
    return QdrantRetriever(CHUNKS, KeywordEmbedder(), DIM)


# ---------------------------------------------------------------- vector index


def test_one_point_per_chunk_with_the_chunk_as_payload(vector):
    assert vector.count() == len(CHUNKS)
    [hit] = vector.search(q("Can I work from home?", k=1))
    assert hit.chunk == CHUNKS[0]   # the whole record comes back


def test_rebuilding_replaces_the_collection():
    index = QdrantRetriever(CHUNKS, KeywordEmbedder(), DIM)
    QdrantRetriever(CHUNKS[:2], KeywordEmbedder(), DIM, client=index._client)

    assert index.count() == 2


@pytest.mark.parametrize(("groups", "country", "expected"), [
    (["all_employees"], None, {"handbook#0", "handbook#1", "handbook#2", "ua-vacation#0"}),
    (["hr"], None, {"handbook#0", "handbook#1", "handbook#2", "ua-vacation#0", "contract#0"}),   # hr includes all
    (["all_employees"], "UA", {"ua-vacation#0"}),
    (["hr"], "UA", {"ua-vacation#0", "contract#0"}),          # the contract is company-wide
    ([], None, set()),                                         # no groups: nothing, never "no filter"
    (["finance"], None, set()),                                # an unknown group sees nothing
])
def test_the_database_filter_applies_access_hierarchy_and_country(vector, groups, country, expected):
    assert set(ids(vector.search(q("anything", groups, k=20, country=country)))) == expected
    assert vector.count(POLICY.expand(groups), country) == len(expected)


# ---------------------------------------------------------------- BM25


def test_bm25_finds_an_exact_code_first():
    assert ids(Bm25Retriever(CHUNKS).search(q("form DB-450")))[0] == "handbook#2"


def test_bm25_skips_chunks_without_query_words_and_of_other_groups_or_countries():
    bm25 = Bm25Retriever(CHUNKS)

    assert ids(bm25.search(q("contractor monthly fee"))) == []
    assert ids(bm25.search(q("contractor monthly fee", ["hr"]))) == ["contract#0"]
    assert ids(bm25.search(q("vacation days", country="UA"))) == ["ua-vacation#0"]
    assert bm25.search(q("")) == [] and Bm25Retriever([]).search(q("x")) == []


def test_bm25_also_searches_the_section_path():
    assert ids(Bm25Retriever(CHUNKS).search(q("telecommuting"))) == ["handbook#0"]


# ---------------------------------------------------------------- RRF, hybrid, rerank


def _hits(*names: str) -> list[Hit]:
    return [Hit(chunk(f"{n}#0"), 99.0) for n in names]


def test_rrf_a_chunk_found_by_both_rankings_wins():
    fused = rrf([_hits("A", "B", "C"), _hits("C", "D")], k=5)

    assert ids(fused)[:2] == ["C#0", "A#0"] and fused[0].score == pytest.approx(1 / 63 + 1 / 61)


def test_rrf_cuts_to_k_replaces_scores_and_keeps_the_chunk():
    fused = rrf([_hits(*map(str, range(10)))], k=3)

    assert ids(fused) == ["0#0", "1#0", "2#0"] and fused[0].score == pytest.approx(1 / 61)
    assert fused[0].chunk == chunk("0#0") and rrf([], k=5) == [] and rrf([[], []], k=5) == []


def test_hybrid_asks_every_retriever_for_the_candidates():
    a, b = ListRetriever(CHUNKS[:3]), ListRetriever(CHUNKS[2:5])

    HybridRetriever([a, b], candidates=20, rrf_k=60).search(q("x", k=2))

    assert [r.queries[0].k for r in (a, b)] == [20, 20]


def test_rerank_moves_the_right_chunk_from_last_to_first():
    candidates = [CHUNKS[0], CHUNKS[1], CHUNKS[4], CHUNKS[2]]   # the disability chunk last

    hits = RerankingRetriever(ListRetriever(candidates), OverlapReranker(), 20).search(
        q("which form for a short-term disability claim", k=2))

    assert ids(hits)[0] == "handbook#2" and len(hits) == 2


def test_rerank_of_nothing_does_not_load_the_model(tmp_path):
    reranker = CrossEncoderReranker("any/model", tmp_path)

    assert RerankingRetriever(ListRetriever([]), reranker, 20).search(q("x")) == []
    assert "_encoder" not in reranker.__dict__   # the cached model was never built


def test_every_configuration_respects_access_and_k(vector):
    configs = configurations(vector, Bm25Retriever(CHUNKS), OverlapReranker(), SearchConfig())

    assert list(configs) == ["vector", "bm25", "hybrid", "hybrid+rerank"]
    for name, retriever in configs.items():
        assert "contract#0" not in ids(retriever.search(q("contractor monthly fee"))), name
        assert "draft#0" not in ids(retriever.search(q("remote work", ["hr"], k=20))), name
        assert len(retriever.search(q("work from home vacation days", k=3))) <= 3


# ---------------------------------------------------------------- real models (skipped until downloaded)


def _downloaded(name: str) -> bool:
    return any(EmbeddingsConfig().models_dir.glob(f"models--*{name}*"))


@pytest.mark.skipif(not _downloaded("paraphrase-multilingual"), reason="embedding model not downloaded")
def test_real_vector_search_finds_a_paraphrase_in_another_language(tmp_path):
    cfg = EmbeddingsConfig()
    embedder = CachingEmbedder(FastEmbedModel(cfg.model, cfg.models_dir), cfg.model, VectorCache(tmp_path / "c.json"))
    index = QdrantRetriever(CHUNKS, embedder, cfg.dim)

    assert ids(index.search(q("Скільки днів на тиждень можна працювати з дому?", k=1))) == ["handbook#0"]


@pytest.mark.skipif(not _downloaded("ms-marco"), reason="reranker model not downloaded")
def test_real_reranker_moves_the_right_chunk_to_the_top():
    reranker = CrossEncoderReranker(SearchConfig().local_rerank_model, EmbeddingsConfig().models_dir)
    candidates = [CHUNKS[0], CHUNKS[1], CHUNKS[4], CHUNKS[2]]

    hits = RerankingRetriever(ListRetriever(candidates), reranker, 20).search(
        q("Which form do I file for short-term disability?"))

    assert ids(hits)[0] == "handbook#2"


# ---------------------------------------------------------------- SearchService


def test_search_service_expands_groups_and_logs_refs_not_texts(caplog):
    service = SearchService(ListRetriever(CHUNKS), POLICY, k=3, mode="test")

    with caplog.at_level(logging.DEBUG, logger="hr_compass"):
        hits = service.search("contractor fee secret question", ["hr"], country="UA")

    assert ids(hits) == ["contract#0", "ua-vacation#0"]
    [info] = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info.fields["groups"] == ["all_employees", "hr"] and info.fields["country"] == "UA"
    assert info.fields["hits"][0].startswith(CHUNKS[3].ref) and "contract#0" not in str(info.fields)
    assert "secret question" not in info.getMessage() + str(info.fields)
    assert any("secret question" in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)
