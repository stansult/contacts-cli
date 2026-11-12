# Contributing

## Project contract

[README.md](README.md) defines behavior. Verify relevant official API contracts before changing scopes,
pagination, field masks, limits, or contact update semantics. Keep user-facing documentation
synchronized with the implementation.

The code is split into pure parsing/planning (`core.py`), API calls (`api.py`), OAuth storage/setup
(`auth.py`), and command-line orchestration (`cli.py`). Keep contact mutation behind the explicit
apply path. Do not add live Google calls to the test suite.

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
dependencies change. Build output belongs in ignored `dist/`.

Before adding or changing tests, establish expected behavior from the README and API references.
Verify supporting fixtures independently. For important regression coverage, run the test against
the unfixed implementation or a narrow reversible fault, confirm the intended assertion fails,
restore the implementation, and confirm it passes. See [testing guidance](docs/testing.md). Diagnose unexpected
failures from actual inputs and outputs before changing assertions or product behavior.

Before committing, reread every edited file and review the complete diff, including new files. Use a
commit message covering all changes. Before pushing executable code, configuration, dependencies,
fixtures, or tests, run the complete checks above. Verify archives do not contain private context or
credentials.

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
test with an injected clock. Progress throttling uses monotonic time independently of the displayed wall clock.
