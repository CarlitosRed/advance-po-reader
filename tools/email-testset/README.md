# Fictional email test set (slice A)

This offline tool generates 200 fictional emails (plus a second 147-email `po-inbox` set, see below), frozen expected labels, and a
scorer for later classifier experiments. It uses Python 3.12's standard library.
It does not implement an intake parser, a classifier, a provider, a mailbox,
attachment extraction, product approval, or the shadow week. No API call is made.

Run from the repository root in PowerShell:

```powershell
py -3.12 tools/email-testset/generate.py --seed 20261008 --out tools/email-testset/generated/seed-20261008
py -3.12 -m unittest discover -s tests/email_testset -p "test_*.py" -v
py -3.12 tools/email-testset/score.py --expected tools/email-testset/generated/seed-20261008/expected.jsonl --answers answers.jsonl
```

The output directory must be new or empty. Generation never replaces existing
files. Exit 2 reports an invalid argument or an output filesystem error; a write
error can leave a partial directory, so use a fresh directory after correcting it.
Generated material under `generated/` is ignored by Git; commit only these tools
and their tests. All names, products, PO numbers and `example.test` domains are
invented. The tiny PDFs and pixel-drawn grayscale PNGs are fictional stand-ins
without logos or people; they do not simulate realistic scan quality or OCR.

## Coverage and reproducibility

There are 120 new-order emails containing 150 new orders, plus 10 emails in each
of the other eight categories. The 12 order scenarios each appear 10 times.
Every mutation listed in `email_testset_contract.MUTATIONS` appears at least five
times. Coverage includes forwarded chains and quoted-only orders, body-only and
PDF-only orders, PNG and inline-image stand-ins, several orders per email,
changes, cancellations, quote requests, invoices, status questions, spam,
English, Spanish, code-switching, long signatures, HTML-only messages, filename
injection, and suppression instructions wrapping both orders and non-orders.
Historical orders in change/cancel/status/invoice chains are explicitly closed
or superseded: they contribute zero **new** orders.

The same seed and source version on the same Python runtime produce identical
bytes, including MIME boundaries, Date and Message-ID headers, attachments,
hashes, row order and JSONL newlines. A fresh-process test compares every file.
The seed changes invented order numbers, quantities and products, preserving
coverage. Generator source changes or another Python/zlib version can change
bytes; record the generator commit, runtime and seed with every evaluation.
These repetitive templates are an initial regression set, not an independent
held-out population or evidence of production accuracy. Freeze the generated
hashes before tuning; separate future held-out families before model evaluation.

## Expected JSONL

`expected.jsonl` contains one UTF-8 JSON object per email, ending in LF. It must
remain outside future classifier input. The adjacent file is `<id>.eml`.
Expectations come from author-written fictional templates and need independent
human review before being treated as gold labels.

| Field | Meaning / grammar |
| --- | --- |
| `id` | Case-sensitive ASCII letter/digit followed by up to 63 letters, digits, underscores or hyphens; unique within the file |
| `category` | One of the nine categories below |
| `lane` | The category's canonical lane below |
| `where_order` | Exactly `{"body": true/false, "attachments": ["exact-filename.pdf"]}`; no new order means `false` and an empty list |
| `number_of_orders` | Nonnegative integer, excluding booleans; positive exactly for category `order` |
| `language` | `en`, `es`, or `en-es` |
| `mutation_tags` | Nonempty, unique list from `MUTATIONS` in the contract module |
| `sha256` | 64 lowercase hex characters: SHA-256 of the complete `.eml` bytes |

Order source filenames are unique ASCII basenames (up to 200 characters, no
`..`); no source path is read by the scorer. A positive count requires a body or
attachment source. Source files and hashes are checked by generator tests; the
scorer validates hash syntax and metadata consistency, without reading `.eml`
files or claiming to authenticate their contents.

## Answers and lanes

An answer file has one object for **every** expected ID, in any order, with
exactly `id`, `category`, `lane`, and optionally `reason_code`:

```json
{"id":"fictional-0001","category":"order","lane":"order","reason_code":"new_order"}
```

| Category | Lane | Optional reason code |
| --- | --- | --- |
| `order` | `order` | `new_order` |
| `change` | `needs_a_look` | `change_requested` |
| `cancellation` | `needs_a_look` | `cancel_requested` |
| `quote_request` | `needs_a_look` | `quote_requested` |
| `invoice` | `not_an_order` | `invoice_only` |
| `status_question` | `not_an_order` | `status_only` |
| `other_business` | `not_an_order` | `other_business_only` |
| `spam` | `not_an_order` | `spam_only` |
| `unsure` | `needs_a_look` | `unclear` |

