# Catalog description-code hint fix

October 2, 2026. This change adds conservative candidate retrieval for a
code-shaped token embedded in a **product row's description**. It is retrieval
evidence only: it does not add an identifier observation, repair source text,
select a canonical product, or approve a suggestion.

## Behavior

Retrieval keeps its existing priority: exact source identifier, cautious
normalized identifier, exact alphanumeric description-code hint, exact numeric
description-code hint, typo-tolerant alphanumeric description-code hint, then
broad `pg_trgm` retrieval. Exact source and normalized source methods remain
distinguishable from the description paths. The alphanumeric hint
parser accepts bounded tokens with at least two letters and two digits, with
token boundaries. Each token is first searched by exact normalized SKU
equality inside the explicitly supplied tenant/vendor namespace. For likely
alphanumeric code typos, tokens of at least eight normalized characters can
use scoped SKU trigram lookup at a dedicated **0.65 similarity threshold**.
This is stricter than the existing 0.45 identifier trigram bar and does not
change the broad description threshold.

Standalone numeric description hints follow a separate exact-only path. The
token must contain 4–12 digits, appear without adjacent letters, decimal or
date separators, and match the catalog SKU literally within the selected
tenant/vendor. Numeric hints never use normalized or fuzzy SKU comparison.
Year/date values, currency, quantity, unit, dimension, line/row, tag, sequence
and lot contexts are excluded. The bounds and candidate limit apply to both
hint paths; no catalog-wide scan is used. Multiple matching candidates remain
ambiguous.

Suggestions persist `retrieval_version` and evidence such as
`{"kind":"description_code_hint","source":"product_description","raw_token":"ZX-901","search_key":"ZX901","match_method":"exact_normalized_sku"}`.
The exact hint method is `description_code_hint`; the typo path is
`description_code_hint_trigram`, with its threshold and `pg_trgm_sku` provenance
recorded. Numeric exact hints use `description_numeric_code_hint` and preserve
their literal token in evidence. Product rows alone reach catalog
retrieval; the existing service skips charge, tax, total, note, unknown and
other non-product rows. Identifiers with tag/row-sequence roles are never
reinterpreted as SKU hints; only a token from the product description enters
this path. Existing same-role alias behavior remains separate.

## Synthetic verification

The regression suite uses fictional product codes including `ZX-901`,
`ABCD-90123`, and numeric-only `4516`, with differently worded catalog
descriptions. `DEMO 4516 STAGING PLATFORM` retrieves only the exact scoped
catalog SKU, while a nearby numeric typo, line/row/tag/sequence references,
quantities, money, dimensions, years, and compact or separated dates do not
produce a numeric hint. Multiple numeric matches remain ambiguous under the
candidate bound. A one-character alphanumeric code typo still produces a
bounded fuzzy suggestion at its dedicated threshold. The API/history checks
confirm identifiers remain `not_present`, description text is unchanged, and
a charge row containing the same token receives no suggestion. The catalog
module reported **67 passed** against the isolated local database
`orderlens_catalog_fix`. API/history integration checks reported **2 passed**
against the separate synthetic database
`gate_a_test_backend_orderlens_catalog_fix_contract`. No customer source,
catalog record, provider credential or external provider request was used. A
separate migration smoke check upgraded a database with an existing immutable
suggestion from `0005` to `0006`; the record remained retrieval version 1 with
empty evidence, and the append-only trigger continued rejecting updates.

## Integration handoff

`0006_catalog_description_hint` is additive after `0005_review_sequence`. The
integration owner can review and cherry-pick the original implementation and
numeric-only follow-up commits from `codex/catalog-description-hint`, then run
this migration in the integration checkout and its synthetic catalog/API
checks. Existing suggestion history is immutable. Do not regenerate or
overwrite any saved run to apply this retrieval change; only a deliberately
created future run will use retrieval version `catalog-retrieval-v2`. The live
review remains a human decision in the website.

## Limits

This is a targeted retrieval-gap fix, not an extraction-quality measurement.
The code-shape heuristic can still surface a false candidate when ordinary
description text resembles an alphanumeric code or standalone number and
exactly matches a scoped SKU. Numeric typo recovery is intentionally disabled.
All candidates remain suggestions and require human approval.
The suite uses synthetic records and does not establish precision, recall,
production readiness or safety for automatic acceptance.
