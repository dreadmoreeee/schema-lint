# schema-lint

Checks the structured data on a page (**JSON-LD, microdata and RDFa Lite**) against the **real schema.org vocabulary**, plus a short summary of what Google asks for in a few rich results. You can point it at URLs, local files or a small crawl. Output is Markdown, JSON or SARIF, and the exit codes work in CI.

```
$ schema-lint https://example.com/
$ schema-lint public/ --format sarif -o schema-lint.sarif      # every .html under public/
$ schema-lint https://example.com/ --crawl --max-pages 20 --fail-on warning
$ python -m schema_lint page.html product.jsonld --format json
```

- **Every block on the page.** It reads all `application/ld+json` scripts (including `@graph`, top-level arrays, `@type` arrays and `@id` references between blocks), all microdata items (`itemref` too) and RDFa Lite (`vocab`, `typeof`, `property`, `prefix`, `resource`).
- **The vocabulary is the vocabulary.** A compact index of schema.org's current release ships with the package: 939 types, 1,538 properties and 547 enumeration values. That covers unknown types and properties with "did you mean" (`adress` gives `address`, `localBusiness` gives `LocalBusiness`), and properties used on a type that does not define them. Inheritance is respected, so a `Restaurant` can use `founder` (from Organization) and `geo` (from Place), and items with several `@type`s get all of their properties.
- **Values are checked against `rangeIncludes`.** That covers ISO 8601 `Date`/`DateTime`/`Time` and durations (`PT30M`), `Number`/`Integer`, `Boolean`, enumeration values (`https://schema.org/InStok` gives `InStock`), absolute URLs, and nested items together with their subtypes (`AggregateOffer` is accepted where `Offer` is expected, and so are `Role` items). Text is fine wherever schema.org allows `Text`. Where it expects an item, plain text is a warning and an `https://` IRI passes.
- **`@context` handling.** `http` or `https` schema.org, with or without a trailing slash; arrays; objects with `@vocab`, prefixes or term definitions. A missing `@context` is an error. Blocks that only use another vocabulary are skipped.
- **Google rich results.** A small table for Organization, LocalBusiness, Product/Offer, FAQPage, BreadcrumbList, Article, Event and Recipe. A missing required property is an error and missing recommended ones are a warning, and every finding links to the Google page it came from. See [Google table](#google-table).
- **Polite crawl mode.** It stays on the same origin, loads at most 30 pages at least 1 s apart, and skips `/cdn-cgi/` and asset links. It honours `robots.txt` with RFC 9309 matching (bundled `rfc9309.py`, not `urllib.robotparser`), and `Crawl-delay` when it is longer.
- **No dependencies.** Standard library only, Python 3.10+. Playwright is optional (`--render`) for pages that inject their markup with JavaScript.

## Measured result

I ran it against my own sites on 2026-09-29: two DeMark Studio pages (English, and a French local page), the public demo pub site, and a crawl of my portfolio. That was 13 page loads in total, at least 1 s apart, plus the assets Chromium fetched for the one `--render` page. Output trimmed where marked:

```
$ schema-lint https://demarkstudio.ca/en/ https://demarkstudio.ca/fr/conception-web/miramichi \
    https://demo.demarkstudio.ca/riverside-pub/site https://marvin.demarkstudio.ca/ https://marvin.demarkstudio.ca/es/
## https://demarkstudio.ca/en/
1 item(s) (1 json-ld): ProfessionalService
| warning | 30 | ProfessionalService | Google LocalBusiness: missing recommended 'telephone', 'geo', 'openingHoursSpecification', 'aggregateRating', 'review' |
| warning | 30 | ProfessionalService > address > PostalAddress | Google LocalBusiness (PostalAddress): missing recommended 'streetAddress', 'postalCode' |

## https://demarkstudio.ca/fr/conception-web/miramichi
3 item(s) (3 json-ld): ProfessionalService, BreadcrumbList, Service
| error | 35 | Service > inLanguage | 'inLanguage' is not a property of Service (it belongs to BroadcastService, CommunicateAction, CreativeWork, Event or ...) |
| error | 35 | Service > priceRange | 'priceRange' is not a property of Service (it belongs to LocalBusiness) |
| warning | 33 | ProfessionalService | Google LocalBusiness: missing recommended 'telephone', 'geo', 'openingHoursSpecification', 'aggregateRating', 'review' |
| warning | 33 | ProfessionalService > address > PostalAddress | Google LocalBusiness (PostalAddress): missing recommended 'streetAddress', 'postalCode' |

## https://demo.demarkstudio.ca/riverside-pub/site
No structured data found.

## https://marvin.demarkstudio.ca/
1 item(s) (1 json-ld): Person
| warning | 26 | Person > nationality | 'nationality' expects Country (an item), got plain text 'Colombian' |

## https://marvin.demarkstudio.ca/es/        (same as above)
5 page(s), 6 item(s): 2 error(s), 6 warning(s), 0 info          (table headers and doc links trimmed)

$ schema-lint --render https://demo.demarkstudio.ca/riverside-pub/site
No structured data found.
1 page(s), 0 item(s): 0 error(s), 0 warning(s), 0 info

$ schema-lint --crawl --max-pages 10 https://marvin.demarkstudio.ca/
fetching https://marvin.demarkstudio.ca/
fetching https://marvin.demarkstudio.ca/es/
fetching https://marvin.demarkstudio.ca/work/demark-studio/
fetching https://marvin.demarkstudio.ca/work/triple-a-woodworks/
fetching https://marvin.demarkstudio.ca/work/stopping-form-spam/
fetching https://marvin.demarkstudio.ca/work/auditing-my-own-sites/
...                                                        (the two Person pages as above)
## https://marvin.demarkstudio.ca/work/demark-studio/
1 item(s) (1 json-ld): Article
| warning | 18 | Article | Google Article: missing recommended 'datePublished', 'dateModified' |
...                                                        (same warning on the other 3 case studies)
6 page(s), 6 item(s): 0 error(s), 6 warning(s), 0 info

$ python -m pytest -q
72 passed in 9.46s
```

Here is what it found on my own sites:

- **Two real errors on the French local page.** Its `Service` block uses `inLanguage` and `priceRange`, and schema.org defines neither on `Service` (`priceRange` only exists on `LocalBusiness`).
- **The demo pub site has no structured data at all.** That is true of the raw HTML and of the Chromium-rendered page. It is a sample restaurant site, exactly where `BarOrPub` markup would help.
- **Smaller warnings.** On the portfolio, `nationality` is plain text where schema.org expects a `Country` item, and the case studies have no `datePublished`/`dateModified`. On DeMark Studio, the Google LocalBusiness recommendations (phone, geo, hours, street address) are missing.

The files in [examples/](examples/) show the usual mistakes (`schema-lint examples/local-business.html` reports 9 errors and 2 warnings), and [examples/ci-github-actions.yml](examples/ci-github-actions.yml) is a CI job that uploads SARIF.


**Fixed on my portfolio the same night.** The `nationality` warning was right: schema.org expects a `Country` item there, not text. I changed the portfolio's JSON-LD to `{"@type": "Country", "name": "Colombia"}`, redeployed and ran it again:

```
$ schema-lint https://marvin.demarkstudio.ca/ https://marvin.demarkstudio.ca/es/
2 page(s), 2 item(s): 0 error(s), 0 warning(s), 0 info
```

## CLI

```
schema-lint <url|file|dir> [...] [--crawl] [--max-pages N] [--delay S] [--format md|json|sarif] [-o FILE]
            [--fail-on error|warning|info|never] [--no-google] [--render] [--user-agent UA] [--timeout S]
```

- Targets: `http(s)://` URLs; `.html` files; `.json`/`.jsonld` files (one JSON-LD document); directories (every `.html`, `.htm` and `.jsonld` inside).
- Exit codes: `0` means no finding at or above `--fail-on` (default `error`). `1` means there is at least one. `2` is a usage error, an unreadable file or a URL that could not be fetched. In crawl mode, only a failure on the first page gives `2`; later failures become `fetch-error` warnings.
- Severities: **error** means the markup is wrong or a required Google property is missing. **warning** means it probably works but is weaker than it should be (text where an item is expected, relative URLs, missing recommended properties). **info** is for pending schema.org terms, pages skipped by robots.txt and retired Google features.
- Requests use `User-Agent: schema-lint/1.0 (+https://github.com/dreadmoreeee/schema-lint)` and only `GET`.
- Python: `from schema_lint import lint_html, lint_file` returns a `Page` with `.items` and `.findings`.

## Google table

[`schema_lint/google.py`](schema_lint/google.py) is **a summary of Google's documentation, not Google's validator**. I copied it by hand from the "Structured data type definitions" tables on [Search Central](https://developers.google.com/search/docs/appearance/structured-data/) and checked it on 2026-09-29. Google edits those pages, and its own tools also look at content, policies and eligibility. Use the [Rich Results Test](https://search.google.com/test/rich-results) for the final word.

| Type (and subtypes) | Required | Recommended | Source |
|---|---|---|---|
| Organization | none | name, url, logo, sameAs, description, address, telephone or contactPoint, email (subset) | [organization](https://developers.google.com/search/docs/appearance/structured-data/organization) |
| LocalBusiness | name, address | url, telephone, geo, openingHoursSpecification, priceRange, aggregateRating, review; menu and servesCuisine for food places (subset) | [local-business](https://developers.google.com/search/docs/appearance/structured-data/local-business) |
| ... OpeningHoursSpecification / GeoCoordinates / PostalAddress | dayOfWeek, opens, closes / latitude, longitude / none | none / none / street, locality, region, postal code, country | same |
| Product | name; offers or review or aggregateRating | image, description, aggregateRating, review, offers | [product-snippet](https://developers.google.com/search/docs/appearance/structured-data/product-snippet) |
| ... Offer / AggregateOffer | price or priceSpecification.price / lowPrice, priceCurrency | priceCurrency, availability / highPrice, offerCount | same |
| FAQPage > Question > Answer | mainEntity > name, acceptedAnswer > text | none | [faqpage](https://developers.google.com/search/docs/appearance/structured-data/faqpage) |
| BreadcrumbList > ListItem | itemListElement > position, name, item (not on the last one) | none | [breadcrumb](https://developers.google.com/search/docs/appearance/structured-data/breadcrumb) |
| Article (NewsArticle, BlogPosting, ...) | none | headline, image, datePublished, dateModified, author, author.name | [article](https://developers.google.com/search/docs/appearance/structured-data/article) |
| Event > Place | name, startDate, location > address | description, endDate, eventStatus, image, offers, organizer, performer | [event](https://developers.google.com/search/docs/appearance/structured-data/event) |
| Recipe > HowToStep / HowToSection | name, image > text / name, itemListElement | aggregateRating, author, cookTime, datePublished, description, keywords, nutrition.calories, prepTime, recipeCategory, recipeCuisine, recipeIngredient, recipeInstructions, recipeYield, totalTime, video | [recipe](https://developers.google.com/search/docs/appearance/structured-data/recipe) |

Only the most specific rule applies, so a `Restaurant` is checked as a LocalBusiness and not also as an Organization. Nodes that share an `@id` are merged first. **FAQPage:** Google stopped showing FAQ rich results and removed their documentation on 2025-06-15, so FAQ findings are `info`. Merchant listings (the stricter Product variant) are not covered.

## Limitations

- JSON-LD line numbers point to the `<script>` element, not to the property inside it.
- Remote `@context` documents other than schema.org are not fetched. `@reverse`, `@nest` and named graphs are ignored.
- RDFa support covers RDFa **Lite** (`about` is read as well); full RDFa 1.1 (`rel`, `rev`, `datatype`, `inlist`) is not.
- Terms from schema.org's pending area get an `info` note. Extensions outside schema.org are skipped, not validated.
- The vocabulary is a snapshot. Run `python scripts/build_vocab.py` to rebuild `schema_lint/data/vocab.json` from the current release.

## Vocabulary licence

The package includes `schema_lint/data/vocab.json`, an index derived from [schema.org](https://schema.org/) ([schemaorg-current-https.jsonld](https://schema.org/version/latest/schemaorg-current-https.jsonld), downloaded 2026-09-29). Schema.org is licensed under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) ([terms](https://schema.org/docs/terms.html)), and the derived index is shared under the same licence. See [NOTICE](NOTICE) and [schema_lint/data/README.md](schema_lint/data/README.md).

## Author

Marvin Palencia, founder of [DeMark Studio](https://demarkstudio.ca), Miramichi, New Brunswick, Canada. Portfolio: [marvin.demarkstudio.ca](https://marvin.demarkstudio.ca)

MIT License.