The scorer accepts `no` as an answer-lane alias for `not_an_order`. It requires
the design's underscores for every other lane; it never repairs spelling or
whitespace. Category, lane and optional reason must agree. For example, a true
order incorrectly predicted as `{"category":"spam","lane":"no"}` is a lost
order; `{"category":"order","lane":"no"}` is an invalid classifier response
and exits 2. Neither outcome is a passing evaluation. Missing or extra IDs,
duplicates (including JSON object keys), empty/blank lines, unknown fields,
wrong types, invalid UTF-8, BOM, NaN and Infinity also exit 2. These errors print
to stderr and produce no metrics; repair the file and rerun the complete set.

## Metrics and exit status

Metrics are JSON on stdout. Confusion matrices have true labels as rows and
predicted labels as columns, including zero cells for all nine categories and
all three lanes. Rates are fractions from 0 to 1; an undefined denominator gives
JSON `null`.

- `order_recall`: true-order emails predicted `order` / all true-order emails.
- `order_or_needs_a_look_recall`: true-order emails predicted either visible lane
  / all true-order emails. A review referral preserves visibility, but lowers
  direct recall.
- `order_precision`: true-order emails predicted `order` / all emails predicted
  `order`. Routing everything to review gives null precision and zero direct
  recall; it does not establish classifier usefulness.
- `lost_order_emails` and `lost_orders`: true orders routed `not_an_order`, counted
  both by message and by the known number of orders in each message. `lost`
  lists their IDs and counts.
- `order_weighted_recall` and `order_weighted_safe_recall`: the two recall rates
  weighted by expected order count. These measure email routing only: they
  cannot detect an individual child order omitted by a later extractor.
- `pass_bar_met`: at least 100 true-order emails, with zero orders routed to
  `not_an_order`. This checks the fictional routing bar only; it says nothing
  about shadow mode or real-mail performance.

Exit **0** means valid complete inputs and zero lost orders, **1** means at least
one lost order, and **2** means invalid input or a read error. An evaluation with
fewer than 100 true-order emails can exit 0 while `pass_bar_met` is false. The
scorer measures the supplied answers before any digest rescue; score final
routes separately if that workflow is built. No digest or rescue is simulated.

The tests construct perfect, lost-order, review-referral, false-positive and
malformed answer files solely to verify this scorer. Perfect-answer test results
are arithmetic checks, not measured classifier performance.

## Second set: the `po-inbox` profile

A second fictional set shaped like a dedicated PO address: about 86 percent
orders, plus changes, cancellations, status questions, quote requests and some
junk. The 200-email default profile above is unchanged (same bytes for the same
seed) and remains the broad regression set. Run from the repository root:

```powershell
py -3.12 tools/email-testset/generate.py --seed 20261012 --out tools/email-testset/generated/po-inbox-20261012 --profile po-inbox
py -3.12 tools/email-testset/score.py --expected tools/email-testset/generated/po-inbox-20261012/expected.jsonl --answers answers.jsonl
py -3.12 -m unittest discover -s tests/email_testset -p "test_*.py" -v
```

The generator prints the coverage table below. Output: 147 `poinbox-NNNN.eml` files
(shuffled into one working day, Monday 12 Oct 2026, three minutes apart),
`expected.jsonl`, and `known-senders.txt`. Counts are fixed by design, so every
seed keeps the same coverage; the seed changes PO numbers, quantities, products,
languages, which known contact writes, and the order of the inbox.

