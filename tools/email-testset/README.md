# Fictional email test set (slice A)

This offline tool generates 200 fictional emails, frozen expected labels, and a
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
