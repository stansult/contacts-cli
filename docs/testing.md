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
| Sender sync | `test_search.py`, `test_search_input.py`, `test_sender_criteria.py`, `test_label_sync.py`, `test_sync.py` | Search requests, completeness, conflicts, writes, and reruns |
| Sender identities | `test_own_addresses.py`, `test_sender_labels.py` | Own-address exclusions and saved display labels |
| Explicit exclusions | `test_exclude.py`, `test_exclude_files.py`, `test_exclude_other.py` | Inline/file parsing, matching, and query integration |
| Email editing | `test_email_edit.py`, `test_primary_normalization.py` | Listing, addition, removal, conflicts, duplicates, and preservation |
| Contact labels | `test_label_edit.py`, `test_remove_label.py`, `test_label_output.py` | Membership edits, case choices, output, and partial failures |
| Custom fields | `test_custom_fields.py` | Exact selectors, duplicate handling, and verified single-field updates |
| Interaction and output | `test_apply_prompt.py`, `test_interrupt.py`, `test_progress.py`, `test_stage_progress.py`, `test_timestamps.py` | Consent, interruption state, counters, and timestamps |
| Diagnostics | `test_metrics.py`, `test_error_logs.py`, `test_run_diagnostics.py` | Local storage, measurement, error responses, and privacy boundaries |
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

## New external-call validation