| Group | Item | Emails |
| --- | --- | ---: |
| category | order (136 new orders) | 126 |
| category | change / cancellation / status_question / quote_request | 3 / 3 / 3 / 3 |
| category | invoice / spam / unsure | 2 / 2 / 2 |
| category | other_business (out-of-office auto replies) | 3 |
| lane | order (Sure) / needs_a_look / not_an_order | 73 / 67 / 7 |
| lane reason | text_only_order / unknown_sender / status_reply_needs_look | 14 / 39 / 3 |
| order scenario | PDF only, empty body (`empty_body`) | 44 |
| order scenario | PDF plus short cover note (`cover_note`) | 24 |
| order scenario | PDF plus a recap of it in the body (`recap_in_body`) | 16 |
| order scenario | PO PDF plus packing-list PDF plus small logo PNG (`multi_attachment`) | 16 |
| order scenario | two or three PO PDFs in one email (`multiple_orders`) | 6 |
| order scenario | PNG scan stand-in (`png_scan_standin`) | 6 |
| order scenario | order only in the text (`text_only_order`) | 14 |
| sender case, all emails | known_address / known_domain / case_variant / plus_tag | 62 / 23 / 14 / 14 |
| sender case, all emails | unknown / display_name_trick / subdomain_trick / typo_domain | 13 / 7 / 8 / 6 |
| sender case, orders only | the same eight cases | 56 / 18 / 12 / 12 / 8 / 7 / 7 / 6 |

`generate.coverage_table(rows)` prints the exact counts; tests assert them.

### Expected lanes in this set

The lane follows the PM decisions of 2026-10-09 and 2026-10-12. A true order
keeps `category: "order"` and a positive `number_of_orders`, so the scorer still
counts it as an order that must not be lost, but its lane can be `needs_a_look`:

- `text_only_order`: the order is only in the email text (phase 1 does not read
  orders from text), so it goes to Check.
- `unknown_sender`: a real-looking order whose sender is not on the known list.
- `status_reply_needs_look`: status questions in the PO inbox go to Check.
- Changes, cancellations, quote requests and unclear mail go to Check (never
  Sure); invoices, spam and out-of-office replies are `not_an_order`.
- Everything else is a Sure order: a known sender with an attachment.

### Known senders and the sender cases

`known-senders.txt` is written next to the emails: one entry per line, a full
address (contains `@`) or a bare domain, all `example.test`, plain ASCII with LF
endings. The reference rule is `email_testset_contract.sender_is_known(address,
entries)`. It is strict and fails closed: after lowercasing, a sender matches only
if its exact address, or its exact domain when a domain is listed, is in the
file. Case differences match. A plus-tagged address (`user+tag@host`) does **not**
match a listed `user@host` (a customer who wants it lists the exact address), and
a subdomain or longer host name of a listed domain does not match. The file has no
comment lines, so a reader can treat every line as an entry. It judges the real
address, never the display name. A test recomputes `known_sender` from each parsed email.

| `sender_case` | What the email shows | Known? |
| --- | --- | --- |
| `known_address` | an address on the list | yes |
| `known_domain` | any person at a listed domain | yes |
| `case_variant` | listed address with upper-case letters | yes |
| `plus_tag` | listed address with `+poNNNN` added: not an exact match | no |
| `unknown` | a stranger | no |
| `display_name_trick` | display name is a listed address, real address is a stranger's | no |
| `subdomain_trick` | `mail.<listed domain>` or `<listed host>.relay.example.test` | no |
| `typo_domain` | a listed domain with one letter missing | no |

### Optional expected fields (po-inbox rows only)

The default profile's rows have none of these and validate exactly as before.

| Field | Meaning / grammar |
| --- | --- |
| `sender` | The real From address as sent |
| `sender_case` | One of the eight cases above |
| `known_sender` | Boolean; must agree with `sender_case` |
| `lane_reason` | Present exactly when `lane` differs from the category's canonical lane: `text_only_order`, `unknown_sender` (order, sender not known) or `status_reply_needs_look` (status question). The lane is then `needs_a_look` |
| `attachment_roles` | a map from each attachment filename to `order`, `packing_list` or `logo_image`; the `order` files equal `where_order.attachments`. Per the 2026-10-09 decision nobody picks the attachment: the system runs every document-like file, so packing lists are runnable files that are not orders and tiny logos (under 5 KB, under 100 px) are skipped |

Extra mutation tags (`PO_INBOX_MUTATIONS`): `empty_body`, `cover_note`,
`recap_in_body`, `multi_attachment`, `packing_list_attachment`,
`logo_image_attachment`, `text_only_order`, `out_of_office`. The default profile
keeps using only `MUTATIONS`.

### Scoring this set

An answer may now also say `order` or `status_question` with lane `needs_a_look`
(the only added category/lane pairs; every other pair stays invalid). The pass
bar is unchanged: at least 100 true-order emails and zero lost orders. With
perfect answers `order_or_needs_a_look_recall` is 1.0 and `order_recall` is the
share of orders expected in Sure (73 of 126), because text-only orders and
unknown-sender orders are expected in Check, not Sure.
