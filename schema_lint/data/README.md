# data/vocab.json

A compact index derived from the schema.org vocabulary, release file
<https://schema.org/version/latest/schemaorg-current-https.jsonld>, downloaded
2026-09-29 by `scripts/build_vocab.py`.

It keeps only what the linter needs: types with their superclasses, properties
with `domainIncludes` and `rangeIncludes`, enumeration members, data types, the
layer of each term (pending, health-lifesci, auto, bib, meta) and
`supersededBy`. Descriptions and the rest of the vocabulary are left out.

Schema.org is licensed under the Creative Commons Attribution-ShareAlike 3.0
license (CC BY-SA 3.0, <https://creativecommons.org/licenses/by-sa/3.0/>);
see <https://schema.org/docs/terms.html>. This derived file is shared under
the same license. The rest of schema-lint is MIT licensed.
