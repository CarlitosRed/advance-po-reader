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
classification. A reused Message-ID with changed bytes creates a related record
in `needs_a_look`, without spending on classification. Shared attachment hashes
are informational links: a signature logo or shared terms document does not block
classification of a distinct message.
Nothing is merged or overwritten. Re-running the same input and output returns
the stored outcome, including a stored fake or pending outcome. Every stdout
summary includes the original record's `provider` (`fake` or `live`) and a `reused`
boolean. Thus offline-to-live and keyless-to-keyed reruns visibly report reuse;
they make no new attempt and do not overwrite the original result. A deliberate new
evaluation needs a separate output directory; a live ledger still prevents a second
attempt for the same content identity, including after an unknown outcome.
When every admitted email in a `--live` run was reused, stderr also prints an
`ALL_REUSED` warning. Offline, mixed new/reused and empty runs do not print it.
Non-`.eml` regular files are counted in one `skipped_non_eml_files` stderr line;
their names/contents are not printed or opened. Directories and `.env*` entries
are excluded. Uppercase `.EML` is admitted as before.

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
For body text without a declared charset, strict UTF-8 is tried first, then strict
Windows-1252. Explicit charsets, undefined Windows-1252 bytes, malformed MIME and
the original size bounds still refuse rather than substituting characters.

Empty-body messages and any unsupported-attachment message go to `needs_a_look`
with `unclear` before classification, so they reserve/spend nothing. An empty-body
message with only supported attachments retains selectable attachment candidates;
its unseen contents still require a person. Empty text alone is not a `CONFLICT`.
Unsupported mixtures retain every opaque attachment but prepare no reader files.
Duplicate and changed-Message-ID rules take precedence over these local routes.

When the classifier returns an order without attachments, the final outcome is
`needs_a_look`/`TEXT_ONLY_ORDER`, with the plain note: "This order is in the email
text only. Phase 1 reads attachments only; please check the email text."
The original classifier answer and full source text remain in the local record.
The note also appears in stdout, including on reuse. No derived PDF is prepared
for a text-only order; other body-only classifier categories keep their routing.
`TEXT_ONLY_ORDER` is a local note code, never an allowed model-output reason.

For orders with body text and supported attachments, the
standard-library renderer also prepares one derived PDF page
with a hash of the original parsed text. English/Spanish WinAnsi text that fits
57 lines at 90 columns is supported. Other Unicode (including the colón symbol),
control characters or overflow require a look with `PDF_LIMIT`; the full text and
original remain available. No replacement characters or truncated PDF is emitted.

## Optional known-sender hint

Add --known-senders PATH_TO_LIST to either offline or separately authorized live
intake. The UTF-8 list contains one exact address or exact domain per line, for
example buyer@customer.example.test or trusted.example.test. Blank lines,
surrounding spaces/tabs, a UTF-8 BOM, duplicates and uppercase ASCII are accepted.
Matching lowercases ASCII only. The file is bounded to 64 KiB and must have at
least one valid entry; one invalid entry refuses the entire run with exit 2 and
`SENDER_LIST_ERROR` before provider construction, key lookup or ledger initialization.
This run-level list error is separate from the per-email `UNKNOWN_SENDER` code.
Missing, unreadable and directory list paths stop the run. Before opening the
list, its lexical and resolved path components are checked: symlinks, Windows
junctions, Windows stream syntax (`:` outside the drive anchor), `.env*` names
and parent `.env*` directories stop the run. Windows 8.3 short names are resolved
to long names and rechecked; benign short names are accepted. These checks do not
detect hard links or protect against concurrent path replacement. Junction/8.3
hardening here applies only to the sender list; shared drop/out/ledger path
hardening is tracked separately.

This is a conservative list format: dotted ASCII DNS domains and unquoted
ASCII local parts without plus-tags or wildcard characters. Display names,
comments, groups, IP literals, trailing domain dots, internationalized or punycode
domains and wildcard patterns are not list entries. A listed domain matches
exactly; it grants no trust to subdomains or suffix/prefix look-alikes. A plus-tag
never inherits an address/domain's trust and cannot be listed.
There is no public-suffix or shared-domain check: listing `gmail.com` or `co.uk`
admits every supported mailbox on that exact domain. Prefer individual addresses
when a domain is shared. `#` comment lines, inline comments and other invalid
entries are refused and stop the entire run; they are not ignored.

Only the single top-level parsed From mailbox supplies identity. Display names,
Reply-To, Sender, Return-Path, subjects and bodies cannot supply a match. Missing,
multiple or defective From headers keep their existing PARSE_FAILED review
route; ambiguous groups/mailbox lists and unsupported identities cannot match.
An otherwise parsed unknown sender goes to needs_a_look / UNKNOWN_SENDER before
classification, with zero classifier calls/reservations and no prepared reader
files. Its original and opaque attachment evidence remain available for a person.
UNKNOWN_SENDER is local; it is not part of the classifier output schema.

