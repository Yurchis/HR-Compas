"""IngestDocuments: every supported document of a folder -> normalised text + chunk records, incrementally.

A file whose bytes (raw_hash) did not change since the last run, under the same pipeline version and settings, is
not extracted again: its records (with their original ingested_at) and its text are reused. Access groups and
countries are always recomputed from the rules, so editing them needs no re-ingest. Files that failed last time
are retried; a file gone from the input folder loses its records and its text. Scans without a text layer and
unsupported types are reported instead of indexed.

Every event goes once to two sinks: audit.jsonl (durable lineage, with paths) and the log (hash refs only:
paths hold people's names).
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from hr_compass.ingestion.domain.chunking import ChunkDraft, chunk_by_headings, chunk_fixed
from hr_compass.ingestion.domain.dedup import NEAR_DUP_JACCARD, content_hash, near_duplicates
from hr_compass.ingestion.domain.document import (
    PIPELINE_VERSION,
    Document,
    Extracted,
    chunk_records,
    country_of,
    dataset_version,
    effective_date,
    title_of,
)
from hr_compass.ingestion.domain.normalize import normalize
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.shared.logging import kv, log_context
from hr_compass.shared.refs import doc_ref
from hr_compass.shared.tokens import Tokenizer

logger = logging.getLogger(__name__)


class DatasetStore(Protocol):
    def load_previous(self) -> tuple[dict[str, Any], dict[str, list[ChunkRecord]]]: ...
    def has_text(self, source: str) -> bool: ...
    def read_text(self, source: str) -> str: ...
    def write_text(self, source: str, text: str) -> None: ...
    def remove_text(self, source: str) -> bool: ...
    def text_sources(self) -> list[str]: ...
    def audit(self, event: str, source: str, **extra: Any) -> dict[str, Any]: ...
    def save(self, manifest: dict[str, Any], records: list[ChunkRecord]) -> None: ...


@dataclass
class IngestResult:
    dataset_version: str
    files: dict[str, dict[str, Any]]                # source -> report entry (status, hashes, chunks ...)
    records: list[ChunkRecord]
    near_duplicates: list[tuple[str, str, float]]
    reused: int
    removed: list[str]

    @property
    def statuses(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.files.values():
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        return counts


@dataclass
class _Run:
    """The state of one run while files are processed."""

    run_id: str
    previous_files: Mapping[str, dict[str, Any]]      # reusable files of the last run (empty if not reusable)
    previous_chunks: Mapping[str, list[ChunkRecord]]
    known_files: Mapping[str, dict[str, Any]] = field(default_factory=dict)   # every file of the last run
    report: dict[str, dict[str, Any]] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    records: list[ChunkRecord] = field(default_factory=list)
    reused: int = 0


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _run_id(previous: str | None) -> str:
    """The run's UTC start time in microseconds, always after the previous run's id: two quick runs must never
    share an id (their audit events would mix), and the clock on Windows ticks only every ~15 ms."""
    now = datetime.now(UTC)
    if previous and now <= (last := datetime.fromisoformat(previous)):
        now = last + timedelta(microseconds=1)
    return now.isoformat(timespec="microseconds")


class IngestDocuments:
    def __init__(self, store: DatasetStore, extract: Callable[[Path], Extracted], supported: Collection[str],
                 policy: AccessPolicy, tokenizer: Tokenizer, *, chunk_tokens: int, countries: Mapping[str, str],
                 raw: bool = False, strategy: str = "headings", fixed_overlap: int = 20) -> None:
        self._store, self._extract, self._supported = store, extract, supported
        self._policy, self._tokenizer = policy, tokenizer
        self._chunk_tokens, self._countries, self._raw = chunk_tokens, countries, raw
        self._strategy, self._fixed_overlap = strategy, fixed_overlap

    @property
    def _config(self) -> dict[str, Any]:
        """Settings that change the chunks (access rules and countries do not: they are applied on every run)."""
        config: dict[str, Any] = {"raw": self._raw, "strategy": self._strategy, "chunk_tokens": self._chunk_tokens}
        if self._strategy == "fixed":
            config["fixed_overlap"] = self._fixed_overlap
        return config

    def _chunk(self, text: str) -> list[ChunkDraft]:
        if self._strategy == "fixed":
            return chunk_fixed(text, self._tokenizer, self._chunk_tokens, self._fixed_overlap)
        return chunk_by_headings(text, self._tokenizer, self._chunk_tokens)

    def run(self, src: Path, *, full: bool = False) -> IngestResult:
        started = time.perf_counter()
        previous, previous_chunks = self._store.load_previous()
        run = self._start(_run_id(previous.get("created_at")), previous, previous_chunks, full)
        with log_context(run_id=run.run_id):
            files = sorted(f for f in src.rglob("*") if f.is_file())
            logger.info("ingest started", extra=kv(files=len(files), full=full, raw=self._raw,
                                                   pipeline_version=PIPELINE_VERSION))
            for n, path in enumerate(files, start=1):
                self._file(run, path, path.relative_to(src).as_posix(), n, len(files))
            removed = self._remove_gone(run)
            pairs = self._near_duplicates(run)
            result = self._finish(run, removed, pairs)
            logger.info("ingest finished", extra=kv(files=len(result.files), reused=result.reused,
                                                    removed=len(removed), chunks=len(result.records),
                                                    statuses=result.statuses, ms=_ms(started)))
        return result

    # ---------------------------------------------------------------- steps

    def _start(self, run_id: str, previous: dict[str, Any], previous_chunks: dict[str, Any], full: bool) -> _Run:
        known = previous.get("files", {})   # a file gone from the input loses its outputs even on a full run
        if full:
            return _Run(run_id, {}, {}, known)
        reusable = (previous.get("pipeline_version") == PIPELINE_VERSION
                    and previous.get("extract_config") == self._config)
        if previous and not reusable:
            logger.warning("pipeline version or extraction settings changed: every file is ingested again",
                           extra=kv(previous=previous.get("pipeline_version"), now=PIPELINE_VERSION))
        return _Run(run_id, known if reusable else {}, previous_chunks if reusable else {}, known)

    def _event(self, run: _Run, name: str, source: str, **extra: Any) -> None:
        """One event, two sinks: audit.jsonl gets the full record, the log only log-safe fields."""
        self._store.audit(name, source, run=run.run_id, **extra)
        safe = {k: (doc_ref(v) if k.endswith("hash") and isinstance(v, str) else v)
                for k, v in extra.items() if k not in ("error", "of")}
        logger.info("file %s", name, extra=kv(event=name, **safe))

    def _file(self, run: _Run, path: Path, rel: str, n: int, total: int) -> None:
        raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        with log_context(doc=doc_ref(raw_hash)):
            logger.debug("[%d/%d] %s", n, total, rel)
            if not self._reused(run, rel, raw_hash):
                self._ingest(run, path, rel, raw_hash)

    def _reused(self, run: _Run, rel: str, raw_hash: str) -> bool:
        """Take the file over from the last run when its bytes did not change and its outputs are complete."""
        prev = run.previous_files.get(rel)
        if not prev or prev.get("raw_hash") != raw_hash or prev.get("status") == "error":
            reason = "new" if not prev else "changed" if prev.get("raw_hash") != raw_hash else "failed before"
            logger.info("ingest", extra=kv(step="plan", decision="ingest", reason=reason))
            return False
        entry = {k: v for k, v in prev.items() if k != "near_duplicates"}  # recomputed at the end
        if prev["status"] != "ok":
            run.report[rel] = entry
            self._event(run, "unchanged", rel, raw_hash=raw_hash, status=prev["status"])
            run.reused += 1
            return True
        old = run.previous_chunks.get(rel, [])
        if not self._store.has_text(rel) or len(old) != prev.get("chunks"):
            logger.warning("unchanged but the outputs of the last run are incomplete: ingest again",
                           extra=kv(step="plan", chunks=len(old), expected=prev.get("chunks")))
            return False
        access, country = self._policy.groups_for(rel), country_of(rel, self._countries)
        run.records += [_relabelled(chunk, access, country) for chunk in old]
        run.report[rel] = {**entry, "access": list(access), "country": country}
        run.texts[rel] = self._store.read_text(rel)
        self._event(run, "unchanged", rel, raw_hash=raw_hash, doc_hash=prev.get("doc_hash"), chunks=len(old),
                    ingested_at=old[0].ingested_at if old else None)
        run.reused += 1
        return True

    def _ingest(self, run: _Run, path: Path, rel: str, raw_hash: str) -> None:
        if path.suffix.lower() not in self._supported:
            run.report[rel] = {"status": "unsupported", "raw_hash": raw_hash}
            logger.warning("unsupported file type, skipped", extra=kv(suffix=path.suffix.lower()))
            self._event(run, "unsupported", rel, raw_hash=raw_hash)
            return
        started = time.perf_counter()
        try:
            extracted = self._extract(path)
        except Exception as exc:  # one broken file must not stop the batch
            error = f"{type(exc).__name__}: {exc}"
            run.report[rel] = {"status": "error", "error": error, "raw_hash": raw_hash}
            logger.error("extract failed", extra=kv(step="extract", ms=_ms(started), error_type=type(exc).__name__))
            logger.debug("extract traceback", exc_info=True)
            self._event(run, "error", rel, raw_hash=raw_hash, error=error)
            return
        text = extracted.text
        pages = text.count("\f") + 1
        logger.info("extracted", extra=kv(step="extract", type=path.suffix.lower().lstrip("."), pages=pages,
                                          chars=len(text), needs_ocr=extracted.needs_ocr, ms=_ms(started)))
        if extracted.needs_ocr:
            run.report[rel] = {"status": "ocr_required", "raw_hash": raw_hash}
            logger.warning("no usable text layer (a scan?): needs OCR, not indexed")
            self._event(run, "ocr_required", rel, raw_hash=raw_hash)
            return
        doc = self._document(rel, path, raw_hash, text, extracted.metadata_title)
        self._store.write_text(rel, doc.text)
        access = self._policy.groups_for(rel)
        started = time.perf_counter()
        records = chunk_records(doc, self._chunk(doc.text), access,
                                self._tokenizer, run.run_id)
        tokens = [r.n_tokens for r in records]
        logger.info("chunked", extra=kv(step="chunk", chunks=len(records), tokens=sum(tokens),
                                        max_tokens=max(tokens, default=0), ms=_ms(started)))
        if not records:
            logger.warning("no chunks: the document is empty after extraction")
        if not access:
            logger.warning("no access rule matches: nobody may read this document")
        run.records += records
        run.texts[rel] = doc.text
        run.report[rel] = {"status": "ok", "title": doc.title, "effective": doc.effective, "country": doc.country,
                           "chars": len(doc.text), "pages": pages, "chunks": len(records), "access": list(access),
                           "raw_hash": raw_hash, "doc_hash": doc.doc_hash}
        self._event(run, "changed" if rel in run.previous_files else "ingested", rel, raw_hash=raw_hash,
                    doc_hash=doc.doc_hash, chunks=len(records), access=list(access), country=doc.country,
                    pipeline_version=PIPELINE_VERSION)

    def _document(self, rel: str, path: Path, raw_hash: str, text: str, metadata_title: str) -> Document:
        effective = effective_date(text)  # from the extracted text, before anything is removed
        if not self._raw:
            started, before = time.perf_counter(), len(text)
            text = normalize(text)
            logger.info("normalised", extra=kv(step="normalize", chars_before=before, chars=len(text),
                                               ms=_ms(started)))
        doc = Document(source=rel, raw_hash=raw_hash, text=text, doc_hash=content_hash(text),
                       title=title_of(text, metadata_title, path.name), effective=effective,
                       country=country_of(rel, self._countries))
        logger.debug("document title=%r effective=%s country=%s", doc.title, doc.effective, doc.country)
        return doc

    def _remove_gone(self, run: _Run) -> list[str]:
        """Files of the last run that are gone from the input, and any stored text no input file produces any
        more (left by an older run): their texts may hold names, so they never outlive their source. Paths are
        compared case-insensitively where the file system is (Windows: "Usa" and "USA" are one folder)."""
        present = {os.path.normcase(rel) for rel in run.report}
        gone = sorted({rel for rel in [*run.known_files, *self._store.text_sources()]
                       if os.path.normcase(rel) not in present})
        for rel in gone:
            raw_hash = run.known_files.get(rel, {}).get("raw_hash", "")
            with log_context(doc=doc_ref(raw_hash)):
                self._store.remove_text(rel)
                self._event(run, "removed", rel, raw_hash=raw_hash)
        return gone

    def _near_duplicates(self, run: _Run) -> list[tuple[str, str, float]]:
        started = time.perf_counter()
        pairs = near_duplicates(run.texts)
        logger.info("near-duplicate check", extra=kv(docs=len(run.texts), pairs=len(pairs),
                                                     threshold=NEAR_DUP_JACCARD, ms=_ms(started)))
        for a, b, score in pairs:
            for one, other in ((a, b), (b, a)):
                run.report[one].setdefault("near_duplicates", []).append({"of": other, "jaccard": round(score, 3)})
            self._event(run, "near_duplicate", a, of=b, jaccard=round(score, 3))
        return pairs

    def _finish(self, run: _Run, removed: list[str], pairs: list[tuple[str, str, float]]) -> IngestResult:
        version = dataset_version(run.report, config={"access": {k: list(v) for k, v in self._policy.rules.items()},
                                                      "countries": dict(self._countries), **self._config})
        manifest = {"dataset_version": version, "pipeline_version": PIPELINE_VERSION, "extract_config": self._config,
                    "created_at": run.run_id, "chunks": len(run.records), "files": run.report}
        self._store.save(manifest, run.records)
        self._event(run, "run_finished", "", dataset_version=version, files=len(run.report), reused=run.reused,
                    chunks=len(run.records))
        return IngestResult(version, run.report, run.records, pairs, run.reused, removed)


def _relabelled(chunk: ChunkRecord, access: Iterable[str], country: str | None) -> ChunkRecord:
    """A reused record under the current access rules and country folders."""
    return replace(chunk.with_access(access), country=country)
