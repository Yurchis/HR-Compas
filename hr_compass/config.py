"""Runtime configuration: `config/settings.toml` + the API key from the environment."""

from __future__ import annotations

import dataclasses
import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.toml"
CONFIG_PATH_ENV = "HR_COMPASS_CONFIG"
API_KEY_ENV = "OPENROUTER_API_KEY"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


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
    schema_name: str = "hr_answer"
    max_repair_attempts: int = 1

    def __post_init__(self) -> None:
        _require(self.max_repair_attempts >= 0, "structured_output.max_repair_attempts must be >= 0")
        _require(bool(self.schema_name), "structured_output.schema_name must not be empty")


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


@dataclass(frozen=True, slots=True)
class RerankConfig:
    """Retrieval: rerank handbook chunks by the question and keep only the top N in the prompt."""

    enabled: bool = False  # off = full-context (the whole handbook profile in the prompt)
    model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
    top_n: int = 8

    def __post_init__(self) -> None:
        _require(bool(self.model), "rerank.model must not be empty")
        _require(self.top_n >= 1, "rerank.top_n must be >= 1")


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str = field(repr=False)
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
    rerank: RerankConfig = field(default_factory=RerankConfig)
    models: Mapping[str, str] = field(default_factory=dict)  # alias -> OpenRouter slug
    pricing: Mapping[str, tuple[float, float]] = field(default_factory=dict)  # slug -> ($/1M input, $/1M output)

    def __post_init__(self) -> None:
        _require(bool(self.api_key), f"{API_KEY_ENV} is not set (add it to .env)")
        bad_prices = [
            k for k, v in self.pricing.items()
            if not (len(v) == 2 and all(isinstance(p, (int, float)) and p >= 0 for p in v))
        ]
        _require(not bad_prices, f"[pricing] needs [input, output] >= 0 in $/1M tokens: {', '.join(bad_prices)}")
        bad = [k for k, v in self.models.items() if not (isinstance(v, str) and v.strip())]
        _require(not bad, f"[models] slug must be a non-empty string: {', '.join(bad)}")
        _require(self.concurrency >= 1, "openrouter.concurrency must be >= 1")
        _require(bool(self.model), "openrouter.model must not be empty")
        overlap = set(self.retry.retry_statuses) & set(self.fallback.skip_statuses)
        _require(not overlap, f"retry.retry_statuses and fallback.skip_statuses overlap: {sorted(overlap)}")

    @property
    def model_chain(self) -> tuple[str, ...]:
        """Primary model followed by fallbacks (de-duplicated, order preserved)."""
        extra = self.fallback.models if self.fallback.enabled else ()
        return tuple(dict.fromkeys((self.model, *extra)))

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
        sections = {
            "generation": GenerationConfig,
            "timeout": TimeoutConfig,
            "retry": RetryConfig,
            "structured_output": StructuredOutputConfig,
            "fallback": FallbackConfig,
            "rerank": RerankConfig,
        }
        built = {name: _build(klass, raw.pop(name, {}), name) for name, klass in sections.items()}
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
        logger.info(
            "config loaded path=%s chain=%s temperature=%s top_p=%s structured=%s concurrency=%d rerank=%s",
            path,
            " -> ".join(settings.model_chain),
            settings.generation.temperature,
            settings.generation.top_p,
            settings.structured_output.enabled,
            settings.concurrency,
            f"{settings.rerank.model} top_n={settings.rerank.top_n}" if settings.rerank.enabled else "off",
        )
        return settings


def _reject_unknown(values: Mapping[str, Any], allowed: set[str], section: str) -> None:
    unknown = set(values) - allowed
    if unknown:
        raise ConfigError(f"[{section}] unknown key(s): {', '.join(sorted(unknown))}")


def _build(klass: type, values: Mapping[str, Any], section: str) -> Any:
    names = {f.name for f in dataclasses.fields(klass)}
    _reject_unknown(values, names, section)
    kwargs = {k: tuple(v) if isinstance(v, list) else v for k, v in values.items()}
    try:
        return klass(**kwargs)
    except TypeError as exc:
        raise ConfigError(f"[{section}] invalid value ({exc})") from exc
