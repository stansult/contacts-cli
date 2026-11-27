# Contact input format

Use this format for `add-contact --file` and `validate-contact --file`. Files contain Google
Person JSON with the supported fields below. For duplicate review, merging, labels, and saving,
see [importing contacts](importing-contacts.md).

## Contents

- [Validate a file locally](#validate-a-file-locally)
- [Inline or file input](#inline-or-file-input)
- [Supported fields](#supported-fields)
- [Validation rules](#validation-rules)
- [Import review and outcomes](#import-review-and-outcomes)

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
./contacts-cli add-contact --first-name Jane --last-name Doe
./contacts-cli add-contact --file contacts.json --label Contacts
```

Inline input requires a name or an email. Repeat `--email` to attach more addresses to the same
contact. `--name` is stored as Google's `unstructuredName`; the CLI does not guess how to split it.
Google parses that full name into components. To supply them explicitly, use `--first-name` and
`--last-name`, together or individually. An omitted component is left empty. Do not combine
`--name` with either explicit component. Name values must be nonblank; an empty string is not a
way to omit a component. Use a file for middle names, other name components, or additional fields.
Do not combine `--file` with any inline name or email option.

Verification checks the full name when one was supplied, allowing Google to add parsed components.
For explicit structured names, it checks the supplied components and rejects unexpected additional
editable components. Generated display/full-name representations are allowed. These same name
rules apply to duplication.

The UTF-8 JSON file contains one Google Person object or a nonempty array of Person objects.
There is no wrapper object and no custom version field. Omit unknown details; use standard fields
where available and custom fields for other facts. Custom keys and labels have no project-specific
meaning to the CLI. For example:

```json
[
  {
    "names": [{"givenName": "Jane", "familyName": "Doe"}],
    "emailAddresses": [{"value": "jane@example.com", "type": "work"}],
    "urls": [{"value": "https://example.com/jane", "type": "LinkedIn"}],
    "userDefined": [
      {"key": "External ID", "value": "record-001"},
      {"key": "External ID", "value": "record-002"}
    ]
  }
]
```

## Supported fields

| Field | Contents and requirements |
| --- | --- |
| `names` | One structured or unstructured name; at least a given, family, middle, or unstructured name |
| `emailAddresses` | Email `value`, optional `type` and `displayName`; dotted email domain; see validation rules below |
| `phoneNumbers` | Phone `value` and optional `type`; digits and common punctuation, optional leading `+` and extension |
| `organizations` | Company `name`, title, department, and other writable Organization properties; at least name, title, or department per entry |
| `addresses` | Full or partial addresses; at least one component; `countryCode` uses two uppercase letters |
| `urls` | HTTP or HTTPS `value` with a host, optional custom `type` such as LinkedIn |
| `userDefined` | Nonblank `key` and `value`; repeated keys supported |
| `biographies` | One explicit Notes `value`, optional API `contentType` |
| `birthdays` | One structured `date`; deprecated free-form `text` is rejected |
| `events` | Structured `date` and optional `type` |
| `nicknames` | Nonblank `value` and optional API-defined `type` |

### Companies

For `organizations`, omit `type` by default. Keep useful company details such as `name`, `title`,
`department`, and dates; do not automatically add `type: "work"` merely because the entry is a
company. For example:

```json
{
  "organizations": [{"name": "Example Company", "title": "Recruiter"}]
}
```

Include an organization type only when it carries useful, intentional information. In our live
test, Google did not retain `work` or `school` when added to an existing untyped organization,
although a custom type and `work` on a newly appended organization were retained. This is an
observed limitation, not a documented universal rule. Supplying a type that Google omits can
cause verification to fail after an update was submitted. The CLI still accepts and verifies
organization types; it does not silently remove them. This guidance does not apply to email or
phone `type` labels, which remain useful.

### Nicknames

A nickname usually needs only `{"value": "J"}`. When `type: "DEFAULT"` is explicitly supplied,
verification also accepts Google omitting that generic type. Nickname values and explicitly
different types must still match.

### Omitted fields and custom markers

Every field is an array, even singleton fields. Every contact needs at least a name, email, phone,
or organization with a company name. `add-contact` preserves supplied custom fields, including
any Created or Duplicate fields, and adds no automatic creation marker. The input file is
unchanged; `validate-contact` only validates input and adds nothing. No Notes are added.
Other omitted fields stay absent.

## Validation rules

Empty arrays are allowed, but empty entries, blank supplied text, unknown properties,
and generated fields such as `resourceName`, `etag`, `metadata`, and `formattedType` are rejected.
Use `--label` instead of raw `memberships`.

### Schema and text

Nested properties and enums are checked against the bundled Google People discovery schema.
Strings, booleans and integers must have the expected JSON types. Control characters and malformed
Unicode are rejected; multiline values are supported for Notes and address text. Duplicate JSON
keys and nonstandard constants such as NaN are errors.

### Email and phone validation

Phone checks are deliberately basic: at least three digits, common separators, and extensions
introduced by `ext`, `ext.`, `x`, `#`, or `;ext=`. A country code is not required. This is not phone
ownership or reachability verification. Email and URL checks likewise do not establish existence. Email domains must contain a dot,
for example `name@example.com`; `name@localhost` and `name@1` are rejected.

### Dates

Dates use integer `year`, `month`, and `day` components. Supported combinations are full dates,
month/day without a year, year alone, and year/month. Omitted components behave as zero. Calendar
validity is checked; February 29 without a year is valid. Booleans do not count as date integers.

### Size limits and error locations

Each contact is limited locally to 500 top-level field entries and 128 KiB of serialized JSON,
consistent with existing creation guards. These are estimates, not Google's storage accounting.
The entire input must validate before authorization or any writes; errors identify the contact number and
field path, with zero-based array indexes, for example:

```text
Contact #3 → emailAddresses[1].value: invalid or unsupported email address
```

## Import review and outcomes

Input validation is separate from duplicate review, saving, and verification. Follow the
[import workflow](importing-contacts.md#import-workflow) for those stages.

### Possible duplicates

See [matching rules and duplicate review](importing-contacts.md#possible-duplicates).

### Matching rules

See [name, company, email, and phone comparisons](importing-contacts.md#possible-duplicates).

### Merging information

See [merge targets, conflicts, and field rules](importing-contacts.md#merging-information).

### Compact label-only imports

See [selecting label-only updates](importing-contacts.md#compact-label-only-imports).

### Grouped email-label changes

See [reviewing email-label replacements together](importing-contacts.md#grouped-email-label-changes).

### Grouped merges without conflicts

See [reviewing additions together](importing-contacts.md#grouped-merges-without-conflicts).

### Contact labels

See [requested labels and case choices](importing-contacts.md#contact-labels).

### Creation and failures

See [creation progress, verification, and partial failures](importing-contacts.md#creation-and-failures).
