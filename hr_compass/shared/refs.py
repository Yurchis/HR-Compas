"""Log-safe references. Source paths and chunk ids carry people's names ("Offer Letter EU <name>.docx"), so INFO
log lines name a document by a hash prefix and a chunk by "<hash>#<index>"; full paths appear only at DEBUG."""

from __future__ import annotations

REF_CHARS = 12


def doc_ref(content_hash: str) -> str:
    return content_hash[:REF_CHARS]


def chunk_ref(doc_hash: str, chunk_index: int) -> str:
    return f"{doc_hash[:REF_CHARS]}#{chunk_index}"
