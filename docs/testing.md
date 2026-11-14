# Testing and verification

## Sources of truth

The [README](../README.md) and [command reference](command-reference.md) define the product contract.
API-specific expectations come from Google's
[Gmail list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), [Gmail metadata](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get), [People batch retrieval](https://developers.google.com/people/api/rest/v1/people/getBatchGet), and [contact update](https://developers.google.com/people/api/rest/v1/people/updateContact) documentation. The
client library's bundled discovery schemas validate request construction.

## Suite

`make check` runs the offline suite, lint, formatting, and local Markdown link checks.
`make check-package` adds fresh builds, archive inspection, and clean wheel installation tests.
Pytest disables network sockets globally; tests must never use real credentials or Google accounts.

| Area | Tests | Contract |
| --- | --- | --- |
| Fixtures and core | `test_fixture_contract.py`, `test_core.py` | Transport semantics, parsing, preservation, limits, and verification |
| Routing and options | `test_cli.py`, `test_global_options.py` | Command routing, required options, help order, and global flags |
| Authorization | `test_auth.py`, `test_reauthorization.py` | OAuth setup, consent, scope upgrades, token storage, and failures |
| Creation and validation | `test_contact_inputs.py`, `test_contact_create.py` | Person JSON, local validation, creation, labels, and partial outcomes |
| Duplication | `test_duplicate.py` | Copyable fields, photo handling, identities, and independent verification |
| Sender sync | `test_search.py`, `test_sync.py` | Search requests, completeness, conflicts, writes, and reruns |
| Sender identities | `test_own_addresses.py`, `test_sender_labels.py` | Own-address exclusions and saved display labels |
| Explicit exclusions | `test_exclude.py`, `test_exclude_files.py` | Inline/file parsing, matching, and query integration |
| Email editing | `test_email_edit.py` | Listing, addition, removal, conflicts, duplicates, and preservation |
| Contact labels | `test_label_edit.py`, `test_remove_label.py`, `test_label_output.py` | Membership edits, case choices, output, and partial failures |
| Custom fields | `test_custom_fields.py` | Exact selectors, duplicate handling, and verified single-field updates |
| Interaction and output | `test_apply_prompt.py`, `test_interrupt.py`, `test_progress.py`, `test_timestamps.py` | Consent, interruption state, counters, and timestamps |
| Diagnostics | `test_metrics.py`, `test_error_logs.py` | Local storage, measurement, error responses, and privacy boundaries |
| Packaging and CI | `test_installed_cli.py`, `test_repository_checks.py`, `test_ci_scope.py` | Installed execution, archives, links, subprocess guards, and CI routing |

Synthetic contact and message inputs live in [tests/fixtures](../tests/fixtures). [FakeGoogle](../tests/fake_google.py) is an in-memory HTTP
transport used with real Google discovery clients. It replaces fields on PATCH rather than appending
them, so a destructive request body cannot accidentally pass a preservation test. Fixture contract
tests call that transport directly, without contacts-cli's orchestration.

Choose intentional fixture variations rather than a Cartesian product of every option. The fake
models selected contracts only. It cannot prove real permissions, server storage limits, Google
normalization, consent setup, or actual account completeness.

## Regression sensitivity

For meaningful behavior changes, first run a regression against unfixed code when practical.
Otherwise introduce one temporary fault at a time and run the targeted test:

| Temporary fault | Expected detection |
| --- | --- |
| Bypass the CLI apply switch | Preview test detects a contact write |
| Stop after the first sender search | Preview additions are incomplete |
| Drop existing emails from the update body | Preservation assertion fails |
| Supply the wrong source etag | Update is rejected; successful-apply assertion fails |
| Skip verification of added emails | Lost-additions scenario incorrectly reports success |

Restore each fault immediately, preferably with `try/finally`, and rerun the correct implementation.
Never retain faulty source or commit temporary mutation artifacts.

Additional regression cases cover oversized-contact no-ops, malformed URL errors, and invalid JSON
after a write. These should distinguish a no-op, a pre-write failure, and an uncertain outcome
rather than silently treating them as equivalent.

The transport regression uses the real authorized HTTP wrapper with synthetic credentials and HTTP
responses. It verifies that a 401 does not cause a second write request after refresh. Setting
`execute(num_retries=0)` alone does not disable that separate retry layer.

## Packaging and live checks

`make build` creates the wheel and source archive. Inspect both archive listings to confirm that
they contain only intended package/project files. Private handoffs, tokens, OAuth clients, local
configuration, caches, and environments must be absent.

Live checks are separate and require explicit authorization. A read-only live check can compare
the complete preview with the Gmail label and contact UI in the authorized account, without
applying. A live write needs its own approval; verify additions, existing custom labels and other
contact data afterward, then confirm the next preview has no additions. Record evidence locally
without publishing personal data.

Duplication tests use the bundled People discovery schema and synthetic source contacts. Fixture
contracts independently check creation, separate source/destination storage, masked reads, missing
contacts, and photo writes. Controlled faults in the apply gate and saved-field verification must
be detected. These checks do not establish live Google normalization or photo fidelity.

Duplicate-link regression: a created fixture contact uses resource `people/c456` and source ID
`1c8`. The independent fixture test confirms those distinct identifiers. Success and partial-failure
output must link to `/person/c456`, not `/person/c1c8`. The success assertion failed against the
original link construction before the fix. This automated test does not establish live browser
navigation behavior.

## GitHub Actions

[Tests workflow](../.github/workflows/ci.yml) runs on pushes, pull requests, and manual dispatch.
The explicit matrix covers Linux with Python 3.11 (the minimum supported version) and macOS with
Python 3.13. Each job installs the locked dependencies and runs `make check`, `make check-package`,
and whitespace checks. Actions are pinned to commit SHAs and uv to a specific version. Jobs have
read-only repository permissions, a 15-minute timeout, and require no Google credentials.

`make check-package` builds into a fresh temporary directory, checks both archives for private
filenames and required runtime modules, installs locked production dependencies and the wheel into
a separate environment, verifies imports come from that environment, and runs the CLI subprocess
suite again. Temporary files are removed afterward. Dependency installation may use the network;
Google-facing test paths are offline. Archive checks cover known private filename patterns and
required modules, not arbitrary secrets embedded in otherwise allowed files.

The CLI subprocess suite uses synthetic cases from [auth-errors.json](../tests/fixtures/auth-errors.json), with explicit client/token
paths outside Git. It runs outside the checkout with piped input. Cases check exit codes, useful
errors, absence of tracebacks and browser prompts, and that token files remain absent or unchanged.
The parent pytest socket restriction does not extend to child processes, so each child loads a
separate guard that blocks and records socket creation, DNS lookup, and browser requests. The
urllib3 local IPv6 import probe completes before the guard is installed; no Google modules or
credentials are loaded during that initialization. Independent tests prove socket and browser
attempts are rejected. The suite requires the guard's ready marker and no attempted actions.

Existing unit tests cover simulated OAuth denial, timeout, missing scopes, and refresh failures.
CI does not establish live Google consent behavior, account permissions, server normalization, or
contact correctness. Live account tests remain separate and require explicit authorization.

Progress reporting tracks [issue #3](https://github.com/stansult/contacts-cli/issues/3). Regression tests first failed because no status was
emitted before the contact request. Timing tests use an injected clock; no sleeps or live calls
are required. The scan callback also runs against the independently tested Google transport
fixture to check actual inspected-message and invalid-header counts. Sender-search optimization
is tracked in [issue #2](https://github.com/stansult/contacts-cli/issues/2).

## CI routing

`scripts/ci_scope.py` permits lightweight checks when every changed file is root `README.md`,
root `CONTRIBUTING.md`, or a `.md` file anywhere under `docs/`. New and nested guides qualify
without changing the classifier. Markdown elsewhere, non-Markdown files, and mixed changes
run full checks. `FULL_CHECK_DOCUMENTS` overrides these rules for explicit automation-input
exceptions; currently there are none. Keep fixtures and artifact-generation inputs outside
`docs/`, as described in [documentation paths](../CONTRIBUTING.md#documentation-paths).

Pushes compare the before/after commits across the entire push. Pull requests compare the merge
base with the PR head. Renames include both old and new paths. Manual runs, empty diffs, new
branches, and unavailable comparison history use full checks. Classification reads the event
file rather than interpolating event values into shell commands.

Documentation-only runs check local links and Markdown heading targets using Python's standard
library, without uv setup, application dependencies, runtime tests, or package builds. Other
runs retain both OS/Python test jobs. `test_ci_scope.py` checks new/nested guides, mixed paths,
and explicit exceptions, and uses a temporary Git repository to verify multi-commit push ranges,
PR ranges, and renames independently of mocks.
Changing this workflow or its classifier therefore runs the full suite.

## Authorization timeout testing

The supported `--auth-timeout SECONDS` option is hidden from help. Use a positive integer to
shorten the browser authorization wait for manual testing:

```sh
./contacts-cli authorize --auth-timeout 5
```

All commands accept it before or after the command name, including commands that offer browser
authorization when a token is missing or lacks required scopes. The default is 300 seconds.
It changes only the browser authorization wait, not API request timeouts or token expiration.
If specified on both sides of the command, the value after the command takes precedence.

## Regression coverage and evidence

The following sections retain fixture contracts, regression sensitivity evidence, and the stated
limits of automated or live verification. Issue lifecycle status belongs in GitHub Issues.

### Metrics

`test_metrics.py` checks the [metrics contract](metrics.md): real discovery-client call counts,
partial runs, outcomes, private-data exclusion, storage failures, and summary grouping. Retry
measurement uses a synthetic HTTP transport with independently checked attempts and disabled
backoff sleeps. Tests redirect logs into temporary directories; they never record real runs.

### Sender-search regression coverage

`test_search.py` verifies one-result searches, existing/discovered exclusions, reduced request
counts for repeated senders, and safe failure on incomplete responses, repeated results, unsupported
addresses, and query limits. The 1,000-message/two-new-sender test first failed against the old
scan with 1,000 header reads, then passed with two reads and three searches. This measures request
volume in a synthetic fixture, not live latency. All-unique senders can require more requests.
A temporary fault disabling accumulated exclusions caused a repeated result and failed the
regression; restoring the exclusions passed.

The fixture independently tests one-result limits, exclusions, case-insensitive address matching,
Spam/Trash, and preservation of dot/plus distinctions. Its exact address matching is a deliberately
limited model, not evidence of Gmail's live matching semantics. Google documents the
[search query and label combination](https://developers.google.com/workspace/gmail/api/guides/filtering)
and [list limits](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list).
Multiple-author search behavior is deferred to [issue #4](https://github.com/stansult/contacts-cli/issues/4).
Record live validation separately; the issue tracker owns the delivery status.

### Sectioned output and sender labels

`test_sender_labels.py` verifies ordered contact/label/search/additions sections and the forced final
counter for both terminal and redirected streams. The counter and label-preview regressions failed
against the previous implementation. New From display names populate the People email `type` field;
encoded names and missing names are covered. The fake transport's custom-label persistence is tested
independently. Both the update response and independent read must preserve the proposed label:
temporarily disabling that verification caused both lost-label regressions to fail, and restoring
it passed. Live Google normalization and UI display remain separately unverified.

### Own sending identities and redundant output

`test_own_addresses.py` verifies primary/alias exclusions in queries and saved data, parser-side
protection when search exclusions are ignored, and safe failure on missing/malformed send-as data
or access denial. Its send-as fixture uses synthetic inputs in `tests/fixtures/send-as.json` and is
contract-tested independently. Before implementation, regressions demonstrated own addresses being
added and redundant email labels being saved. The updated behavior omits labels matching their
address case-insensitively and removes the two repeated summary count lines. No live account
queries are part of these tests.

### Operational timestamps

`test_timestamps.py` covers date-once behavior across output streams, same-day completion, midnight
rollover, multiline continuations, undecorated help, timestamped errors, interruption cleanup,
untimestamped updating counters in terminal and redirected output, and forced final progress.
Clocks are injected; no sleeps or live Google access are needed.
Existing output-content tests remove only date/time decoration when checking their original
contracts; timestamp tests independently check the exact decoration and ordering. The output
convention is documented in [Contributing](../CONTRIBUTING.md#operational-timestamps).

### Full-size duplicate photos (#1)

Synthetic 8×8 and 64×64 checkerboard PNGs exercise thumbnail versus full-size downloads.
Regression tests cover path and suffix size options, retained crop options, conflicting query
sizes, and exact uploaded bytes. Unknown URL size formats stop before downloading. These cases
failed against the thumbnail implementation. Fixture dimensions and decoding were independently
checked with macOS sips. No account images are included in fixtures. The user confirmed improved
photo quality in a live duplication test on 2026-11-12. Automated tests do not establish Google's
upload fidelity for every image.


### Explicit sender exclusions

`test_exclude.py` covers repeatable `--exclude` values, trimming and case-insensitive matching,
deduplication, automatic exclusions, preview/apply behavior, preservation of existing entries,
and absence of persistence between runs. Invalid inputs stop before authorization. A transport
that returns an excluded sender followed by an empty search verifies candidate filtering still
blocks writes. Removing that filter causes an incorrect write and fails the regression; the
fixture does not rely on the repeated-message guard. Existing search-fixture contract tests
independently verify query exclusion behavior. The user also verified live previews with four
explicit exclusions: seven additions with exclusions versus eleven without; both were declined.

New sender labels matching a contact display name or company are omitted in preview and saved
additions, using the same case/whitespace normalization as address matching. Tests cover both
identities being present, blank identity lists, and distinct labels with a shared prefix. Existing
email entries remain unchanged. Four omission cases failed before this change.

`test_exclude_files.py` covers combining multiple files with address flags, duplicate/case
normalization, comments, blank lines, pasted display labels, relative paths, fresh reads, and
file/line diagnostics before authorization. A synthetic text fixture has its parsing contract
checked independently of CLI integration. Missing, unreadable, and non-UTF-8 files are covered.

### Direct email editing

`test_email_edit.py` covers shared add/remove inputs, label normalization before collisions,
conflicting input rejection, keep/replace/all decisions, final confirmation, duplicate reduction,
removal of all entries, no-op reruns, primary preservation/reassignment, concurrent changes,
failed verification, and avoidance of Gmail calls. The synthetic transport's empty-list update
contract is tested independently. Tests do not establish live Google normalization behavior.

Display regressions cover totals and numbered rows, multiple duplicate groups, local conflict and removal
numbering after consolidation, separate addition/update sections, missing and skipped entries,
and action headings with --apply. Listing tests cover populated and empty contacts, read-only
requests, no Gmail calls, invalid inputs, and silent plural aliases with singular help text.
Local-numbering and listing regressions failed before their implementation. A controlled fault
retaining Proposed headings during apply failed the intended assertion before restoration.


### New-contact inputs

`test_contact_inputs.py` covers Person field/schema and value validation, partial dates, generated
fields, singleton and size limits, malformed files, precise locations, inline/file exclusivity,
and rejection before authorization. The synthetic full-field fixture is checked independently against the
bundled discovery schema and explicit expected values. `test_contact_create.py` covers preview-only behavior,
confirmation, label pagination/reuse/creation, sequential contact creation, independent readback,
partial failures and no mutation retries. The label fixture has independent storage, pagination,
and duplicate-name conflict checks. All account interactions use the offline HTTP fixture.

Creation-output tests cover readable previews, requested/saved mismatches, definite rejection,
unknown write outcomes, interruptions during writing versus verification, partial batches, and
labels created before contact processing stops. These cases verify that each failure prints one
outcome without a second generic error from the CLI.

Local validation command tests exercise one object, arrays, missing files, invalid field paths,
file-only options and the silent plural alias. Authorization, connection and input functions are
replaced with failing sentinels to verify validation remains offline and noninteractive.

### API error logging

`test_error_logs.py` verifies full JSON, non-JSON and binary error bodies, HTTP status and method,
command context, unique private files, request-data exclusion, read/write failures, and failure
to save a log without masking the original error. A real Google HttpRequest with a synthetic
transport checks exact response preservation and no mutation retries. Tests redirect logs into
temporary directories through `CONTACTS_CLI_ERROR_LOG_DIR`.

### Contact labels

`test_label_edit.py` independently checks the membership HTTP fixture's additive, idempotent,
readback and not-found behavior. Product tests cover preview/apply/confirmation, plural alias,
existing memberships and fields, no-op reruns, case choices, cancellation, partial failures,
no mutation retries, and missing new or prior memberships during verification.

`test_remove_label.py` checks removal fixture idempotency and last-membership refusal independently,
then covers singular/plural commands, preview/confirmation/apply, missing and unapplied labels,
no-create case choices, no-op reruns, retained label definitions and contact data, and verification
of both requested absence and preserved memberships.

### Label output scenarios

`tests/test_label_output.py` covers membership-aware case choices, exact spelling precedence
when case variants coexist, creation versus addition counts, whole-command cancellation,
multiple case matches, and single versus multiple-label success output. It exercises the real
CLI and fake Google client; fixture membership behavior is independently checked in
`test_label_edit.py` and `test_remove_label.py`. The new output assertions were run against
the previous implementation and failed for the intended wording and preview differences.

### Custom field editing

`tests/test_custom_fields.py` independently checks replacement/clearing and etag behavior in the
HTTP fixture, then covers singular/plural commands, previews, exact matching, duplicate preservation
and removal, case-only notices, empty-field removal, confirmation, invalid input, size guards,
concurrent edits, and response/readback verification. A temporary disabled verifier made the three
verification regression tests fail as intended; the verifier was restored. The full suite also
checks the email commands using the shared single-field update path. Installed CLI help checks
cover both custom-field commands.
