"""After building the index: does the database filter let every group see exactly what the rules allow?"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.chunk import ChunkRecord


class CountingIndex(Protocol):
    def count(self, groups: Iterable[str] | None = None, country: str | None = None) -> int: ...


@dataclass(frozen=True, slots=True)
class AccessCheck:
    total: int
    visible: dict[str, int]     # group -> chunks the index returns for a user of that group
    expected: dict[str, int]    # group -> chunks the access rules allow
    without_groups: int         # must be 0

    @property
    def ok(self) -> bool:
        return self.visible == self.expected and self.without_groups == 0


def check_access(index: CountingIndex, chunks: list[ChunkRecord], policy: AccessPolicy) -> AccessCheck:
    groups = sorted({g for c in chunks for g in c.access})
    return AccessCheck(
        total=index.count(),
        visible={g: index.count(policy.expand([g])) for g in groups},
        expected={g: sum(policy.can_read(c.access, [g]) for c in chunks) for g in groups},
        without_groups=index.count(policy.expand([])),
    )
