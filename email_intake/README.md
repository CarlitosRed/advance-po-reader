# Fictional email intake core

This package sorts locally saved fictional `.eml` files and prepares source files
for a person to select in the reader. It has no reader connection, mailbox, product
approval, catalog, UI or notification service. Every product still needs a person.

From the repository root, with Python 3.12 or later:

```powershell
python scripts/email-intake.py --drop tests/email_intake/fixtures --out output/email-review
python scripts/email-intake.py --drop tests/email_intake/fixtures --out output/email-scripted --fake-results tests/email_intake/fixtures/fake-results.json
python -m unittest discover -s tests/email_intake -v
python -m unittest discover -s tests -v
```

The first command uses a FakeProvider that sends everything to `needs_a_look`.
The second supplies trusted SHA-bound answers for twelve tiny fictional fixtures.
It exercises routing, retention and preparation; it does not measure model accuracy
or prove that an injection cannot influence a live model. The repository's existing
unittest discovery also runs the intake suite. No runtime dependencies are added.

`records/` contains one immutable JSON record per source name and content identity.
`sources/` retains admitted originals and opaque attachment bytes. `calls.jsonl`
records safe attempt metadata, including token counts (null when unknown; zero for
fake calls). `quiet-digest.jsonl` keeps every final non-order with an attachment
unresolved for local checking. Original names, subjects, bodies and attachment
names appear only in local evidence records, never in stdout or call/digest logs.
Input originals are never removed. Keep output in an ignored private directory.

Exact original bytes under another name create a duplicate link without another
classification. A reused Message-ID or shared attachment hash with changed bytes
creates a related record in `needs_a_look`, without spending on classification.
Nothing is merged or overwritten. Re-running the same input and output returns
the stored outcome, including a stored fake or pending outcome. A deliberate new
evaluation needs a separate output directory; a live ledger still prevents a second
attempt for the same content identity, including after an unknown outcome.

Parser limits are 2 MiB per email, 32 KiB top-level headers, eight boundary
declarations/depth, 64 parts, 24 attachments and 12,000 body UTF-8 bytes. Malformed
MIME, unknown encodings, attached emails, excessive nesting and limits require a
look. Oversized originals stay in the drop folder: only a bounded prefix-and-size
identity and pending record are written, so do not move those inputs before review.
There is no claim that this bounded identity is the whole-original SHA-256.

Archives, macros and other unsupported types are retained as `.bin` evidence and
force review; they are never unpacked or executed. PDF/PNG/JPEG reader candidates
require matching declared media type, a supported filename extension and a file
signature. This is an admission check, not full structural validation: the human
and reader must still validate/select the source. Filenames are never storage paths.
Inline images are included in the manifest and the quiet net. HTML is converted
locally, scripts/styles are removed, and remote resources are never fetched.

For body-only orders, the standard-library renderer produces one derived PDF page
with a hash of the original parsed text. English/Spanish WinAnsi text that fits
57 lines at 90 columns is supported. Other Unicode (including the colón symbol),
control characters or overflow require a look with `PDF_LIMIT`; the full text and
original remain available. No replacement characters or truncated PDF is emitted.

## Deferred live path

The builder has made no paid calls. Carlos can later run the following only with
fictional emails, an environment-provided key, and ONE shared phase-one ledger:

```powershell
python scripts/email-intake.py --drop PATH_TO_FICTIONAL_MAIL --out output/live-email-review --live --ledger output/phase-one-spend.sqlite3
```

The ledger's parent must already exist. No environment files are loaded. Without
`--live`, the CLI does not look up the API key or construct an HTTPS connection.
With `--live`, a missing key/ledger stops calls and leaves a visible reason. The
adapter sends subject, preserved text segments and attachment metadata; it excludes
sender, hashes, local paths and attachment contents. The fixed request uses
`gpt-6-luna`, Responses, `reasoning.effort=none`, `store=false`, no tools and the
closed nine-category/three-lane JSON schema. Code rejects invalid pairs, refusals,
incomplete responses and schema failures. No second model or hidden retry exists.

Each call commits a SQLite reservation before transport. The fixed $3 classifier
ledger uses integer nanodollars and conservative Standard write-rate accounting
($0.125/M input, $0.50/M output), a 6,000 input-token reservation and 100 maximum
output tokens: $0.0008 per reservation. Requests whose serialized UTF-8 byte count
plus 2,048 framing/schema allowance exceeds 6,000 are rejected without truncation.
Usage within bounds settles the reservation conservatively; missing, invalid or
out-of-bound usage keeps the full reservation. Unknown transport outcomes retain
their reservation across restart and block another attempt for the same identity.
Concurrent admissions are serialized in SQLite. There is no reset command.

Use the SAME ledger for all phase-one classifier runs. Creating/replacing ledgers
or spending in another application is outside this cap's control. Reader work is
not invoked or budgeted here: this package cannot enforce an account-wide cap or
reserve money for a separate reader. Do not start paid reader work under this slice.
The estimate is a conservative admission bound, not measured live token usage.
Model access, actual usage/pricing and retention eligibility remain untested live.
`store=false` does not promise zero provider retention.

A stale `.intake-lock` after a crash blocks writes for human investigation. Storage
corruption/path aliases/permission failures stop the run with a fixed reason rather
than attempting recovery or repeating requests. Symlink creation was unavailable
in the local Windows test environment; that test is explicitly skipped there.

## Evidence boundaries

The twelve scripted fixtures do not meet the design's 100+ fictional-order accuracy
bar or week of shadow checking. Those remain later human-controlled acceptance
work. No real mail is authorized by this package or its examples.

Official API facts checked 2026-10-08:

- [Luna model, effort, Structured Outputs and Standard rates](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [Strict output schema and refusal/incomplete handling](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Responses text.format and store=false](https://developers.openai.com/api/docs/guides/migrate-to-responses)
