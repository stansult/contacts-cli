# Testing and verification

## Sources of truth

The [README](../README.md) defines the product contract. API-specific expectations come
from Google's [Gmail list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list),
[Gmail metadata](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get),
[People batch retrieval](https://developers.google.com/people/api/rest/v1/people/getBatchGet),
and [contact update](https://developers.google.com/people/api/rest/v1/people/updateContact)
documentation. The client library's bundled discovery schemas validate request construction.

## Suite

`make check` is the complete local entry point. Pytest disables network sockets globally;
tests must never use real credentials or Google accounts.

| Tests | Contract |
| --- | --- |
| `test_fixture_contract.py` | Fixture filtering, pagination, read masks, replacement semantics, etags, and full email lists |
| `test_core.py` | Parsing, deduplication, identifiers, preservation, limits, and saved-state verification |
| `test_sync.py` | CLI preview/apply, real Google client request construction, multiple pages, conflicts, error outcomes, and reruns |
| `test_cli.py` | Subcommand routing, required options, rejected legacy/mixed options, token forwarding, and authorization defaults |
| `test_auth.py` | Explicit OAuth setup, browser opt-out, token paths/permissions, refresh, and denied consent |

Synthetic contact and message inputs live in [tests/fixtures](../tests/fixtures).
[FakeGoogle](../tests/fake_google.py) is an in-memory HTTP transport used with real
Google discovery clients. It replaces fields on PATCH rather than appending them, so a
destructive request body cannot accidentally pass a preservation test. Fixture contract
tests call that transport directly, without contacts-cli's orchestration.

Choose intentional fixture variations rather than a Cartesian product of every option.
The fake models selected contracts only. It cannot prove real permissions, server
storage limits, Google normalization, consent setup, or actual account completeness.

## Regression sensitivity

For meaningful behavior changes, first run a regression against unfixed code when
practical. Otherwise introduce one temporary fault at a time and run the targeted test:

| Temporary fault | Expected detection |
| --- | --- |
| Bypass the CLI apply switch | Preview test detects a contact write |
| Stop after the first message page | Preview count and additions are incomplete |
| Drop existing emails from the update body | Preservation assertion fails |
| Supply the wrong source etag | Update is rejected; successful-apply assertion fails |
| Skip verification of added emails | Lost-additions scenario incorrectly reports success |

Restore each fault immediately, preferably with `try/finally`, and rerun the correct
implementation. Never retain faulty source or commit temporary mutation artifacts.

Additional regression cases cover oversized-contact no-ops, malformed URL errors, and
invalid JSON after a write. These should distinguish a no-op, a pre-write failure, and
an uncertain outcome rather than silently treating them as equivalent.

The transport regression uses the real authorized HTTP wrapper with synthetic credentials
and HTTP responses. It verifies that a 401 does not cause a second write request after
refresh. Setting `execute(num_retries=0)` alone does not disable that separate retry layer.

## Packaging and live checks

`make build` creates the wheel and source archive. Inspect both archive listings to
confirm that they contain only intended package/project files. Private handoffs, tokens,
OAuth clients, local configuration, caches, and environments must be absent.

Live checks are separate and require explicit authorization. A future read-only check
should compare the complete preview with the Gmail label and contact UI in the authorized
account, without applying. A live write needs its own approval; verify additions,
existing custom labels and other contact data afterward, then confirm the next preview
has no additions. Record evidence locally without publishing personal data.
