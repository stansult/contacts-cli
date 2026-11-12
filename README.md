# contacts-cli

A local command-line tool to add Gmail senders to Google contacts and duplicate contacts.

## Install

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). From a checkout:

```sh
uv sync --locked
./contacts-cli --help
```

## Google setup

Configure Google API access once, then authorize the CLI in your browser:

1. [Create a Google Cloud project](https://console.cloud.google.com/projectcreate) and enable [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) and [Google People API](https://console.cloud.google.com/apis/library/people.googleapis.com).
2. Configure OAuth consent and add your account as a test user.
3. Download a Desktop app client file to `~/.config/contacts-cli/credentials.json`.
4. Run `./contacts-cli authorize` and complete browser sign-in.

Follow the [detailed Google setup instructions](docs/google-setup.md) for each step. Later runs reuse
saved authorization; missing or insufficient authorization offers browser setup.

## Sender-sync preview and apply

Add missing senders from a Gmail label to an existing contact:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact 'https://contacts.google.com/person/c123456789'
```

Review the additions, then answer `y` to **Apply these additions?** Existing addresses and other
contact details stay unchanged. Your configured Gmail sending addresses are excluded. Sender
display names become custom email labels. Run the same command again whenever you want to sync.

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

## Common options

- `--contact` accepts a Google Contacts URL or `people/c123456789`; lookup by name is not supported.
- Enter or `n` at a confirmation prompt makes no changes.
- Add `--apply` to either command to save without asking. Each run reads current data; each
  duplicate creates a new contact. Piped or redirected runs without `--apply` only preview.
- Use `./contacts-cli <command> --help` for all options.

## More information

- [Command reference](docs/command-reference.md): search logic, copied fields, output, limits, and exit codes.
- [Google setup](docs/google-setup.md): credentials, permissions, and authorization troubleshooting.
- [Local metrics](docs/metrics.md): timing and API counts; run `make metrics` for a summary.
- [Contributing](CONTRIBUTING.md) and [testing](docs/testing.md): development workflow and checks.
