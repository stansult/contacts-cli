# New-contact input

`add-contact` validates all input, previews every supplied field, and asks once before creating
contacts and any missing labels. Use `--apply` to skip confirmation. Noninteractive runs without
`--apply` preview only. Each contact is created sequentially and independently read back to verify
its supplied values; generated properties and entry reordering are allowed.

## Validate a file locally

```sh
./contacts-cli validate-contact --file contacts.json
```

This file-only command uses the same structure and data validation as `add-contact`. It requires
no authorization, makes no Google requests, and never prompts. Success reports the valid contact
count; errors identify the file or contact and field. Exit codes are 0 for valid input, 1 for file
or validation errors, and 2 for invalid command arguments. It does not check label existence or
guarantee Google will accept the contacts. `add-contact` validates again before proceeding.

## Inline or file input

```sh
./contacts-cli add-contact --name 'Jane Doe' --email 'jane@example.com'
./contacts-cli add-contact --file contacts.json --label Recruiter
```

Inline input requires a name or an email. Repeat `--email` to attach more addresses to the same
contact. `--name` is stored as Google's `unstructuredName`; the CLI does not guess how to split it.
Use a file for structured names or additional fields. Do not combine `--file` with either inline
option. Repeat `--label` to apply contact labels to every input contact. Label text must be nonblank.
Names match exactly, including case; repeated identical names are deduplicated. With no exact match,
a case-only collision offers each existing label, Create new, or Cancel. Enter selects the first
existing label. Invalid answers repeat the prompt; end-of-input cancels. The final preview shows
the selected spelling. Choosing an existing label does not rename it.

These choices require terminal input, output, and error streams. Noninteractive runs stop on a
case-only collision and show the exact existing spellings to use with `--label`. `--apply` skips
only final write confirmation; it still prompts for a label choice interactively and stops on a
collision noninteractively. There is no extra flag to bypass this choice.

Existing user labels are reused, and missing labels appear under Labels to create. Ambiguous or
system labels are rejected. Resolving a label choice makes no changes. Labels and contacts are
created only after final confirmation, or with `--apply`.


The UTF-8 JSON file contains one Google Person object or a nonempty array of Person objects.
There is no wrapper object and no custom version field. For example:

```json
[
  {
    "names": [{"givenName": "Jane", "familyName": "Doe"}],
    "emailAddresses": [{"value": "jane@example.com", "type": "work"}],
    "urls": [{"value": "https://example.com/jane", "type": "LinkedIn"}],
    "userDefined": [
      {"key": "Pipeline ID", "value": "P-001"},
      {"key": "Pipeline ID", "value": "P-002"}
    ]
  }
]
```

## Supported fields

| Field | Contents and requirements |
| --- | --- |
| `names` | One structured or unstructured name; at least a given, family, middle, or unstructured name |
| `emailAddresses` | Email `value`, optional `type` and `displayName`; existing email syntax validation |
| `phoneNumbers` | Phone `value` and optional `type`; digits and common punctuation, optional leading `+` and extension |
| `organizations` | Company `name`, title, department, and other writable Organization properties; at least name, title, or department per entry |
| `addresses` | Full or partial addresses; at least one component; `countryCode` uses two uppercase letters |
| `urls` | HTTP or HTTPS `value` with a host, optional custom `type` such as LinkedIn |
| `userDefined` | Nonblank `key` and `value`; repeated keys supported |
| `biographies` | One explicit Notes `value`, optional API `contentType` |
| `birthdays` | One structured `date`; deprecated free-form `text` is rejected |
| `events` | Structured `date` and optional `type` |
| `nicknames` | Nonblank `value` and optional API-defined `type` |

A nickname usually needs only `{"value": "J"}`. When `type: "DEFAULT"` is explicitly supplied,
verification also accepts Google omitting that generic type. Nickname values and explicitly
different types must still match.

