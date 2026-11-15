"""Who may read what: rules map a document path to groups, a user's groups expand along the hierarchy.

Rules (config/access.json): a key is a path prefix ("Policies/") or, with * ? [, a glob over the whole path
("*Offer Letter*"). The longest matching key wins; no match -> no groups, so an unlisted document is not exposed
by accident. The hierarchy ([access].inherits) says what a group includes: hr includes all_employees, so an HR
user does not need to list both. Enforcement happens in the search (a database filter), never in a prompt.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

GLOB_CHARS = frozenset("*?[")


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    rules: Mapping[str, tuple[str, ...]]
    inherits: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def groups_for(self, source: str) -> tuple[str, ...]:
        """Groups that may read chunks of `source`."""
        matches = [rule for rule in self.rules
                   if (fnmatchcase(source, rule) if GLOB_CHARS & set(rule) else source.startswith(rule))]
        return tuple(self.rules[max(matches, key=len)]) if matches else ()

    def expand(self, groups: Iterable[str]) -> frozenset[str]:
        """The user's groups plus everything they include, transitively; empty names are dropped."""
        result: set[str] = set()
        pending = [g for g in groups if g]
        while pending:
            group = pending.pop()
            if group not in result:
                result.add(group)
                pending.extend(self.inherits.get(group, ()))
        return frozenset(result)

    def can_read(self, access: Iterable[str], groups: Iterable[str]) -> bool:
        return bool(set(access) & self.expand(groups))
