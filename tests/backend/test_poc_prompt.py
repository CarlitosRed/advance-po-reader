"""The extraction prompt must tell the model that unknown rows need an uncertainty reason."""
from backend.providers import EXTRACTION_PROMPT, PROMPT_VERSION


def test_prompt_requires_an_uncertainty_reason_on_unknown_rows():
    flat = " ".join(EXTRACTION_PROMPT.split())
    assert "Every row with row_kind unknown MUST carry a non-null uncertainty string" in flat
    assert "ambiguous_layout" in flat and "never leave uncertainty null on an unknown row" in flat
    assert PROMPT_VERSION == "po-literal-evidence-v3"
