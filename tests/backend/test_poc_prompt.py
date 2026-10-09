"""The extraction prompt must state every row/page/region/observation rule the contract enforces."""
from backend.providers import EXTRACTION_PROMPT, PROMPT_VERSION

RULE_PHRASES = [
    "exactly one page observation per source page",           # page coverage
    "partial/failed REQUIRE a non-null",                      # partial pages need a reason
    "complete REQUIRES uncertainty null",
    "region_reference is unique within the page",             # regions
    "x1>x0 and y1>y0",
    "cites {page_number, region_reference}",                  # evidence references
    "row_id is unique in the document",
    "product_item: row_kind product, with an item_group_id",  # kind/role combinations
    "document_detail: row_kind charge/tax/subtotal/total/note, item_group_id null",
    "continuation: row_kind unknown (NOT product)",
    "every row with row_kind unknown (including continuations) MUST carry a non-null",
    'never leave uncertainty null',
    'row_kind "unknown", row_role',                           # exact continuation marking
    "continuation_of =",
    "no identifiers, and quantity, unit,",
    "Give EVERY row its own tight region",                    # no shared table-wide region
    "never cite one shared table-wide region",
    "y0 >= product y1",                                       # continuation adjacency numbers
    "y0 - product y1 <= 0.08",
    "x-range must overlap the product region's x-range",
    "exactly one",                                            # one root per item group
    "region of the same row and page",                                # quantity/unit evidence containment
    "observed = literal raw_value plus evidence",             # observation states
    "not_present and not_applicable = raw_value null",
    "never an empty string",
    "unsupported/unknown",                                    # document type reason
]


def test_prompt_states_every_contract_rule():
    flat = " ".join(EXTRACTION_PROMPT.split())
    missing = [phrase for phrase in RULE_PHRASES if " ".join(phrase.split()) not in flat]
    assert not missing, missing
    assert PROMPT_VERSION == "po-literal-evidence-v6"


def test_prompt_keeps_the_literal_evidence_instructions():
    flat = " ".join(EXTRACTION_PROMPT.split())
    for phrase in ("Preserve exact printed", "Never guess absent/unreadable values or repair an ID",
                   "Do not provide parsed numbers, catalog IDs", "Use original literal observation"):
        assert phrase in flat


def test_prompt_gives_the_identifier_role_vocabulary():
    """source_role must be a catalog role, never the PO's own header text."""
    from backend.catalog import CANONICAL_SKU_ROLES
    flat = " ".join(EXTRACTION_PROMPT.split())
    for role in sorted(CANONICAL_SKU_ROLES) + ["line_number", "other"]:
        assert f"- {role}:" in flat, role
    assert "source_label is the literal printed column/field header text" in flat
    assert "never the header text" in flat
    assert "Never use a line number, row sequence number, quantity or price column as a product code" in flat
