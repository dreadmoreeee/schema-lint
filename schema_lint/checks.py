"""Checks items against the schema.org vocabulary."""
from __future__ import annotations

import datetime as dt
import re

from .model import Finding, Item, Ref, schema_name
from .vocab import Vocab

TEXT_LIKE = {"Text", "CssSelectorType", "XPathType", "PronounceableText"}
NUMBER = {"Number", "Float"}
_TZ = r"(?:Z|[+-]\d{2}(?::?\d{2})?)?"
_TIME = r"\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?" + _TZ
DATE_RE = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")
DATETIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(" + _TIME + r")$")
TIME_RE = re.compile(r"^" + _TIME + r"$")
DURATION_RE = re.compile(r"^-?P(?=\d|T\d)(?:\d+(?:[.,]\d+)?Y)?(?:\d+(?:[.,]\d+)?M)?(?:\d+(?:[.,]\d+)?W)?"
                         r"(?:\d+(?:[.,]\d+)?D)?(?:T(?=\d)(?:\d+(?:[.,]\d+)?H)?(?:\d+(?:[.,]\d+)?M)?"
                         r"(?:\d+(?:[.,]\d+)?S)?)?$")
NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
INT_RE = re.compile(r"^[+-]?\d+$")
ABS_URL_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)\S+$")


def is_date(s: str) -> bool:
    if not DATE_RE.match(s):
        return False
    if len(s) == 10:
        try:
            dt.date.fromisoformat(s)
        except ValueError:
            return False
    elif len(s) == 7 and not 1 <= int(s[5:7]) <= 12:
        return False
    return True


def _time_ok(t: str) -> bool:
    m = re.match(r"^(\d{2}):(\d{2})(?::(\d{2}))?", t)
    if not m:
        return False
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return (h < 24 or (h == 24 and mi == 0 and s == 0)) and mi < 60 and s < 61


def is_datetime(s: str) -> bool:
    m = DATETIME_RE.match(s)
    return bool(m) and is_date(m.group(1)) and _time_ok(m.group(2))


def is_time(s: str) -> bool:
    return bool(TIME_RE.match(s)) and _time_ok(s)


def is_duration(s: str) -> bool:
    return bool(DURATION_RE.match(s))


def _q(s: str, n: int = 60) -> str:
    s = s.replace("\n", " ")
    return repr(s if len(s) <= n else s[: n - 3] + "...")


def _or(names) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


