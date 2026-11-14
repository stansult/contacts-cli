# contacts-cli

A command-line tool for creating and managing Google Contacts, including copying contacts and
collecting email senders from Gmail.

## Install and authorize

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). From a checkout:

```sh
uv sync --locked
./contacts-cli --help
```

Follow [Google setup](docs/google-setup.md) to create the Desktop OAuth client file and save it as
`~/.config/contacts-cli/credentials.json`. Then authorize your account:

```sh
./contacts-cli authorize
```

Later commands reuse the saved authorization. Local file validation needs no Google setup.

## Common usage

- Replace the example values below with your own. `--contact` accepts a Google Contacts URL such
  as `https://contacts.google.com/person/c123456789` or its bare ID, `c123456789`.
- Commands that change contacts show a preview and ask for confirmation. Enter or `n` at the
  final confirmation makes no changes. `--apply` skips that final confirmation; conflict choices
  follow each command's rules. Piped or redirected runs without `--apply` do not write.
- `add-contact` and `duplicate` create new contacts each time; they do not merge with existing ones.
- Use `./contacts-cli <command> --help` for command options. Global options, including `--token`,
  appear in `./contacts-cli --help` and work before or after the command.

## Add contacts

```sh
./contacts-cli add-contact --name 'Jane Doe' --email jane@example.com
./contacts-cli add-contact --file contacts.json --label Recruiter
```

Use inline options for a name and emails, or a JSON file for one or more contacts with additional
fields. Each new contact gets a **Created** custom field with its creation time.
See [contact input and creation](docs/contact-input.md).

## Duplicate a contact

```sh
./contacts-cli duplicate --contact c123456789 --name 'Delivery backup'
```

Copies editable fields and the custom photo, and adds a **Duplicate** custom field with the
creation time. Omit `--name` to keep the original name. See [duplication details](docs/command-reference.md#duplicate-a-contact).

## Sender-sync

```sh
./contacts-cli sender-sync --label 'Example/Delivery' --contact c123456789
```

Adds missing sender addresses from a Gmail label, excluding addresses already on the contact and
your Gmail sending addresses. Sender names become email labels when useful. Use `--exclude ADDRESS`
or `--exclude-file PATH` to skip other senders. See [search and exclusion details](docs/command-reference.md#sender-sync-preview-and-apply).

## List email addresses

```sh
./contacts-cli list-email --contact c123456789
```

Shows a numbered list with labels and duplicate references.

## Add or remove email addresses

```sh
./contacts-cli add-email --contact c123456789 --add 'person@example.com — Work'
./contacts-cli remove-email --contact c123456789 --remove person@example.com
```

Repeat the address option or use `--add-file` / `--remove-file` for lists. Removal deletes all
matching entries. Adding an existing address can change its label or consolidate duplicates;
see [email conflict and apply rules](docs/command-reference.md#add-email-and-remove-email).

## Add or remove labels

```sh
./contacts-cli add-label --contact c123456789 --label Recruiter
./contacts-cli remove-label --contact c123456789 --label Recruiter
```

Repeat `--label` for multiple labels. Addition creates missing labels; removal takes labels off
this contact without deleting the labels themselves. Case-only matches may require a choice,
even with `--apply`. See [label choices](docs/command-reference.md#label-choices-and-output).

## Add or remove custom fields

```sh
./contacts-cli add-custom-field --contact c123456789 --key 'Pipeline ID' --value P-001
./contacts-cli remove-custom-field --contact c123456789 --key 'Pipeline ID' --value P-001
./contacts-cli remove-custom-field --contact c123456789 --key Created
```

Keys and values match exactly, including case. Addition skips an existing pair and appends a new
value. Removal without `--value` removes every entry with that key.
See [custom field details](docs/command-reference.md#add-custom-field-and-remove-custom-field).

## Validate a contact file

```sh
./contacts-cli validate-contact --file contacts.json
```

Validates locally without authorization or Google access. See [validation details](docs/contact-input.md#validate-a-file-locally).

## More information

- [Command reference](docs/command-reference.md): options, matching, conflicts, limits, and exit codes.
- [Contact input](docs/contact-input.md): JSON fields, validation, and creation outcomes.
- [Google setup](docs/google-setup.md): credentials, permissions, and authorization troubleshooting.
- [API error logs](docs/error-logs.md): Google error responses saved locally for troubleshooting.
- [Local metrics](docs/metrics.md): sender-sync timing and API counts; `make metrics` summarizes runs.
- [Contributing](CONTRIBUTING.md) and [testing](docs/testing.md): development workflow and checks.
