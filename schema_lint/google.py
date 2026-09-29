"""A summary of Google's rich-result requirements for a few schema.org types.

This is NOT Google's validator. It is a small table copied by hand from the
"Structured data type definitions" sections of Google Search Central
(developers.google.com/search/docs/appearance/structured-data/...), checked
2026-09-29. Google changes these pages; the source link is in every finding.

Notation: "a|b" = one of them is enough; "a.b" = property b of the item in a.
Where Google lists many optional extras, "recommended" keeps the commonly
useful subset (marked "subset" in the README).
"""
from __future__ import annotations

from .model import Finding, Item, Ref

DOCS = "https://developers.google.com/search/docs/appearance/structured-data/"
CHECKED = "2026-09-29"

RULES: dict[str, dict] = {
    # -- top-level features ------------------------------------------------
    "Organization": {
        "source": DOCS + "organization",
        "required": [],
        "recommended": ["name", "url", "logo", "sameAs", "description", "address", "telephone|contactPoint",
                        "email|contactPoint.email"],
        "nested": {"address": ["PostalAddress"]},
    },
    "LocalBusiness": {
        "source": DOCS + "local-business",
        "required": ["name", "address"],
        "recommended": ["url", "telephone", "geo", "openingHoursSpecification", "priceRange",
                        "aggregateRating", "review"],
        "recommended_if": {"FoodEstablishment": ["menu", "servesCuisine"]},
        "nested": {"address": ["PostalAddress"], "geo": ["GeoCoordinates"],
                   "openingHoursSpecification": ["OpeningHoursSpecification"]},
    },
    "Product": {
        "source": DOCS + "product-snippet",
        "required": ["name", "offers|review|aggregateRating"],
        "recommended": ["image", "description", "aggregateRating", "review", "offers"],
        "nested": {"offers": ["AggregateOffer", "Offer"]},
    },
    "FAQPage": {
        "source": DOCS + "faqpage",
        "retired": "Google stopped showing FAQ rich results and removed their documentation on 2025-06-15; "
                   "this markup is still valid schema.org but no longer earns a rich result",
        "required": ["mainEntity"],
        "recommended": [],
        "nested": {"mainEntity": ["Question"]},
    },
    "BreadcrumbList": {
        "source": DOCS + "breadcrumb",
        "required": ["itemListElement"],
        "recommended": [],
        "nested": {"itemListElement": ["ListItem"]},
    },
    "Article": {
        "source": DOCS + "article",
        "required": [],
        "recommended": ["headline", "image", "datePublished", "dateModified", "author", "author.name"],
    },
    "Event": {
        "source": DOCS + "event",
        "required": ["name", "startDate", "location"],
        "recommended": ["description", "endDate", "eventStatus", "image", "offers", "organizer", "performer"],
        "nested": {"location": ["Place"], "offers": ["Offer"]},
    },
    "Recipe": {
        "source": DOCS + "recipe",
        "required": ["name", "image"],
        "recommended": ["aggregateRating", "author", "cookTime", "datePublished", "description", "keywords",
                        "nutrition.calories", "prepTime", "recipeCategory", "recipeCuisine", "recipeIngredient",
                        "recipeInstructions", "recipeYield", "totalTime", "video"],
        "nested": {"recipeInstructions": ["HowToSection", "HowToStep"]},
    },
    # -- nested types (only checked where Google's page puts them) -------------
    "PostalAddress": {"source": DOCS + "local-business", "required": [],
                      "recommended": ["streetAddress", "addressLocality", "addressRegion", "postalCode",
                                      "addressCountry"]},
    "GeoCoordinates": {"source": DOCS + "local-business", "required": ["latitude", "longitude"],
                       "recommended": []},
    "OpeningHoursSpecification": {"source": DOCS + "local-business", "required": ["dayOfWeek", "opens", "closes"],
                                  "recommended": []},
    "Offer": {"source": DOCS + "product-snippet", "required": ["price|priceSpecification.price"],
              "recommended": ["priceCurrency|priceSpecification.priceCurrency", "availability"]},
    "AggregateOffer": {"source": DOCS + "product-snippet", "required": ["lowPrice", "priceCurrency"],
                       "recommended": ["highPrice", "offerCount"]},
    "Question": {"source": DOCS + "faqpage", "required": ["name", "acceptedAnswer"], "recommended": [],
                 "nested": {"acceptedAnswer": ["Answer"]}},
    "Answer": {"source": DOCS + "faqpage", "required": ["text"], "recommended": []},
    "ListItem": {"source": DOCS + "breadcrumb", "required": ["position", "name|item.name", "item"],
                 "recommended": [], "optional_on_last": ["item"]},
    "Place": {"source": DOCS + "event", "required": ["address"], "recommended": ["name"]},
    "HowToSection": {"source": DOCS + "recipe", "required": ["name", "itemListElement"], "recommended": []},
    "HowToStep": {"source": DOCS + "recipe", "required": ["text|itemListElement"], "recommended": []},
}
TOP_LEVEL = ["Organization", "LocalBusiness", "Product", "FAQPage", "BreadcrumbList", "Article", "Event", "Recipe"]


