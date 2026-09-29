"""The schema.org vocabulary index shipped in data/vocab.json (built by scripts/build_vocab.py)."""
from __future__ import annotations

import difflib
import functools
import json
import pathlib

DATA = pathlib.Path(__file__).resolve().parent / "data" / "vocab.json"


class Vocab:
    def __init__(self, index: dict) -> None:
        self.index = index
        self.types: dict[str, list[str]] = index["types"]
        self.datatypes: set[str] = set(index["datatypes"])
        self.properties: dict[str, list[list[str]]] = index["properties"]
        self.enums: dict[str, list[str]] = index["enums"]
        self.layer: dict[str, str] = index.get("layer", {})
        self.superseded: dict[str, str] = index.get("superseded", {})
        self._member_of: dict[str, set[str]] = {}
        for enum_type, members in self.enums.items():
            for m in members:
                self._member_of.setdefault(m, set()).add(enum_type)
        self._lower_types = {t.lower(): t for t in self.types}
        self._lower_props = {p.lower(): p for p in self.properties}

    # -- lookups --------------------------------------------------------
    def is_type(self, name: str) -> bool:
        return name in self.types

    def is_property(self, name: str) -> bool:
        return name in self.properties

    def is_member(self, name: str) -> bool:
        return name in self._member_of

    def member_types(self, name: str) -> set[str]:
        return self._member_of.get(name, set())

    @functools.lru_cache(maxsize=None)
    def ancestors(self, name: str) -> frozenset[str]:
        """The type itself plus every supertype."""
        seen = {name}
        stack = [name]
        while stack:
            for sup in self.types.get(stack.pop(), []):
                if sup not in seen:
                    seen.add(sup)
                    stack.append(sup)
        return frozenset(seen)

    def is_subtype(self, name: str, of: str) -> bool:
        return of in self.ancestors(name)

    def is_enumeration(self, name: str) -> bool:
        return name in self.types and "Enumeration" in self.ancestors(name) or name in self.enums

    def enum_members(self, name: str) -> set[str]:
        """Members of an enumeration type, including members of its subtypes."""
        out: set[str] = set()
        for t, members in self.enums.items():
            if self.is_subtype(t, name):
                out.update(members)
        return out

    def domain(self, prop: str) -> list[str]:
        return self.properties[prop][0]

    def range(self, prop: str) -> list[str]:
        return self.properties[prop][1]

    def allowed_on(self, prop: str, types: list[str]) -> bool:
        domain = set(self.domain(prop))
        if not domain:
            return True
        return any(domain & self.ancestors(t) for t in types)

    # -- suggestions ----------------------------------------------------
    def suggest_type(self, name: str) -> str | None:
        return self._suggest(name, self._lower_types, list(self.types))

    def suggest_property(self, name: str, types: list[str] | None = None) -> str | None:
        candidates = list(self.properties)
        if types:
            allowed = [p for p in candidates if self.allowed_on(p, types)]
            hit = self._suggest(name, self._lower_props, allowed)
            if hit:
                return hit
        return self._suggest(name, self._lower_props, candidates)

    @staticmethod
    def _suggest(name: str, lower: dict[str, str], candidates: list[str]) -> str | None:
        exact = lower.get(name.lower())
        if exact and exact in candidates:
            return exact
        hits = difflib.get_close_matches(name, candidates, n=1, cutoff=0.75)
        return hits[0] if hits else None


@functools.lru_cache(maxsize=1)
def load() -> Vocab:
    return Vocab(json.loads(DATA.read_text(encoding="ascii")))
