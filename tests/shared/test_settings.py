from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from hr_compass.shared.paths import ROOT, resolve
from hr_compass.shared.settings import (
    ConfigError,
    FallbackConfig,
    GenerationConfig,
    RetryConfig,
    SearchConfig,
    Settings,
)

ENV = {"OPENROUTER_API_KEY": "k"}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "c.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_shipped_config_loads_without_a_key():
    s = Settings.load(env={})   # ingest / index / search / eval lint need no key

    assert s.model_chain[0] == s.model and len(s.model_chain) >= 2
    assert s.search.mode == "hybrid+rerank" and s.search.k == 5 and s.ingest.chunk_tokens == 120
    assert s.ingest.countries == {"Usa": "USA", "UA": "UA", "costa Rica": "Costa Rica"}
    assert s.access.inherits["hr"] == ("all_employees",) and s.models["gpt4omini"] == "openai/gpt-4o-mini"


def test_only_the_model_client_requires_the_key():
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        Settings.load(env={}).require_api_key()
    assert Settings.load(env=ENV).require_api_key() == "k"


def test_unknown_keys_sections_and_bad_values_are_errors(tmp_path):
    for text, match in [("[retry]\nbogus = 1\n", "unknown key"), ("[timeout]\nconnect_s = -1\n", "connect_s"),
                        ("[nope]\nx = 1\n", "unknown section"), ("[rerank]\nenabled = true\n", "unknown section"),
                        ('[search]\nmode = "magic"\n', "search.mode"), ("[search]\nk = 30\n", "k <= candidates"),
                        ('[ingest]\nstrategy = "semantic"\n', "ingest.strategy"),
                        ("[ingest]\nchunk_tokens = 100\nfixed_overlap = 100\n", "fixed_overlap")]:
        with pytest.raises(ConfigError, match=match):
            Settings.load(write(tmp_path, text), ENV)


def test_relative_paths_are_resolved_against_the_project_root(tmp_path):
    s = Settings.load(write(tmp_path, '[ingest]\noutput_dir = "out/clean"\n[eval]\ntestset = "t.json"\n'), ENV)

    assert s.ingest.output_dir == ROOT / "out" / "clean" and s.eval.testset == ROOT / "t.json"
    assert resolve(tmp_path) == tmp_path   # absolute stays absolute


def test_nested_tables_become_mappings_of_tuples(tmp_path):
    s = Settings.load(write(tmp_path, '[access.inherits]\nhr = ["all_employees", "managers"]\n'
                                      '[ingest.countries]\n"PL" = "Poland"\n'), ENV)

    assert s.access.inherits == {"hr": ("all_employees", "managers")} and s.ingest.countries == {"PL": "Poland"}


def test_the_fingerprint_changes_with_any_setting_but_not_with_the_key():
    s = Settings.load(env=ENV)

    assert s.fingerprint() == replace(s, api_key="other").fingerprint() and len(s.fingerprint()) == 64
    assert s.fingerprint() != replace(s, search=SearchConfig(k=3)).fingerprint()
    assert s.fingerprint() != replace(s, model="anthropic/claude-haiku-5.5").fingerprint()


def test_the_embedding_provider_is_validated_and_every_model_has_its_own_cache_file(tmp_path):
    s = Settings.load(write(tmp_path, '[embeddings]\nprovider = "openrouter"\n'
                                      'model = "openai/text-embedding-3-large"\ndim = 3072\n'), ENV)

    assert s.embeddings.cache_file.name == "openai-text-embedding-3-large.json"
    assert Settings.load(env=ENV).embeddings.cache_file.name == \
        "sentence-transformers-paraphrase-multilingual-MiniLM-L12-v2.json"
    with pytest.raises(ConfigError, match=r"embeddings\.provider"):
        Settings.load(write(tmp_path, '[embeddings]\nprovider = "magic"\n'), ENV)


def test_the_key_never_appears_in_repr():
    assert "secret-key" not in repr(replace(Settings.load(env=ENV), api_key="secret-key"))


def test_backoff_is_exponential_and_capped():
    r = RetryConfig(base_delay_s=1, multiplier=2, max_delay_s=5, jitter=False)
    assert [r.delay(i, 0.5) for i in range(5)] == [1, 2, 4, 5, 5]
    assert RetryConfig(base_delay_s=1, jitter=True).delay(2, 0.5) == 2.0


@pytest.mark.parametrize("top_p", [0, 1.5])
def test_top_p_is_validated(top_p):
    with pytest.raises(ConfigError, match="top_p"):
        GenerationConfig(top_p=top_p)


def test_overlapping_retry_and_fallback_statuses_are_rejected():
    with pytest.raises(ConfigError, match="overlap"):
        Settings(fallback=FallbackConfig(skip_statuses=(429,)))


def test_fallback_disabled_uses_the_primary_model_only_and_aliases_resolve():
    s = Settings(fallback=FallbackConfig(enabled=False, models=("x",)), models={"mini": "openai/gpt-4o-mini"})
    assert s.model_chain == (s.model,)
    assert s.resolve_model("mini") == "openai/gpt-4o-mini" and s.resolve_model("a/b") == "a/b"


def test_pricing_is_validated(tmp_path):
    assert Settings.load(write(tmp_path, '[pricing]\n"a/b" = [0.15, 0.60]\n'), ENV).pricing == {"a/b": (0.15, 0.6)}
    with pytest.raises(ConfigError, match="pricing"):
        Settings.load(write(tmp_path, '[pricing]\n"a/b" = [-1, 0.6]\n'), ENV)
