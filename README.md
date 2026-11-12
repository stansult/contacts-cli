# contacts-cli

A local command-line tool for working with Google contacts.

The `sender-sync` command previews missing `From` addresses by searching Gmail messages carrying one
label, then optionally appends missing addresses to one existing Google contact. Existing emails,
custom email labels, and other contact details are retained. Addresses are never removed.

The `duplicate` command previews and creates a copy of a contact, with an optional replacement
name. It preserves the original and adds a Duplicate custom field identifying the script and
creation date/time.

This is a local Python CLI. It has no hosted service or database. A temporary loopback callback
listener runs only during explicit OAuth setup.

## Install

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). From a checkout:

```sh
uv sync --locked
./contacts-cli --help
```

The executable `./contacts-cli` launcher runs the CLI through uv with the locked dependencies. It
forwards all arguments and also works when invoked by its full path from another directory. Relative
file arguments are relative to your current directory. The longer `uv run --locked contacts-cli`
invocation still works from the checkout.

Alternatively, install into an existing virtual environment with `python -m pip install .`. That
provides the `contacts-cli` command, but does not use the repository's dependency lock.

## Commands

- [`sender-sync`](#sender-sync-preview-and-apply): preview or append missing Gmail label senders to an existing contact.
- [`duplicate`](#duplicate-a-contact): preview or create a new contact by copying an existing contact.
- `authorize`: explicitly set up Google OAuth credentials.

Use `./contacts-cli <command> --help` for command-specific options. A subcommand is required; the
former top-level sync flags and `--authorize` flag are no longer accepted.

Both previews identify the contact as `Contact: 'name: Jane' (people/c123456789)`. A nonblank
name takes precedence over the company. Without a name, they show
`Contact: 'company: Example Company' (people/c123456789)`; without either, they show
`Contact: 'Unnamed' (people/c123456789)`.

Both commands require terminal input, output, and error streams before asking for write
confirmation. Piped or redirected runs without `--apply` remain preview-only. End-of-input at the
prompt makes no changes. `--apply` skips write confirmation in both interactive and scripted runs.

## Google setup

Configure Google API access and authorize the CLI to use your account.

1. [Create a Google Cloud project](https://console.cloud.google.com/projectcreate) and enable [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) and [Google People API](https://console.cloud.google.com/apis/library/people.googleapis.com).
2. Configure OAuth consent and add your account as a test user.
3. Download a Desktop app client file to `~/.config/contacts-cli/credentials.json`.
4. Run `./contacts-cli authorize` and complete browser sign-in.

See [detailed Google setup instructions](docs/google-setup.md). Existing `gmail.metadata` authorizations need upgrading to
`gmail.readonly`; the CLI detects insufficient permissions and offers browser reauthorization.
See [upgrading an existing authorization](docs/google-setup.md#upgrading-an-existing-authorization).
The new permission permits reading message bodies, although this CLI continues to request only
headers and labels. Sender searches use the Gmail read-only permission.

## Sender-sync preview and apply

The command shows a preview first:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact 'https://contacts.google.com/person/c123456789'
```

The contact may also be given as `people/c123456789`. Output identifies the contact and label,
shows inspected-message and new-sender counts in progress, then existing email entries and additions.

The search excludes existing contact addresses and all configured Gmail “Send mail as” addresses,
including your primary address and aliases. It requests one matching message, reads its From
header, and excludes newly discovered addresses from the next search. It stops when no matching
messages remain. For many messages from a few senders, this avoids reading each message header.

Progress appears automatically on stderr: reading the contact, finding the label, then messages
inspected and new senders found. In a terminal, the scan counter updates in place at most once
per second; redirected output uses separate lines at most once every ten seconds. The contact and
label details appear immediately after their lookups, with blank lines separating sections. The
last counter update always appears, bypassing throttling, followed by `Search finished.` and the
existing-email count. Updates occur as requests finish; there is no estimated total or percentage. Invalid From
headers stop the search and block all writes.
The complete preview stays on stdout. Counts describe inspected messages, not the label’s total size.

Operational output begins with a local `[YYYY-MM-DD]` date line. Primary messages use local
`[HH:MM:SS]` timestamps, including stage messages, confirmation prompts, completion, and errors.
Contact/label details and addition-list entries remain unprefixed as continuation lines. Blank
separators and help remain undecorated. If the run crosses midnight, the ending date appears after
the last message. Updating sender counters have no timestamp and always show the final count.

In an interactive terminal, the preview is followed by `Apply these additions? [y/N]`.
Answer `y` or `yes` to save; Enter, `n`, or any other answer leaves the contact unchanged.
No prompt appears when there are no additions.

To save without the confirmation prompt, use `--apply`:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact 'https://contacts.google.com/person/c123456789' \
  --apply
```

Each command scans current data; `--apply` is not approval of a frozen previous preview. Reuse the
same flags after changing a Gmail filter and applying it to matching messages. There is no need to
maintain an exclusion query or a filter ID. A run with no missing addresses sends no contact update.

## Duplicate a contact

Preview a copy, optionally choosing a replacement name:

```sh
./contacts-cli duplicate \
  --contact 'https://contacts.google.com/person/c123456789' \
  --name 'Delivery backup'
```

In an interactive terminal, the preview is followed by `Create this duplicate? [y/N]`.
Answer `y` or `yes` to create it; Enter, `n`, or any other answer makes no changes.

Add `--apply` to create it without the confirmation prompt:

```sh
./contacts-cli duplicate \
  --contact 'https://contacts.google.com/person/c123456789' \
  --name 'Delivery backup' \
  --apply
```

Omit `--name` to keep the original name. A replacement replaces all name components and is stored
as the given name without guessing how to split it. Preview lists entry counts for each copied
field and whether a custom photo will be copied. Success prints the new contact's link, using
the person identifier returned by Google.

Each copy adds a **Duplicate** custom field, for example:
`Created by contacts-cli on November 11, 2026 at 2:30 PM (UTC−08:00)`.
The timestamp uses the computer's local time when that run prepares the copy, including its UTC
offset. Existing custom fields, including earlier Duplicate entries, are preserved. A separate
preview run does not fix the timestamp for a later `--apply` run.

The copy includes editable contact fields exposed by the People API: names, emails and custom
labels, phones, addresses, notes, dates, organizations, relationships, URLs, custom fields, and
other editable details, including file-as and skills. User contact groups, My Contacts, and Starred
memberships are retained. Unsupported system groups stop creation. Profile-only data, generated
IDs, timestamps, verification flags, and read-only domain memberships are not copied.

Custom photos are downloaded before creation and uploaded in a separate request afterward. Only
HTTPS Googleusercontent photo URLs are accepted, without redirects, with a 10 MiB local limit.
Default avatars are generated by Google. Verification confirms a custom photo exists; it does not
compare image bytes or guarantee the original upload resolution.

The source contact is never updated. A fresh source read catches changes before creation, but the
read and creation are not atomic. Each `--apply` creates another contact, even with identical flags.
Creation and photo writes are never automatically retried. If the result is uncertain or a photo
write fails, inspect Google Contacts before retrying. The error includes the new contact's link
when available; no automatic deletion or rollback is attempted.

An independent read verifies editable fields and primary choices after saving. Server
normalization can cause a conservative verification failure. The same local 500-entry and 128 KiB
limits apply. Existing authorization is reused; this command does not read Gmail messages.

Sources: [contact creation](https://developers.google.com/people/api/rest/v1/people/createContact), [editable Person fields](https://developers.google.com/people/api/rest/v1/people#Person), and [photo updates](https://developers.google.com/people/api/rest/v1/people/updateContactPhoto).

## Sender-sync behavior and limits

- Each sync reads Gmail's [Send mail as list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings.sendAs/list)
  once, using the existing `gmail.readonly` permission. No new authorization scope is needed.
  Retrieval errors, missing primary identity, or malformed addresses stop before searching or
  writing. Configured sending addresses are excluded from both searches and parsed candidates.
  Addresses already stored in the contact remain unchanged; this feature does not remove them.
- Labels must match by exact name. Searches include labeled Spam and Trash.
  Only individual messages carrying the label are considered; unrelated messages in the same
  conversation are excluded.
- `From` is the source, not `Reply-To`, `Sender`, or the envelope sender. Display names, comments,
  folded headers, and multiple valid mailboxes are parsed. Encountered missing, duplicate,
  malformed, or unsupported headers are reported by message ID and block all writes. Raw headers
  are not printed.
  Internationalized local parts that the Python parser reports as defective are unsupported.
- Comparison ignores case and surrounding whitespace. Gmail dot variants and `+tags` remain
  distinct. New entries retain the first observed spelling. The display name from the inspected
  From header becomes the new email's custom label, shown as `address@example.com — Display Name`.
  Without a display name, or when it matches the email address ignoring case and surrounding
  whitespace, the address is shown and saved without a custom label. The search does not
  fetch other messages to look for alternate names. Existing values, labels, display names, and
  source-primary choices are retained. Saved additions are checked for their proposed labels.
- The People API is read directly using `getBatchGet`, with contact-only sources and an explicit
  field mask. Profile-only data is not copied. Multiple editable contact sources and
  incomplete/error responses are rejected. Full-list retrieval relies on Google's documented API
  contract; there is no independent count to detect silent server omissions.
- Only `emailAddresses` is updated. A fresh read and source etag protect against concurrent edits.
  Conflicts stop the run; they are not automatically merged or retried. The response and an
  independent subsequent read are checked for additions and preservation.
- Local guards reject projected contacts over 500 top-level field entries or 128 KiB of JSON, and
  new addresses over 1,024 characters are rejected by parsing. These are estimates, not Google's
  internal storage accounting; the server may reject a smaller contact. Existing oversized contacts
  can still be processed as no-ops.
- Gmail search is not an atomic mailbox snapshot. Messages arriving or being relabeled during a
  search may require another run. A deleted message or observed loss of the selected label aborts
  the search. Repeated message IDs or results with no new sender also stop it before any write.
- Exclusions use quoted full addresses. Unsupported address syntax stops the run instead of being
  inserted into the search query. A local guard limits the URL-encoded query to 6,000 bytes; this
  is a conservative CLI limit, not a documented Google maximum. Exceeding it stops before writing.
  API errors also stop the run; partial discoveries are never applied after a search failure.
- This relies on Gmail's sender matching, rather than inspecting every header. Excluded messages
  are not checked for malformed headers or additional authors. The multiple-author case is deferred
  in [issue #4](https://github.com/stansult/contacts-cli/issues/4). Gmail matching of unusual addresses remains subject to live verification.
- Requests are sequential: normally one header read and one search per new sender, plus a final
  empty search and contact/label requests. When most messages have different senders, this can use
  more requests than the old full scan. Local metrics allow comparisons with the previous baseline.
- Read requests allow up to three retries. Updates are never automatically retried by the
  application. After an uncertain write or failed verification, inspect the contact and run a new
  preview before deciding whether another apply is needed. No rollback write is attempted.

Sources: [Gmail listing contract](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), [message metadata](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get), [People email fields](https://developers.google.com/people/api/rest/v1/people#Person),
[contact update contract](https://developers.google.com/people/api/rest/v1/people/updateContact), [Google Contacts limits](https://support.google.com/contacts/answer/148779?hl=en).

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Complete preview, verified write, successful authorization, or no-op |
| `1` | Input/data/API/setup error; no successful update reported |
| `2` | Invalid command-line arguments |
| `3` | Write may have occurred or was submitted, but was not verified |
| `130` | Interrupted; the message states whether a contact write had started |

## Development

Run `make check` for offline tests, lint, formatting, and local documentation links. Run
`make check-package` to build and inspect packages and test a clean wheel installation.
GitHub Actions runs both checks on Linux/Python 3.11 and macOS/Python 3.13 for pushes and pull requests.
`make build` creates wheel and source archives in `dist/`. See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow rules and [docs/testing.md](docs/testing.md) for test contracts
and validation boundaries.

## Run metrics

Sender sync records local timing, API counts, and scan totals in the ignored
`.contacts-cli/runs.jsonl`. Run `make metrics` to summarize runs. See [metric definitions and privacy](docs/metrics.md)
for recorded fields, interrupted runs, storage overrides, and comparison guidance.
