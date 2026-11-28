# Contributing

## Project contract

[README.md](README.md) covers usage; the [command reference](docs/command-reference.md) defines
command behavior. The [input format](docs/contact-input.md) defines accepted JSON, and the
[import guide](docs/importing-contacts.md) covers duplicate review, merging, and batch outcomes.
Verify relevant official API contracts before changing scopes,
pagination, field masks, limits, or contact update semantics. Keep user-facing documentation
synchronized with the implementation.

## Code structure

- `cli.py` defines arguments and routes commands; command modules handle creation, email edits,
  label edits, custom fields, and duplication.
- `core.py`, `address_inputs.py`, and `contact_inputs.py` provide shared parsing and validation.
- `api.py` handles Google requests, conflict protection, and shared update verification;
  `auth.py` handles OAuth setup and token storage.
- `contact_resolution.py` compiles reusable `ContactFilters` and evaluates AND matching without
  prompts or writes. `list-contact` owns filter spelling choices and result presentation.
  `resolve_single_contact` reuses complete-identifier matching before single-target command
  dispatch; `resolve_contacts` supplies multiple-target lookup for labeling, phone formatting,
  and field listings. `batch_lists.py` shares read-only iteration and outcomes for email, phone,
  and label lists; existing field renderers preserve their display and duplicate conventions.
  `load_batch_identifiers` combines repeatable inputs with shared file parsing. IDs bypass scans.
  Follow the [shared batch contract](docs/batch-contacts.md); it defines input ordering,
  selection, and failure handling.
  Command modules retain target reads, preview, write protection, and verification.
- `label_data.py` shares paginated label reads, membership validation, active-user filtering, and
  identity validation across listing, creation, and removal. Command modules own matching and
  presentation.
- `phone_edit.py` shares phone reads and verification; `phone_format.py` uses local
  `phonenumberslite` formatting and the shared guarded field-update path.
- `email_edit_ui.py` selects approved email changes, including individual duplicate removals.
- `web_emails.py` reads static webpages; `url_email_add.py` handles their email-addition flow.
  `selection.py` provides number/range parsing, direct all/number/cancel choices, and reusable review
  confirmation. Commands supply rows and wording, then map selected numbers to their write plans.
- `deadline.py`, `persistent_reader.py`, and `read_worker.py` bound reads and reuse a
  command-scoped process/connection; writes stay in the parent transport.
- `output.py` and `progress.py` provide shared presentation; `metrics.py` and `error_logs.py`
  record local diagnostics.

Keep mutations behind final confirmation or explicit apply. Do not add live Google calls to the
suite. The [email editing rationale](docs/email-editing-plan.md) records design decisions;
user-facing behavior belongs in the command reference.

## Validate new external calls before integration

Before adding a new external API operation to a normal command flow, verify it independently
against the real service using the intended credentials, scopes, client/transport, and request
shape. Documentation and passing offline tests do not establish live access, latency, or behavior.
This gate applies before enabling the call locally, not only before committing or releasing it.