Every field is an array, even singleton fields. Every contact needs at least a name, email, phone,
or organization with a company name. `add-contact` appends a custom field labeled **Created**:
`Created by contacts-cli on November 14, 2026 at 1:30 AM (UTC−08:00)`. Its timestamp is generated
immediately before each contact's creation request, using local time, and the field is verified
with the other saved values. The preview shows that it will be added. Supplied custom fields,
including an existing Created field, are preserved. The input file is unchanged; `validate-contact`
only validates input and adds nothing. No Notes are added. Other omitted fields stay absent.
Empty arrays are allowed, but empty entries, blank supplied text, unknown properties,
and generated fields such as `resourceName`, `etag`, `metadata`, and `formattedType` are rejected.
Use `--label` instead of raw `memberships`.

Nested properties and enums are checked against the bundled Google People discovery schema.
Strings, booleans and integers must have the expected JSON types. Control characters and malformed
Unicode are rejected; multiline values are supported for Notes and address text. Duplicate JSON
keys and nonstandard constants such as NaN are errors.

Phone checks are deliberately basic: at least three digits, common separators, and extensions
introduced by `ext`, `ext.`, `x`, `#`, or `;ext=`. A country code is not required. This is not phone
ownership or reachability verification. Email and URL checks likewise do not establish existence. Email domains must contain a dot,
for example `name@example.com`; `name@localhost` and `name@1` are rejected.

Dates use integer `year`, `month`, and `day` components. Supported combinations are full dates,
month/day without a year, year alone, and year/month. Omitted components behave as zero. Calendar
validity is checked; February 29 without a year is valid. Booleans do not count as date integers.

Each contact is limited locally to 500 top-level field entries and 128 KiB of serialized JSON,
consistent with existing creation guards. These are estimates, not Google's storage accounting.
The entire input must validate before authorization or any writes; errors identify the contact number and
field path, with zero-based array indexes, for example:

```text
Contact #3 → emailAddresses[1].value: invalid or unsupported email address
```

## Creation and failures

The numbered preview includes all supplied fields with readable property names, dates, and
yes/no values, plus the labels applied to every contact.
Timestamped progress identifies each label and contact being created. Created contact, followed
by a Google Contacts link, confirms creation before readback verification begins. A later
Verification failed message means the contact exists but its saved fields could not be verified.
Created and verified confirms both stages. With `--apply`, the preview heading is Creating contacts.

| Outcome | What the output tells you |
| --- | --- |
| Successful creation and readback | Created contact with a link, then Created and verified |
| Saved values differ | The contact was created, but verification failed; Requested and Saved show the differing field |
| Readback cannot complete | The contact was created, but verification failed, followed by the read error |
| Google rejects creation | The contact or label was not created, followed by the reason |
| Write result is unknown | Creation outcome is unknown; inspect Google Contacts before retrying |
| Interrupted during verification | The contact or label was created, but verification was interrupted |
| Interrupted during a write | Creation outcome is unknown |
| Label creation or verification fails | Label outcome and saved label count; contacts have not been attempted |

For a batch, the summary separates created contacts, verified contacts, and contacts not attempted.
Created includes contacts whose verification failed; verified is a subset of created. Unknown
outcomes are not included in the created count. Zero remaining counts and label counts are omitted
when they add no information. Single-contact failures state the outcome directly without a batch
summary. Previously created contacts and labels remain saved.

This command creates only: it does not find, merge, or update existing contacts. Repeating an
input creates another contact. A failure or interruption stops further creation. There is no
automatic rollback; a label may remain empty if contact creation fails. Writes are not automatically
retried. Inspect Google Contacts before retrying an uncertain write; retry only the remaining input
after checking it. A label created by another process between preview and creation causes a conflict
and stops the run.

Sources: [Google Person fields](https://developers.google.com/people/api/rest/v1/people),
[contact creation restrictions](https://developers.google.com/people/api/rest/v1/people/createContact),
[contact label creation](https://developers.google.com/people/api/rest/v1/contactGroups/create).
