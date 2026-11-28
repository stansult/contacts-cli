# contacts-cli

A command-line tool for creating and managing Google Contacts, including copying contacts and
collecting email addresses from Gmail senders or webpages.

## Install and authorize

Requires macOS or Linux, Python 3.11 or newer, and [uv](https://docs.astral.sh/uv/). From a checkout:

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
  Contact lookup also accepts a full name, email, or complete phone number through
  `--contact`. Multiple matches require selection; partial lookup remains in `list-contact`.
  See [contact identifiers](docs/command-reference.md#contact-identifiers).
- Commands that change contacts or labels show a preview and ask for confirmation. With multiple
  choices, contact creation, sender-sync, email edits, custom-field edits, and label removal offer
  selection by number/range. Ranges include displayed items within their bounds, skipping gaps;
  endpoints need not be displayed. Explicit numbers must be available. Enter or `n` at the subsequent
  confirmation returns to selection; `q` cancels. A simple `[y/N]` prompt writes only after `y` or `yes`.
- `--apply` selects all eligible items and skips final confirmation; conflict choices follow each
  command's rules. Piped or redirected runs without `--apply` do not write.
- `add-contact` checks for possible duplicates before creation; `duplicate` intentionally creates
  a copy. During `add-contact` duplicate review, merge can add information to a chosen match.
- Use `./contacts-cli <command> --help` for command options. Global options, including `--token`,
  appear in `./contacts-cli --help` and work before or after the command.

## Find contacts

```sh
./contacts-cli list-contact --search 'Jane'
./contacts-cli list-contact --search 'Jane Doe' --exact
./contacts-cli list-contact --search 'jane@example.com'
./contacts-cli list-contact --search '2025550142'
./contacts-cli list-contact --name 'Jane' --company 'Example' --label Recruiter
```

Shows all matches with names, IDs, companies, emails, and phones. Names contain the search text,
ignoring case and extra spaces. Phones match numbers ending in the supplied digits, ignoring
formatting. Use `--exact` for a complete name or phone number, including its country code.
Emails match completely; IDs and Google Contacts URLs also work. For explicit fields, use
`--name`, `--email`, `--phone`, `--company`, or `--label`. Different filters combine with AND.
Company matching is partial unless `--exact` is supplied; labels match complete names, with a
choice for case differences. `--search` can combine with company and label filters, but not with
name, email, or phone filters. Generic search does not search company fields.
No contact selection or changes. See [matching rules](docs/command-reference.md#list-contact).

## Add contacts

```sh
./contacts-cli add-contact --name 'Jane Doe' --email jane@example.com
./contacts-cli add-contact --file contacts.json --label Recruiter
```

Use `--name` for a full name that Google parses, or `--first-name` and `--last-name` for explicit
components (together or individually). Combine either form with emails, or use a JSON file for
one or more contacts with additional fields. For multiple contacts, choose `all` or numbers/ranges such as `2,4-6`, then confirm.
Single-part names alone do not trigger duplicate suggestions; matching emails or phones still do.
When only contact labels are missing, review compact groups by label and select contacts by number.
Possible duplicates require interactive skip/merge/create-separately/cancel review, including with
`--apply`. A default-Yes prompt can skip selected inputs whose saved matches all contain the
supplied information and labels. Merge can add information or labels and resolve conflicts with Keep, Replace, or Keep both where supported. See [matching rules](docs/importing-contacts.md#possible-duplicates).
Similar email-label-only changes can be reviewed together, with bulk Replace/Keep or selection
by number. Conflict-free matches also offer grouped Merge/Skip with each target and its additions
shown. Other differences retain individual review.
Batch imports continue after contact-specific failures and report them at the end; account or
connection problems stop the batch. Any failure returns a nonzero exit status.
See [contact input and creation](docs/contact-input.md).

## Duplicate a contact

```sh
./contacts-cli duplicate --contact c123456789 --name 'Delivery backup'
```

Copies editable fields and the custom photo. Omitted options keep the original fields.
Use `--name`, repeatable `--email`, or repeatable `--phone` to replace a field, or `--clear-name`, `--clear-email`, and `--clear-phone`
to leave it empty. `--no-photo` skips the photo. The source contact stays unchanged.

```sh
./contacts-cli duplicate --contact c123456789 --name 'Jane Doe' \
  --email jane@example.com --clear-phone --no-photo
```

`--name` supplies a full name for Google to parse. Use `--first-name` and/or `--last-name` instead
for explicit components. Either form replaces the entire original name; omitted components are
empty. Replacement emails and phones replace the entire original list and have no labels.
See [duplication details](docs/command-reference.md#duplicate-a-contact).

## Sender-sync

Adds missing sender addresses from a Gmail label or search, excluding addresses already on the
contact and your Gmail sending addresses. Sender names become email labels when useful.

```sh
./contacts-cli sender-sync --label 'Example/Delivery' --contact c123456789
```

Use either `--label` or `--search`:

```sh
./contacts-cli sender-sync --search 'from:example.com after:2026/01/01' --contact c123456789
```

Case-only Gmail label matches prompt for a choice in interactive runs. A label can contain
messages from unrelated senders; use `--exclude` or `--exclude-file` to skip their addresses.
With `--search 'from:dhl.com OR subject:dhl'`, the preview separates addresses matching `dhl.com`
from other senders. You can choose to skip those other senders, or use `--exclude-other` to skip
them automatically. You can then choose all remaining addresses or some by number.
`--apply` alone includes both groups without selection. See [address selection rules](docs/command-reference.md#grouping-additions-by-address-criteria).

Use `--exclude ADDRESS` or a quoted pattern such as `--exclude '*@example.com'` to skip senders.
`*` matches zero or more characters, ignoring case. `--exclude-file PATH` accepts one address or
pattern per line, without shell quotes. Wildcards filter discovered senders locally. See [search and exclusion details](docs/command-reference.md#sender-sync-preview-and-apply).

Malformed `From` headers are skipped with a warning and local diagnostic log; valid senders
can still be added. `Reply-To` addresses are not collected.

## List email addresses

`list-email`, `list-phone`, and contact-specific `list-label` accept repeated `--contact`,
optionally combined with `--contact-file contacts.txt`. Results are grouped by contact; unmatched
inputs are skipped. These commands only read data. See the [batch listing rules](docs/batch-contacts.md#read-only-field-listings).

```sh
./contacts-cli list-email --contact c123456789
```

Shows a numbered list with labels and duplicate references.

## Add or remove email addresses

```sh
./contacts-cli add-email --contact c123456789 --add 'person@example.com - Work'
./contacts-cli remove-email --contact c123456789 --remove person@example.com
```

Repeat the address option or use `--add-file` / `--remove-file` for lists. Removal also accepts
`*` patterns: `--remove '*@example.com'`. `*` matches zero or more characters, ignoring case;
quote patterns in the shell, but not in files. Removal lets you select individual
matching entries. Adding an existing address can change its label or consolidate duplicates.
Select all proposed changes or specific numbers/ranges before confirming. Each removal number
selects one stored entry, so you can remove just one duplicate. `--apply` removes all matches.

To remove only extra copies of repeated addresses:

```sh
./contacts-cli remove-email --contact c123456789 --duplicates
```

This keeps the primary entry for each address, or the first stored entry when none is primary.
Review the extra entries and select which to remove; differing labels still count as duplicates.
Unique addresses remain unchanged. `--apply` removes all proposed extra entries.

For a webpage, use `--from-url` instead of address/file options:

```sh
./contacts-cli add-email --contact c123456789 --from-url 'https://example.com/contact'
```

Enter `all` or numbers/ranges such as `3-5,8`, then confirm. New addresses have
no labels; existing addresses and labels stay unchanged. `--apply` adds all new addresses.
See [webpage input](docs/command-reference.md#webpage-email-input) and
[email conflict and apply rules](docs/command-reference.md#add-email-and-remove-email).

## List phones or remove duplicate entries

```sh
./contacts-cli list-phone --contact c123456789
./contacts-cli remove-phone --contact c123456789 --duplicates
```

Listing shows labels, primary status, and duplicate references. Duplicate removal keeps the
primary entry for each repeated number, or the first stored entry when none is primary.
It offers the extra entries for individual selection before confirmation. `--apply` removes
all proposed extras. Different labels still count as duplicates, so review which entry is kept.
Matching ignores formatting and uses Google's canonical number when available; different
extensions stay separate, and no country code is guessed. Unique and unparseable numbers remain
unchanged. See [phone details](docs/command-reference.md#list-phone-and-remove-phone).

## Format phone numbers

```sh
./contacts-cli format-phone --contact c123456789 --contact 'Jane Example'
./contacts-cli format-phone --contact-file contacts.txt
```

Repeat `--contact`, use a file with one identifier per line, or combine both. Overlapping inputs
process each contact once. The preview shows readable international formatting, such as
`+1 202-555-0142 ext. 42`. Select entries across contacts and confirm once, or use `--apply`
for all proposed changes. Labels and duplicates
stay intact. Missing contacts are skipped; ambiguous matches require selection.
Numbers without a known country code remain unchanged.
See [formatting rules](docs/command-reference.md#format-phone).

## List, add, or remove labels

```sh
./contacts-cli list-label
./contacts-cli add-label --label Recruiter
./contacts-cli list-label --contact c123456789
./contacts-cli add-label --contact jane@example.com --label Recruiter
./contacts-cli add-label --contact-file contacts.txt --label Recruiter
./contacts-cli remove-label --contact c123456789 --label Recruiter
```

`list-label` lists all account user labels with their contact counts. With contact inputs, it lists
only those contacts’ labels, without counts.

`add-label` accepts a contact URL, ID, full name, email, or phone with repeatable `--contact`,
optionally combined with a `--contact-file` containing one identifier per line. Multiple matches
offer a choice (`s` skips that identifier; `q` cancels the command); batches
support selection by number or range before confirmation. Unmatched identifiers are reported and
skipped. Phone lookup ignores formatting and a leading `+`, but requires all base-number digits.
Omit the extension to find all contacts with that base number; supply one to match it exactly.
After approval, missing labels are created before contacts are updated. Contact-specific failures
continue; shared or uncertain failures stop. See the [batch rules](docs/batch-contacts.md).
With neither contact option, it creates account labels. Case-only matches may require a choice
even with `--apply`.
Repeat `--label` for multiple labels when adding or removing.

`remove-label` requires a contact and offers only labels attached to it. It accepts names or
quoted `*` patterns such as `--label 'Recruit*'`, including case variants. Choose all or numbered
labels before confirming; `--apply` removes all matches. Removal detaches labels from this contact;
the labels themselves remain available in the account.
See [label choices](docs/command-reference.md#label-choices-and-output).

## Add or remove custom fields

```sh
./contacts-cli add-custom-field --contact c123456789 --field 'Pipeline ID' P-001
./contacts-cli remove-custom-field --contact c123456789 --key 'Pipeline ID' --value P-001
./contacts-cli remove-custom-field --contact c123456789 --key Created
```

Repeat `--field KEY VALUE` to add multiple pairs; quote text containing spaces. Addition matches
exactly, skips existing pairs, and offers selection when several new pairs are proposed.
Removal offers exact and case-different matches in separate selectable groups. Without `--value`,
it offers all values under the key and its case variants. Choose `all` or numbers/ranges
before confirming; identical key/value duplicates stay together. `--apply` removes all matches,
including case variants.
See [custom field details](docs/command-reference.md#add-custom-field-and-remove-custom-field).

## Validate a contact file

```sh
./contacts-cli validate-contact --file contacts.json
```

Validates locally without authorization or Google access. See [validation details](docs/contact-input.md#validate-a-file-locally).

## Testing

Tests use **pytest** with synthetic Google API responses, covering previews, selected changes,
verification, and failure handling. Automated Google-facing tests use no real accounts or credentials.
**pytest-socket** blocks network access by default; **Ruff** checks Python style and formatting.
Packaging checks also build and test a clean installation. GitHub Actions runs full checks on
Linux/Python 3.11 and macOS/Python 3.13; ordinary documentation changes use lightweight checks.

Start with the [testing overview](tests/README.md) for the suite's structure and tools.
See the [testing guide](docs/testing.md) for commands and contributor procedures, or
[regression evidence](docs/regression-coverage.md) for specific tested behavior and limitations.

## More information

- [Command reference](docs/command-reference.md): options, matching, conflicts, limits, and exit codes.
- [Contact input](docs/contact-input.md): JSON format, supported fields, and validation.
- [Importing contacts](docs/importing-contacts.md): duplicate review, merging, labels, and partial failures.
- [Google setup](docs/google-setup.md): credentials, permissions, and authorization troubleshooting.
- [Diagnostic logs](docs/error-logs.md): API errors, email-verification failures, and sender-sync traces.
- [Local metrics](docs/metrics.md): sender-sync timing and API counts; `make metrics` summarizes runs.
- [Contributing](CONTRIBUTING.md) and [testing](docs/testing.md): development workflow and checks.
