# contacts-cli

A local command-line tool to sync Gmail senders, add or remove contact emails, and duplicate contacts.

## Install

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). From a checkout:

```sh
uv sync --locked
./contacts-cli --help
```

## Add contacts

`./contacts-cli add-contact --name 'Jane Doe' --email 'jane@example.com'` previews a new contact
and asks before creating it. Use `--file contacts.json` for one or more Google Person objects,
`--label Recruiter` to apply an exact, case-sensitive contact label (created if missing), and `--apply` to skip final confirmation.
Case-only label collisions offer a choice interactively, even with `--apply`; noninteractive runs
stop and show the existing spelling.
Each new contact gets a **Created** custom field recording the CLI and creation time.
See the [input format and creation details](docs/contact-input.md).

## Duplicate a contact

Create a copy, optionally giving it a different name:

```sh
./contacts-cli duplicate \
  --contact 'https://contacts.google.com/person/c123456789' \
  --name 'Delivery backup'
```

Review the preview, then answer `y` to **Create this duplicate?** Omit `--name` to keep the original
name. The copy includes editable fields and the custom photo, plus a **Duplicate** field with its
creation date/time. The original stays unchanged; success prints the new contact's link.

## Sender-sync preview and apply

Add missing senders from a Gmail label to an existing contact:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact 'https://contacts.google.com/person/c123456789'
```

Review the additions, then answer `y` to **Apply these additions?** Existing addresses and other
contact details stay unchanged. Your configured Gmail sending addresses are excluded. Sender
display names become custom email labels unless they match the email address, contact name, or
company. Run the same command again whenever you want to sync.

To skip specific senders for this run, add `--exclude 'ignore@example.com'`. Repeat the option for
more addresses: `--exclude 'ignore@example.com' --exclude 'another@example.com'`.
You can also use `--exclude-file './excluded.txt'`, containing one address per line. Repeat either
option or combine them. Blank lines and `#` comments are ignored; pasted `address — Display Name`
lines work too. Existing contact entries are never removed.

## List email addresses

```sh
./contacts-cli list-email --contact 'c123456789'
```

Shows existing entries with a total, numbered rows, labels, and duplicate references.

## Add or remove email addresses

```sh
./contacts-cli add-email --contact 'c123456789' \
  --add 'person@example.com — Work' --add-file './addresses.txt'

./contacts-cli remove-email --contact 'c123456789' \
  --remove 'person@example.com' --remove-file './addresses.txt'
```

Repeat or combine individual and file options. Both commands preview changes and ask before
saving. A bare address means no label when adding. Conflicting existing labels or duplicate
entries offer Replace / Keep / Replace all / Keep all; replacement leaves one matching entry.
Removal deletes every matching entry, keeping the contact itself.

`--apply` skips confirmation but preserves conflicting existing entries. For `add-email`, combine
it with `--replace-existing` to approve label replacements/removals and duplicate consolidation.
Conflicting labels in the input are errors. See [email editing details](docs/command-reference.md#add-email-and-remove-email).

## Add labels

```sh
./contacts-cli add-label --contact c123456789 --label Recruiter
```

Repeat `--label` for multiple labels. Existing labels are preserved; already applied labels are
skipped. Missing labels are created after confirmation. Case-only matches offer the same choices
as `add-contact`. Use `--apply` to skip final confirmation. See [label details](docs/command-reference.md#add-label).

## Remove labels

```sh
./contacts-cli remove-label --contact c123456789 --label Recruiter
```

Removes labels from this contact, preserving the labels themselves and other contact information.
Repeat `--label` for multiple removals. Missing or unapplied labels are skipped. Preview and
confirmation work like `add-label`. See [removal details](docs/command-reference.md#remove-label).

## Add or remove custom fields

```sh
./contacts-cli add-custom-field --contact c123456789 --key 'Pipeline ID' --value P-001
./contacts-cli remove-custom-field --contact c123456789 --key 'Pipeline ID' --value P-001
./contacts-cli remove-custom-field --contact c123456789 --key Created
```

Keys and values match exactly, including case. Adding an existing pair does nothing; a different
value is appended. Removal without `--value` removes every entry with that key. Review the
numbered preview and confirm, or use `--apply`. See [custom field details](docs/command-reference.md#add-custom-field-and-remove-custom-field).

## Validate a contact file

Check a file locally with `./contacts-cli validate-contact --file contacts.json`; no authorization
is needed. See [local validation](docs/contact-input.md#validate-a-file-locally).

## Google setup

Configure Google API access once, then authorize the CLI in your browser:

1. [Create a Google Cloud project](https://console.cloud.google.com/projectcreate) and enable [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) and [Google People API](https://console.cloud.google.com/apis/library/people.googleapis.com).
2. Configure OAuth consent and add your account as a test user.
3. Download a Desktop app client file to `~/.config/contacts-cli/credentials.json`.
4. Run `./contacts-cli authorize` and complete browser sign-in.

Follow the [detailed Google setup instructions](docs/google-setup.md) for each step. Later runs reuse
saved authorization; missing or insufficient authorization offers browser setup.

## Common options

- `--contact` accepts a Google Contacts URL or a bare ID such as `c123456789`;
  lookup by name is not supported.
- Enter or `n` at a confirmation prompt makes no changes.
- Add `--apply` to a command that makes changes to save without asking. Each run reads current data; each
  duplicate creates a new contact. Piped or redirected runs without `--apply` only preview.
- Use `./contacts-cli --help` for global options (`--token`), accepted
  before or after the command. Use `./contacts-cli <command> --help` for command options.

## More information

- [Command reference](docs/command-reference.md): search logic, copied fields, output, limits, and exit codes.
- [Google setup](docs/google-setup.md): credentials, permissions, and authorization troubleshooting.
- [API error logs](docs/error-logs.md): full Google error responses saved locally for troubleshooting.
- [Local metrics](docs/metrics.md): timing and API counts; run `make metrics` for a summary.
- [Contributing](CONTRIBUTING.md) and [testing](docs/testing.md): development workflow and checks.
