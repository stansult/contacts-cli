# contacts-cli

A local command-line tool for working with Google contacts.

The `sender-sync` command previews unique `From` addresses from every Gmail message
carrying one label, then optionally appends missing addresses to one existing Google contact. Existing emails,
custom email labels, and other contact details are retained. Addresses are never removed.

This is a local Python CLI. It has no hosted service or database. A temporary loopback
callback listener runs only during explicit OAuth setup.

## Install

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).
From a checkout:

```sh
uv sync --locked
./contacts-cli --help
```

The executable `./contacts-cli` launcher runs the CLI through uv with the locked
dependencies. It forwards all arguments and also works when invoked by its full path
from another directory. Relative file arguments are relative to your current directory.
The longer `uv run --locked contacts-cli` invocation still works from the checkout.

Alternatively, install into an existing virtual environment with `python -m pip install .`.
That provides the `contacts-cli` command, but does not use the repository's dependency lock.

## Commands

- `sender-sync`: preview or append missing Gmail label senders to an existing contact.
- `authorize`: explicitly set up Google OAuth credentials.

Use `./contacts-cli <command> --help` for command-specific options. A subcommand is
required; the former top-level sync flags and `--authorize` flag are no longer accepted.

## Google setup

1. Create or select your Google Cloud project and enable the **Gmail API** and **People API**.
2. Configure the OAuth consent screen for your own use. If the app is in Testing mode,
   add the intended Google account as a test user.
3. Create an OAuth client with application type **Desktop app**. Download its JSON file
   outside this repository at `~/.config/contacts-cli/credentials.json`.
4. Authorize explicitly:

   ```sh
   ./contacts-cli authorize
   ```

5. The command opens your default browser. Select the account that owns both the Gmail
   label and the contact. Complete authorization within five minutes, while the terminal
   command is running. The URL is also printed so you can open it manually if needed.

Use `--credentials /outside/git/client.json` to override the default client file.
Use `./contacts-cli authorize --no-browser` to print the URL without launching a browser.
The Desktop OAuth client file must already exist; the command does not create it.

The requested scopes are `gmail.metadata` and `contacts` (with Google's
`https://www.googleapis.com/auth/` prefix). Gmail access covers headers and labels, not
message bodies or mail changes. Contacts permission allows writes across the account;
Google does not offer a scope restricted to the selected contact. The CLI only calls
the contact update endpoint when `--apply` is present.

See Google's [desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app)
and [Gmail scope descriptions](https://developers.google.com/workspace/gmail/api/auth/scopes).

Tokens default to `~/.config/contacts-cli/token.json`. Use `--token /outside/git/token.json`
after the subcommand on both `authorize` and `sender-sync` commands to select another
token/account. A contact URL's
`/u/0/` or `/u/1/` segment does **not** select the API account; the token does.

Token writes are atomic, with owner-only file permissions on POSIX systems. The CLI
rejects client and token paths inside a Git worktree, including resolved symlinks.
Keep downloaded clients, tokens, and backups outside Git. Never paste their contents
into issues or logs. Repository ignore rules are an additional safeguard, not secret detection.

Ordinary runs refresh saved credentials without a browser. If the token file is missing,
`sender-sync` lists authorization options. In an interactive terminal it asks
`Authorize now in your browser? [y/N]`. Only `y` or `yes` starts authorization with the
default client file; on success the original command resumes, including `--apply` if
supplied. Declining or reaching end-of-input exits with code 1. Noninteractive runs
show the options and exit without prompting. A custom `--token` path is preserved
through authorization and in the suggested commands.

The default client file must already exist. For a different client file or manual
browser opening, use the listed standalone `authorize` commands and rerun sender-sync.
Invalid or revoked tokens still require explicit authorization; other errors do not
trigger the missing-token prompt. Google documents that external
apps in Testing mode generally receive refresh tokens valid for seven days with these
scopes; see [token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

## Preview and apply

Preview is the default:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact 'https://contacts.google.com/person/c123456789'
```

The contact may also be given as `people/c123456789`. Output identifies the contact and
label, counts scanned messages, unique senders and existing email entries, and lists additions.

After reviewing a preview, explicitly request a write:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact 'https://contacts.google.com/person/c123456789' \
  --apply
```

Each command scans current data; `--apply` is not approval of a frozen previous preview.
Reuse the same flags after changing a Gmail filter and applying it to matching messages.
There is no need to maintain an exclusion query or a filter ID. A run with no missing
addresses sends no contact update.

## Behavior and limits

- Labels must match by exact name. Every results page is read, including labeled Spam
  and Trash. Only individual messages carrying the label are considered; unrelated
  messages in the same conversation are excluded.
- `From` is the source, not `Reply-To`, `Sender`, or the envelope sender. Display names,
  comments, folded headers, and multiple valid mailboxes are parsed. Missing, duplicate,
  malformed, or unsupported headers are reported by message ID and block all writes.
  Raw headers are not printed. Internationalized local parts that the Python parser
  reports as defective are unsupported.
- Comparison ignores case and surrounding whitespace. Gmail dot variants and `+tags`
  remain distinct. New entries retain the first observed spelling and have no custom
  label. Existing values, labels, display names, and source-primary choices are retained.
- The People API is read directly using `getBatchGet`, with contact-only sources and
  an explicit field mask. Profile-only data is not copied. Multiple editable contact
  sources and incomplete/error responses are rejected. Full-list retrieval relies on
  Google's documented API contract; there is no independent count to detect silent
  server omissions.
- Only `emailAddresses` is updated. A fresh read and source etag protect against
  concurrent edits. Conflicts stop the run; they are not automatically merged or retried.
  The response and an independent subsequent read are checked for additions and preservation.
- Local guards reject projected contacts over 500 top-level field entries or 128 KiB
  of JSON, and new addresses over 1,024 characters are rejected by parsing. These are
  estimates, not Google's internal storage accounting; the server may reject a smaller
  contact. Existing oversized contacts can still be processed as no-ops.
- Gmail pagination is not an atomic mailbox snapshot. Messages arriving or being
  relabeled during a scan may require another run. A deleted message or observed loss
  of the selected label aborts the scan. Large labels take time: requests are sequential,
  with one metadata read per message, plus listing and contact requests.
- Read requests allow up to three retries. Updates are never automatically retried by
  the application. After an uncertain write or failed verification, inspect the contact
  and run a new preview before deciding whether another apply is needed. No rollback
  write is attempted.

Sources: [Gmail listing contract](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list),
[message metadata](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get),
[People email fields](https://developers.google.com/people/api/rest/v1/people#Person),
[contact update contract](https://developers.google.com/people/api/rest/v1/people/updateContact),
[Google Contacts limits](https://support.google.com/contacts/answer/148779?hl=en).

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Complete preview, verified update, successful authorization, or no-op |
| `1` | Input/data/API/setup error; no successful update reported |
| `2` | Invalid command-line arguments |
| `3` | Update may have occurred or was submitted, but was not verified |
| `130` | Interrupted; inspect a new preview if an update was in progress |

## Development

Run `make check` for all offline tests, lint, and format checks, and `make build` for
wheel and source archives. See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow rules
and [docs/testing.md](docs/testing.md) for test contracts and validation boundaries.
