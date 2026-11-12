# Testing and verification

## Sources of truth

The [README](../README.md) defines the product contract. API-specific expectations come from Google's
[Gmail list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), [Gmail metadata](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get), [People batch retrieval](https://developers.google.com/people/api/rest/v1/people/getBatchGet), and [contact update](https://developers.google.com/people/api/rest/v1/people/updateContact) documentation. The
client library's bundled discovery schemas validate request construction.

## Suite

`make check` runs the offline suite, lint, formatting, and local Markdown link checks.
`make check-package` adds fresh builds, archive inspection, and clean wheel installation tests.
Pytest disables network sockets globally; tests must never use real credentials or Google accounts.

| Tests | Contract |
| --- | --- |
| `test_fixture_contract.py` | Fixture filtering, pagination, read masks, replacement semantics, etags, and full email lists |
| `test_core.py` | Parsing, deduplication, identifiers, preservation, limits, and saved-state verification |
| `test_search.py` | One-result searches, exclusions, request counts, query limits, malformed responses, and no-progress guards |
| `test_sync.py` | CLI preview/apply, real Google client request construction, sender exclusions, conflicts, error outcomes, and reruns |
| `test_cli.py` | Subcommand routing, required options, rejected legacy/mixed options, token forwarding, authorization defaults, and missing-token consent/resumption |
| `test_duplicate.py` | Copy fixture identity/storage, all editable field families, full email lists, preview/apply, optional name, source changes, photo handling, partial outcomes, and independent verification |
| `test_progress.py` | Status before API requests, real scan counters, invalid/empty scans, throttled terminal/redirected output, and clean error/interruption endings |
| `test_interrupt.py` | Ctrl+C during connection, scanning, consent, pre-write reads, writes, and post-write verification |
| `test_apply_prompt.py` | Preview before consent, yes/no/empty/EOF handling, redirected streams, explicit apply bypass, and no-addition runs |
| `test_installed_cli.py` | Real entry point help, missing/malformed client and token files, wrong client type, incomplete credentials, missing scopes, and subprocess guard contracts |
| `test_repository_checks.py` | Rejection of private archive files, missing runtime modules, and broken local links/headings |
| `test_reauthorization.py` | Old-scope detection before refresh, consent/decline/EOF, noninteractive guidance, scope requests, and existing-token preservation |
| `test_auth.py` | Explicit OAuth setup, browser opt-out, token paths/permissions, refresh, and denied consent |

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

Live checks are separate and require explicit authorization. A future read-only check should compare
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
original link construction before the fix. Live browser navigation remains separately unverified.

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

## Metrics

`test_metrics.py` checks the [metrics contract](metrics.md): real discovery-client call counts,
partial runs, outcomes, private-data exclusion, storage failures, and summary grouping. Retry
measurement uses a synthetic HTTP transport with independently checked attempts and disabled
backoff sleeps. Tests redirect logs into temporary directories; they never record real runs.

## Sender-search regression coverage

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
Do not close #2 until separately authorized live validation is recorded.

## Sectioned output and sender labels

`test_sender_labels.py` verifies ordered contact/label/search/additions sections and the forced final
counter for both terminal and redirected streams. The counter and label-preview regressions failed
against the previous implementation. New From display names populate the People email `type` field;
encoded names and missing names are covered. The fake transport's custom-label persistence is tested
independently. Both the update response and independent read must preserve the proposed label:
temporarily disabling that verification caused both lost-label regressions to fail, and restoring
it passed. Live Google normalization and UI display remain separately unverified.

## Own sending identities and redundant output

`test_own_addresses.py` verifies primary/alias exclusions in queries and saved data, parser-side
protection when search exclusions are ignored, and safe failure on missing/malformed send-as data
or access denial. Its send-as fixture uses synthetic inputs in `tests/fixtures/send-as.json` and is
contract-tested independently. Before implementation, regressions demonstrated own addresses being
added and redundant email labels being saved. The updated behavior omits labels matching their
address case-insensitively and removes the two repeated summary count lines. No live account
queries are part of these tests.

## Operational timestamps

`test_timestamps.py` covers date-once behavior across output streams, same-day completion, midnight
rollover, multiline continuations, undecorated help, timestamped errors, interruption cleanup,
untimestamped updating counters in terminal and redirected output, and forced final progress.
Clocks are injected; no sleeps or live Google access are needed.
Existing output-content tests remove only date/time decoration when checking their original
contracts; timestamp tests independently check the exact decoration and ordering. The convention
matches screenshots and pdf-slim; those projects already use it and need no corresponding change.

## Full-size duplicate photos (#1)

Synthetic 8×8 and 64×64 checkerboard PNGs exercise thumbnail versus full-size downloads.
Regression tests cover path and suffix size options, retained crop options, conflicting query
sizes, and exact uploaded bytes. Unknown URL size formats stop before downloading. These cases
failed against the thumbnail implementation. Fixture dimensions and decoding were independently
checked with macOS sips. No account images are included in fixtures. The user confirmed improved
photo quality in a live duplication test on 2026-11-12. Automated tests do not establish Google's
upload fidelity for every image.
