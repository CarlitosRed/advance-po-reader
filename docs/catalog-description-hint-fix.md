# Catalog description-code hint fix

October 2, 2026. This change adds conservative candidate retrieval for a
code-shaped token embedded in a **product row's description**. It is retrieval
evidence only: it does not add an identifier observation, repair source text,
select a canonical product, or approve a suggestion.

## Behavior

Retrieval keeps its existing priority: exact source identifier, cautious
normalized identifier, exact description-code hint, typo-tolerant description
code hint, then broad `pg_trgm` retrieval. Exact source and normalized source
methods remain distinguishable from both new paths. The hint parser accepts
bounded tokens with at least two letters and two digits, with token boundaries.
Each token is first searched by exact normalized SKU equality inside the
explicitly supplied tenant/vendor namespace. For likely code typos, tokens of
at least eight normalized characters can use scoped SKU trigram lookup at a
dedicated **0.65 similarity threshold**. This is stricter than the existing
0.45 identifier trigram bar and does not change the broad description
threshold. It does not run an unbounded catalog scan. A hint can return zero,
one, or multiple candidates; normalized SKU collisions and multiple matching
hints remain ambiguous. The configured candidate bound still applies.

Suggestions persist `retrieval_version` and evidence such as
`{"kind":"description_code_hint","source":"product_description","raw_token":"ZX-901","search_key":"ZX901","match_method":"exact_normalized_sku"}`.
The exact hint method is `description_code_hint`; the typo path is
`description_code_hint_trigram`, with its threshold and `pg_trgm_sku` provenance
recorded. Product rows alone reach catalog
retrieval; the existing service skips charge, tax, total, note, unknown and
other non-product rows. Identifiers with tag/row-sequence roles are never
reinterpreted as SKU hints; only a token from the product description enters
this path. Existing same-role alias behavior remains separate.

## Synthetic verification

The regression suite uses fictional product codes including `ZX-901` and
`ABCD-90123`, with differently worded catalog descriptions. A one-character
code typo produces a bounded fuzzy suggestion at the dedicated threshold; an
absent SKU produces no candidate. It also covers absent observed identifier
values, raw identifier preservation, exact identifier priority, code-shape and
token-boundary controls, normalized collisions, tenant/vendor isolation,
candidate truncation, charge-row exclusion, and the established broad `pg_trgm`
behavior. The catalog module reported **41 passed** against the isolated local
database `orderlens_catalog_fix`. An API/history integration check reported
**1 passed** against the separate synthetic database
`gate_a_test_backend_orderlens_catalog_fix_contract`. No customer source,
catalog record, provider credential or external provider request was used. A
separate migration smoke check upgraded a database with an existing immutable
suggestion from `0005` to `0006`; the record remained retrieval version 1 with
empty evidence, and the append-only trigger continued rejecting updates.

## Integration handoff

`0006_catalog_description_hint` is additive after `0005_review_sequence`. The
integration owner can review and cherry-pick the commit from
`codex/catalog-description-hint`, then run this migration in the integration
checkout and its synthetic catalog/API checks. Existing suggestion history is
immutable. Do not regenerate or overwrite any saved run to apply this retrieval
change; only a deliberately created future run will use retrieval version
`catalog-retrieval-v2`. The live review remains a human decision in the website.

## Limits

This is a targeted retrieval-gap fix, not an extraction-quality measurement.
The code-shape heuristic can still surface a false candidate when ordinary
description text happens to look like a product code and exactly matches a
scoped SKU. Such candidates remain suggestions and require human approval.
The suite uses synthetic records and does not establish precision, recall,
production readiness or safety for automatic acceptance.