Follow the [integration gate](../CONTRIBUTING.md#validate-new-external-calls-before-integration)
before a new external operation enters the normal command path:

1. Verify the official API contract and identify the intended scope, client/transport, request
   shape, and expected response. State what the probe will read or change.
2. Prepare a standalone probe for that operation. Use a short explicit timeout and one attempt
   with automatic retries disabled. Agree on a larger bound if the operation needs it; do not
   discover a long retry sequence through the normal user command.
3. Obtain authorization for the specific live access, or have the user run the probe. Keep
   credentials and account data outside tracked files. Mutations need an explicitly approved
   target and cleanup plan; permission to read does not authorize writes.
4. Capture the operation, relevant environment/configuration, duration, response status/shape,
   and underlying exception if it fails. Keep private details in ignored local evidence and a
   sanitized result in the issue. A timeout or generic failure is unresolved evidence, not a pass.
5. After a successful probe, integrate the call with deliberate timeout/retry limits and visible
   progress. Test failure handling offline as well. If the probe fails or cannot run, stop the
   integration and discuss the next diagnostic or an explicitly agreed alternative.

A successful probe is evidence for the tested configuration, not a guarantee of future service
availability. Keep live checks separate from the network-disabled automated suite. Existing
fixture-contract and regression requirements still apply; neither kind of test replaces the other.

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

## Sender search input

Search-input regression tests cover required/exclusive source options, blank and oversized input
before authorization, grouped queries, manual exclusions, preview/apply, and metrics privacy.
The fixture maps explicitly configured base queries to message IDs; it does not parse Gmail's
search language. A direct transport test independently checks that selection and subsequent
sender exclusions. New search tests were run before implementation and failed for missing search
support; the completed implementation passes them.

### Gmail label case choices

`test_gmail_label_choices.py` exercises the actual sender-sync path through the offline transport:
exact-match precedence, single-match default Yes, multiple-match selection, cancellation,
noninteractive spelling hints, missing labels, and choices with `--apply`. Tests assert the
selected label ID is sent to Gmail and cancellation makes no search or write. The case-choice
regressions failed against the former exact-only implementation. They use the existing
independently contract-tested label-filtering fixture; no live Gmail access is involved.

### Search address criteria (#7)

`test_sender_criteria.py` covers positive from/to extraction, quoted values, grouping, negation,
ignored fields, unsupported values, malformed/nested syntax, case and domain-boundary matching,
and subdomains. CLI tests cover split totals, continuous numbering, empty groups, fallback,
no-op runs, preserved display labels, and saving both groups. Fallback explanation tests verify
placement below the total and absence for grouped previews, label mode, and no-op runs. The three
fallback wording cases failed before the explanation was added. A direct transport test verifies
the synthetic message selection and From headers independently of product grouping. The fake
does not evaluate Gmail syntax; configured query-to-ID mappings represent server results.

Regression tests ran before implementation and failed for missing grouping and criteria support.
Tests validate the CLI's documented classification rules, not equivalence to Gmail's full search
semantics. No live account reads or writes are part of this coverage.


### Excluding Other senders (#8)

`test_exclude_other.py` covers interactive keep/exclude/default decisions, invalid answers,
EOF cancellation, final write confirmation, explicit flags, and noninteractive preview/apply.
It verifies the actual saved plan and retained original entries, not just displayed counts.
Output tests check explicit add/skip group summaries and contact-specific confirmation wording;
eight wording regressions failed before those messages replaced the selected/excluded summary.
It also covers unusable criteria before authorization, no-other/no-results/all-excluded cases,
manual exclusions, malformed scans, and retained saved-result verification. Existing direct
transport contracts cover the synthetic selected messages and update/readback behavior.
Fifteen cases failed against the prior implementation before the feature was added.

### Email verification diagnostics (#10)

`test_verification_details.py` checks named field differences, raw omitted versus true
sourcePrimary values, unpaired duplicate counts, and update-response versus readback stages.
The original seven cases failed before the diagnostics were added. A later user reproduction
confirmed that omitted-to-true sourcePrimary caused a false verification failure. Verification now
allows primary assignment when no source-primary choice was recorded, while preserving explicit
choices, email content, and duplicate counts. The affected diagnostic test now expects success;
additional regressions cover explicit-primary loss and content loss during normalization.

`test_primary_normalization.py` independently checks synthetic transport normalization, then
exercises the actual update response and independent readback through the API. Both API regressions
and the omitted/false-to-true unit regressions failed before the fix. Success creates no verification
log. Tests use synthetic contacts and do not establish other Google normalization behavior.
Email verification failures still save bounded local evidence as described below.


### Verification log retention

`test_verification_logs.py` covers raw before/expected/saved email snapshots, both failure
stages, command context, owner-only files, no logging on success, and unavailable readback.
Retention uses independently created files with explicit timestamps to verify exactly 20
verification logs remain and HTTP/unrelated files survive. Storage failures preserve the original
unverified error. Six regressions failed before logging was implemented.


### Label sync without filter discovery

`test_label_sync.py` checks that interactive label runs only ask for final write confirmation,
`--apply` runs without prompts, and neither makes filter requests. It also verifies that
`--label --exclude-other` fails before authorization and refresh-filters is absent from help.
These five regressions failed before removing filter discovery. Existing Gmail label-choice,
search-criteria, and sender-selection tests retain coverage of those supported paths.

### Opt-in run diagnostics

`test_run_diagnostics.py` runs sender-sync with `--diagnostics` through the real API client and
synthetic transport. It reads the flushed log from inside a pending message-list request, then checks
success, timeout/retries, interruption, exit codes, exception frames, credential redaction, file
permissions, and context reset. Four regressions failed before implementation. Retry backoff is
removed only in tests; the client still performs its actual retry logic. Retention uses independently
created files with explicit timestamps and checks that unrelated log types survive. Storage failure
must preserve the command result. These tests do not call Google or establish the live failure cause.


The default-run regression confirms that omitting `--diagnostics` creates no run trace or diagnostic
messages; it failed against unconditional tracing before the opt-in gate was added.

### Shared stage progress

`test_stage_progress.py` exercises the generic helper independently of Gmail: the 5-second and
10-second boundaries, fixed start timestamps, backward wall-clock changes, monotonic durations,
midnight completion, plain redirected output, final details, and updater cleanup on error and
interruption. A synchronized stream observes animation while the main thread waits, then confirms
that a prompt stops the updater. Nine regressions failed before the helper existed. Existing scan,
CLI, and timestamp tests now expect one completion line carrying the final sender counts and cover
unchanged processing results. Test-only injected clocks and disabled background animation allow
deterministic boundary checks; these are not CLI flags.


### Isolated read deadline transport

`test_read_deadline.py` exercises `DeadlineHTTP` and the production worker protocol with a
synthetic transport in `fixtures/deadline_worker.py`. The fixture disables sockets and uses
blocking pipes for stalls; direct protocol tests independently verify success, HTTP rejection,
and DNS failure responses. No Google access or credentials are needed.

Coverage includes DNS and response stalls, continuous response delay, retry backoff, worker
termination and forced kill, Ctrl+C cleanup, refreshed credentials reused by subsequent reads,
HTTP error bodies, long GET queries encoded as POST, write rejection inside a read, unchanged
parent-side writes, initial token-refresh deadlines, and parent-side metrics/diagnostics.
The elapsed-time regression failed with a deliberately doubled deadline and passed after restoring
it. Fixture marker files establish that each stalled worker reached the intended operation.
The connected-client test verifies Gmail and People reads use the deadline transport; authorization
tests verify refreshed tokens are saved. The connected-client assertion failed before activation.
The transport was independently validated with authorized read-only Gmail-label and contact reads
before activation. Offline tests do not establish live service latency or network reliability.


### Webpage email input and numbered selection

`tests/test_web_emails.py` covers static HTML/mailto extraction, explicitly hidden content,
case-insensitive deduplication, reusable number/range selection, invalid input, cancellation,
returning to selection, noninteractive preview, explicit apply, and preservation of existing
labels and duplicates. A synthetic HTTP response is independently checked before exercising
content-type and decompressed-size limits. A real stalled subprocess verifies deadline cleanup;
no test contacts an external server. Controlled faults verify that extraction, selection,
preservation, and size-limit regressions are detected.

An isolated public-page fetch using the production reader returned the six expected addresses
in about one second on 2026-11-16 before CLI integration. This validates that page's static HTML,
not arbitrary website layouts. The user subsequently verified extraction, contact lookup, preview,
and cancellation on the same page. Saving URL-derived additions has automated coverage but has
not been verified against a live contact.


`tests/test_partial_selection.py` covers sender-sync subsets across grouped and ungrouped
previews, original numbering, excluded-number rejection, returning to selection, cancellation,
redirected streams, and exact saved entries. The subset-save regressions failed against the
previous confirmation-only implementation. Existing fixture-contract tests independently verify
the synthetic Gmail search results and headers used by these scenarios. URL tests exercise the
same shared review flow, including preserving existing labels and duplicates.

The direct-input selection tests also failed against the intermediate two-step menu: numeric
answers were rejected and the scripted replies were exhausted. The shared prompt now accepts
`all`, numbers/ranges, or `q` directly, without a preceding `some` choice.

Single-available-address confirmation tests cover Yes, No, Enter, q, and end-of-input, including
retained nonsequential numbering. They failed against the redundant cancel menu before the fix.
Selecting one address from several separately verifies that Return to selection remains available.

`tests/test_email_selection.py` covers mixed addition/update selection, whole-address duplicate
removal (case variants, missing labels, primary markers), returning to selection without repeated
conflict prompts, cancellation, informational-number rejection, stale previews, and a valid subset
of an oversized proposal. Exact saved-list assertions verify preservation of unselected data.
The initial selection regressions failed before integration. Temporarily bypassing the selected-input
filter caused eight tests to fail, including preservation, skipped conflicts, and size limits; the
fault was restored. Existing transport fixtures model full-field replacement and concurrent edits;
the stale-preview tests expect the external edit to remain saved with zero CLI writes.

### Persistent read transport

[The transport design and benchmark guide](persistent-reader-prototype.md) describes the worker and its
local-only test server. `test_persistent_reader_probe.py` runs a child fixture with real loopback
HTTP keep-alive, synthetic credentials, explicit stalls, and protocol failures. This is an explicit
exception to socket-free child fixtures: it binds only localhost and never contacts Google.
Server startup skips `HTTPServer`'s reverse-DNS lookup; a regression test forbids both hostname
and reverse-address resolution while exercising a complete fixture request. That test failed at
`HTTPServer.server_bind` before the override. Intentional DNS-stall scenarios still test the
client resolver independently.
These tests now import the production worker and IPC client directly. `test_read_deadline.py`
also verifies successful retries reuse the process, connection failures replace it, backoff shares
the original deadline, refreshed read credentials reach parent-side writes, and command exits
close resources on success, handled errors, interruption, and unexpected exceptions. Repeated CLI
invocations get separate workers. The installed-wheel suite starts the real packaged worker and
checks its write guard with external actions blocked.


Integration regression sensitivity was checked with reversible faults: disabling connection reuse,
skipping command cleanup, dropping refreshed credentials, and extending the read deadline each
failed the corresponding test. Each fault was restored before the final complete suite. The retry
fixture independently proves a 503-then-200 sequence. The fake Google transport exposes close
calls, and the installed subprocess guard appends evidence from both parent and worker.


### Command active timing

`test_command_timing.py` checks monotonic elapsed time excluding input waits, EOF and interruption
while waiting, nested waits, repeated commands, and footer output on normal and exceptional exits.
An AST check ensures terminal prompts use the shared timing wrapper. Help remains undecorated;
the timestamp suite checks footer ordering at midnight. Browser authorization uses the same wait
context. Stored sender-sync metrics retain their previous elapsed-time semantics.

### Removal patterns

`test_remove_patterns.py` covers zero-or-more `*` matching, whole-address anchoring, case,
base domains versus subdomains, literal punctuation, overlap, file input, unmatched patterns,
and validation before Google access. CLI cases cover duplicate groups, subsets, cancellation,
noninteractive previews, apply, and concurrent edits. A stored literal-star address verifies
that selection never expands patterns again. The new matching/selection tests failed against
the original exact-address implementation before the feature was added.

### Contact creation selection

`test_contact_selection.py` exercises the shared number/range selector through `add-contact`:
subsets, original input order/numbers, overlaps, invalid selections, reselection, cancellation,
and end-of-input before any label or contact writes. It checks selected contact fields, labels,
and Created markers, plus original input numbers and selected-only counts after failure or
interruption. Single-contact confirmation, noninteractive previews, and `--apply` retain their
existing behavior; validation still covers the full input. Six subset/failure cases failed
against the original all-or-nothing implementation before the change.
