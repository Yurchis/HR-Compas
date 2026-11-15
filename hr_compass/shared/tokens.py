"""Token counting: the `Tokenizer` port the domain depends on, and its tiktoken implementation."""

from __future__ import annotations

from functools import cached_property
from typing import Protocol


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...

    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: list[int]) -> str: ...


class TiktokenTokenizer:
    """cl100k_base for chunk sizes, o200k_base (gpt-4o family) for the prompt budget; downloaded on first use."""

    def __init__(self, encoding: str = "cl100k_base") -> None:
        self.encoding_name = encoding

    @cached_property
    def _encoding(self):
        import tiktoken

        return tiktoken.get_encoding(self.encoding_name)

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))

    def encode(self, text: str) -> list[int]:
        return self._encoding.encode(text)

    def decode(self, tokens: list[int]) -> str:
        return self._encoding.decode(tokens)
