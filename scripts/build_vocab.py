"""Build schema_lint/data/vocab.json from the official schema.org JSON-LD.

Run once when schema.org publishes a new release:

    python scripts/build_vocab.py                 # downloads the current release
    python scripts/build_vocab.py --file x.jsonld # uses a file you already have

The full vocabulary (about 1.5 MB) is not shipped; only the index the linter
needs: classes with their superclasses, properties with domainIncludes and
rangeIncludes, enumeration members, datatypes, layers and supersededBy.
schema.org is licensed CC BY-SA 3.0 (https://schema.org/docs/terms.html).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import urllib.request

SOURCE = "https://schema.org/version/latest/schemaorg-current-https.jsonld"
USER_AGENT = "schema-lint/1.0 (+https://github.com/dreadmoreeee/schema-lint)"
OUT = pathlib.Path(__file__).resolve().parent.parent / "schema_lint" / "data" / "vocab.json"
LAYERS = {
    "https://pending.schema.org": "pending",
    "https://attic.schema.org": "attic",
    "https://health-lifesci.schema.org": "health-lifesci",
    "https://auto.schema.org": "auto",
    "https://bib.schema.org": "bib",
    "https://meta.schema.org": "meta",
}


def _ids(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    out = []
    for v in value:
        ident = v.get("@id") if isinstance(v, dict) else v
        if isinstance(ident, str) and ident.startswith("schema:"):
            out.append(ident[len("schema:"):])
    return out


def build(graph: list[dict]) -> dict:
    classes: dict[str, list[str]] = {}
    datatype_roots: set[str] = set()
    properties: dict[str, list[list[str]]] = {}
    typed_members: list[tuple[str, list[str]]] = []
    layer: dict[str, str] = {}
    superseded: dict[str, str] = {}
    for node in graph:
        ident = node.get("@id", "")
        if not ident.startswith("schema:"):
            continue
        name = ident[len("schema:"):]
        types = node.get("@type", [])
        types = types if isinstance(types, list) else [types]
        part = node.get("schema:isPartOf")
        if isinstance(part, dict) and part.get("@id") in LAYERS:
            layer[name] = LAYERS[part["@id"]]
        newer = _ids(node.get("schema:supersededBy"))
        if newer:
            superseded[name] = newer[0]
        if "rdfs:Class" in types:
            classes[name] = _ids(node.get("rdfs:subClassOf"))
            if "schema:DataType" in types:
                datatype_roots.add(name)
        elif "rdf:Property" in types:
            properties[name] = [sorted(_ids(node.get("schema:domainIncludes"))),
                                sorted(_ids(node.get("schema:rangeIncludes")))]
        else:
            typed_members.append((name, [t[len("schema:"):] for t in types if t.startswith("schema:")]))

    def ancestors(c: str, seen: set[str] | None = None) -> set[str]:
        seen = set() if seen is None else seen
        for s in classes.get(c, []):
            if s not in seen:
                seen.add(s)
                ancestors(s, seen)
        return seen

    datatypes = sorted(c for c in classes if c in datatype_roots or ancestors(c) & datatype_roots)
    enums: dict[str, list[str]] = {}
    for member, member_types in typed_members:
        for t in member_types:
            enums.setdefault(t, []).append(member)
    for t in enums:
        enums[t].sort()
    return {
        "source": SOURCE,
        "license": "CC BY-SA 3.0, schema.org (https://schema.org/docs/terms.html)",
        "retrieved": dt.date.today().isoformat(),
        "types": dict(sorted(classes.items())),
        "datatypes": datatypes,
        "properties": dict(sorted(properties.items())),
        "enums": dict(sorted(enums.items())),
        "layer": dict(sorted(layer.items())),
        "superseded": dict(sorted(superseded.items())),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="local copy of schemaorg-current-https.jsonld")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    if args.file:
        raw = pathlib.Path(args.file).read_text(encoding="utf-8")
    else:
        req = urllib.request.Request(SOURCE, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    index = build(json.loads(raw)["@graph"])
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=True, sort_keys=False) + "\n",
                   encoding="ascii")
    print(f"{out}: {len(index['types'])} types, {len(index['properties'])} properties, "
          f"{sum(len(v) for v in index['enums'].values())} enumeration members, "
          f"{out.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    main()