class GoogleCheck:
    def __init__(self, vocab, index: dict[str, list[Item]], url: str = "") -> None:
        self.vocab, self.index, self.url = vocab, index, url
        self.findings: list[Finding] = []

    def _known(self, item: Item) -> list[str]:
        return [t for t in item.schema_types if self.vocab.is_type(t)]

    def _values(self, item: Item, prop: str) -> list:
        out: list = []
        sources = [item] + [x for x in self.index.get(item.id or "", []) if x is not item]
        for src in sources:
            for v in src.props.get(prop, []):
                if isinstance(v, Ref):
                    targets = self.index.get(v.id)
                    out.extend(targets if targets else [v])
                else:
                    out.append(v)
        return out

    def has(self, item: Item, spec: str) -> bool:
        for alt in spec.split("|"):
            head, _, rest = alt.partition(".")
            values = [v for v in self._values(item, head) if v is not None and v != "" and v != []]
            if not rest and values:
                return True
            if rest and any(isinstance(v, Item) and self.has(v, rest) for v in values):
                return True
        return False

    def _pick(self, item: Item, names: list[str]) -> str | None:
        known = self._known(item)
        for name in names:  # most specific first
            if any(self.vocab.is_subtype(t, name) for t in known):
                return name
        return None

    def run(self, items: list[Item]) -> list[Finding]:
        done: set[int] = set()
        for item in items:
            known = self._known(item)
            matched = [r for r in TOP_LEVEL if any(self.vocab.is_subtype(t, r) for t in known)]
            matched = [r for r in matched if not any(o != r and self.vocab.is_subtype(o, r) for o in matched)]
            for rule in matched:
                self.apply(rule, item, rule, item.label, False, done)
        return self.findings

    def apply(self, name: str, item: Item, feature: str, path: str, is_last: bool, done: set) -> None:
        key = (id(item), name)
        if key in done:
            return
        done.add(key)
        rule = RULES[name]
        retired = RULES[feature].get("retired")
        where = f"Google {feature}" + (f" ({name})" if name != feature else "")
        if retired and name == feature:
            self._add("info", "google-retired", f"{feature}: {retired}", path, item, rule)
        for spec in rule["required"]:
            if is_last and spec in rule.get("optional_on_last", []):
                continue
            if not self.has(item, spec):
                sev = "info" if retired else "error"
                self._add(sev, "google-required", f"{where}: missing required {_fmt(spec)}", path, item, rule)
        recommended = list(rule["recommended"])
        for t, extra in rule.get("recommended_if", {}).items():
            if any(self.vocab.is_subtype(k, t) for k in self._known(item)):
                recommended += extra
        missing = [_fmt(s) for s in recommended if not self.has(item, s)]
        if missing:
            self._add("info" if retired else "warning", "google-recommended",
                      f"{where}: missing recommended {', '.join(missing)}", path, item, rule)
        for prop, names in rule.get("nested", {}).items():
            values = [v for v in self._values(item, prop) if isinstance(v, Item)]
            for i, v in enumerate(values):
                child = self._pick(v, names) or (names[-1] if not v.types else None)
                if child:
                    self.apply(child, v, feature, f"{path} > {prop} > {v.label}", i == len(values) - 1, done)

    def _add(self, severity: str, code: str, message: str, path: str, item: Item, rule: dict) -> None:
        self.findings.append(Finding(severity, code, message, path=path, syntax=item.syntax, line=item.line,
                                     url=self.url, help=rule["source"]))


def _fmt(spec: str) -> str:
    return " or ".join(f"'{s}'" for s in spec.split("|"))
