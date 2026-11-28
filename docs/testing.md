# Testing and verification

This is the contributor guide for running checks and establishing reliable test evidence.
For a shorter introduction to the tools and test layers, see the [testing overview](../tests/README.md).

## Quick checks

Use Python 3.11+ and uv. Run these commands from the repository root:

```sh
uv sync --locked
make check          # Offline suite, lint, formatting, and documentation links
make check-package  # Fresh archives and installed CLI checks
make check-docs     # Local documentation links and headings
```

For ordinary Markdown-only edits, follow the [documentation review exception](../CONTRIBUTING.md#review-formatting-and-push-scope).
See [regression coverage](regression-coverage.md) for detailed test contracts and recorded evidence.

## Contents

- [Suite and fixtures](#suite)
- [Regression sensitivity](#regression-sensitivity)
- [New external-call validation](#new-external-call-validation)
- [Packaging and live checks](#packaging-and-live-checks)
- [GitHub Actions](#github-actions) and [CI routing](#ci-routing)
- [Authorization timeout testing](#authorization-timeout-testing)
- [Regression coverage and evidence](#regression-coverage-and-evidence)

## Sources of truth

The [README](../README.md) and [command reference](command-reference.md) define the product contract.
API-specific expectations come from Google's
[Gmail list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), [Gmail metadata](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get), [People batch retrieval](https://developers.google.com/people/api/rest/v1/people/getBatchGet), and [contact update](https://developers.google.com/people/api/rest/v1/people/updateContact) documentation. The
client library's bundled discovery schemas validate request construction.

## Suite

`make check` runs the offline suite, lint, formatting, and local Markdown link checks.
`make check-package` adds fresh builds, archive inspection, and clean wheel installation tests.
Pytest uses pytest-socket to disable sockets by default in its process. Local transport probes
run controlled subprocesses; installed CLI tests load a separate network/browser guard.
Tests must never use real credentials or Google accounts. Ruff handles lint and formatting;
uv provides locked dependencies, and Hatchling builds the package.

### Coverage map

These are starting points, not an exhaustive list of test files.

| Area | Tests | Contract |
| --- | --- | --- |
| Fixtures and core | `test_fixture_contract.py`, `test_core.py` | Transport semantics, parsing, preservation, limits, and verification |
| Routing and options | `test_cli.py`, `test_global_options.py` | Command routing, required options, help order, and global flags |
| Authorization | `test_auth.py`, `test_reauthorization.py` | OAuth setup, consent, scope upgrades, token storage, and failures |
| Creation and validation | `test_contact_inputs.py`, `test_contact_create.py` | Person JSON, local validation, creation, labels, and partial outcomes |
| Import review and merging | `test_contact_matches.py`, `test_contact_merge.py`, `test_merge_conflicts.py`, `test_grouped_additions.py`, `test_label_only_import.py` | Duplicate decisions, conflict resolution, grouped review, and saved outcomes |
| Contact lookup | `test_list_contact.py`, `test_contact_resolution.py` | Partial/exact listing, identifier files, ambiguity, and label targets |
| Duplication | `test_duplicate.py` | Copyable fields, photo handling, identities, and independent verification |
| Sender sync | `test_search.py`, `test_search_input.py`, `test_sender_criteria.py`, `test_label_sync.py`, `test_sync.py` | Search requests, completeness, conflicts, writes, and reruns |
| Sender identities | `test_own_addresses.py`, `test_sender_labels.py` | Own-address exclusions and saved display labels |
| Explicit exclusions | `test_exclude.py`, `test_exclude_files.py`, `test_exclude_patterns.py`, `test_exclude_other.py` | Exact and wildcard inputs, group exclusion, local matching, and query integration |
| Email editing | `test_email_edit.py`, `test_email_selection.py`, `test_email_update_output.py`, `test_primary_normalization.py` | Listing, addition, removal, conflicts, duplicates, and preservation |
| Contact labels | `test_label_edit.py`, `test_remove_label.py`, `test_label_output.py`, `test_label_selection.py` | Membership edits, case choices, wildcard removal, selection, and partial failures |
| Account labels | `test_account_labels.py`, `test_list_label.py`, `test_label_counts.py`, `test_label_data.py` | Shared catalog reads, listing, counts, and label creation |
| Custom fields | `test_custom_fields.py`, `test_custom_field_add_pairs.py`, `test_custom_field_selection.py` | Exact additions, case-insensitive removal choices, partial selection, duplicate handling, and preservation |
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

## GitHub Actions

[Tests workflow](../.github/workflows/ci.yml) runs on pushes, pull requests, and manual dispatch.
An explicit `run-name` uses the commit message for pushes, the pull request title for PRs,
and `Tests on <branch or tag> (manual run)` for manual runs. The workflow itself remains `Tests`.
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

## CI routing

`scripts/ci_scope.py` permits lightweight checks when every changed file is root `README.md`,
root `CONTRIBUTING.md`, `tests/README.md`, or a `.md` file anywhere under `docs/`. New and nested
guides qualify without changing the classifier. Only the exact `tests/README.md` path is exempt
under `tests/`; fixtures and other Markdown there still require full checks. Other non-documentation
paths and mixed changes run full checks. `FULL_CHECK_DOCUMENTS` overrides these rules for explicit
automation-input exceptions; currently there are none. Keep fixtures and artifact-generation inputs outside
`docs/`, as described in [documentation paths](../CONTRIBUTING.md#documentation-paths).

Pushes compare the before/after commits across the entire push. Pull requests compare the merge
base with the PR head. Renames include both old and new paths. Manual runs, empty diffs, new
branches, and unavailable comparison history use full checks. Classification reads the event
file rather than interpolating event values into shell commands.

Documentation-only runs check local links and Markdown heading targets, including the tests README,
using Python's standard library, without uv setup, application dependencies, runtime tests, or
package builds. Other runs retain both OS/Python test jobs. `test_ci_scope.py` checks new/nested guides, mixed paths,
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

Detailed test contracts and historical evidence live in the [regression reference](regression-coverage.md).
Use its subsystem index rather than maintaining a second full list of regression topics here:

- [Contact input and importing](regression-coverage.md#contact-input-and-importing)
- [Duplication](regression-coverage.md#duplication)
- [Contact lookup and labels](regression-coverage.md#contact-lookup-and-labels)
- [Email and custom-field editing](regression-coverage.md#email-and-custom-field-editing)
- [Gmail sender searches](regression-coverage.md#gmail-sender-searches)
- [Presentation and interaction](regression-coverage.md#presentation-and-interaction)
- [Transport and diagnostics](regression-coverage.md#transport-and-diagnostics)

Record the tested behavior, fixture checks, evidence that the regression detects failure, and
limits of the result. Keep private logs outside Git. Historical suite counts are evidence for
that change, not a current coverage metric or a promise that live Google behavior is identical.
