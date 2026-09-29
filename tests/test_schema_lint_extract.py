import json

import pytest

from schema_lint.extract import extract, links
from schema_lint.model import Item, Ref, schema_name


def ld(obj, raw=False):
    body = obj if raw else json.dumps(obj)
    return f'<html><head>\n<script type="application/ld+json">\n{body}\n</script></head><body></body></html>'


def codes(findings):
    return [f.code for f in findings]


@pytest.mark.parametrize("ctx", ["https://schema.org", "http://schema.org", "https://schema.org/", "http://schema.org/",
                                 ["https://schema.org", {"ex": "https://example.com/ns#"}],
                                 {"@vocab": "https://schema.org/"}, {"@vocab": "http://schema.org/"}])
def test_context_variants_resolve_to_schema_org(ctx):
    items, findings = extract(ld({"@context": ctx, "@type": "Product", "name": "Widget"}))
    assert findings == []
    assert items[0].types == ["Product"]
    assert items[0].props == {"name": ["Widget"]}


def test_prefixed_terms_and_full_iris():
    doc = {"@context": {"s": "https://schema.org/"}, "@type": "s:Product", "s:name": "Widget",
           "http://schema.org/sku": "W-1"}
    items, findings = extract(ld(doc))
    assert findings == []
    assert items[0].types == ["Product"] and items[0].props == {"name": ["Widget"], "sku": ["W-1"]}


def test_schema_prefix_is_defined_by_the_schema_org_context():
    items, _ = extract(ld({"@context": "https://schema.org", "@type": "schema:Event", "schema:name": "Gala"}))
    assert items[0].types == ["Event"] and items[0].props["name"] == ["Gala"]


def test_other_vocabulary_properties_are_ignored():
    doc = {"@context": ["https://schema.org", {"ex": "https://example.com/ns#"}], "@type": "Product",
           "ex:colourCode": "12", "name": "Widget"}
    items, findings = extract(ld(doc))
    assert findings == [] and items[0].props == {"name": ["Widget"]}


def test_graph_type_arrays_and_ids():
    doc = {"@context": "https://schema.org", "@graph": [
        {"@type": ["Organization", "LocalBusiness"], "@id": "#org", "name": "Example Co"},
        {"@type": "WebSite", "@id": "https://example.com/#site", "publisher": {"@id": "#org"}}]}
    items, findings = extract(ld(doc), "https://example.com/about")
    assert findings == []
    assert [i.types for i in items] == [["Organization", "LocalBusiness"], ["WebSite"]]
    assert items[0].id == "https://example.com/about#org"
    assert items[1].props["publisher"] == [Ref("https://example.com/about#org")]


def test_top_level_array_and_nested_items():
    doc = [{"@context": "https://schema.org", "@type": "Product", "name": "A",
            "offers": [{"@type": "Offer", "price": 5}, {"@type": "Offer", "price": {"@value": "6"}}]},
           {"@context": "https://schema.org", "@type": "Thing", "name": "B"}]
    items, _ = extract(ld(doc))
    assert len(items) == 2
    offers = items[0].props["offers"]
    assert all(isinstance(o, Item) for o in offers)
    assert [o.props["price"][0] for o in offers] == [5, "6"]


def test_missing_context_is_an_error_but_still_checked():
    items, findings = extract(ld({"@type": "Product", "name": "Widget"}))
    assert codes(findings) == ["missing-context"]
    assert items[0].types == ["Product"]


def test_non_schema_context_is_skipped():
    items, findings = extract(ld({"@context": "https://example.com/other", "@type": "Thing"}))
    assert items == [] and codes(findings) == ["not-schema-org"]


def test_unmapped_term_with_vocab_free_context():
    doc = {"@context": {"name": "https://schema.org/name"}, "@type": "https://schema.org/Product",
           "name": "Widget", "colour": "red", "schema:sku": "x"}
    items, findings = extract(ld(doc))
    assert items[0].props == {"name": ["Widget"]}
    assert sorted(f.message.split("'")[1] for f in findings if f.code == "unmapped-term") == ["colour", "schema:sku"]


