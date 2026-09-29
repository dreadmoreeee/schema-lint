import json

import pytest

from schema_lint import lint_html
from schema_lint.checks import is_date, is_datetime, is_duration, is_time
from schema_lint.vocab import load


def run(obj, google=False, url="https://example.com/"):
    html = f'<script type="application/ld+json">{json.dumps(obj)}</script>'
    return lint_html(html, url, google=google).findings


def doc(**props):
    return {"@context": "https://schema.org", **props}


def only(findings, code):
    return [f for f in findings if f.code == code]


# -- vocabulary -------------------------------------------------------------
def test_vocab_index_is_the_real_vocabulary():
    v = load()
    assert v.is_subtype("Restaurant", "LocalBusiness")
    assert {"Organization", "Place", "Thing"} <= v.ancestors("LocalBusiness")
    assert v.is_subtype("Integer", "Number") and "URL" in v.datatypes
    assert "InStock" in v.enum_members("ItemAvailability")
    assert v.is_enumeration("DayOfWeek") and "Monday" in v.enum_members("DayOfWeek")
    assert "Thing" in v.domain("name") and "Text" in v.range("name")
    assert v.index["license"].startswith("CC BY-SA 3.0")


def test_build_vocab_from_a_small_graph():
    import importlib.util
    import pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "build_vocab.py"
    spec = importlib.util.spec_from_file_location("build_vocab", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    graph = [
        {"@id": "schema:Thing", "@type": "rdfs:Class"},
        {"@id": "schema:Text", "@type": ["rdfs:Class", "schema:DataType"]},
        {"@id": "schema:URL", "@type": "rdfs:Class", "rdfs:subClassOf": {"@id": "schema:Text"}},
        {"@id": "schema:Enumeration", "@type": "rdfs:Class", "rdfs:subClassOf": {"@id": "schema:Thing"}},
        {"@id": "schema:Colour", "@type": "rdfs:Class", "rdfs:subClassOf": {"@id": "schema:Enumeration"},
         "schema:isPartOf": {"@id": "https://pending.schema.org"}},
        {"@id": "schema:Red", "@type": "schema:Colour"},
        {"@id": "schema:name", "@type": "rdf:Property", "schema:domainIncludes": {"@id": "schema:Thing"},
         "schema:rangeIncludes": [{"@id": "schema:Text"}, {"@id": "schema:URL"}]},
        {"@id": "schema:oldName", "@type": "rdf:Property", "schema:supersededBy": {"@id": "schema:name"}},
        {"@id": "ex:Other", "@type": "rdfs:Class"},
    ]
    index = mod.build(graph)
    assert index["types"]["URL"] == ["Text"] and "Other" not in index["types"]
    assert index["datatypes"] == ["Text", "URL"]
    assert index["properties"]["name"] == [["Thing"], ["Text", "URL"]]
    assert index["enums"] == {"Colour": ["Red"]}
    assert index["layer"] == {"Colour": "pending"} and index["superseded"] == {"oldName": "name"}


# -- names ------------------------------------------------------------------
def test_unknown_type_and_property_with_suggestions():
    f = run(doc(**{"@type": "Resturant", "nmae": "x"}))
    assert "did you mean 'Restaurant'" in only(f, "unknown-type")[0].message
    f = run(doc(**{"@type": "Restaurant", "nmae": "x", "Telephone": "1"}))
    msgs = " ".join(x.message for x in only(f, "unknown-property"))
    assert "did you mean 'name'" in msgs and "did you mean 'telephone'" in msgs


def test_case_mismatched_type_suggests_the_right_case():
    f = run(doc(**{"@type": "localBusiness", "name": "x"}))
    assert "did you mean 'LocalBusiness'" in only(f, "unknown-type")[0].message


def test_type_used_as_property_and_enum_value_used_as_type():
    f = run(doc(**{"@type": "Product", "Offer": {"@type": "InStock"}}))
    assert "is a type, not a property" in only(f, "unknown-property")[0].message
    assert only(f, "enum-as-type")


# -- domains and inheritance ------------------------------------------------------
def test_property_not_allowed_on_type():
    f = run(doc(**{"@type": "Person", "name": "Alex", "sku": "1"}))
    [x] = only(f, "property-not-allowed")
    assert "'sku' is not a property of Person" in x.message and x.path == "Person > sku"


def test_inherited_properties_from_every_supertype():
    # LocalBusiness is both an Organization (founder) and a Place (geo); name comes from Thing.
    f = run(doc(**{"@type": "Restaurant", "name": "x", "founder": {"@type": "Person", "name": "A"},
                   "geo": {"@type": "GeoCoordinates", "latitude": 47.1, "longitude": -65.5},
                   "servesCuisine": "Pizza", "acceptsReservations": True}))
    assert only(f, "property-not-allowed") == [] and only(f, "wrong-type") == []


def test_multi_typed_item_takes_the_union_of_properties():
    f = run(doc(**{"@type": ["Product", "Car"], "sku": "1", "vehicleIdentificationNumber": "X"}))
    assert only(f, "property-not-allowed") == []
    f = run(doc(**{"@type": ["Person"], "vehicleIdentificationNumber": "X"}))
    assert only(f, "property-not-allowed")


# -- values ------------------------------------------------------------------------
@pytest.mark.parametrize("value,code", [
    ("2026-10-03", None), ("2026-10-03T19:30", None), ("2026-10-03T19:30:00-03:00", None),
    ("2026-10-03T19:30:00Z", None), ("2026-10-03T19:30:00.5+0100", None),
    ("October 3, 2026", "invalid-date"), ("2026-13-01", "invalid-date"), ("2026-02-30", "invalid-date"),
    ("2026-10-03 19:30", "invalid-date"), ("2026-10-03T25:00", "invalid-date")])
def test_date_and_datetime_values(value, code):
    f = run(doc(**{"@type": "Event", "startDate": value}))
    assert [x.code for x in f] == ([code] if code else [])


def test_date_time_duration_helpers():
    assert is_date("2026") and is_date("2026-09") and not is_date("2026-9-1")
    assert is_datetime("2026-09-29T08:00:00+01:00") and not is_datetime("2026-09-29")
    assert is_time("08:30") and is_time("23:59:59Z") and not is_time("8:30") and not is_time("24:30")
    assert is_duration("PT30M") and is_duration("P1DT2H") and is_duration("P2W")
    assert not is_duration("30 minutes") and not is_duration("P") and not is_duration("PT")


def test_time_and_duration_properties():
    f = run(doc(**{"@type": "Recipe", "name": "x", "cookTime": "30 min", "prepTime": "PT15M"}))
    assert [x.code for x in f] == ["invalid-duration"]
    f = run(doc(**{"@type": "OpeningHoursSpecification", "opens": "9am", "closes": "17:00"}))
    assert [x.code for x in f] == ["invalid-date"]


def test_numbers_integers_and_booleans():
    ok = doc(**{"@type": "Offer", "price": "19.99"})
    assert run(ok) == []  # price is Number or Text
    f = run(doc(**{"@type": "GeoCoordinates", "latitude": "north"}))
    assert run(doc(**{"@type": "GeoCoordinates", "latitude": 47.1})) == []
    assert [x.code for x in f] == []  # latitude also accepts Text
    f = run(doc(**{"@type": "Organization", "numberOfEmployees": {"@type": "QuantitativeValue", "value": 5}}))
    assert f == []
    f = run(doc(**{"@type": "Book", "numberOfPages": "many"}))
    assert [x.code for x in f] == ["invalid-number"]
    f = run(doc(**{"@type": "Book", "numberOfPages": 12.5}))
    assert [x.code for x in f] == ["wrong-type"]
    assert run(doc(**{"@type": "Book", "numberOfPages": "300"})) == []
    assert run(doc(**{"@type": "Restaurant", "acceptsReservations": "True"})) == []
    assert run(doc(**{"@type": "Place", "isAccessibleForFree": "https://schema.org/False"})) == []
    f = run(doc(**{"@type": "Place", "isAccessibleForFree": "sometimes"}))
    assert [x.code for x in f] == ["invalid-boolean"]


def test_enumeration_values():
    for good in ("https://schema.org/InStock", "http://schema.org/InStock", "InStock"):
        assert run(doc(**{"@type": "Offer", "availability": good})) == []
    f = run(doc(**{"@type": "Offer", "availability": "https://schema.org/InStok"}))
    assert f[0].code == "invalid-enum" and f[0].severity == "error" and "InStock" in f[0].message
    f = run(doc(**{"@type": "OpeningHoursSpecification", "dayOfWeek": ["Monday", "Funday"]}))
    assert [x.code for x in f] == ["invalid-enum"]


def test_urls_and_text():
    assert run(doc(**{"@type": "Thing", "url": "https://example.com/a", "sameAs": ["https://example.org/x"]})) == []
    f = run(doc(**{"@type": "Thing", "url": "/relative/path"}))
    assert [(x.code, x.severity) for x in f] == [("relative-url", "warning")]
    f = run(doc(**{"@type": "Thing", "url": "not a url"}))
    assert [(x.code, x.severity) for x in f] == [("invalid-url", "error")]
    # image is ImageObject or URL: plain words are a warning, not an error
    f = run(doc(**{"@type": "Thing", "image": "a photo of the shop"}))
    assert [(x.code, x.severity) for x in f] == [("invalid-url", "warning")]


def test_nested_types_subtypes_and_roles():
    ok = doc(**{"@type": "Product", "name": "x", "offers": {"@type": "AggregateOffer", "lowPrice": 1,
                                                              "priceCurrency": "CAD"}})
    assert run(ok) == []  # AggregateOffer is a subtype of Offer
    f = run(doc(**{"@type": "Product", "offers": {"@type": "Person", "name": "x"}}))
    assert [x.code for x in f] == ["wrong-type"] and "got Person" in f[0].message
    role = doc(**{"@type": "SportsTeam", "athlete": {"@type": "OrganizationRole", "startDate": "2020"}})
    assert run(role) == []
    f = run(doc(**{"@type": "Thing", "name": {"@type": "Person", "name": "x"}}))
    assert [x.code for x in f] == ["wrong-type"]


def test_untyped_nested_object_takes_the_only_class_in_range():
    f = run(doc(**{"@type": "Organization", "address": {"streetAddress": "1 Main", "postcode": "E1V"}}))
    [x] = f
    assert x.code == "unknown-property" and "(PostalAddress) > postcode" in x.path
    assert "did you mean 'postalCode'" in x.message


def test_text_where_an_item_is_expected():
    f = run(doc(**{"@type": "Article", "author": "Alex Example"}))
    assert [(x.code, x.severity) for x in f] == [("text-for-item", "warning")]
    assert run(doc(**{"@type": "Article", "author": "https://example.com/about#alex"})) == []


def test_references_resolve_across_blocks_on_the_page():
    html = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Person",'
            '"@id":"https://example.com/#alex","name":"Alex"}</script>'
            '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"x",'
            '"offers":{"@id":"https://example.com/#alex"},"brand":{"@id":"https://example.com/#alex"}}</script>')
    f = lint_html(html, "https://example.com/", google=False).findings
    assert [x.code for x in f] == ["wrong-type", "wrong-type"]  # brand wants Brand or Organization
    assert "'offers' expects Demand or Offer, but https://example.com/#alex is Person" in f[0].message + f[1].message
    # an unresolved reference is fine where an item is expected
    assert run(doc(**{"@type": "Product", "brand": {"@id": "https://example.org/brand"}})) == []


def test_empty_values_and_superseded_terms():
    f = run(doc(**{"@type": "Thing", "name": ""}))
    assert [x.code for x in f] == ["empty-value"]
    v = load()
    old = next(iter(sorted(p for p in v.superseded if v.is_property(p) and "Thing" in v.domain(p))), None)
    if old:
        f = run(doc(**{"@type": "Thing", old: "x"}))
        assert "superseded" in [x.code for x in f]


def test_microdata_and_rdfa_go_through_the_same_checks():
    html = """<div itemscope itemtype="https://schema.org/Event"><span itemprop="nmae">x</span>
      <time itemprop="startDate">next Friday</time></div>
      <div vocab="https://schema.org/" typeof="Person"><span property="sku">1</span></div>"""
    f = lint_html(html, "https://example.com/", google=False).findings
    assert sorted((x.syntax, x.code) for x in f) == [("microdata", "invalid-date"), ("microdata", "unknown-property"),
                                                     ("rdfa", "property-not-allowed")]