Prepare a minimal isolated probe with a short finite timeout, one attempt, and diagnostics for
elapsed time, status or underlying exception. Obtain explicit authorization before running it
against an account, or let the user run it. A general feature-implementation approval does not
by itself authorize live account access. Writes require explicit approval and an agreed test target.
See the [external-call validation procedure](docs/testing.md#new-external-call-validation).

Do not make an unverified or failing operation a dependency of the existing command. Keep probe
and offline implementation work isolated until the live check succeeds. If validation cannot be
completed, explain the missing evidence and agree on how to proceed; do not silently replace it
with mocks or make the user's normal command the first live experiment.

Record the result and timing before integration, then choose timeout, retry, progress, and failure
behavior appropriate to the observed operation. Repeat the check when a material change to the
endpoint, scopes, transport, or request shape invalidates the existing evidence.

## Documentation paths

Keep ordinary user and contributor guides under `docs/`, including nested directories.
Documentation-only CI applies when every changed path is root `README.md`, root
`CONTRIBUTING.md`, `tests/README.md`, or a `.md` file under `docs/`. New guides under `docs/`
need no classifier update. The tests README is an orientation guide; other Markdown under
`tests/` remains subject to full checks because it may be fixture input.
Mixed changes and all other paths run full checks.

Markdown used as a test fixture, executable input, or artifact-generation source belongs outside
`docs/`. If a justified exception must remain there, add its exact path to
`FULL_CHECK_DOCUMENTS` in `scripts/ci_scope.py` and test that it triggers full checks. This rule
relies on this repository's documentation layout; it does not treat arbitrary Markdown as safe.

## Markdown formatting

Wrap prose at roughly 80–100 characters per line, excluding inline link URLs from the character
count. Preserve paragraph and list structure, code blocks, and tables.

## Checks

Use Python 3.11+ and uv:

```sh
uv sync --locked
make check
make build
make check-package
git diff --check
```

`make check` runs Ruff lint and formatting checks plus the complete pytest suite with network
sockets disabled, plus local documentation link checks. `make check-package` verifies fresh archives
and a clean wheel installation. `make format` formats Python files. Update `uv.lock` with `uv lock` when
dependencies change. `make build` creates wheel and source archives in ignored `dist/`.
GitHub Actions runs both checks on Linux/Python 3.11 and macOS/Python 3.13 for code or configuration
changes. Pushes and pull requests changing only ordinary documentation paths run local-link and
heading checks on Ubuntu without installing application dependencies. Manual runs use full checks.
See [CI routing](docs/testing.md#ci-routing) for classification and fallback rules.

Follow the [testing guide](docs/testing.md) for fixture contracts, regression sensitivity,
packaging, and live-check boundaries. Establish expected behavior from product documentation
and API contracts before changing tests. Independently verify supporting fixture contracts.

For an approved behavior change, identify and update affected tests alongside the implementation.
Assertions requiring the previous behavior may deliberately fail during regression verification
or surface later in the full suite. Correct clearly outdated assertions without another approval
request; preserve coverage and confirm required tests pass in the final state. Do not weaken
assertions merely to make tests pass.

An unexpected failure contradicts the approved behavior or has an unclear cause; discovering a
failure after editing does not by itself make it unexpected. Inspect actual inputs, configuration,
and output, then discuss unresolved behavior or scope questions before changing tests or product
code to resolve them. Expected regression failures and clearly outdated assertions do not require
that pause. Existing scope, time-estimate, and external-action approval requirements still apply.

Before committing, reread every edited file and review the complete diff, including new files. Use a
commit message covering all changes. Before pushing executable code, configuration, dependencies,
fixtures, or tests, run the complete checks above. Verify archives do not contain private context or
credentials.

## Review, formatting, and push scope

- Finish review and required checks before committing. Inspect each result before the next action;
  do not put checks, commit, and push in a shell sequence that continues after a failed check.
- Classify findings by their actual effect. Failed product tests, broken links, invalid syntax,
  and formatting that changes meaning or rendering block the commit. A harmless trailing blank
  line in a Markdown document is a non-blocking cosmetic notice, even when `git diff --check`
  returns a nonzero exit code. Inspect the diagnostic rather than treating that exit code alone
  as a product failure. Do not suppress other failures to bypass a cosmetic notice.
- Include small formatting corrections introduced by the current edits in the same change when
  convenient. Leave unrelated cosmetic issues alone unless they affect readability or meaning.
- After a push, defer purely cosmetic findings to the next substantive change. Do not create a
  separate commit or push solely to remove a harmless blank line, rewrap prose, or make a similar
  cosmetic correction unless the user explicitly requests that cleanup.
- A request to “commit and sync” authorizes committing and pushing the reviewed changes. It does
  not authorize subsequent cleanup pushes. A tool finding does not expand that authorization.
- For ordinary Markdown-only changes, review the full diff and rendered wording, confirm that
  every changed file is Markdown, verify local links, and inspect whitespace diagnostics. Full
  runtime suites are unnecessary unless the Markdown drives automation or artifact generation.

## Privacy and external actions

This repository is public. If proposed content may expose private information, flag the specific
concern and remind the contributor that it would be public before publishing it.

Keep `HANDOFF.md`, account-specific continuity, tokens, OAuth clients, and generated previews out of
Git and distribution archives. Use synthetic `example.com` fixture data. Credentials and tokens must
live outside the checkout. Do not force-add ignored files.

Building/testing the CLI does not authorize live account reads, OAuth consent, contact updates, or
publication. Obtain explicit authorization for those actions when working as an assistant. For
browser assistance, use only the user-designated browser instance.

## Bugs and delivery

Use [GitHub Issues](https://github.com/stansult/contacts-cli/issues) as the bug tracker. Record expected versus observed behavior, synthetic
reproduction steps, affected version or commit, user-impact severity, and relevant test evidence.
Never include private mail or contact data. Link regression tests, fix commits, and user-facing
changelog notes when applicable. Record invalid, duplicate, or expected-behavior resolutions
explicitly.

Distinguish a local implementation, a pushed commit, a published artifact, and verified live
behavior. Release bugs remain open until the corrected release is available and its relevant
behavior has been verified. This repository currently has no automated deployment or package
publication workflow.

## Operational timestamps

Keep the shared convention used by the screenshots and pdf-slim projects: local `[YYYY-MM-DD]`
before the first operational message, local `[HH:MM:SS]` on primary messages, and an ending date
only when the run crosses midnight. Leave updating sender counters, continuation lines, blank
separators, and help undecorated. Use `output.py` for date state shared across stdout/stderr and
test with an injected clock. `StageProgress` in `progress.py` owns animation, timing, rendering,
and updater cleanup; adapters supply stage names, optional details/counters, timestamp preference,
and completion text. Keep Gmail/contact logic out of that helper. Central constants define elapsed
display after 5 seconds and completion duration at 10 seconds. Use monotonic timing and fixed start
timestamps; stop the updater before prompts/output and on success, failure, or interruption.
Animate only interactive stderr. Preserve plain redirected output and final counts.