def test_invalid_json_reports_the_line():
    html = '<html>\n<head>\n<script type="application/ld+json">\n{"@context": "https://schema.org",\n "name": "x",}\n</script>'
    items, findings = extract(html)
    assert items == [] and codes(findings) == ["json-syntax"]
    assert findings[0].line == 5


def test_comment_wrapped_json_and_type_with_charset():
    html = ('<script type="application/ld+json; charset=utf-8"><!--\n'
            '{"@context":"https://schema.org","@type":"Thing","name":"x"}\n--></script>')
    items, findings = extract(html)
    assert findings == [] and items[0].types == ["Thing"]


def test_microdata_values_nesting_and_itemref():
    html = """<div itemscope itemtype="https://schema.org/Event" itemref="loc">
      <h1 itemprop="name">Launch &amp; Party</h1>
      <time itemprop="startDate" datetime="2026-10-03T19:00">Oct 3</time>
      <a itemprop="url" href="/events/launch">more</a>
      <img itemprop="image" src="img/launch.jpg">
      <meta itemprop="eventStatus" content="https://schema.org/EventScheduled">
      <div itemprop="offers" itemscope itemtype="http://schema.org/Offer">
        <span itemprop="price" content="10.00">$10</span><span itemprop="name description">Ticket</span>
      </div>
    </div>
    <p id="loc" itemprop="location" itemscope itemtype="https://schema.org/Place"><span itemprop="name">Hall</span></p>"""
    items, findings = extract(html, "https://example.com/events/")
    assert findings == [] and len(items) == 1
    ev = items[0]
    assert ev.types == ["Event"] and ev.syntax == "microdata"
    assert ev.props["name"] == ["Launch & Party"]
    assert ev.props["startDate"] == ["2026-10-03T19:00"]
    assert ev.props["url"] == ["https://example.com/events/launch"]
    assert ev.props["image"] == ["https://example.com/events/img/launch.jpg"]
    offer = ev.props["offers"][0]
    assert offer.types == ["Offer"] and offer.props["price"] == ["10.00"]
    assert offer.props["name"] == ["Ticket"] and offer.props["description"] == ["Ticket"]
    assert ev.props["location"][0].props["name"] == ["Hall"]


def test_microdata_other_vocabulary_is_kept_out():
    items, _ = extract('<div itemscope itemtype="https://example.com/Thing"><span itemprop="name">x</span></div>')
    assert items[0].types == ["https://example.com/Thing"] and items[0].props == {}


def test_rdfa_lite_vocab_prefix_and_nesting():
    html = """<div vocab="https://schema.org/" typeof="LocalBusiness" resource="#biz">
      <span property="name">Example Pub</span>
      <div property="address" typeof="PostalAddress"><span property="addressLocality">Exampleville</span></div>
      <a property="url" href="/">home</a>
      <meta property="og:title" content="ignored">
    </div>
    <div prefix="s: http://schema.org/" typeof="s:Person"><span property="s:name">Alex Example</span></div>
    <meta property="og:description" content="no subject, ignored">"""
    items, findings = extract(html, "https://example.com/pub")
    assert findings == []
    biz, person = items
    assert biz.syntax == "rdfa" and biz.types == ["LocalBusiness"] and biz.id == "https://example.com/pub#biz"
    assert biz.props["name"] == ["Example Pub"] and biz.props["url"] == ["https://example.com/"]
    assert biz.props["address"][0].props == {"addressLocality": ["Exampleville"]}
    assert person.types == ["Person"] and person.props == {"name": ["Alex Example"]}


def test_base_href_and_links():
    html = '<base href="https://example.com/sub/"><a href="page">x</a><a href="/other#frag">y</a><a rel="nofollow" href="z">z</a>'
    assert links(html, "https://example.com/") == ["https://example.com/sub/page", "https://example.com/other#frag"]


def test_schema_name():
    assert schema_name("https://schema.org/Product") == "Product"
    assert schema_name("http://schema.org/InStock") == "InStock"
    assert schema_name("https://example.com/Product") is None
