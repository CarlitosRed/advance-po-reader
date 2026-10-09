"""Version-one vocabulary shared by the offline fixture generator and scorer."""

CATEGORY_LANE = {
    "order": "order",
    "change": "needs_a_look",
    "cancellation": "needs_a_look",
    "quote_request": "needs_a_look",
    "invoice": "not_an_order",
    "status_question": "not_an_order",
    "other_business": "not_an_order",
    "spam": "not_an_order",
    "unsure": "needs_a_look",
}
CATEGORY_REASON = dict(zip(CATEGORY_LANE, (
    "new_order", "change_requested", "cancel_requested", "quote_requested",
    "invoice_only", "status_only", "other_business_only", "spam_only", "unclear",
)))
LANGUAGES = ("en", "es", "en-es")
LANES = ("order", "needs_a_look", "not_an_order")
MUTATIONS = (
    "forwarded_chain", "quoted_history", "quoted_only_order", "multiple_orders",
    "body_only_order", "pdf_only_order", "png_scan_standin", "inline_image",
    "cancellation", "change", "quote_request", "invoice", "status_question",
    "spam", "spanish", "english", "code_switching", "long_signature",
    "html_only", "injection_order", "injection_non_order", "filename_injection",
)
