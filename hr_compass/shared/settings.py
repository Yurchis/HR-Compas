"""Runtime configuration: `config/settings.toml` + the API key from the environment.

Every tunable number lives here, not in code. An unknown section or key, or an invalid value, is a startup error.
`Settings.fingerprint()` hashes the effective settings (never the key), so every result file can say exactly which
configuration produced it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hr_compass.shared.paths import CONFIG_DIR, resolve

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = CONFIG_DIR / "settings.toml"
CONFIG_PATH_ENV = "HR_COMPASS_CONFIG"
API_KEY_ENV = "OPENROUTER_API_KEY"
SEARCH_MODES = ("vector", "bm25", "hybrid", "hybrid+rerank")
CHUNK_STRATEGIES = ("headings", "fixed")
RERANKERS = ("local", "openrouter")
EMBEDDING_PROVIDERS = ("local", "openrouter")


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


# ---------------------------------------------------------------- the model client


@dataclass(frozen=True, slots=True)
class TimeoutConfig:
    connect_s: float = 5.0
    read_s: float = 60.0
    write_s: float = 10.0
    pool_s: float = 5.0
    attempt_s: float = 90.0

    def __post_init__(self) -> None:
        for f in dataclasses.fields(self):
            _require(getattr(self, f.name) > 0, f"timeout.{f.name} must be > 0")


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_retries: int = 3
    base_delay_s: float = 1.0
    multiplier: float = 2.0
    max_delay_s: float = 30.0
    jitter: bool = True
    respect_retry_after: bool = True
    retry_statuses: tuple[int, ...] = (408, 429, 500, 502, 503, 504)

    def __post_init__(self) -> None:
        _require(self.max_retries >= 0, "retry.max_retries must be >= 0")
        _require(self.base_delay_s >= 0, "retry.base_delay_s must be >= 0")
        _require(self.multiplier >= 1, "retry.multiplier must be >= 1")
        _require(self.max_delay_s >= self.base_delay_s, "retry.max_delay_s must be >= base_delay_s")

    def delay(self, attempt: int, random_unit: float) -> float:
        """Backoff before retry number `attempt` (0-based); `random_unit` in [0, 1) drives jitter."""
        ceiling = min(self.max_delay_s, self.base_delay_s * self.multiplier**attempt)
        return ceiling * random_unit if self.jitter else ceiling


@dataclass(frozen=True, slots=True)
class StructuredOutputConfig:
    enabled: bool = True
    strict: bool = True
    max_repair_attempts: int = 1

    def __post_init__(self) -> None:
        _require(self.max_repair_attempts >= 0, "structured_output.max_repair_attempts must be >= 0")


@dataclass(frozen=True, slots=True)
class FallbackConfig:
    enabled: bool = True
    models: tuple[str, ...] = ()
    skip_statuses: tuple[int, ...] = (400, 401, 402, 403)


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    temperature: float = 0.0
    top_p: float = 1.0  # nucleus sampling; 1.0 = off
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        _require(0 <= self.temperature <= 2, "generation.temperature must be in [0, 2]")
        _require(0 < self.top_p <= 1, "generation.top_p must be in (0, 1]")
        _require(self.max_tokens > 0, "generation.max_tokens must be > 0")


# ---------------------------------------------------------------- the RAG pipeline


@dataclass(frozen=True, slots=True)
class IngestConfig:
    source_dir: Path = Path("data/data_dirty")
    output_dir: Path = Path("data/data_clean")
    strategy: str = "headings"          # headings: by structure, whole blocks; fixed: a sliding token window
    chunk_tokens: int = 120
    fixed_overlap: int = 20             # fixed only: tokens shared by neighbouring windows
    tokenizer: str = "cl100k_base"
    archive_marker: str = "/Archive/"   # outdated copies: indexed for hr, never a relevant answer
    countries: Mapping[str, str] = field(
        default_factory=lambda: {"Usa": "USA", "UA": "UA", "costa Rica": "Costa Rica"})   # path segment -> country

    def __post_init__(self) -> None:
        _require(self.strategy in CHUNK_STRATEGIES, f"ingest.strategy must be one of {CHUNK_STRATEGIES}")
        _require(self.chunk_tokens >= 16, "ingest.chunk_tokens must be >= 16")
        _require(0 <= self.fixed_overlap < self.chunk_tokens, "ingest.fixed_overlap must be in [0, chunk_tokens)")
        _set_paths(self, "source_dir", "output_dir")


@dataclass(frozen=True, slots=True)
class EmbeddingsConfig:
    provider: str = "local"            # local: fastembed on CPU; openrouter: the /embeddings endpoint (needs the key)
    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    dim: int = 384
    batch_size: int = 64
    models_dir: Path = Path(".models")
    cache_dir: Path = Path(".cache/embeddings")   # one JSON file per model

    def __post_init__(self) -> None:
        _require(self.provider in EMBEDDING_PROVIDERS, f"embeddings.provider must be one of {EMBEDDING_PROVIDERS}")
        _require(self.dim > 0 and self.batch_size > 0, "embeddings.dim and batch_size must be > 0")
        _set_paths(self, "models_dir", "cache_dir")

    @property
    def cache_file(self) -> Path:
        """.cache/embeddings/<model, slashes as dashes>.json: a cache never mixes models of different sizes."""
        return self.cache_dir / f"{re.sub(r'[^A-Za-z0-9._-]+', '-', self.model)}.json"


@dataclass(frozen=True, slots=True)
class SearchConfig:
    mode: str = "hybrid+rerank"
    k: int = 5
    candidates: int = 20
    rrf_k: int = 60
    reranker: str = "local"
    local_rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    openrouter_rerank_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"

    def __post_init__(self) -> None:
        _require(self.mode in SEARCH_MODES, f"search.mode must be one of {SEARCH_MODES}")
        _require(self.reranker in RERANKERS, f"search.reranker must be one of {RERANKERS}")
        _require(1 <= self.k <= self.candidates, "search needs 1 <= k <= candidates")
        _require(self.rrf_k > 0, "search.rrf_k must be > 0")


@dataclass(frozen=True, slots=True)
class RagConfig:
    prompt: Path = Path("prompts/v6_rag_cited.md")
    intake: bool = True
    intake_prompt: Path = Path("prompts/intake_v3_en.md")
    condense: bool = True
    condense_prompt: Path = Path("prompts/condense_v1.md")
    history_turns: int = 3
    context_budget: int = 1500
    context_tokenizer: str = "o200k_base"

    def __post_init__(self) -> None:
        _require(self.context_budget > 0, "rag.context_budget must be > 0")
        _require(self.history_turns >= 0, "rag.history_turns must be >= 0")
        _set_paths(self, "prompt", "intake_prompt", "condense_prompt")


@dataclass(frozen=True, slots=True)
class AccessConfig:
    rules_file: Path = Path("config/access.json")
    default_groups: tuple[str, ...] = ("all_employees",)
    inherits: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: {
        "hr": ("all_employees",), "managers": ("all_employees",), "leadership": ("all_employees",)})

    def __post_init__(self) -> None:
        _require(bool(self.default_groups), "access.default_groups must not be empty")
        _set_paths(self, "rules_file")


@dataclass(frozen=True, slots=True)
class EvalConfig:
    testset: Path = Path("data/testset.json")
    labels: Path = Path("data/labels.json")
    results_dir: Path = Path("results")
    tolerance: float = 0.05
    kinds_min: int = 2
    judge_prompts: str = "judge-v3"

    def __post_init__(self) -> None:
        _require(0 <= self.tolerance < 1, "eval.tolerance must be in [0, 1)")
        _require(self.kinds_min >= 1, "eval.kinds_min must be >= 1")
        _set_paths(self, "testset", "labels", "results_dir")


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    dir: Path = Path("logs")
    max_bytes: int = 5_000_000
    backup_count: int = 5

    def __post_init__(self) -> None:
        _require(self.max_bytes > 0 and self.backup_count >= 0, "logging.max_bytes > 0, backup_count >= 0")
        _set_paths(self, "dir")


def _set_paths(config: object, *names: str) -> None:
    for name in names:
        object.__setattr__(config, name, resolve(getattr(config, name)))


# ---------------------------------------------------------------- settings


SECTIONS: dict[str, type] = {
    "generation": GenerationConfig, "timeout": TimeoutConfig, "retry": RetryConfig,
    "structured_output": StructuredOutputConfig, "fallback": FallbackConfig, "ingest": IngestConfig,
    "embeddings": EmbeddingsConfig, "search": SearchConfig, "rag": RagConfig, "access": AccessConfig,
    "eval": EvalConfig, "logging": LoggingConfig,
}


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str = field(default="", repr=False)   # only the model client needs it: `require_api_key`
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/gpt-4o-mini"
    concurrency: int = 4
    app_url: str | None = None
    app_title: str | None = "HR Compass"
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    structured_output: StructuredOutputConfig = field(default_factory=StructuredOutputConfig)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    rag: RagConfig = field(default_factory=RagConfig)
    access: AccessConfig = field(default_factory=AccessConfig)
    eval: EvalConfig = field(default_factory=EvalConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    models: Mapping[str, str] = field(default_factory=dict)  # alias -> OpenRouter slug
    pricing: Mapping[str, tuple[float, float]] = field(default_factory=dict)  # slug -> ($/1M input, $/1M output)

    def __post_init__(self) -> None:
        bad_prices = [k for k, v in self.pricing.items()
                      if not (len(v) == 2 and all(isinstance(p, (int, float)) and p >= 0 for p in v))]
        _require(not bad_prices, f"[pricing] needs [input, output] >= 0 in $/1M tokens: {', '.join(bad_prices)}")
        bad = [k for k, v in self.models.items() if not (isinstance(v, str) and v.strip())]
        _require(not bad, f"[models] slug must be a non-empty string: {', '.join(bad)}")
        _require(self.concurrency >= 1, "openrouter.concurrency must be >= 1")
        _require(bool(self.model), "openrouter.model must not be empty")
        overlap = set(self.retry.retry_statuses) & set(self.fallback.skip_statuses)
        _require(not overlap, f"retry.retry_statuses and fallback.skip_statuses overlap: {sorted(overlap)}")

    def require_api_key(self) -> str:
        _require(bool(self.api_key), f"{API_KEY_ENV} is not set (add it to .env)")
        return self.api_key

    @property
    def model_chain(self) -> tuple[str, ...]:
        """Primary model followed by fallbacks (de-duplicated, order preserved)."""
        extra = self.fallback.models if self.fallback.enabled else ()
        return tuple(dict.fromkeys((self.model, *extra)))

    def resolve_model(self, name: str) -> str:
        """An alias from [models] or an OpenRouter slug as is."""
        return self.models.get(name, name)

    def fingerprint(self) -> str:
        """sha256 of the effective settings without the key: the same fingerprint, the same configuration."""
        values = {f.name: getattr(self, f.name) for f in dataclasses.fields(self) if f.name != "api_key"}
        return hashlib.sha256(json.dumps(_plain(values), sort_keys=True).encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: Path | None = None, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        path = path or Path(env.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH)
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: invalid TOML ({exc})") from exc

        top = dict(raw.pop("openrouter", {}))
        models = dict(raw.pop("models", {}))
        pricing = {k: tuple(v) if isinstance(v, list) else v for k, v in raw.pop("pricing", {}).items()}
        built = {name: _build(klass, raw.pop(name, {}), name) for name, klass in SECTIONS.items()}
        if raw:
            raise ConfigError(f"{path}: unknown section(s): {', '.join(sorted(raw))}")
        _reject_unknown(top, {"base_url", "model", "concurrency", "app_url", "app_title"}, "openrouter")
        if "base_url" in top:
            top["base_url"] = str(top["base_url"]).rstrip("/")
        for key in ("app_url", "app_title"):
            if key in top:
                top[key] = top[key] or None
        settings = cls(api_key=env.get(API_KEY_ENV, "").strip(), models=models, pricing=pricing, **top, **built)
        # The API key is never logged, not even masked.
        logger.info("config loaded path=%s chain=%s search=%s reranker=%s fingerprint=%s", path,
                    " -> ".join(settings.model_chain), settings.search.mode, settings.search.reranker,
                    settings.fingerprint()[:12])
        return settings


def _plain(value: Any) -> Any:
    """JSON-ready form: dataclasses -> dicts, paths -> strings relative to nothing machine-specific."""
    if dataclasses.is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Path):
        return value.name   # the file name: the same settings on two machines give the same fingerprint
    return value


def _reject_unknown(values: Mapping[str, Any], allowed: set[str], section: str) -> None:
    unknown = set(values) - allowed
    if unknown:
        raise ConfigError(f"[{section}] unknown key(s): {', '.join(sorted(unknown))}")


def _convert(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, Mapping):
        return {k: _convert(v) for k, v in value.items()}
    return value


def _build(klass: type, values: Mapping[str, Any], section: str) -> Any:
    _reject_unknown(values, {f.name for f in dataclasses.fields(klass)}, section)
    try:
        return klass(**{k: _convert(v) for k, v in values.items()})
    except TypeError as exc:
        raise ConfigError(f"[{section}] invalid value ({exc})") from exc
