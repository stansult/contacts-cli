# Command reference

[Back to usage](../README.md). Detailed command behavior, output, and limitations.

## Contents

- [Running the CLI](#running-the-cli), [contact identifiers](#contact-identifiers),
  [confirmation and conflicts](#previews-confirmation-and-conflicts), [output](#output-and-timestamps)
- [Add-contact](#add-contact), [duplicate](#duplicate-a-contact), [sender-sync](#sender-sync-preview-and-apply)
- [List-email](#list-email), [add-email and remove-email](#add-email-and-remove-email)
- [Add-label](#add-label), [remove-label](#remove-label), [label choices](#label-choices-and-output)
- [Custom fields](#add-custom-field-and-remove-custom-field), [validate-contact](#validate-contact),
  [authorization](#authorization)
- [Global options](#global-options), [email validation](#email-input-validation),
  [error details](#api-error-details), [exit codes](#exit-codes)

## Running the CLI

This is a local Python CLI. Browser authorization uses a temporary local callback listener,
whether started with `authorize` or offered during another command.

The executable `./contacts-cli` launcher runs the CLI through uv with the locked dependencies. It
forwards all arguments and also works when invoked by its full path from another directory. Relative
file arguments are relative to your current directory. The longer `uv run --locked contacts-cli`
invocation still works from the checkout.

Alternatively, install into an existing virtual environment with `python -m pip install .`. That
provides the `contacts-cli` command, but does not use the repository's dependency lock.

Use `./contacts-cli <command> --help` for command-specific options. A subcommand is required.

## Contact identifiers

Commands targeting an existing contact accept a Google Contacts URL or the bare ID `c123456789`.
The ID is the final part of the website URL, after `/person/`. Lookup by name is not supported.
For compatibility, `people/c123456789` is also accepted: `people/` is Google's People API resource
prefix, not part of the website URL.

Contact headings use the bare ID: `Contact: 'name: Jane' (c123456789)`. A nonblank name takes
precedence over company; otherwise the heading shows `company: Example Company` or `Unnamed`.
The saved token selects the account; a URL's `/u/0/` or `/u/1/` segment does not.

## Previews, confirmation, and conflicts

Contact-changing commands show their intended changes before saving. Interactive confirmation requires
terminal input, output, and error streams. Enter, `n`, or end-of-input at the final confirmation
makes no changes. Piped or redirected runs without `--apply` do not write; unresolved label choices
may stop the run before a complete preview.

`--apply` skips final write confirmation, not every decision. Label case choices still prompt in
interactive runs and stop noninteractive runs. With `--apply`, email conflicts are kept unless
explicitly approved with `--replace-existing`. Each command's section describes its matching and conflict rules.

Each invocation reads current data: `--apply` does not approve a frozen preview from an earlier run.
Creation commands create new contacts each time. Updates preserve unrelated contact data and
verify the saved result. After an uncertain write or failed verification, inspect the contact
before retrying; a failed batch can leave earlier changes saved.

## Output and timestamps

Email, label, and custom-field lists show totals and numbered rows. Preview headings describe
proposed changes; with `--apply`,
action headings describe the intended writes. Only completion messages confirm verified success.

Operational output begins with a local `[YYYY-MM-DD]` date line. Primary messages use local
`[HH:MM:SS]` timestamps, including stage messages, confirmation prompts, completion, and errors.
Details and list entries remain unprefixed. Blank lines and help remain undecorated. If a run
crosses midnight, the ending date appears after the last message. Updating sender counters have
no timestamp and always show their final count.

## Add-contact

`add-contact` accepts inline `--name` and repeatable `--email`, or `--file` with one Person object
or an array. Repeatable `--label` reuses existing labels or previews missing labels for creation.
Case-only label collisions require choosing an existing label, creating new, or cancelling;
noninteractive collisions stop. `--apply` does not resolve this choice.
Confirmation approves all contacts and new labels; `--apply` skips the final prompt. Noninteractive runs
without `--apply` only preview. See [contact creation](contact-input.md) for supported fields,
validation, progress, verification, and partial-failure behavior.

## Duplicate a contact

Preview a copy, optionally choosing a replacement name:

```sh
./contacts-cli duplicate \
  --contact c123456789 \
  --name 'Delivery backup'
```

In an interactive terminal, the preview is followed by `Create this duplicate? [y/N]`.
Answer `y` or `yes` to create it; Enter, `n`, or any other answer makes no changes.

Add `--apply` to create it without the confirmation prompt:

```sh
./contacts-cli duplicate \
  --contact c123456789 \
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
Recognized `/s100/` or `=s100` URL size settings are changed to `s0` to request the full-size
image; other URL options are retained and a conflicting `sz` query parameter is removed.
Unrecognized size formats or failed downloads stop creation, with no thumbnail fallback. This
size-setting behavior was verified experimentally; Google may change it.
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

## Sender-sync preview and apply

The command shows a preview first:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact c123456789
```

Output identifies the contact and label,
shows inspected-message and new-sender counts in progress, then existing email entries and additions.

Use repeatable `--exclude ADDRESS` options to skip additional individual senders for that run.
Addresses are compared case-insensitively after trimming surrounding whitespace; duplicates are
combined. Domains, wildcards, display names, and address lists are not accepted. Invalid or
unsupported values are rejected before authorization or network access. Manual exclusions are
combined with automatic exclusions in Gmail queries and in parsed candidate filtering. They
are not saved for later runs and do not remove addresses already stored in the contact. The same
query-size limit applies to the combined exclusions. Gmail matching limitations below still apply.

Use `--exclude-file PATH` to read a UTF-8 list, one address per line. Repeat the option for
multiple files and combine it with `--exclude`. Blank lines, surrounding whitespace, and lines
starting with `#` are ignored. A line copied from the preview may include ` — Display Name` after
the address; only the address is used. Inline comments and comma-separated lists are not supported.
All file addresses use the same validation and deduplication as `--exclude`. Missing, unreadable,
non-UTF-8 files and invalid entries stop before authorization; invalid entries report the file
and line number. Relative paths use the current working directory. Files are read fresh each run.

```text
# Excluded senders
ignore@example.com
another@example.com — Notifications
```

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
The complete preview stays on stdout. Proposed addresses appear one per line without a `+` prefix,
with a custom label after ` — ` when applicable. Counts describe inspected messages, not the label’s
total size.

In an interactive terminal, the preview is followed by `Apply these additions? [y/N]`.
Answer `y` or `yes` to save; Enter, `n`, or any other answer leaves the contact unchanged.
No prompt appears when there are no additions.

To save without the confirmation prompt, use `--apply`:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact c123456789 \
  --apply
```

Each command scans current data; `--apply` is not approval of a frozen previous preview. Reuse the
same flags after changing a Gmail filter and applying it to matching messages. There is no need to
maintain an exclusion query or a filter ID. A run with no missing addresses sends no contact update.

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
  Without a display name, or when it matches the email address, any contact display name, or any
  company name ignoring case and surrounding whitespace, the address is shown and saved without
  a custom label. Both names and companies are checked even when the contact has both. The search does not
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

## List-email

```sh
./contacts-cli list-email --contact 'c123456789'
```

Reads the contact and lists every existing email entry in its stored order, with a total,
numbered rows, optional labels, and duplicate references. An empty contact shows zero entries.
It does not modify the contact or search Gmail. No apply confirmation is needed, and `--apply`
is not accepted. The command uses the saved authorization and supports `--token` like the
editing commands.

## Add-email and remove-email

`add-email` accepts repeatable `--add 'address — Label'` and `--add-file PATH` options.
`remove-email` accepts repeatable `--remove ADDRESS` and `--remove-file PATH` options.
Both require `--contact` and at least one individual or file option. Use the same UTF-8 file
format as exclusions: one address per line, optional ` — Label`, blank lines and whole-line `#`
comments. Options combine; files are read fresh relative to the current directory. An empty file
requests no changes. Removal ignores labels and matches only normalized addresses.

These commands read contacts directly; they do not search Gmail or exclude your sending identities.
They reuse the saved authorization. Address parsing is shared with exclusions, but Gmail query
syntax restrictions and query-length limits do not apply to direct contact edits.

Addition normalizes addresses and labels for comparison, suppresses redundant labels matching
the address/contact name/company, then deduplicates incoming entries. Conflicting resulting
labels for one address stop before any write and identify both inputs; correct the inputs and
retry. A bare address and an address whose label was suppressed both request no label.

For existing entries, equal labels need no change. A label supplied for an unlabeled entry is
included in the proposed changes. Changing or removing an existing label prompts in interactive
runs. Duplicate stored entries also prompt, even if their labels match. Replace consolidates
all matching entries into one; Keep preserves them all. The primary matching entry survives when
present, otherwise the first matching entry, retaining its spelling and other metadata. Existing
primary status is preserved. The preview shows the old labels and the entry-count reduction.

Conflict choices are `y` (Replace), `n` or Enter (Keep), `a` (Replace all conflicts), and `s`
(Keep all conflicts). All applies to current and remaining stored-entry conflicts, not unrelated
new additions. End-of-input keeps remaining conflicts. After these choices, the final preview
lists changes, skipped conflicts, and remaining email entries, followed by one apply confirmation.

`--replace-existing` approves all stored-entry conflicts but still requires final confirmation
unless `--apply` is also supplied. With `--apply` alone, existing conflicts are preserved and
reported while non-conflicting changes are saved. Noninteractive runs do not ask conflict questions;
without `--apply` they only preview. Unresolved conflicts are shown under Skipped conflicts.

Removal deletes all entries matching each address, regardless of labels, with counts shown in
the preview. Each stored entry has its own numbered row, including duplicates; rows show the
address and its label when present. Later occurrences of the same address (ignoring case) show
`[duplicate of #N]`, referencing its first row, without implying a preferred entry.
The heading counts both entries and distinct addresses.
Absent addresses are listed under Not found. Removing every email is allowed and
leaves the contact intact with zero email entries. A no-op performs no update. Later sender-sync
runs can add matching senders again; reuse the removal list as exclusions if appropriate.

Only emailAddresses is written. Other contact fields and retained email metadata are preserved.
A fresh read and etag check reject concurrent changes; writes are not automatically retried.
Both the response and an independent read verify the complete expected email list and labels.
If the primary email is removed, Google may assign primary status to a remaining entry; this is
allowed, while a surviving primary choice must be preserved. Failed verification reports an
unverified update. These commands are not undo; [issue #5](https://github.com/stansult/contacts-cli/issues/5) tracks that separate enhancement.

## Email list display

Email lists use a heading with a total followed by aligned, numbered rows. Labels appear only
when present. This applies to sender-sync additions and the direct email editing commands,
including missing addresses and skipped conflicts. Addition rows do not repeat “Add.” Updates
have a separate section showing the old and new values.

Use `list-email` to see all existing entries. Add/remove commands show only the existing total;
existing entries are displayed when needed for a conflict decision. Every displayed list starts
at 1, including conflict matches and removal previews. Duplicate references point to the first
occurrence within that list. Numbers do not identify a preferred or primary address.

Without `--apply`, change headings say Proposed additions, Proposed updates, or Proposed removals.
With `--apply`, they say Adding, Updating, or Removing. These headings describe the requested action;
only the final Saved and verified message confirms success.

## Add-label

```sh
./contacts-cli add-label --contact c123456789 --label Recruiter --label Follow-up
```

Adds one or more contact labels to an existing contact. `--contact` accepts a URL or bare ID;
repeat `--label` for more labels. Names match exactly and case-sensitively. The shared
[case-collision choices](contact-input.md#contact-labels) offer existing labels, create new,
or cancel. `--apply` skips final confirmation but not label choices; unresolved noninteractive
collisions stop. See [label choices and output](#label-choices-and-output) for membership-aware wording.

The preview separates labels already on this contact from proposed additions, with totals
and numbered rows. New labels appear once, marked `(new label)`. If every label is already on
the contact, the command makes no changes. Otherwise it
asks once before creating labels or adding memberships. Noninteractive runs without `--apply`
preview only.

The CLI uses Google's additive group-membership operation, sending no membership removals or
contact-field replacement. Existing memberships and other contact fields are preserved. It rereads
the contact before each addition, skips memberships applied since preview, and independently reads
back afterward to check the added label and prior memberships. It stops if the contact identity
changes or verification fails.

Operations run sequentially without automatic mutation retries. On failure or interruption, the
command reports verified additions and newly created labels; completed changes remain saved.
A newly created label may remain empty if adding the contact fails. Inspect the contact before
retrying; a new preview skips labels already applied. HTTP errors use the shared local error logs.
The command adds no Created or Duplicate custom field.

API contract: [modify contact group members](https://developers.google.com/people/api/rest/v1/contactGroups.members/modify).

## Remove-label

```sh
./contacts-cli remove-label --contact c123456789 --label Recruiter --label Follow-up
```

Removes the specified labels from one existing contact. It does not delete label definitions or
change other contacts. Names and case-collision choices follow `add-label`, except removal never
offers Create new. The menu offers removal of matching labels on this contact and Cancel command. `--apply` skips final confirmation,
not case choices; unresolved noninteractive case collisions stop. Case-only matches absent from
the contact are reported and skipped without a choice.

The numbered preview separates labels not found, labels not applied to this contact, and proposed
removals. Repeated labels are deduplicated. Missing or unapplied labels are no-ops; if none are
applied, the command exits without writes. Otherwise confirmation approves all listed removals.
Noninteractive runs without `--apply` preview only.

Each request removes only this contact from one label. A fresh contact read checks identity and
current memberships before the write; a label removed since preview is skipped. Independent
readback verifies the removed label is absent and other memberships remain. Other contact fields
are never sent for replacement. Labels themselves remain, even if empty. Google may refuse removal
of a contact's last contact-group membership; that refusal is reported and processing stops.

On errors or interruption, verified removals remain saved and later removals stop. Mutation requests
are not retried automatically. Inspect the contact before retrying; a fresh preview skips labels
already removed. Shared [error logs](error-logs.md) capture failed HTTP responses.

## Label choices and output

For `add-label` and `remove-label`, label lookup distinguishes existence anywhere in Google
Contacts from membership on the selected contact. Choices reflect both spelling and membership.

### Adding labels

Exact spelling takes precedence over case-only alternatives, including when both spellings exist.
Other case variants do not affect the decision for an exact match.

| Requested spelling | State | Action |
| --- | --- | --- |
| Exact match | Already on this contact | Skip; show under “Already on this contact.” |
| Exact match | Exists elsewhere, absent from this contact | Include in additions. |
| Case-only match | Already on this contact | Offer to keep it or create and add the requested spelling too. |
| Case-only match | Exists elsewhere, absent from this contact | Offer to add it or create and add the requested spelling instead. |
| No match | Does not exist | Preview creating and adding it. |

For a case-only match already on the contact:

```text
This contact already has 'Recruiter', which differs only by case from 'recruiter'.
  1. Keep 'Recruiter'; skip adding 'recruiter'
  2. Create 'recruiter' and add it too
  3. Cancel command
Choose 1–3 (Enter = 1):
```

For a case-only match not on the contact:

```text
Label 'Recruiter' exists in Google Contacts, but isn't on this contact.
Its spelling differs only by case from 'recruiter'.
  1. Add 'Recruiter'
  2. Create 'recruiter' and add it instead
  3. Cancel command
Choose 1–3 (Enter = 1):
```

If several case-only alternatives exist, each choice states whether the label will be kept or
added. The prompt shows the numbered range and the default selected by Enter.

### Removing labels

Removal choices say “Remove 'Recruiter' from this contact.” Labels absent from the contact
are reported and skipped. Removal never offers to create a label.
Exact matches still take precedence over case-only alternatives.

```text
This contact has 'Recruiter', which differs only by case from 'recruiter'.
  1. Remove 'Recruiter' from this contact
  2. Cancel command
Choose 1–2 (Enter = 1):
```

### Preview, confirmation, and completion

“Cancel command” cancels the entire command before writes. Labels already present appear under
“Already on this contact.” Each addition appears once; `(new label)` marks labels needing creation.
Contact details and preview sections are separated by blank lines.

Final confirmation states the actual action counts. For one new label it asks “Create 1 new label
and add it to this contact?” Mixed additions distinguish labels to create from labels to add.
Choices select the plan; final confirmation authorizes writes unless `--apply` was supplied.

Success says “Added and verified” or “Removed and verified.” A single-label run has one final
success summary; multiple-label runs also report each verified change. Completed changes remain
saved if a later operation fails.

## Add-custom-field and remove-custom-field

```sh
./contacts-cli add-custom-field --contact c123456789 --key 'Pipeline ID' --value P-001
./contacts-cli remove-custom-field --contact c123456789 --key 'Pipeline ID' --value P-001
./contacts-cli remove-custom-field --contact c123456789 --key Duplicate
```

These commands edit custom key/value entries (`userDefined` in Google Person JSON). Each invocation
accepts one `--key`; addition requires `--value`. Removal accepts an optional value: supplying it
removes all matching key/value pairs, including duplicates; omitting it removes every entry with
that key. Removing `Created` or `Duplicate` affects only those stored custom fields, not the contact
itself. These markers receive no special treatment.

Matching is exact and case-sensitive, with whitespace preserved. Input must be nonblank text
without control characters. Case-only similarities are listed as notices, not selected as matches:
adding `created` does not reuse `Created`; removing `created` does not remove `Created`.
There is no case-choice menu. Adding an exact pair already present skips it, preserving any stored
duplicates. A different value under the same key is appended, never used as a replacement. A removal
with no matches reports a no-op. This version has no file input or replacement option.

The numbered preview shows a total and the entries to add or remove, followed by the remaining
entry count. Interactive runs ask for confirmation; noninteractive runs preview only unless
`--apply` is supplied. `--apply` skips confirmation and uses Adding/Removing headings. The silent
aliases `add-custom-fields` and `remove-custom-fields` are accepted; help uses singular names.
Both commands accept global `--token` and `--auth-timeout` options before or after the command.

The update sends only the complete intended `userDefined` list and contact source metadata.
Unmatched custom fields are retained, as are other contact fields. A fresh read and source etag
protect against concurrent changes; conflicts stop rather than merging or retrying. The response
and an independent read must both match the expected custom fields (including duplicate counts)
and preserve the other fields in the contact read mask. Verification errors report an unverified
update: inspect the contact before retrying. The shared local size guards, API error logging,
interrupt handling, and exit codes apply. No mutation is automatically retried.

API contract: [updateContact field masks and source etags](https://developers.google.com/people/api/rest/v1/people/updateContact).

## Validate-contact

`validate-contact --file PATH` checks a UTF-8 contact JSON file locally using the same validator as
`add-contact`, then reports the contact count. Authorization, prompts, and Google access are not
needed. Inline fields, labels and `--apply` are not supported. See [local validation](contact-input.md#validate-a-file-locally).

## Authorization

See [detailed Google setup instructions](google-setup.md). Existing `gmail.metadata` authorizations need upgrading to
`gmail.readonly`; the CLI detects insufficient permissions and offers browser reauthorization.
See [upgrading an existing authorization](google-setup.md#upgrading-an-existing-authorization).
The new permission permits reading message bodies, although this CLI continues to request only
headers and labels. Sender searches use the Gmail read-only permission.

## Global options

`--token PATH` appears in `contacts-cli --help`. Command help shows
command-specific options and points to top-level help for global options. Both positions work:

```sh
./contacts-cli --token /path/token.json list-email --contact 'c123456789'
./contacts-cli list-email --contact 'c123456789' --token /path/token.json
```

If supplied both before and after the command, the value after the command takes precedence.

## Email input validation

Email addresses supplied inline or through files for add-contact, add-email, remove-email, and
sender-sync exclusions must have a dotted domain, such as `name@example.com`. Single-component
domains such as `name@localhost` or `name@1` are rejected. Validation does not check whether a
domain or mailbox exists.

## API error details

Failed Google API HTTP responses are saved locally, and the terminal prints the log path. See
[API error logs](error-logs.md) for locations, recorded fields, and troubleshooting details.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Successful preview, verified write, authorization, validation, no-op, or cancelled label choice |
| `1` | Input, API, or setup error; earlier successful changes in a batch may remain saved |
| `2` | Invalid command-line arguments |
| `3` | A write occurred or may have occurred, but the operation did not complete with verified success |
| `130` | Interrupted; read the output to distinguish no write, saved changes, and uncertain outcomes |

Use the command's outcome message and any partial-result summary to determine what was saved.
An exit code alone does not identify which contacts or labels changed.
