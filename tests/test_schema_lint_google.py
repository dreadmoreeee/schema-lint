import json

from schema_lint import lint_html
from schema_lint.google import RULES, TOP_LEVEL


def google(*objs):
    html = "".join(f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in objs)
    return [f for f in lint_html(html, "https://example.com/").findings if f.code.startswith("google-")]


def doc(**props):
    return {"@context": "https://schema.org", **props}


def test_table_has_a_google_source_for_every_rule():
    for name, rule in RULES.items():
        assert rule["source"].startswith("https://developers.google.com/search/docs/appearance/structured-data/")
    assert set(TOP_LEVEL) == {"Organization", "LocalBusiness", "Product", "FAQPage", "BreadcrumbList",
                              "Article", "Event", "Recipe"}


def test_local_business_required_and_recommended():
    f = google(doc(**{"@type": "BarOrPub", "name": "The Example Tap"}))
    errors = [x for x in f if x.severity == "error"]
    assert [x.message for x in errors] == ["Google LocalBusiness: missing required 'address'"]
    assert errors[0].help.endswith("/local-business")
    [warn] = [x for x in f if x.severity == "warning"]
    assert "'telephone'" in warn.message and "'menu'" in warn.message  # BarOrPub is a FoodEstablishment
    # most specific rule only: no Organization warning on a LocalBusiness
    assert not any("Google Organization" in x.message for x in f)


def test_nested_rules_for_local_business():
    f = google(doc(**{"@type": "LocalBusiness", "name": "x", "address": {"@type": "PostalAddress",
                      "streetAddress": "1 Main St"},
                      "openingHoursSpecification": [{"@type": "OpeningHoursSpecification", "dayOfWeek": "Monday",
                                                     "opens": "09:00"}]}))
    msgs = [x.message for x in f if x.severity == "error"]
    assert msgs == ["Google LocalBusiness (OpeningHoursSpecification): missing required 'closes'"]


def test_product_needs_offers_review_or_rating_and_offer_needs_price():
    f = google(doc(**{"@type": "Product", "name": "Widget"}))
    assert [x.message for x in f if x.severity == "error"] == [
        "Google Product: missing required 'offers' or 'review' or 'aggregateRating'"]
    f = google(doc(**{"@type": "Product", "name": "Widget", "offers": {"@type": "Offer", "priceCurrency": "CAD"}}))
    assert [x.message for x in f if x.severity == "error"] == [
        "Google Product (Offer): missing required 'price' or 'priceSpecification.price'"]
    f = google(doc(**{"@type": "Product", "name": "Widget", "offers": {
        "@type": "Offer", "priceSpecification": {"@type": "UnitPriceSpecification", "price": 3, "priceCurrency": "CAD"},
        "availability": "https://schema.org/InStock"}}))
    assert [x for x in f if x.severity == "error"] == []
    f = google(doc(**{"@type": "Product", "name": "W", "offers": {"@type": "AggregateOffer", "lowPrice": 3}}))
    assert [x.message for x in f if x.severity == "error"] == [
        "Google Product (AggregateOffer): missing required 'priceCurrency'"]


def test_breadcrumb_last_item_may_omit_item_and_name_can_sit_on_item():
    ok = doc(**{"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "item": {"@id": "https://example.com/books", "name": "Books"}},
        {"@type": "ListItem", "position": 2, "name": "Science fiction"}]})
    assert google(ok) == []
    bad = doc(**{"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Books"},
        {"@type": "ListItem", "name": "Science fiction"}]})
    assert sorted(x.message for x in google(bad)) == [
        "Google BreadcrumbList (ListItem): missing required 'item'",
        "Google BreadcrumbList (ListItem): missing required 'position'"]


def test_faq_is_reported_as_retired_not_as_errors():
    f = google(doc(**{"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "Why?"}]}))
    assert {x.severity for x in f} == {"info"}
    assert any(x.code == "google-retired" and "2025-06-15" in x.message for x in f)
    assert any("missing required 'acceptedAnswer'" in x.message for x in f)


def test_article_event_recipe():
    f = google(doc(**{"@type": "BlogPosting", "headline": "Hi"}))
    assert [x.severity for x in f] == ["warning"] and "Google Article" in f[0].message
    f = google(doc(**{"@type": "MusicEvent", "name": "Gig", "location": {"@type": "Place", "name": "Hall"}}))
    assert sorted(x.message for x in f if x.severity == "error") == [
        "Google Event (Place): missing required 'address'", "Google Event: missing required 'startDate'"]
    f = google(doc(**{"@type": "Recipe", "name": "Soup", "nutrition": {"@type": "NutritionInformation",
                                                                      "calories": "200 calories"}}))
    assert [x.message for x in f if x.severity == "error"] == ["Google Recipe: missing required 'image'"]
    assert "nutrition.calories" not in [x for x in f if x.severity == "warning"][0].message


def test_nodes_with_the_same_id_are_merged():
    a = doc(**{"@type": "LocalBusiness", "@id": "https://example.com/#biz", "name": "x"})
    b = doc(**{"@type": "LocalBusiness", "@id": "https://example.com/#biz",
               "address": {"@type": "PostalAddress", "streetAddress": "1 Main St"}})
    assert [x for x in google(a, b) if x.severity == "error"] == []


def test_references_count_as_present():
    g = doc(**{"@graph": [
        {"@type": "Organization", "@id": "#org", "name": "Example Co", "url": "https://example.com/",
         "logo": "https://example.com/logo.png", "sameAs": ["https://example.org/exampleco"],
         "description": "Widgets", "telephone": "+1-506-555-0100", "email": "hello@example.com",
         "address": {"@id": "#addr"}},
        {"@type": "PostalAddress", "@id": "#addr", "streetAddress": "1 Main St", "addressLocality": "Exampleville",
         "addressRegion": "NB", "postalCode": "E1V 0A0", "addressCountry": "CA"}]})
    assert google(g) == []
