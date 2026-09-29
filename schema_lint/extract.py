"""Extract JSON-LD, microdata and RDFa Lite items from HTML with the standard library."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from .model import Finding, Item, Ref, schema_name

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
        "source", "track", "wbr"}
SCHEMA_CONTEXTS = {"https://schema.org", "http://schema.org", "https://schema.org/", "http://schema.org/",
                   "https://www.schema.org", "http://www.schema.org", "https://www.schema.org/",
                   "http://www.schema.org/", "https://schema.org/docs/jsonldcontext.json",
                   "http://schema.org/docs/jsonldcontext.json", "https://schema.org/docs/jsonldcontext.jsonld"}
SCHEMA = "https://schema.org/"
# RDFa 1.1 initial context: the prefixes that matter here.
RDFA_PREFIXES = {"schema": "http://schema.org/", "og": "http://ogp.me/ns#", "dc": "http://purl.org/dc/terms/",
                 "foaf": "http://xmlns.com/foaf/0.1/", "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                 "xsd": "http://www.w3.org/2001/XMLSchema#"}
URL_ATTR = {"a": "href", "area": "href", "link": "href", "audio": "src", "embed": "src", "iframe": "src",
            "img": "src", "source": "src", "track": "src", "video": "src", "object": "data"}


# -- a tiny, forgiving DOM ---------------------------------------------------
class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "line")

    def __init__(self, tag: str, attrs: dict, parent: "Node | None", line: int) -> None:
        self.tag, self.attrs, self.parent, self.line = tag, attrs, parent, line
        self.children: list = []

    def text(self) -> str:
        out: list[str] = []
        stack: list = [self]
        while stack:
            n = stack.pop()
            if isinstance(n, str):
                out.append(n)
            elif n.tag not in ("script", "style"):
                stack.extend(reversed(n.children))
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def iter(self):
        stack: list = [self]
        while stack:
            n = stack.pop()
            if isinstance(n, Node):
                yield n
                stack.extend(reversed(n.children))


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None, 1)
        self.stack = [self.root]
        self.base: str | None = None

    def handle_starttag(self, tag, attrs):
        a: dict[str, str] = {}
        for k, v in attrs:
            a.setdefault(k.lower(), v if v is not None else "")
        node = Node(tag, a, self.stack[-1], self.getpos()[0])
        self.stack[-1].children.append(node)
        if tag == "base" and self.base is None and a.get("href"):
            self.base = a["href"]
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_html(html: str) -> tuple[Node, str | None]:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root, b.base


# -- JSON-LD ------------------------------------------------------------------
class _Ctx:
    def __init__(self) -> None:
        self.vocab: str | None = None
        self.terms: dict[str, str] = {}
        self.has_context = False

    def copy(self) -> "_Ctx":
        c = _Ctx()
        c.vocab, c.terms, c.has_context = self.vocab, dict(self.terms), self.has_context
        return c


class JsonLd:
    def __init__(self, base: str, line: int, findings: list[Finding]) -> None:
        self.base, self.line, self.findings = base, line, findings
        self.unmapped: set[str] = set()

    def note(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message, syntax="json-ld", line=self.line))

    def context(self, ctx: _Ctx, local) -> _Ctx:
        ctx = ctx.copy()
        ctx.has_context = True
        for entry in local if isinstance(local, list) else [local]:
            if entry is None:
                ctx = _Ctx()
                ctx.has_context = True
            elif isinstance(entry, str):
                if entry.strip() in SCHEMA_CONTEXTS:
                    ctx.vocab = SCHEMA
                    ctx.terms.setdefault("schema", SCHEMA)
                else:
                    self.note("warning", "remote-context",
                              f"@context '{entry}' is not schema.org and is not fetched; its terms are not checked")
            elif isinstance(entry, dict):
                for key, value in entry.items():
                    if key == "@vocab" and isinstance(value, str):
                        v = value.strip()
                        ctx.vocab = SCHEMA if v.rstrip("/") + "/" in ("https://schema.org/", "http://schema.org/") else v
                    elif key.startswith("@"):
                        continue
                    elif isinstance(value, str):
                        ctx.terms[key] = value
                    elif isinstance(value, dict) and isinstance(value.get("@id"), str):
                        ctx.terms[key] = value["@id"]
            else:
                self.note("error", "bad-context", "@context must be a string, an object or an array")
        return ctx

    def expand(self, term: str, ctx: _Ctx, depth: int = 0) -> str | None:
        if depth > 8:
            return None
        if term in ctx.terms and ctx.terms[term] != term:
            return self.expand(ctx.terms[term], ctx, depth + 1)
        if ":" in term:
            return self._prefixed(term, ctx)
        if ctx.vocab:
            return ctx.vocab + term
        return None

    @staticmethod
    def _prefixed(term: str, ctx: _Ctx) -> str | None:
        prefix, _, suffix = term.partition(":")
        if suffix.startswith("//"):
            return term
        if prefix in ctx.terms:
            return ctx.terms[prefix] + suffix
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*$", prefix) and prefix.lower() in ("urn", "mailto", "tel", "data"):
            return term
        return None

    def term_name(self, term: str, ctx: _Ctx) -> str | None:
        """Schema.org name for a key/type, the IRI for other vocabularies, None if unmapped."""
        iri = self.expand(term, ctx)
        if iri is None:
            return None
        return schema_name(iri) or iri

    def top(self, data, ctx: _Ctx) -> list[Item]:
        if isinstance(data, list):
            out: list[Item] = []
            for d in data:
                out.extend(self.top(d, ctx))
            return out
        if not isinstance(data, dict):
            self.note("error", "bad-json-ld", "a JSON-LD block must contain an object or an array of objects")
            return []
        if "@context" in data:
            ctx = self.context(ctx, data["@context"])
        if "@graph" in data:
            graph = data["@graph"]
            return self.top(graph if isinstance(graph, list) else [graph], ctx)
        value = self.node(data, ctx)
        return [value] if isinstance(value, Item) else []

    def node(self, obj: dict, ctx: _Ctx):
        if "@context" in obj:
            ctx = self.context(ctx, obj["@context"])
        if "@value" in obj:
            return obj["@value"]
        for k in ("@list", "@set"):
            if k in obj:
                return [self.value(v, ctx) for v in (obj[k] if isinstance(obj[k], list) else [obj[k]])]
        keys = [k for k in obj if k != "@context"]
        if keys == ["@id"] and isinstance(obj["@id"], str):
            return Ref(urljoin(self.base, obj["@id"]))
        item = Item("json-ld", self.line)
        if isinstance(obj.get("@id"), str):
            item.id = urljoin(self.base, obj["@id"])
        raw_types = obj.get("@type", [])
        for t in raw_types if isinstance(raw_types, list) else [raw_types]:
            if not isinstance(t, str):
                continue
            name = self.term_name(t, ctx)
            if name is None:
                self.unmapped.add(t)
            else:
                item.types.append(name)
        for key, value in obj.items():
            if key.startswith("@"):
                continue
            name = self.term_name(key, ctx)
            if name is None:
                self.unmapped.add(key)
                continue
            if ":" in name:  # another vocabulary
                continue
            for v in value if isinstance(value, list) else [value]:
                v = self.value(v, ctx)
                for x in v if isinstance(v, list) else [v]:
                    item.add(name, x)
        return item

    def value(self, v, ctx: _Ctx):
        if isinstance(v, dict):
            return self.node(v, ctx)
        if isinstance(v, list):
            return [self.value(x, ctx) for x in v]
        return v


def _json_text(raw: str) -> str:
    s = raw.strip()
    for opener, closer in (("<!--", "-->"), ("<![CDATA[", "]]>"), ("//<![CDATA[", "//]]>")):
        if s.startswith(opener) and s.endswith(closer):
            s = s[len(opener):-len(closer)].strip()
    return s


def _contexts(data) -> list:
    out: list = []
    stack = [data]
    while stack:
        d = stack.pop()
        if isinstance(d, dict):
            if "@context" in d:
                out.append(d["@context"])
            stack.extend(v for k, v in d.items() if k != "@context")
        elif isinstance(d, list):
            stack.extend(d)
    return out


def jsonld_items(text: str, base: str, line: int, findings: list[Finding]) -> list[Item]:
    parser = JsonLd(base, line, findings)
    try:
        data = json.loads(_json_text(text))
    except ValueError as e:
        lead = text[: len(text) - len(text.lstrip())].count("\n")
        err_line = line + lead + getattr(e, "lineno", 1) - 1
        findings.append(Finding("error", "json-syntax", f"invalid JSON: {getattr(e, 'msg', e)}",
                                syntax="json-ld", line=err_line))
        return []
    has_ctx = (isinstance(data, dict) and "@context" in data) or bool(
        isinstance(data, list) and data and all(isinstance(d, dict) and "@context" in d for d in data))
    ctx = _Ctx()
    if has_ctx and "schema.org" not in json.dumps(_contexts(data)):
        findings.append(Finding("info", "not-schema-org",
                                "JSON-LD block without a schema.org @context; skipped", syntax="json-ld", line=line))
        return []
    if not has_ctx:
        parser.note("error", "missing-context",
                    "no @context; without \"@context\": \"https://schema.org\" these terms mean nothing "
                    "to a JSON-LD processor (checked as if it were schema.org)")
        ctx.vocab = SCHEMA
        ctx.terms["schema"] = SCHEMA
    items = parser.top(data, ctx)
    for term in sorted(parser.unmapped):
        parser.note("error", "unmapped-term",
                    f"'{term}' does not map to any vocabulary term through @context and is ignored")
    return items


# -- microdata ----------------------------------------------------------------
def _url(node: Node, base: str) -> str | None:
    attr = URL_ATTR.get(node.tag)
    if attr is None:
        return None
    return urljoin(base, node.attrs.get(attr, "").strip())


def _literal(node: Node, base: str) -> str:
    if node.tag == "meta":
        return node.attrs.get("content", "")
    url = _url(node, base)
    if url is not None:
        return url
    if node.tag in ("data", "meter") and "value" in node.attrs:
        return node.attrs["value"]
    if node.tag == "time" and "datetime" in node.attrs:
        return node.attrs["datetime"]
    if "content" in node.attrs:  # not in the microdata spec, but Google reads it on any element
        return node.attrs["content"]
    return node.text()


def _itemtypes(node: Node) -> list[str]:
    out = []
    for t in node.attrs.get("itemtype", "").split():
        out.append(schema_name(t) or t)
    return out


def microdata_items(root: Node, base: str) -> list[Item]:
    by_id = {n.attrs["id"]: n for n in root.iter() if "id" in n.attrs}

    def build(scope: Node, seen: frozenset) -> Item:
        item = Item("microdata", scope.line, _itemtypes(scope))
        if scope.attrs.get("itemid"):
            item.id = urljoin(base, scope.attrs["itemid"].strip())
        schema_vocab = any(":" not in t for t in item.types) or not item.types
        pending = list(scope.children)
        for ref in scope.attrs.get("itemref", "").split():
            if ref in by_id:
                pending.append(by_id[ref])
        visited: set[int] = set()
        while pending:
            n = pending.pop(0)
            if not isinstance(n, Node) or id(n) in visited:
                continue
            visited.add(id(n))
            if "itemprop" in n.attrs:
                if "itemscope" in n.attrs:
                    value = build(n, seen | {id(scope)}) if id(n) not in seen else Ref("(cycle)")
                else:
                    value = _literal(n, base)
                for name in n.attrs["itemprop"].split():
                    prop = schema_name(name) if "://" in name else (name if schema_vocab else None)
                    if prop:
                        item.add(prop, value)
            if "itemscope" not in n.attrs:
                pending[0:0] = n.children
        return item

    return [build(n, frozenset()) for n in root.iter() if "itemscope" in n.attrs and "itemprop" not in n.attrs]


# -- RDFa Lite ------------------------------------------------------------------
def rdfa_items(root: Node, base: str) -> list[Item]:
    top: list[Item] = []

    def expand(term: str, vocab: str | None, prefixes: dict[str, str]) -> str | None:
        if ":" in term:
            prefix, _, suffix = term.partition(":")
            if suffix.startswith("//"):
                return schema_name(term) or term
            if prefix in prefixes:
                iri = prefixes[prefix] + suffix
                return schema_name(iri) or iri
            return term  # unknown prefix: another vocabulary
        if vocab:
            return schema_name(vocab + term) or vocab + term
        return None

    def walk(node: Node, vocab: str | None, prefixes: dict[str, str], subject: Item | None) -> None:
        a = node.attrs
        if "vocab" in a:
            vocab = a["vocab"].strip() or None
        if "prefix" in a:
            prefixes = dict(prefixes)
            parts = a["prefix"].split()
            for p, iri in zip(parts[::2], parts[1::2]):
                if p.endswith(":"):
                    prefixes[p[:-1]] = iri
        props = [expand(p, vocab, prefixes) for p in a.get("property", "").split()]
        props = [p for p in props if p and ":" not in p]
        if "typeof" in a:
            item = Item("rdfa", node.line)
            item.types = [t for t in (expand(x, vocab, prefixes) for x in a["typeof"].split()) if t]
            ident = a.get("resource") or a.get("about")
            if ident:
                item.id = urljoin(base, ident.strip())
            if subject is not None and props:
                for p in props:
                    subject.add(p, item)
            else:
                top.append(item)
            subject = item
        elif props and subject is not None:
            if "content" in a:
                value = a["content"]
            elif "resource" in a:
                value = Ref(urljoin(base, a["resource"].strip()))
            else:
                value = _literal(node, base)
            for p in props:
                subject.add(p, value)
        for c in node.children:
            if isinstance(c, Node):
                walk(c, vocab, prefixes, subject)

    walk(root, None, dict(RDFA_PREFIXES), None)
    return [i for i in top if i.types]


# -- everything on a page ----------------------------------------------------------
def extract(html: str, url: str = "") -> tuple[list[Item], list[Finding]]:
    """All structured-data items on a page, plus problems found while reading them."""
    root, base_href = parse_html(html)
    base = urljoin(url, base_href) if base_href else url
    findings: list[Finding] = []
    items: list[Item] = []
    for n in root.iter():
        if n.tag == "script" and n.attrs.get("type", "").split(";")[0].strip().lower() == "application/ld+json":
            items.extend(jsonld_items("".join(c for c in n.children if isinstance(c, str)), base, n.line, findings))
    items.extend(microdata_items(root, base))
    items.extend(rdfa_items(root, base))
    return items, findings


def links(html: str, url: str) -> list[str]:
    root, base_href = parse_html(html)
    base = urljoin(url, base_href) if base_href else url
    out = []
    for n in root.iter():
        if n.tag in ("a", "area") and n.attrs.get("href"):
            rel = n.attrs.get("rel", "").lower().split()
            if "nofollow" not in rel:
                out.append(urljoin(base, n.attrs["href"].strip()))
    return out
