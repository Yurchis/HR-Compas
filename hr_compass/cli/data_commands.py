"""`hr-compass ingest`, `index`, `search`."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from hr_compass.cli.container import Container
from hr_compass.knowledge.application.index_check import check_access


def ingest(c: Container, args: argparse.Namespace) -> int:
    source = args.src or c.settings.ingest.source_dir
    result = c.ingest(raw=args.raw).run(source, full=args.full)
    print(f"dataset_version {result.dataset_version[:16]} | {len(result.files)} files {result.statuses} "
          f"| reused {result.reused} | removed {len(result.removed)} | chunks {len(result.records)}")
    print(f"near-duplicate document pairs: {len(result.near_duplicates)} -> {c.settings.ingest.output_dir}")
    for source, entry in result.files.items():
        if entry["status"] in ("error", "ocr_required"):
            print(f"  {entry['status']:<13} {source}  {entry.get('error', '')}")
    return 0


def index(c: Container, args: argparse.Namespace) -> int:
    started = time.perf_counter()
    vector_index = c.vector_index   # embeds every chunk (cache first) and builds the collection
    print(f"chunks {len(c.chunks)} | embedded now {c.embedder.last_missing} (rest from cache) "
          f"| model {c.settings.embeddings.model} | {time.perf_counter() - started:.1f}s")
    check = check_access(vector_index, c.chunks, c.policy)
    print(f"index: {check.total} points; chunks each group sees (groups expand: {dict(c.settings.access.inherits)})")
    for group, seen in check.visible.items():
        note = "" if seen == check.expected[group] else f"   MISMATCH: the rules allow {check.expected[group]}"
        print(f"  {group:<15} {seen:>5}{note}")
    print(f"  {'(no groups)':<15} {check.without_groups:>5}")
    print("access filter: " + ("OK" if check.ok else "LEAK or mismatch, see above"))
    return 0 if check.ok else 1


def search(c: Container, args: argparse.Namespace) -> int:
    configs = c.search_configurations
    unknown = set(args.config or []) - set(configs)
    if unknown:
        raise SystemExit(f"unknown --config {sorted(unknown)}; choose from {list(configs)}")
    groups = c.user_groups(args.groups)
    print(f"query {args.query!r} | groups {groups} -> {sorted(c.policy.expand(groups))} | country {args.country}")
    for name, retriever in configs.items():
        if args.config and name not in args.config:
            continue
        started = time.perf_counter()
        hits = retriever.search(c.search.query(args.query, groups, args.country))
        print(f"\n== {name}  ({(time.perf_counter() - started) * 1000:.0f} ms)")
        for hit in hits:
            print(f"  {hit.score:8.4f}  {hit.chunk.chunk_id[-60:]:<60}  {hit.chunk.section[-40:]}")
        if not hits:
            print("  (nothing)")
    return 0


def add_parsers(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("ingest", help="documents -> normalised text + chunk records (incremental)")
    p.add_argument("--src", type=Path, help="input folder (default: [ingest].source_dir)")
    p.add_argument("--full", action="store_true", help="ignore the previous run and re-ingest every file")
    p.add_argument("--raw", action="store_true", help="keep the extracted text as is, without normalisation")
    p.set_defaults(func=ingest, component="ingest")

    p = sub.add_parser("index", help="embed every chunk (cached), build the vector index, check access")
    p.set_defaults(func=index, component="index")

    p = sub.add_parser("search", help="show the top hits of every search configuration for one query")
    p.add_argument("query")
    p.add_argument("--groups", help="comma-separated groups of the user (default: [access].default_groups)")
    p.add_argument("--country", choices=("USA", "UA", "Costa Rica"))
    p.add_argument("--config", action="append", help="only this configuration (repeatable)")
    p.set_defaults(func=search, component="search")
