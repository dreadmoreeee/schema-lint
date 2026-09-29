"""Data model shared by the extractors, the checks and the reports."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SEVERITIES = ("error", "warning", "info")
RANK = {"info": 1, "warning": 2, "error": 3}

_SCHEMA_IRI = re.compile(r"^https?://(?:www\.)?schema\.org/([^/#?]+)$")


def schema_name(iri: str) -> str | None:
    """'https://schema.org/Product' or 'http://schema.org/Product' -> 'Product', else None."""
    m = _SCHEMA_IRI.match(iri.strip())
    return m.group(1) if m else None


@dataclass
class Ref:
    """A reference to another node, e.g. {"@id": "https://example.com/#org"}."""
    id: str


@dataclass
class Item:
    """One structured-data node, whatever syntax it came from.

    types: schema.org type names ('Product'); types from other vocabularies keep
    their full IRI (they contain ':'). props: schema.org property name -> values;
    a value is a str/int/float/bool, a nested Item or a Ref.
    """
    syntax: str
    line: int = 0
    types: list[str] = field(default_factory=list)
    id: str | None = None
    props: dict[str, list] = field(default_factory=dict)

    def add(self, name: str, value) -> None:
        self.props.setdefault(name, []).append(value)

    @property
    def schema_types(self) -> list[str]:
        return [t for t in self.types if ":" not in t]

    @property
    def label(self) -> str:
        return "/".join(self.types) if self.types else "(no type)"


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    path: str = ""
    syntax: str = ""
    line: int = 0
    url: str = ""
    help: str = ""

    def as_dict(self) -> dict:
        d = {"severity": self.severity, "code": self.code, "message": self.message,
             "path": self.path, "syntax": self.syntax, "line": self.line, "url": self.url}
        if self.help:
            d["help"] = self.help
        return d


@dataclass
class Page:
    url: str
    items: list[Item] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    error: str = ""
