# Testing overview

The suite checks that contacts-cli makes only approved changes, preserves existing information,
and reports failures accurately. It exercises command behavior with synthetic data, including
interactive choices, cancellation, duplicate handling, and verification after writes.

For setup, required checks, and live-test rules, use the [testing guide](../docs/testing.md).
For individual regression contracts and evidence, use the
[coverage reference](../docs/regression-coverage.md). This page is a map of the suite.

## Tools

| Tool | Role |
| --- | --- |
| Python and pytest | Test cases, shared fixtures, parametrized scenarios, and assertions |
| pytest-socket | Network sockets disabled by default in the pytest process |
| Google discovery clients | Real request construction against the synthetic HTTP transport |
| Ruff | Lint and formatting checks |
| uv and Hatchling | Locked environments, package builds, and clean-install verification |
| GitHub Actions | Linux/Python 3.11 and macOS/Python 3.13 checks |

No real Google credentials or accounts are used by automated tests. Dependencies may need network
access during installation. Tests of local networking explicitly use controlled local endpoints;
Google-facing paths remain offline. Child CLI processes have their own network/browser guard.

## Test layers

| Layer | What it establishes | Starting points |
| --- | --- | --- |
| Parsing and planning | Inputs produce the intended changes or useful validation errors | [test_core.py](test_core.py), [test_contact_inputs.py](test_contact_inputs.py) |
| CLI and interaction | Preview, selection, confirmation, and cancellation affect actual saved results | [test_email_selection.py](test_email_selection.py), [test_merge_conflicts.py](test_merge_conflicts.py) |
| API behavior | Request bodies, preservation, verification, pagination, and failures | [test_sync.py](test_sync.py), [test_fixture_contract.py](test_fixture_contract.py) |
| Installation and tooling | Installed CLI behavior, archive contents, documentation links, and CI routing | [test_installed_cli.py](test_installed_cli.py), [test_repository_checks.py](test_repository_checks.py), [test_ci_scope.py](test_ci_scope.py) |

Tests are organized by behavior rather than one test file per source module. Email, label, import,
and sender-search features have several focused files. The coverage reference provides a topic
index when a filename alone is not enough.

## How Google is simulated

[FakeGoogle](fake_google.py) is an in-memory HTTP transport used by the real Google discovery
clients. It stores synthetic contacts and messages and models selected Google response behavior.
[Shared fixtures](conftest.py) connect that transport to the application's API wrapper and isolate
local logs and metrics in temporary directories. Reusable input data lives in [fixtures](fixtures).

The fake replaces fields on PATCH rather than appending them. Tests can therefore detect an update
that accidentally drops existing data. Fixture-contract tests exercise the fake directly, without
the CLI, so a mistaken fixture cannot silently define the expected product behavior.

## Running checks

From the repository root, after installing Python 3.11+ and uv:

```sh
uv sync --locked
make check          # Full pytest suite, Ruff, and documentation checks
make check-package  # Fresh archives and tests of the installed CLI
make check-docs     # Local documentation links and heading targets
```

For a focused iteration, run a relevant file, for example:

```sh
uv run --locked pytest tests/test_email_selection.py
```

Focused checks do not replace the complete checks required before pushing code or tests.
The [testing guide](../docs/testing.md#ci-routing) explains the documentation-only exception.

## What passing tests mean

Assertions check saved state and absence of unintended writes, as well as output and exit status.
Regression tests are checked against unfixed behavior or a temporary controlled fault when
practical. Supporting fixture behavior is verified independently.

Passing offline tests does **not** prove live permissions, Google normalization, account
completeness, or real service latency. Live probes are separate, explicitly authorized work.
See the [external-call validation procedure](../docs/testing.md#new-external-call-validation)
before integrating a new Google operation.
