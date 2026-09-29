"""Markdown, JSON and SARIF 2.1.0 output."""
from __future__ import annotations

import collections
import json

from . import __version__
from .model import RANK, Item, Page

TOOL_URI = "https://github.com/dreadmoreeee/schema-lint"
DESCRIPTIONS = {
    "json-syntax": "JSON-LD block is not valid JSON",
    "missing-context": "JSON-LD block has no @context",
    "unmapped-term": "JSON-LD term does not map to a vocabulary term",
    "remote-context": "JSON-LD @context that is not schema.org",
    "bad-context": "Malformed @context",
    "bad-json-ld": "Malformed JSON-LD",
    "not-schema-org": "JSON-LD block that does not use schema.org",
    "unknown-type": "Type is not in schema.org",
    "enum-as-type": "Enumeration value used as a type",
    "datatype-as-type": "Data type used as an item type",
    "missing-type": "Item without a type",
    "unknown-property": "Property is not in schema.org",
    "property-not-allowed": "Property not defined for the item's type",
    "superseded": "Superseded schema.org term",
    "pending": "Term from schema.org's pending area",
    "wrong-type": "Value does not match the property's expected types",
    "text-for-item": "Plain text where an item is expected",
    "invalid-date": "Date/time value is not ISO 8601",
    "invalid-duration": "Duration is not ISO 8601",
    "invalid-number": "Value is not a number",
    "invalid-boolean": "Value is not a boolean",
    "invalid-enum": "Value is not a member of the expected enumeration",
    "invalid-url": "Value is not a URL",
    "relative-url": "URL is not absolute",
    "empty-value": "Empty value",
    "google-required": "Missing a property Google requires for the rich result",
    "google-recommended": "Missing properties Google recommends for the rich result",
    "google-retired": "Rich result no longer shown by Google",
    "fetch-error": "Page could not be fetched",
    "robots-disallowed": "Page skipped because robots.txt disallows it",
}


def counts(pages: list[Page]) -> dict[str, int]:
    c = collections.Counter(f.severity for p in pages for f in p.findings)
    return {"error": c["error"], "warning": c["warning"], "info": c["info"]}


def _types(items: list[Item]) -> str:
    c = collections.Counter(i.label for i in items)
    return ", ".join(f"{t} x{n}" if n > 1 else t for t, n in c.items())


def _syntaxes(items: list[Item]) -> str:
    c = collections.Counter(i.syntax for i in items)
    return ", ".join(f"{n} {s}" for s, n in c.items())


def _sorted(findings):
    return sorted(findings, key=lambda f: (-RANK[f.severity], f.line, f.path, f.code))


def markdown(pages: list[Page]) -> str:
    out = ["# schema-lint report", ""]
    for p in pages:
        out.append(f"## {p.url}")
        out.append("")
        if p.error:
            out.append(f"Could not fetch: {p.error}")
        elif p.items:
            out.append(f"{len(p.items)} item(s) ({_syntaxes(p.items)}): {_types(p.items)}")
        elif not any(f.code == "robots-disallowed" for f in p.findings):
            out.append("No structured data found.")
        out.append("")
        if p.findings:
            out.append("| Severity | Line | Where | Finding |")
            out.append("|---|---|---|---|")
            for f in _sorted(p.findings):
                msg = f.message.replace("|", "\\|")
                if f.help:
                    msg += f" ([docs]({f.help}))"
                where = (f.path or f.syntax).replace("|", "\\|")
                out.append(f"| {f.severity} | {f.line or ''} | {where} | {msg} |")
            out.append("")
    c = counts(pages)
    out.append(f"{len(pages)} page(s), {sum(len(p.items) for p in pages)} item(s): "
               f"{c['error']} error(s), {c['warning']} warning(s), {c['info']} info")
    return "\n".join(out) + "\n"


def _item_json(item: Item) -> dict:
    return {"syntax": item.syntax, "line": item.line, "types": item.types, "id": item.id,
            "properties": sorted(item.props)}


def as_json(pages: list[Page]) -> str:
    data = {
        "tool": "schema-lint", "version": __version__,
        "pages": [{"url": p.url, "error": p.error or None, "items": [_item_json(i) for i in p.items],
                   "findings": [f.as_dict() for f in _sorted(p.findings)]} for p in pages],
        "summary": {"pages": len(pages), "items": sum(len(p.items) for p in pages), **counts(pages)},
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}


def sarif(pages: list[Page]) -> str:
    used = sorted({f.code for p in pages for f in p.findings})
    rules = []
    for code in used:
        rule = {"id": code, "shortDescription": {"text": DESCRIPTIONS.get(code, code)}}
        helps = {f.help for p in pages for f in p.findings if f.code == code and f.help}
        if len(helps) == 1:
            rule["helpUri"] = helps.pop()
        rules.append(rule)
    index = {code: i for i, code in enumerate(used)}
    results = []
    for p in pages:
        for f in _sorted(p.findings):
            loc = {"physicalLocation": {"artifactLocation": {"uri": f.url or p.url}}}
            if f.line:
                loc["physicalLocation"]["region"] = {"startLine": f.line}
            if f.path:
                loc["logicalLocations"] = [{"fullyQualifiedName": f.path}]
            text = f.message + (f" See {f.help}" if f.help else "")
            results.append({"ruleId": f.code, "ruleIndex": index[f.code], "level": SARIF_LEVEL[f.severity],
                            "message": {"text": text}, "locations": [loc]})
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "schema-lint", "version": __version__,
                                      "informationUri": TOOL_URI, "rules": rules}},
                  "results": results}],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


FORMATS = {"md": markdown, "markdown": markdown, "json": as_json, "sarif": sarif}
