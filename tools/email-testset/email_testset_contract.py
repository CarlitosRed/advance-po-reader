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

# --- PO-inbox profile additions (optional; the default profile never uses them) ---
# Extra mutation tags only the po-inbox profile emits. MUTATIONS stays frozen.
PO_INBOX_MUTATIONS = (
    "empty_body", "cover_note", "recap_in_body", "multi_attachment",
    "packing_list_attachment", "logo_image_attachment", "text_only_order", "out_of_office",
)
# Optional expected-row field `lane_reason`: present exactly when the row's lane
# differs from CATEGORY_LANE[category]. The only legal deviation is needs_a_look.
LANE_REASONS = {
    "text_only_order": "order",             # phase 1 does not read orders from email text
    "unknown_sender": "order",              # real-looking order, sender not on the known list
    "status_reply_needs_look": "status_question",  # status replies in the PO inbox go to Check
}
# (category, lane) pairs a classifier answer may use besides the canonical lane.
ANSWER_LANE_EXCEPTIONS = (("order", "needs_a_look"), ("status_question", "needs_a_look"))
# Optional expected-row field `sender_case`.
SENDER_CASES = (
    "known_address", "known_domain", "case_variant",
    "plus_tag", "unknown", "display_name_trick", "subdomain_trick", "typo_domain",
)
KNOWN_SENDER_CASES = SENDER_CASES[:3]
ATTACHMENT_ROLES = ("order", "packing_list", "logo_image")


def sender_is_known(address, entries):
    """Reference rule for the known-sender hint (fictional test oracle).

    `address` is the real address (addr-spec), never a display name. Case is
    ignored. The rule is strict and fails closed: an entry containing `@` must
    equal the whole address, and an entry without `@` must equal the whole
    domain exactly. A plus-tagged address (user+tag@host) does NOT match a
    listed user@host, and a subdomain or longer host name does not match.
    """
    address = address.strip().lower()
    domain = address.rpartition("@")[2]
    for entry in entries:
        entry = entry.strip().lower()
        if "@" in entry:
            if entry == address:
                return True
        elif entry and entry == domain:
            return True
    return False