A known sender merely continues through existing classification and review
rules; text-only, empty-body, unsupported, duplicate, conflict and provider-error
outcomes cannot be promoted by this hint. The From header is a claim, not
authenticated sender proof: a forged exact From can match. This feature does
not verify mailbox ownership or authorize automatic product approval.

Hint-enabled output folders retain a canonical policy hash in sender-policy.json.
The same normalized list can replay immutable outcomes. Enabling a list over
existing outcomes, changing the list, or disabling it on that output folder
refuses with CONFLICT: use a separate empty output folder for a new policy.
This prevents an old order outcome bypassing the hint on replay. Output folders
that have never enabled the option retain the existing behavior and file format.

### Sender-list path claims and probes

These checks run before the list is opened, on Python 3.12 or later. The test
names below are in `tests/email_intake/test_senders.py`.

| Class | Covered behavior and evidence boundary | Probe |
| --- | --- | --- |
| Symlink file/parent | Refused by inherited `safe_path`; simulated components are tested; real symlink creation was unavailable here | `test_symlink_components_never_opened` |
| Junction file/parent | Refused by the sender-list check; simulated components and a real owned Windows junction are tested | `test_junction_components_never_opened`, `test_real_junction_list_never_opened` |
| 8.3 short name | Resolve and recheck long-name components; a real benign short-name list passes; resolved `.env*` file/parent refusals are simulated without creating or opening `.env*` files | `test_real_short_name_resolves_to_long_name`, `test_resolved_short_name_env_components_never_opened` |
| Windows stream | `:stream` and `::$DATA` syntax refused before open | `test_env_parent_and_stream_list_never_opened` |
| Literal `.env*` file | Refused before open, including uppercase and trailing dot/space forms | `test_env_named_list_never_opened`, `test_env_parent_and_stream_list_never_opened` |
| Literal parent `.env*` directory | Refused before open, including uppercase | `test_env_parent_and_stream_list_never_opened` |
| Hard links/concurrent replacement | No protection claimed; not probed | Separate hardening work |

The review-round repair implements only sender-list path admission, bounded raw
From matching and the distinct list-error code. It documents shared-domain and
comment-line behavior and the path limits above. Shared `safe_path` is unchanged.
The existing parser `AttributeError` on `From: :;[[Name]` can stop a whole run;
it also exists on main and remains a separate issue, outside this E3 repair.

## Deferred live path

The builder has made no paid calls. The Program Owner can later run the following only with
fictional emails, an environment-provided key, and ONE shared phase-one ledger:

```powershell
python scripts/email-intake.py --drop PATH_TO_FICTIONAL_MAIL --out output/live-email-review --live --ledger output/phase-one-spend.sqlite3 --init-ledger
```

Use `--init-ledger` only for deliberate first creation or recovery of a zero-byte
file left before schema creation; omit it on subsequent runs. A zero-byte file
without that flag refuses. Non-empty/corrupt files and zero-byte files with
non-empty SQLite recovery sidecars cannot be initialized as a fresh cap.
A missing ledger without the flag exits 2 before key lookup or classification.
The resolved absolute ledger path is printed to stderr; per-email JSONL stays on
stdout. Reusing the flag never resets an existing ledger. Connections refuse a
deleted ledger instead of recreating it. The ledger's parent must already exist.
No environment files are loaded. Without
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
output tokens: $0.0008 per reservation. Requests whose complete serialized byte
count exceeds 6,000 are rejected without truncation. Prompt, schema and framing
are already included in that count and receive no second allowance.
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

A stale `.intake-lock` after a crash blocks writes with a `--break-lock` hint.
That explicit flag can recover a bounded PID marker only when the owner is
provably gone. Live/reused PIDs, permission failures and legacy empty/malformed
markers refuse. A process-held OS lock on the permanent `.intake-guard` serializes
all runs and marker recovery/removal; a hard kill releases that OS ownership.
The guard file remains after normal runs and does not require recovery.
Storage corruption and permission failures stop the run with a fixed reason rather
than attempting recovery or repeating requests. Shared drop/out/ledger paths use
the inherited symlink checks; their Windows junction/8.3 gaps are tracked in a
separate hardening PR. Sender-list checks are described above. Symlink creation was unavailable
in the local Windows test environment; that test is explicitly skipped there.

## Evidence boundaries

PR #29 scorer mapping: convert each final record to `id`, `category`, and `lane`,
using the frozen source SHA to match its test ID. Omit the optional `reason_code`
when exporting answers: the scorer's category reasons exclude local intake codes
such as `CONFLICT`, `LIMIT`, and `PDF_LIMIT`. Keep those codes in the source records
and report their counts alongside scorer metrics; never replace the final lane.

The twelve scripted fixtures do not meet the design's 100+ fictional-order accuracy
bar or week of shadow checking. Those remain later human-controlled acceptance
work. No real mail is authorized by this package or its examples.

Official API facts checked 2026-10-08:

- [Luna model, effort, Structured Outputs and Standard rates](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [Strict output schema and refusal/incomplete handling](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Responses text.format and store=false](https://developers.openai.com/api/docs/guides/migrate-to-responses)