class Checker:
    def __init__(self, vocab: Vocab, url: str = "") -> None:
        self.v = vocab
        self.url = url
        self.findings: list[Finding] = []
        self.index: dict[str, list[Item]] = {}
        self._seen: set[tuple] = set()

    # -- plumbing ---------------------------------------------------------
    def add(self, severity: str, code: str, message: str, path: str, item: Item) -> None:
        key = (code, message, path, item.syntax, item.line)
        if key not in self._seen:
            self._seen.add(key)
            self.findings.append(Finding(severity, code, message, path, item.syntax, item.line, self.url))

    def build_index(self, items: list[Item]) -> dict[str, list[Item]]:
        stack = list(items)
        seen: set[int] = set()
        while stack:
            it = stack.pop()
            if id(it) in seen:
                continue
            seen.add(id(it))
            if it.id:
                self.index.setdefault(it.id, []).append(it)
            for values in it.props.values():
                stack.extend(v for v in values if isinstance(v, Item))
        return self.index

    def run(self, items: list[Item]) -> list[Finding]:
        self.build_index(items)
        for item in items:
            self.item(item, item.label, None, 0)
        return self.findings

    # -- items --------------------------------------------------------------
    def known_types(self, item: Item) -> list[str]:
        return [t for t in item.schema_types if self.v.is_type(t)]

    def item(self, item: Item, path: str, implied: str | None, depth: int) -> None:
        if depth > 40:
            return
        v = self.v
        known: list[str] = []
        for t in item.schema_types:
            if v.is_type(t):
                known.append(t)
                if t in v.superseded:
                    self.add("warning", "superseded", f"type '{t}' is superseded by '{v.superseded[t]}'", path, item)
                elif v.layer.get(t) == "pending":
                    self.add("info", "pending", f"type '{t}' is in schema.org's pending area and may change", path, item)
                if t in v.datatypes:
                    self.add("error", "datatype-as-type", f"'{t}' is a data type, not a type for an item", path, item)
            elif v.is_member(t):
                self.add("error", "enum-as-type",
                         f"'{t}' is an enumeration value ({_or(sorted(v.member_types(t)))}), not a type", path, item)
            else:
                hint = v.suggest_type(t)
                self.add("error", "unknown-type", f"unknown type '{t}'" + (f"; did you mean '{hint}'?" if hint else ""),
                         path, item)
        if not item.types:
            if implied:
                known = [implied]
            else:
                self.add("warning", "missing-type", "item has no @type/itemtype, so its properties cannot be checked "
                         "against a type", path, item)
        elif not item.schema_types:
            return  # only other vocabularies
        for prop, values in item.props.items():
            ppath = f"{path} > {prop}"
            if not v.is_property(prop):
                if v.is_type(prop):
                    msg = f"'{prop}' is a type, not a property"
                else:
                    hint = v.suggest_property(prop, known)
                    msg = f"unknown property '{prop}'" + (f"; did you mean '{hint}'?" if hint else "")
                self.add("error", "unknown-property", msg, ppath, item)
                for val in values:
                    if isinstance(val, Item):
                        self.item(val, f"{ppath} > {val.label}", None, depth + 1)
                continue
            if prop in v.superseded:
                self.add("warning", "superseded", f"property '{prop}' is superseded by '{v.superseded[prop]}'",
                         ppath, item)
            elif v.layer.get(prop) == "pending":
                self.add("info", "pending", f"property '{prop}' is in schema.org's pending area and may change",
                         ppath, item)
            if known and not v.allowed_on(prop, known):
                domain = v.domain(prop)
                shown = _or(domain[:4] + (["..."] if len(domain) > 4 else []))
                self.add("error", "property-not-allowed",
                         f"'{prop}' is not a property of {_or(known)} (it belongs to {shown})", ppath, item)
            for val in values:
                self.value(prop, val, ppath, item, depth)

    # -- values ------------------------------------------------------------
    def value(self, prop: str, val, path: str, owner: Item, depth: int) -> None:
        v = self.v
        rng = v.range(prop)
        classes = [r for r in rng if r not in v.datatypes and not v.is_enumeration(r)]
        if isinstance(val, Item):
            known = self.known_types(val)
            implied = None
            if not val.types:
                implied = classes[0] if len(classes) == 1 else None
                if not classes:
                    self.add("error", "wrong-type", f"'{prop}' expects {_or(rng)}, got an object", path, owner)
            elif known and not self._accepts(rng, known):
                self.add("error", "wrong-type", f"'{prop}' expects {_or(rng)}, got {_or(known)}", path, owner)
            label = val.label if val.types else (f"({implied})" if implied else "(no type)")
            self.item(val, f"{path} > {label}", implied, depth + 1)
        elif isinstance(val, Ref):
            targets = self.index.get(val.id, [])
            known = [t for x in targets for t in self.known_types(x)]
            if known and not self._accepts(rng, known):
                self.add("error", "wrong-type", f"'{prop}' expects {_or(rng)}, but {val.id} is {_or(known)}",
                         path, owner)
            elif not targets and not classes and "URL" not in rng:
                self.add("warning", "wrong-type", f"'{prop}' expects {_or(rng)}, got a reference to {val.id}",
                         path, owner)
        elif val is None or (isinstance(val, str) and not val.strip()):
            self.add("warning", "empty-value", f"'{prop}' is empty", path, owner)
        elif isinstance(val, bool):
            if not ({"Boolean"} | TEXT_LIKE) & set(rng):
                self.add(self._sev(classes), "wrong-type", f"'{prop}' expects {_or(rng)}, got boolean {val}",
                         path, owner)
        elif isinstance(val, (int, float)):
            ok = TEXT_LIKE & set(rng) or NUMBER & set(rng) or ("Integer" in rng and float(val).is_integer())
            if not ok:
                got = "a non-integer number" if "Integer" in rng else f"number {val}"
                self.add(self._sev(classes), "wrong-type", f"'{prop}' expects {_or(rng)}, got {got}", path, owner)
        elif isinstance(val, str):
            self.text(prop, val.strip(), rng, classes, path, owner)

    def _accepts(self, rng: list[str], types: list[str]) -> bool:
        return any(self.v.is_subtype(t, r) for t in types for r in rng + ["Role"])

    @staticmethod
    def _sev(classes: list[str]) -> str:
        return "warning" if classes else "error"

    def text(self, prop: str, s: str, rng: list[str], classes: list[str], path: str, owner: Item) -> None:
        v = self.v
        problems: list[str] = []
        if not rng:
            return
        for r in rng:
            if r in TEXT_LIKE:
                return
            if r == "URL":
                if ABS_URL_RE.match(s):
                    return
                problems.append("url")
            elif r == "Date":
                if is_date(s):
                    return
                problems.append("date")
            elif r == "DateTime":
                if is_datetime(s) or is_date(s):
                    return
                problems.append("date")
            elif r == "Time":
                if is_time(s):
                    return
                problems.append("date")
            elif r in NUMBER:
                if NUMBER_RE.match(s):
                    return
                problems.append("number")
            elif r == "Integer":
                if INT_RE.match(s):
                    return
                problems.append("number")
            elif r == "Boolean":
                if s.lower() in ("true", "false") or schema_name(s) in ("True", "False"):
                    return
                problems.append("boolean")
            elif v.is_subtype(r, "Quantity"):
                if r != "Duration" or is_duration(s):
                    return
                problems.append("duration")
            elif v.is_enumeration(r):
                members = v.enum_members(r)
                if (schema_name(s) or s) in members:
                    return
                problems.append("enum")
            else:
                if re.match(r"^https?://\S+$", s):  # an IRI naming the item, as href/itemid/@id would
                    return
                problems.append("class")
        expects = f"'{prop}' expects {_or(rng)}"
        if "enum" in problems:
            members = sorted(set().union(*(v.enum_members(r) for r in rng if v.is_enumeration(r))))
            name = schema_name(s) or s
            hint = v._suggest(name, {m.lower(): m for m in members}, members)
            looks_enum = bool(schema_name(s)) or re.match(r"^[A-Za-z]+$", s)
            if looks_enum or hint:
                example = f"https://schema.org/{hint}" if hint else ", ".join(members[:3])
                self.add("error" if looks_enum else "warning", "invalid-enum",
                         f"{expects}; {_q(s)} is not one of its values" + (f"; did you mean '{example}'?" if hint else
                                                                          f" (e.g. {example})"), path, owner)
                return
        if problems == ["url"] or (set(problems) <= {"url", "class"} and "url" in problems):
            if " " not in s and not s.startswith("<"):
                self.add("warning", "relative-url", f"{expects}; {_q(s)} is not an absolute URL", path, owner)
            else:
                self.add(self._sev(classes), "invalid-url", f"{expects}, got text {_q(s)}", path, owner)
            return
        kinds = set(problems)
        if kinds == {"date"}:
            fmt = {"Date": "2026-10-03", "DateTime": "2026-10-03T19:30:00-03:00", "Time": "19:30:00"}
            examples = " or ".join(fmt[r] for r in rng if r in fmt)
            self.add("error", "invalid-date", f"{expects} in ISO 8601 (e.g. {examples}), got {_q(s)}", path, owner)
        elif kinds == {"duration"}:
            self.add("error", "invalid-duration", f"{expects} as an ISO 8601 duration (e.g. PT1H30M), got {_q(s)}",
                     path, owner)
        elif kinds <= {"number", "boolean"}:
            self.add("error", "invalid-" + sorted(kinds)[-1], f"{expects}, got {_q(s)}", path, owner)
        elif kinds == {"class"}:
            self.add("warning", "text-for-item", f"{expects} (an item), got plain text {_q(s)}", path, owner)
        else:
            self.add(self._sev(classes), "wrong-type", f"{expects}, got text {_q(s)}", path, owner)
