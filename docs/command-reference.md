# Command reference

[Back to usage](../README.md). Detailed command behavior, output, and limitations.

Multi-option menus list choices on separate lines and spell out the Enter default, for example
`Choose an option (Enter = return to selection):`. Simple yes/no confirmations use `[y/N]`
or `[Y/n]`, with the capital letter indicating the Enter default.

## Contents

- [Running the CLI](#running-the-cli), [contact identifiers](#contact-identifiers),
  [multiple-contact rules](batch-contacts.md),
  [confirmation and conflicts](#previews-confirmation-and-conflicts),
  [numbered selections](#numbered-selections), [output](#output-and-timestamps)
- [List-contact](#list-contact), [Add-contact](#add-contact), [duplicate](#duplicate-a-contact), [sender-sync](#sender-sync-preview-and-apply)
- [List-email](#list-email), [add-email and remove-email](#add-email-and-remove-email)
- [List-phone and remove-phone](#list-phone-and-remove-phone)
- [Format-phone](#format-phone)
- [List-label](#list-label), [add-label](#add-label), [remove-label](#remove-label), [label choices](#label-choices-and-output)
- [Custom fields](#add-custom-field-and-remove-custom-field), [validate-contact](#validate-contact),
  [authorization](#authorization)
- [Active timing](#active-timing), [network timeouts](#network-timeouts)
- [Global options](#global-options), [email validation](#email-input-validation),
  [error details](#api-error-details), [exit codes](#exit-codes), [request pacing](#google-contacts-request-pacing)

## Running the CLI

This is a local Python CLI. Browser authorization uses a temporary local callback listener,
whether started with `authorize` or offered during another command.

The executable `./contacts-cli` launcher runs the CLI through uv with the locked dependencies. It
forwards all arguments and also works when invoked by its full path from another directory. Relative
file arguments are relative to your current directory. The longer `uv run --locked contacts-cli`
invocation still works from the checkout.

Alternatively, install into an existing virtual environment with `python -m pip install .`. That
provides the `contacts-cli` command, but does not use the repository's dependency lock.

Use `./contacts-cli <command> --help` for a short usage summary, command-specific options,
and a direct link to the detailed section below. A subcommand is required.

## Contact identifiers

Single-contact commands accept a Google Contacts URL, bare ID, full name, email, or complete
phone number through `--contact`. This applies to email, `list-phone`, `remove-phone`, custom-field
commands, `duplicate`, `sender-sync`, and contact-specific `list-label` and `remove-label`.
`format-phone` and `add-label` support [multiple-contact resolution](batch-contacts.md).

- Names match completely, ignoring case and extra whitespace; a one-word saved name can match.
- Emails match completely, ignoring case.
- Phones ignore punctuation and an optional leading `+`, but require all base-number digits.
  No country is guessed. An extension restricts the match to that extension; omitting it can
  match several contacts sharing a base number.
- One match continues to the command's normal preview. Multiple matches show identifying
  details and require exactly one displayed number, or `q` to cancel. Enter, `all`, lists, and
  ranges do not select a contact. End-of-input cancels.
- No match returns an error without changes. Noninteractive ambiguous lookup also errors,
  including with `--apply`; use an ID to resolve the ambiguity.
- Selecting a contact does not approve a write. Normal confirmation, `--apply`, concurrent-edit
  protection, and verification still apply to the selected contact.

IDs and URLs avoid the account-wide matching read. The ID is the final part of the website URL,
after `/person/`, such as `c123456789`. Other identifiers read saved matching fields once, then
the command reads full target details as usual. Company and label filters and partial lookup
remain in `list-contact`; `add-label` retains its existing multiple-contact resolution.

```sh
./contacts-cli list-email --contact 'Jane Example'
./contacts-cli format-phone --contact jane@example.com
./contacts-cli remove-label --contact '+1 202-555-0142' --label Test
```
For compatibility, `people/c123456789` is also accepted: `people/` is Google's People API resource
prefix, not part of the website URL.

Contact headings use the bare ID: `Contact: 'name: Jane' (c123456789)`. A nonblank name takes
precedence over company; otherwise the heading shows `company: Example Company` or `Unnamed`.
The saved token selects the account; a URL's `/u/0/` or `/u/1/` segment does not.

## Previews, confirmation, and conflicts

Commands that change contacts or labels show their intended changes before saving. Interactive
confirmation requires terminal input, output, and error streams. A simple `[y/N]` prompt writes
only after `y` or `yes`. With multiple choices, contact creation, sender-sync, email edits,
custom-field edits, and label removal offer numbered selection followed by confirmation.
At that confirmation, Enter or `n` returns to selection; `q` or end-of-input cancels.
Piped or redirected runs without `--apply` do not write; unresolved label choices
may stop the run before a complete preview.

`--apply` selects all eligible items and skips final write confirmation, not every decision.
Label case choices and possible contact duplicates still require interactive review. With `--apply`,
email conflicts are kept unless explicitly approved with `--replace-existing`. Each command's
section describes its matching and conflict rules.

Each invocation reads current data: `--apply` does not approve a frozen preview from an earlier run.
`add-contact` can merge into a chosen match; `duplicate` creates a new copy. Updates preserve unrelated contact data and
verify the saved result. After an uncertain write or failed verification, inspect the contact
before retrying; a failed batch can leave earlier changes saved.

## Numbered selections

Enter `all`, displayed numbers, or ascending ranges directly. These rules apply to shared
selections for contacts, email addresses, labels, custom fields, and grouped import review.

| Input | Meaning |
| --- | --- |
| `all` | Select every currently available item |
| `18,37` | Select those displayed numbers; an unavailable explicit number is an error |
| `1-19` | Select displayed items from 1 through 19; gaps and undisplayed endpoints are allowed |
| `37-100` | Select displayed items in that interval, even if 100 is not displayed |
| `18,18-37` | Combine selections; overlapping items count once |
| `q` or end-of-input | Cancel without saving |

Results stay in displayed order. Ranges never include hidden, excluded, or already-reviewed
items. An empty range contributes nothing to a combined selection. If the whole selection is
empty, or the input is blank, malformed, or reversed, the prompt asks again.

## Output and timestamps

Email, label, and custom-field lists show totals and numbered rows. Preview headings describe
proposed changes; with `--apply`,
action headings describe the intended writes. Only completion messages confirm verified success.

Operational output begins with a local `[YYYY-MM-DD]` date line. Primary messages use local
`[HH:MM:SS]` timestamps, including stage messages, confirmation prompts, completion, and errors.
Details and list entries remain unprefixed. Blank lines and help remain undecorated. If a run
crosses midnight, the ending date appears after the last message. Updating sender counters have
no timestamp; the completion line includes the final counts and finish timestamp.

Sender-sync waiting and scanning stages share one progress helper. Interactive stderr shows an
immediate spinner with a fixed start timestamp for waiting stages. After 5 seconds, it also shows
`elapsed Ns`. Completion replaces the live line with a finish timestamp; stages lasting at least
10 seconds include `(took N.Ns)`. Durations use a monotonic clock, independently of clock changes.
Errors and interruptions end the stage as failed or interrupted, not finished. Progress stops
before prompts and other output. Redirected stderr has plain start/completion lines and throttled
counter updates, without animation or control codes. These thresholds require no CLI flags.

## List-contact

```sh
./contacts-cli list-contact --search 'Jane'
./contacts-cli list-contact --search 'Jane Doe' --exact
./contacts-cli list-contact --search jane@example.com
./contacts-cli list-contact --search '2025550142'
./contacts-cli list-contact --search '+1 202 555 0142' --exact
./contacts-cli list-contact --search c123456789
```

### Search options

Supply `--search` or at least one explicit filter. `list-contacts` is also accepted;
help uses the singular form. Each filter accepts one value.

| Option | Default matching | With `--exact` |
| --- | --- | --- |
| `--search` | Automatically interprets a name, email, phone, ID, or URL | Complete names and phones |
| `--name` | Name contains text, ignoring case and extra whitespace | Complete name |
| `--email` | Complete email, ignoring case | Unchanged |
| `--phone` | Base-number suffix, ignoring formatting | Complete base number |
| `--company` | Any company name contains text, ignoring case and extra whitespace | Complete company name |
| `--label` | Complete existing user-label name | Unchanged |

Different filters combine with AND. `--search` may combine with `--company` and `--label`,
but not with `--name`, `--email`, or `--phone`. Use explicit filters to combine those fields.
Empty values, invalid explicit emails/phones, and incompatible combinations fail before authorization.
Wildcards are not supported; `*` in name/company text is literal.

```sh
./contacts-cli list-contact --name Jane --company Example
./contacts-cli list-contact --email jane@example.com --label Recruiter
./contacts-cli list-contact --phone 2025550142 --company Example
./contacts-cli list-contact --label Recruiter
./contacts-cli list-contact --search Jane --label Recruiter
./contacts-cli list-contact --company 'Example Ltd' --exact
```

`--search` retains its original interpretation and never searches company fields. For example,
`--search Josh` finds `Josh`, `Josh Smith`, and `Joshua`; `--name 123` explicitly searches names
rather than interpreting the digits as a phone suffix. `--exact` affects every supplied name,
phone, and company criterion.

### Label filtering

Exact label spelling wins. If only case-different labels exist, interactive runs offer existing
spellings or cancellation; redirected runs require exact spelling and report an error.
Missing labels return zero matches without creating anything. System labels are not supported.
Label choices only resolve the filter; they never add or remove labels.

### Email and ID matching

Email, ID, and URL searches reuse the [contact lookup rules](#contact-matching-rules) in both modes.
Emails match completely, ignoring case. Other commands retain their existing matching behavior;
partial names and phone suffixes apply only to `list-contact`.

### Phone matching

Phone lookup ignores formatting and an optional leading `+`. By default, the saved base number
must end with the supplied digits: `2025550142` finds `+12025550142`, and `0142` finds both.
This is suffix matching, not matching digits anywhere in the number. Short suffixes can return
many contacts. No country is inferred. With `--exact`, every base-number digit must match,
including any stored country code. A longer search never matches a shorter saved number.
Without an extension, all extensions of matching base numbers are included; a supplied extension
must match exactly in both modes. Extensions are never treated as part of the base-number suffix.

### Results and account reads

All matching saved contacts appear in a numbered list with name, ID, first company, emails,
and phones. A canonical phone form is omitted when it repeats the displayed number.
Multiple matches need no selection, including in redirected output. Zero matches
(including a missing ID) produce a zero count and successful exit; read failures remain errors.
The command does not modify contacts. Name, email, phone, company, and label filters read the
account's saved contact matching fields. Label filtering also reads label definitions and adds
memberships to the same paginated contact read, without one request per contact. ID/URL searches
read only the specified contact, even when combined with company or label filters.

## Add-contact

Create one contact from inline fields, or import a JSON file containing one or more contacts.
Possible matches are reviewed before anything is saved.

### Examples

```sh
./contacts-cli add-contact --name 'Jane Doe' --email jane@example.com
./contacts-cli add-contact --first-name Jane --last-name Doe
./contacts-cli add-contact --file contacts.json --label Contacts
```

### Input options

| Option | Purpose |
| --- | --- |
| `--name NAME` | Full name for Google to parse |
| `--first-name NAME`, `--last-name NAME` | Explicit name parts, together or individually; cannot combine with `--name` |
| `--email ADDRESS` | Email for the inline contact; repeatable |
| `--file PATH` | One Person JSON object or an array; cannot combine with inline fields |
| `--label LABEL` | Contact label for selected contacts; repeatable; create if missing |
| `--apply` | Process all inputs and skip final confirmation; duplicate and label choices still prompt |

See [contact input](contact-input.md) for supported fields, JSON examples, and validation.

### Review and saving

1. Review the inputs and possible matches. Single-part names alone do not suggest duplicates;
   complete names, emails, phones, and eligible company-only identities can.
2. Select inputs by original number, or select all. Already-complete inputs can be skipped together.
3. For possible matches, choose Skip, Merge, or Create separately. Merge conflicts offer Keep,
   Replace, or Keep both where multiple entries are supported. Similar changes can be reviewed
   together; label-only updates use compact groups.
4. Confirm the final plan. Review choices have not saved anything yet. Completed writes are
   independently verified.

Noninteractive runs without `--apply` preview only. Noninteractive `--apply` stops on possible
matches or unresolved label choices before writing. Contact-specific failures allow independent
contacts to continue; account, connection, and shared-label failures stop the batch.

The [import guide](importing-contacts.md) covers matching, grouped review, conflict decisions,
label choices, concurrency checks, verification, and partial failures.

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

### Replacing or clearing fields

Omit a field option to keep the source value. Overrides affect only the new contact:

| Field | Replace | Leave empty |
| --- | --- | --- |
| Name | `--name 'Jane Doe'` or `--first-name Jane --last-name Doe` | `--clear-name` |
| Emails | `--email jane@example.com` (repeatable) | `--clear-email` |
| Phones | `--phone '+1 202 555 0142'` (repeatable) | `--clear-phone` |
| Photo | Copied by default | `--no-photo` |

`--name` replaces all name components with a full name (`unstructuredName`) for Google to parse,
just as in `add-contact`. Use `--first-name` and `--last-name` together or individually for explicit
components. Those options also replace the whole original name, so omitted components are empty.
Do not combine `--name` with either explicit component, or `--clear-name` with any name input.
Without any name option, existing editable name components are copied.

Replacement emails and phones replace the entire original list, including its
labels and primary choices. New entries have no labels; Google assigns the primary choice.
Repeat `--email` or `--phone` to supply multiple entries. Surrounding whitespace is stripped from
email/phone values. Names, companies, memberships, and other fields not overridden stay unchanged.

### Validation

Replacement values must be nonblank; use the clear options instead of an empty string.
Emails use the same dotted-domain validation as contact creation; names and wildcard patterns are
not accepted as email values. Phones use the same format validation as contact creation and may
include an extension. Quote values containing spaces. Replacement and clearing options for the
same field are mutually exclusive. Invalid inputs are rejected before authorization.

### Preview and copied data

Preview shows replacement values, explicitly marks cleared fields, lists resulting entry counts,
and states whether a photo will be copied. A cleared field has no entries in the new contact.
Success prints the new contact's link, using the person identifier returned by Google.

Custom fields are copied unchanged, including any existing Created or Duplicate fields.
No automatic creation marker is added.

The copy includes editable contact fields exposed by the People API: names, emails and custom
labels, phones, addresses, notes, dates, organizations, relationships, URLs, custom fields, and
other editable details, including file-as and skills. User contact groups, My Contacts, and Starred
memberships are retained. Unsupported system groups stop creation. Profile-only data, generated
IDs, timestamps, verification flags, and read-only domain memberships are not copied.

### Photos

With `--no-photo`, photo download and upload are skipped, even if the source photo URL is missing
or unsupported. The new contact uses Google's default avatar; its source photo is untouched.
Otherwise, custom photos are downloaded before creation and uploaded in a separate request
afterward. Only HTTPS Googleusercontent photo URLs are accepted, without redirects, with a
10 MiB local limit.
Recognized `/s100/` or `=s100` URL size settings are changed to `s0` to request the full-size
image; other URL options are retained and a conflicting `sz` query parameter is removed.
Unrecognized size formats or failed downloads stop creation, with no thumbnail fallback. This
size-setting behavior was verified experimentally; Google may change it.
Default avatars are generated by Google. Verification confirms a custom photo exists; it does not
compare image bytes or guarantee the original upload resolution.

### Saving and verification

The source contact is never updated. A fresh source read catches changes before creation, but the
read and creation are not atomic. Each `--apply` creates another contact, even with identical flags.
Creation and photo writes retry only explicit transient rate-limit rejections. If the result is uncertain or a photo
write fails, inspect Google Contacts before retrying. The error includes the new contact's link
when available; no automatic deletion or rollback is attempted.

An independent read verifies the resulting editable fields, including replacements and cleared
fields, and retained primary choices after saving. Full names allow Google's generated components;
explicit name parts must be preserved, allowing generated display/full-name representations.
With `--no-photo`, it also checks that no custom
photo is present. Server normalization can cause a conservative verification failure. The same
local 500-entry and 128 KiB limits apply. Existing authorization is reused; this command does not
read Gmail messages.

Sources: [contact creation](https://developers.google.com/people/api/rest/v1/people/createContact), [editable Person fields](https://developers.google.com/people/api/rest/v1/people#Person), and [photo updates](https://developers.google.com/people/api/rest/v1/people/updateContactPhoto).

## Sender-sync preview and apply

The command shows a preview first:

```sh
./contacts-cli sender-sync \
  --label 'Example/Delivery' \
  --contact c123456789
```

Alternatively, supply a Gmail search expression:

```sh
./contacts-cli sender-sync --search 'subject:delivery OR subject:shipment' --contact c123456789
```

### Choosing a message source

Exactly one of `--label` or `--search` is required. Quote the search expression in your shell.
Blank searches are rejected before authorization. Search mode uses Gmail's
[search syntax](https://support.google.com/mail/answer/7190), groups the expression in parentheses,
and appends the same sender exclusions as label mode. Gmail evaluates the query; the CLI does
not validate its complete syntax or independently recheck it against message contents.
Both modes include matching Spam and Trash; explicit query restrictions still apply.
Search mode skips label lookup and label-membership checks. Raw queries are not stored in metrics.

Output identifies the contact and label or search,
shows inspected-message and new-sender counts in progress, then existing email entries and additions.

### Excluding senders

Use repeatable `--exclude ADDRESS_OR_PATTERN` options to skip senders for this run. Matching
ignores case and surrounding whitespace; duplicate inputs are combined. An exact address or a
pattern containing `*` is accepted. `*` matches zero or more characters across the entire address.
Quote patterns in the shell:

```sh
./contacts-cli sender-sync --label 'Example/Delivery' --contact c123456789 --exclude '*@example.com'
```

`*@example.com` matches that exact domain; `*@*.example.com` matches its subdomains.
`*example.com` also matches addresses ending in `notexample.com`. Bare domains, display names,
address lists, and other wildcard syntax (`?`, brackets) are not accepted. Invalid or unsupported
values are rejected before authorization or network access. Exclusions are not saved for later
runs and do not remove addresses already stored in the contact.

Exact exclusions join existing-contact and sending-address exclusions in Gmail queries. Star
patterns are matched locally, never sent as Gmail search expressions. After inspecting a matching
sender, the CLI excludes its concrete address from subsequent searches, so its other messages
are not inspected. This means wildcard exclusions still require a header read for each newly
discovered excluded sender; exact exclusions can avoid those reads. `--exclude '*'` accepts no
new senders but still scans. Inspected counts include these reads; new-sender counts omit excluded
addresses. The query-size limit still applies as concrete exclusions accumulate. Repeated valid
results and unsafe query values still stop the scan. Malformed headers are skipped. Gmail matching
limitations below still apply.

### Exclusion files

Use `--exclude-file PATH` to read a UTF-8 list, one address or pattern per line. Repeat the option
for multiple files and combine it with `--exclude`. Do not put shell quotes around file patterns.
Blank lines, surrounding whitespace, and lines starting with `#` are ignored. A line copied from
the preview may include ` - Display Name` after the address or pattern; that label is ignored.
Inline comments and comma-separated lists are not supported. Files use the same validation and
deduplication as `--exclude`. Missing, unreadable, non-UTF-8 files and invalid entries stop before
authorization; invalid entries report the file and line number. Relative paths use the current
working directory. Files are read fresh each run.

```text
# Excluded senders
ignore@example.com
*@notifications.example.com
another@example.com - Notifications
```

### Search process and progress

The search excludes existing contact addresses and all configured Gmail “Send mail as” addresses,
including your primary address and aliases. It requests one matching message, reads its From
header, and excludes newly discovered addresses from the next search. It stops when no matching
messages remain. For many messages from a few senders, this avoids reading each message header.

Progress appears automatically on stderr: reading the contact and sending addresses, finding the
label when selected, then messages inspected and new senders found. In a terminal, the scan counter
updates in place at most once per second; redirected output uses separate lines at most once every ten seconds. The contact and
label details appear immediately after their lookups, with blank lines separating sections. The
final counts appear in the timestamped `Search finished: …` completion line, followed by the
existing-email count. Counters change as requests finish; the spinner continues while waiting.
There is no estimated total or percentage. Malformed From headers are skipped and logged;
valid senders remain eligible for saving.
The complete preview stays on stdout. Proposed addresses appear one per line without a `+` prefix,
with a custom label after ` — ` when applicable. Counts describe inspected messages, not the total
number of matching messages.

### Selecting and saving senders

In an interactive terminal, choose all eligible addresses or a subset by number/range, then
confirm. One eligible address uses a simple `[y/N]` confirmation. No prompt appears when there
are no additions. See [selection and grouped previews](#grouping-additions-by-address-criteria).

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

### Grouping additions by address criteria

With `--search`, the additions preview separates **Matching address criteria** from **Other
senders** when the query contains usable positive `from:` or `to:` criteria. Only explicitly
supplied criteria contribute; recipients from fetched messages are never used to invent criteria.
This describes address matches, not why Gmail returned a particular message.

#### Recognized search criteria

Supported criteria use lowercase `from:` / `to:` with full addresses or dotted domains,
optionally double-quoted. Parentheses or braces can group values separated by spaces or `OR`:
`from:(one@example.com OR two@example.com)`. Groups such as
`{from:example.com to:example.org}` also contribute. Each recognized criterion is an alternative
for classification, regardless of the broader query's Boolean logic.

Matching ignores address case. A domain includes its subdomains: `example.com` matches
`person@mail.example.com`, but not `person@notexample.com`. Full addresses match exactly;
dot variants and plus tags remain distinct.

Negated criteria/groups (`-` or `NOT`), other fields, quoted search text, names, `me`, wildcards,
and unsupported address forms do not contribute. A field group containing unsupported values,
nested fields, or negation is skipped as a whole. Unbalanced quotes/groups or nesting beyond
32 levels disable grouping for the query. This conservative extraction does not validate or alter
the actual Gmail query.

#### Grouped preview

The overall total appears first, followed by both group totals and numbered rows. Numbering
continues across groups; order within each group follows the normal sorted additions. Empty
groups show zero. When there are no usable criteria, search runs with additions retain a single
list with this explanation below the total:
`Ungrouped: no full addresses or domains in from:/to: criteria.`

With `--label`, the preview shows one list of sender addresses. A label can contain messages
from unrelated senders. The command cannot determine which addresses matched the filter that
applied a label. Use `--exclude` or `--exclude-file` to skip particular addresses, or use
`--search` with full addresses or domains in `from:`/`to:` criteria to separate matching
addresses from other senders. Label runs do not fetch Gmail filters or ask about them.

#### Choosing sender groups

In search mode, both groups start included. In interactive runs, when Other senders is nonempty,
the command asks `Exclude Other senders? [y/N]` before final write confirmation. Yes selects only matching
addresses; Enter or No keeps both. Invalid answers repeat the question; end-of-input cancels
without writing. A summary names the available groups and skipped addresses.

After exclusions, both label and search runs offer partial selection when more than one address
remains:

```text
Choose addresses:
  all     Select all
  3-5,8   Select by number or range
  q       Cancel
Selection:
```

See [numbered selections](#numbered-selections) for range syntax and sparse numbering.

A subset preview keeps original numbers and shows its total. Selecting all does not repeat the
list. Final confirmation offers Yes to add, No or Enter to return to selection, and `q` to cancel.
With just one available address, only `Add this address to this contact? [y/N]` is shown;
No or Enter cancels. Selecting one address from several still offers Return to selection. Zero eligible addresses
means no selection or confirmation. Selection affects only this run and does not save exclusions.

#### Excluding other senders with a flag

Use `--exclude-other` to explicitly exclude that group without the selection question:

```sh
./contacts-cli sender-sync --search 'from:example.com OR subject:delivery' --contact c123456789 --exclude-other
```

Without `--apply`, final confirmation is still required in a terminal; noninteractive runs
only preview. With `--exclude-other --apply`, only matching additions are saved. With
`--apply` alone, both groups are saved without an exclusion question. Noninteractive runs never
ask selection questions; without the flag, both groups remain selected.

With the flag, the additions total counts only matching entries and the second group is marked
`Other senders (excluded)`. No Other senders means no group-exclusion question. Excluding all
candidates reports `No additions selected; no update made.` and skips final confirmation.
Existing contact entries and manual exclusions are preserved.

`--exclude-other` requires `--search` with usable positive full-address/domain criteria.
Using it with `--label`, or with a search lacking those criteria, fails before authorization or
account access. The flag is never silently ignored. Runs without additions omit the fallback
explanation.

For a query starting with a minus sign, use `--search='-from:person@example.com subject:delivery'`
so the shell argument is passed as the search value.

## Sender-sync behavior and limits

### Sending identities and Gmail labels

- Each sync reads Gmail's [Send mail as list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings.sendAs/list)
  once, using the existing `gmail.readonly` permission. No new authorization scope is needed.
  Retrieval errors, missing primary identity, or malformed addresses stop before searching or
  writing. Configured sending addresses are excluded from both searches and parsed candidates.
  Addresses already stored in the contact remain unchanged; this feature does not remove them.
- Gmail label selection prefers an exact name, even when other case variants exist. Without an
  exact match, an interactive run offers a single case-only match with `[Y/n]` (Enter means Yes),
  or a numbered choice of multiple matches plus Cancel command. Declining or end-of-input cancels
  before message searches or contact writes. Missing labels report “was not found”; this command
  never creates Gmail labels. Noninteractive runs require exact spelling and report case-only
  alternatives. `--apply` skips final write confirmation but still requires resolving label choices.
  The selected spelling appears in the Label heading. Searches include labeled Spam and Trash.
  Only individual messages carrying the selected label are considered; unrelated messages in the
  same conversation are excluded.

### Sender parsing and saved labels

- `From` is the source, not `Reply-To`, `Sender`, or the envelope sender. Display names, comments,
  folded headers, and multiple valid mailboxes are parsed. Encountered missing, duplicate,
  malformed, or unsupported headers are skipped and reported by message ID. Other valid senders
  remain eligible for selection and saving, including with `--apply`. Raw headers are saved in
  local diagnostic files, not printed. See [malformed-message logs](error-logs.md#malformed-message-headers).
  The completion line includes the skipped-message count; skipped messages contribute no addresses.
  Internationalized local parts that the Python parser reports as defective are unsupported.
- Comparison ignores case and surrounding whitespace. Gmail dot variants and `+tags` remain
  distinct. New entries retain the first observed spelling. The display name from the inspected
  From header becomes the new email's custom label, shown as `address@example.com — Display Name`.
  Without a display name, or when it matches the email address, any contact display name, or any
  company name ignoring case and surrounding whitespace, the address is shown and saved without
  a custom label. Both names and companies are checked even when the contact has both. The search does not
  fetch other messages to look for alternate names. Existing values, labels, display names, and
  explicit source-primary choices are retained. If no email had an explicit source-primary choice,
  Google assigning one during saving is allowed. Saved additions are checked for their proposed labels.

### Contact reads and updates

- The People API is read directly using `getBatchGet`, with contact-only sources and an explicit
  field mask. Profile-only data is not copied. Multiple editable contact sources and
  incomplete/error responses are rejected. Full-list retrieval relies on Google's documented API
  contract; there is no independent count to detect silent server omissions.
- Only `emailAddresses` is updated. A fresh read and source etag protect against concurrent edits.
  Conflicts stop the run; they are not automatically merged or retried. The response and an
  independent subsequent read are checked for additions and preservation.

### Size and query limits

- Local guards reject projected contacts over 500 top-level field entries or 128 KiB of JSON, and
  new addresses over 1,024 characters are rejected by parsing. These are estimates, not Google's
  internal storage accounting; the server may reject a smaller contact. Existing oversized contacts
  can still be processed as no-ops.
- Exclusions use quoted full addresses. Unsupported address syntax stops the run instead of being
  inserted into the search query. A local guard limits the entire URL-encoded query, including the
  base search, to 6,000 bytes. This is a conservative CLI limit, not a documented Google maximum.
  Exceeding it stops before writing.
  API errors also stop the run; partial discoveries are never applied after a search failure.

### Mailbox changes and incomplete searches

- Gmail search is not an atomic mailbox snapshot. Messages arriving or being relabeled during a
  search may require another run. A deleted message or observed loss of the selected label aborts
  the search. Repeated valid message IDs or results with no new sender also stop it before any write.
  For malformed messages, the CLI follows the next result page with the same query, remembering
  skipped IDs to avoid repeated header reads/logs. After finding a valid sender, it restarts with
  updated sender exclusions. Page tokens are never reused with a changed query; repeated or invalid
  tokens stop the run. Skipped results can require additional searches after each restart.
- This relies on Gmail's sender matching, rather than inspecting every header. Excluded messages
  are not checked for malformed headers or additional authors. The multiple-author case is deferred
  in [issue #4](https://github.com/stansult/contacts-cli/issues/4). Gmail matching of unusual addresses remains subject to live verification.

### Request counts and retries

- Requests are sequential: normally one header read and one search per new sender, plus a final
  empty search and contact/label requests. When most messages have different senders, this can use
  more requests than the old full scan. Local metrics allow comparisons with the previous baseline.
- Gmail reads allow up to three retries. People API reads and writes retry only explicit
  transient rate-limit rejections. After an uncertain write or failed verification, inspect the contact and run a new
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

`add-email` accepts repeatable `--add 'address - Label'` and `--add-file PATH` options.
`remove-email` accepts repeatable `--remove ADDRESS` and `--remove-file PATH` options.
Both require `--contact`. Add-email also accepts `--from-url` instead of individual/file inputs.
Remove-email also accepts `--duplicates` instead of individual/file inputs.
Otherwise, at least one individual or file option is required. Use the same UTF-8 file
format as exclusions: one address per line, optional ` - Label`, blank lines and whole-line `#`
comments. Options combine; files are read fresh relative to the current directory. An empty file
requests no changes. Removal ignores labels and matches addresses case-insensitively.
Use a space on each side of the keyboard hyphen: `address@example.com - Label`.
The same parser accepts spaced en/em dashes for compatibility with pasted preview output.
Hyphens inside addresses and dashes within labels are preserved. This applies to inline
add/remove inputs and addition, removal, and exclusion files.

### Removal patterns

Removal also accepts `*` patterns in both `--remove` and `--remove-file`. `*` matches zero or
more characters, case-insensitively against the whole address. Only `*` is supported; `?` and
bracket patterns are not. Quote patterns on the command line to prevent shell expansion:

```sh
./contacts-cli remove-email --contact c123456789 --remove '*@example.com'
```

- `*@example.com` matches that exact domain.
- `*@*.example.com` matches its subdomains, not the base domain.
- `*example.com` matches any suffix, including `person@notexample.com`.
- `abc*@example.com` matches both `abc@example.com` and `abcdef@example.com`.
- `*` matches every email address on the contact.

In files, write patterns without quotes, one per line. Optional labels are ignored, just as for
exact removals. Patterns expand against the contact read for the preview. Overlapping patterns
and exact addresses include each stored entry once. Each duplicate is separately selectable.
Selection uses those snapshot entries, not a new pattern search. A contact changed
after preview is rejected before writing. With `--apply`, every matching entry is removed.
Add-email requires exact addresses. Sender-sync exclusions accept the same `*` patterns; see
[exclusion inputs](#sender-sync-preview-and-apply).

These commands read contacts directly; they do not search Gmail or exclude your sending identities.
They reuse the saved authorization. Address parsing is shared with exclusions, but Gmail query
syntax restrictions and query-length limits do not apply to direct contact edits.

### Remove duplicate email entries

```sh
./contacts-cli remove-email --contact c123456789 --duplicates
```

`--duplicates` finds repeated addresses, ignoring case. It cannot be combined with `--remove`
or `--remove-file`. Dots and plus tags remain significant; distinct addresses are never combined.

For each repeated address, keep the primary entry; if none is primary, keep the first stored
entry. If several are marked primary, keep the first of those. Differing labels or display names
do not make addresses distinct: the extra occurrences are still offered for removal.
The retained entry keeps its original spelling, label, and metadata.

The preview numbers only extra occurrences as removal choices. A separate **Kept entries**
list shows the retained occurrences and primary markers; its numbers cannot be selected.
Select `all` or numbers/ranges, then confirm. Unselected extra occurrences remain unchanged.
One extra occurrence uses a simple confirmation. With no duplicates, nothing is written.

`--apply` removes all proposed extra occurrences without prompting. Noninteractive runs without
it only preview. Unique addresses and other contact fields stay unchanged. The same concurrent
edit protection and verification used for ordinary removal apply.

### Addition conflicts

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

Conflict menus put each option on its own line. For a single match, its choices are indented
beneath the entry, separated by a blank line. Choices affecting a duplicate group or all remaining
conflicts stay outside individual rows. Choose `r` to apply the described label change
or duplicate consolidation, or `k` or Enter to keep the existing entries. The prompt spells out
the Enter default; keeping an entry continues the command rather than cancelling it.
When more existing-email decisions remain, `a` applies requested labels and duplicate consolidation
to this and remaining conflicts; `s` keeps existing entries for this and remaining conflicts.
New addresses and already-identical entries do not count as remaining decisions.
Keeping existing entries does not cancel new additions. When only one new addition is selected,
the final confirmation names its address.
The earlier `y`/`n` keys still work as aliases for `r`/`k`.
Batch choices apply to current and remaining stored-entry conflicts, not unrelated
new additions. End-of-input keeps remaining conflicts. After these choices, the final preview
lists kept entries under **Unchanged**, proposed changes, and remaining email entries. Interactive
runs then select changes by number before final confirmation.

`--replace-existing` approves all stored-entry conflicts but still requires final confirmation
unless `--apply` is also supplied. With `--apply` alone, existing conflicts are preserved and
reported while non-conflicting changes are saved. Noninteractive runs do not ask conflict questions;
without `--apply` they only preview. Existing entries kept without replacement are shown under
**Unchanged**, with their saved labels.

### Removal groups and missing addresses

Removal lists every matching stored entry with its own selectable number, including case-only
or completely identical duplicates. Select just one duplicate to preserve the others. Each row
shows its stored address, label when present, and a `(primary)` marker when applicable.
The heading counts both entries and distinct addresses.
Absent addresses and unmatched patterns are listed under Not found. Removing every email is
allowed and leaves the contact intact with zero email entries. A no-op performs no update. Later
sender-sync runs can add matching senders again. Addresses and patterns from the removal list
can be reused with `--exclude-file` to skip those senders in later runs.

### Selecting email changes

Interactive add/remove runs use `all`, numbers/ranges such as `3-5,8`, or `q` to cancel.
Additions and updates have continuous numbering; each update (including duplicate consolidation)
is indivisible. Removal numbers select individual stored entries. Not found uses separate,
nonselectable numbers after the proposed changes. Its informational note is omitted when there
are no proposed removals. Unchanged entries
are listed without selection numbers before proposed changes.
Subset previews retain original numbers and recalculate remaining email entries. Only selected
changes are applied; unselected entries retain their original labels, duplicates, and metadata.

No or Enter at final confirmation returns to selection without repeating label-conflict decisions.
With one eligible change, a simple `[y/N]` confirmation replaces selection. Multiple matching
email entries offer selection even when they share the same address. Zero changes means no prompt.
A smaller selected subset is checked
against size limits independently of the full proposal. `--apply` saves all eligible changes,
respecting the existing conflict rules; noninteractive runs without it remain preview-only.

### Saving email changes

Only emailAddresses is written. Other contact fields and retained email metadata are preserved.
A fresh read and etag check reject concurrent changes. Only explicit transient rate-limit
rejections can retry; uncertain writes are never replayed.
Both the response and an independent read verify the complete expected email list and labels.
If the primary email is removed, Google may assign primary status to a remaining entry; this is
allowed, while a surviving primary choice must be preserved. Failed verification reports an
unverified update. These commands are not undo; [issue #5](https://github.com/stansult/contacts-cli/issues/5) tracks that separate enhancement.

### Webpage email input

```sh
./contacts-cli add-email --contact c123456789 --from-url 'https://example.com/contact'
```

Reads one public HTTP/HTTPS page without Google credentials or browser cookies. Redirects are
followed (up to five); linked pages are not crawled. The fetch has a 15-second total deadline,
including DNS and redirects, and a 2 MiB limit on the final decompressed HTML body. Non-HTML
responses and HTTP errors stop before Google authorization or contact access. URLs with embedded credentials are
rejected. Empty results also stop before accessing Google.

Extracts addresses from text and `mailto:` recipients, deduplicates case-insensitively, and sorts
by address. Mailto subject/body/cc query parameters are ignored. Scripts, styles, comments,
templates, page-head content, and explicitly hidden elements are ignored. This is static HTML
parsing, not browser rendering: external CSS visibility, JavaScript-generated content, obfuscated
addresses, and addresses split across markup are not reliably supported. Results can be incomplete;
review the numbered preview. No labels are inferred.

`--from-url` cannot combine with `--add`, `--add-file`, or `--replace-existing`. Unlike a bare
address supplied through those other inputs, an extracted address carries no label-change request.
Addresses already on the contact are skipped; all existing labels and duplicate entries remain.

Interactive runs show only new addresses as numbered proposed additions. They use the same
single-step selection prompt and final confirmation as
[sender-sync](#grouping-additions-by-address-criteria). Enter `all` or numbers and ranges directly;
a subset preview retains original numbers. Selecting all does not repeat the list. One available
address goes straight to confirmation.

Noninteractive runs preview all additions without prompting or writing. `--apply` selects and saves
all new addresses without selection or confirmation. Existing conflict protection and independent
readback verification still apply. No Gmail search or sending-address exclusions are involved.

## Email list display

Email lists use a heading with a total followed by aligned, numbered rows. Labels appear only
when present. This applies to sender-sync additions and the direct email editing commands,
including missing addresses. Unchanged entries use a total and unnumbered rows. Addition rows do not repeat “Add.” Updates
have a separate section describing the action beneath each address:
`Remove label: Work`, `Change label: Work → Personal`, or `Add label: Work`.
Duplicate consolidation says `Combine 3 entries into one` and gives the resulting label
(or `none`). Entry counts are omitted when only a label changes.
When every update removes a label, the heading says **Proposed label removal(s)**.
The zero-additions heading is hidden when updates exist. A single-update confirmation names
the label action or duplicate consolidation, including when selected from a larger list.

Use `list-email` to see all existing entries. Add/remove commands show only the existing total;
existing entries are displayed when needed for a conflict decision. Conflict-match lists start at 1. Proposed additions and updates share continuous numbering;
removal previews number individual stored entries. Sender-sync numbering continues across
its two address groups. Duplicate references in list-email and conflict lists point to the first
occurrence within that list; removal previews show each entry separately. Numbers do not identify
a preferred or primary address.

Without `--apply`, change headings say Proposed additions, Proposed updates, or Proposed removals.
With `--apply`, they say Adding, Updating, Removing, or Removing labels. These headings describe the requested action;
only the final Saved and verified message confirms success.

Email previews omit a display name that equals the email address, ignoring case. A different
display name remains visible. This affects presentation only; saved contact data is preserved.

## List-phone and remove-phone

```sh
./contacts-cli list-phone --contact c123456789
./contacts-cli remove-phone --contact c123456789 --duplicates
./contacts-cli remove-phone --contact c123456789 --duplicates --apply
```

Both commands require a [contact identifier](#contact-identifiers). Silent plural aliases `list-phones` and
`remove-phones` are accepted. `remove-phone` currently requires `--duplicates`; removal by
number, patterns, and input files is not supported. There is no `add-phone` command yet.

### Listing and duplicate matching

`list-phone` shows all phone entries with their labels and primary status. Later occurrences
of the same normalized number reference the first displayed occurrence: `[duplicate of #1]`.
That reference describes repetition, not which entry removal will retain.

Duplicate detection uses these rules:

- Ignore formatting and an optional leading `+`, keeping every base-number digit.
- Prefer Google's canonical number when available. For example, a saved `(202) 555-0142`
  whose canonical form is `+12025550142` matches a saved `+1 202-555-0142`.
- Without that canonical form, `2025550142` does not match `+12025550142`. There is no suffix
  matching or country inference for removal.
- Preserve extensions from the original value even when the canonical form omits them.
  Different extensions, and a number with versus without an extension, are distinct.
- Labels do not affect duplicate identity. Unparseable numbers and conflicting extension
  information are excluded from duplicate removal and remain visible in listing.

### Selecting and saving removals

For each duplicate group, keep its first primary entry, or its first stored entry when none
is primary. Show extra occurrences as numbered removal choices and kept entries separately as
informational rows. Each selectable number represents one stored occurrence, including identical
copies. Choosing a subset leaves all unselected occurrences unchanged; kept entries cannot be selected.

Multiple choices use the shared all/number/range selection and final confirmation. A single extra
entry uses a yes/no confirmation. Return-to-selection and cancellation follow the usual rules.
Noninteractive runs without `--apply` only preview. `--apply` removes every proposed extra.
No duplicates means a successful no-op.

Saving rereads the contact and rejects changes since preview. Only `phoneNumbers` is updated.
Verification checks the exact retained values, labels, counts, primary choices, contact identity,
and unrelated contact fields, both in the update response and an independent readback.
Generated canonical forms and translated labels may change without a verification failure.
Verification failures report an unverified update; they do not retry the write.

## Format-phone

```sh
./contacts-cli format-phone --contact c123456789
./contacts-cli format-phone --contact 'Jane Example' --contact c123456789
./contacts-cli format-phone --contact-file contacts.txt
./contacts-cli format-phone --contact c123456789 --contact-file contacts.txt --apply
```

Standardizes phone values on one or more contacts. Repeat `--contact`, supply one `--contact-file`,
or combine them. Files use the [shared identifier-list format](batch-contacts.md#inputs-and-matching).
Inline inputs precede file entries. IDs, URLs, full names, emails, and complete phones are accepted.
Resolved contacts are deduplicated, so overlapping inputs never update a contact twice.
The silent plural alias `format-phones` is accepted. There is no `--format` option on other commands.

Ambiguous identifiers offer one, several, or all matching contacts; `s` skips the identifier and
`q` cancels the command. Unmatched identifiers and missing IDs are reported and skipped.
Noninteractive ambiguity stops before writes, even with `--apply`.

### Formatting rules

- Uses readable international formatting with country-specific grouping, such as
  `+1 202-555-0142` or `+44 20 7946 0018`.
- Writes extensions as `ext. N`, preserving their digits, including leading zeros.
- Uses Google's saved canonical number when available; otherwise requires an explicit `+`
  international number. It never guesses the country for a local number.
- Leaves unsupported text, unknown country codes, impossible lengths, conflicting extensions,
  and disagreeing international/canonical numbers unchanged, with a reason.
- Uses the local `phonenumberslite` library. Plausible length is checked; formatting does not
  establish whether a number is assigned or active. Formatting itself makes no network calls.

### Review and saving

All contacts are read and planned before saving. The preview groups before/after changes under
stable contact headings. Selectable numbers refer to phone entries, not contacts: entry numbering
continues across contacts, counting unchanged entries too, so gaps are expected. On one contact,
these remain its original phone positions. Unsupported entries are informational; contacts needing
no changes appear separately.

Choose all or individual phone-entry numbers/ranges, then confirm once for the selected batch.
A single change uses a yes/no question. Noninteractive runs without `--apply` only preview;
`--apply` saves all proposed formatting. Already formatted entries need no write.

Saving updates each selected contact once and reports progress out of the selected contact count.
Explicit contact rejection, stale previews, or contact-specific verification mismatches are reported
and other contacts continue. Connection, authorization, unrecovered quota, uncertain write outcomes,
and interruption stop the batch. A failed verification read is an uncertain result, not a safe retry.
The completion summary separates verified, failed, unverified, and unattempted contacts, plus unchanged,
unselected, and missing contacts. Any failure returns nonzero; completed changes remain saved.
See [shared outcomes](batch-contacts.md#saving-and-outcomes).

Formatting preserves labels, primary choices, duplicate occurrences, and unrelated fields; it
never removes duplicate numbers. Saving uses the same reread, concurrent-edit protection, and
response/readback verification as [phone removal](#list-phone-and-remove-phone).

## List-label

```sh
./contacts-cli list-label
./contacts-cli list-label --contact c123456789
```

Without `--contact`, lists all account user labels with their total contact counts, including
`0 contacts` for empty labels. Counts come from the same paginated label request, without
reading individual contacts. If a returned count is malformed, the row says `count unavailable`.
With `--contact`, shows the contact and only labels applied to it, without counts. Both lists have a total and numbered rows,
sorted alphabetically without regard to case. Original spellings remain visible.
System groups and deleted labels are omitted. An empty list shows `Labels: 0 labels`.
The command only reads data, never prompts for a write, and has no `--apply` option. The silent
alias `list-labels` is accepted. Global options work before or after the command.

## Add-label

```sh
./contacts-cli add-label --label Recruiter --label Follow-up
./contacts-cli add-label --contact c123456789 --label Recruiter --label Follow-up
```

### Creating account labels

Without either contact option, creates account labels without reading or editing any contact. Existing
labels appear under `Already exists`; only missing labels are proposed for creation. If all
requested labels exist, no changes are made. Confirmation asks only about creation; `--apply`
creates all missing labels. Each creation is independently verified. On failure or interruption,
creation stops, reports verified and unattempted counts, and leaves completed creations saved.
List account labels before retrying. For case-only collisions, choices explicitly say
`Keep 'test1'; skip creating 'TEST1'`, `Create 'TEST1' as a separate label`, or `Cancel command`.
Keeping an existing label creates nothing; it is not applied to any contact.

### Contact identifiers and files

With `--contact`, identify a saved contact by Google Contacts URL, bare ID, full name, email,
or phone. Repeat `--contact` and optionally combine it with `--contact-file contacts.txt`.
Inline identifiers are processed first, then file entries; each resolved contact is processed once.
Files are UTF-8 plain text (a BOM is accepted), one identifier per line; blanks and lines
starting with `#` are ignored. This is an identifier list, not the Person JSON used by `add-contact`:

```text
# Contacts to label
c123456789
Jane Example
jane@example.com
+1 (202) 555-0142 ext. 42
```

### Contact matching rules

Names match the complete saved name, ignoring case and extra whitespace. Emails match the complete
address, ignoring case; no substring or wildcard matching. Phone punctuation and an optional
leading `+` are ignored. All base-number digits, including country codes, must match.
Without an extension, the input matches every saved extension of that base number, including
numbers without an extension. Multiple matching contacts require selection. Supply an extension
to require that exact extension: `12025550142 x42` matches the example above, while
`12025550142 x43` does not. `12025550142` also matches it; `2025550142` does not.
No country is inferred; `00` is not converted to `+`.
The same complete-identifier rules apply to single-contact commands. Import duplicate matching
is unchanged.
Names, emails, and phones use one paginated read of saved contacts; IDs avoid that account-wide read.
Company-only lookup is not supported; use an ID, email, or phone for an unnamed company contact.

### Resolving contacts

Single matches appear in numbered groups with name, ID, company when present, and the matching
email or phone once on the same line. Unrelated addresses and phones are omitted. Name matches
omit the input when it repeats the displayed name. Each group has one timestamped heading.
Multiple matches show the input once in the heading and name, ID, and company in each row,
then allow one, several, or all
through the shared number/range selector. At this matching prompt, `s` skips just the current
identifier and continues through the file; `q` or end-of-input cancels the entire command before
changes. Skipping does not remove earlier selections or prevent the same contact from matching
a later, different identifier; a message explains when that happens. If nothing remains selected,
no labels are created or applied. A completed resolution prints reviewed-input, matched,
unmatched, and skipped-by-choice counts, plus the distinct contact count. Repeated file entries
are deduplicated before review. Supplied IDs are counted separately until the following contact
read validates them. Unmatched inputs are grouped separately from contact choices.
Repeated identifiers and overlapping selections resolve
to each contact only once. Unmatched identifiers and IDs explicitly reported as not found are
reported and skipped; resolved contacts continue to preview and confirmation. If none remain,
the command exits successfully without creating labels or changing contacts. Connection,
authorization, and incomplete-read errors still stop before changes. No contacts are created.
Noninteractive ambiguity stops even with `--apply`;
use explicit IDs or rerun interactively.

### Selecting contacts to label

For multiple resolved contacts, identical label additions appear once in the heading rather
than on every row. When additions differ, each row retains its own label details. The selection
prompt says “Choose contacts to label,” and final confirmation names the labels.
The numbered preview shows labels to add; unchanged contacts
are reported separately. Contacts keep their original numbers across matching, unchanged,
proposed, and selected lists, including across file identifiers. Numbers are assigned when a
contact is first encountered; repeated matches reuse that number. Filtering leaves gaps rather
than renumbering, and only numbers in the current selectable list can be selected.
Choose all or a subset and confirm once. `--apply` uses all resolved
contacts. Label spelling is resolved once for the batch, and missing labels are created once.
Cancelling at any selection stage makes no changes. Noninteractive runs without `--apply` preview
only. Single-contact output retains its existing label preview.

### Label spelling and preview

Repeat `--label` for more labels. Label names match exactly and case-sensitively. The shared
[case-collision choices](importing-contacts.md#contact-labels) offer existing labels, create new,
or cancel. `--apply` skips final confirmation but not label choices; unresolved noninteractive
collisions stop. See [label choices and output](#label-choices-and-output) for membership-aware wording.

The preview separates labels already on this contact from proposed additions, with totals
and numbered rows. New labels appear once, marked `(new label)`. If every label is already on
the contact, the command makes no changes. Otherwise it
asks once before creating labels or adding memberships. Noninteractive runs without `--apply`
preview only.

### Saving label additions

The CLI uses Google's additive group-membership operation, sending no membership removals or
contact-field replacement. Existing memberships and other contact fields are preserved. It rereads
the contact before each addition, skips memberships applied since preview, and independently reads
back afterward to check the added label and prior memberships. A stale contact identity is a
contact-specific failure.

After approval, all missing labels needed by selected contacts are created and verified before
any contact is changed. Shared-label creation failure stops; created labels remain saved.

Contacts are processed sequentially with a progress counter. Explicit contact-specific failures
and saved-content verification mismatches are reported, and later contacts continue. Shared-label,
authorization, connection, unrecovered quota, uncertain-write, and verification-read failures stop.
Only explicit transient rate-limit rejections retry automatically.

The summary separates verified, failed, unverified, and unattempted contacts, plus unchanged and
unselected contacts when applicable. A contact is verified only if every selected label is
satisfied. If an addition fails midway, the output names labels already verified on that contact,
the failed or unverified label, and labels not attempted. Completed changes remain saved.
Saved additions and labels applied concurrently since preview are counted separately.

Exit status is 1 for failures, 3 for unverified writes, or 130 for interruption. Inspect uncertain
results before retrying; a new preview skips labels already applied. HTTP errors use shared local
error logs. See the [shared batch rules](batch-contacts.md). No Created or Duplicate field is added.

API contract: [modify contact group members](https://developers.google.com/people/api/rest/v1/contactGroups.members/modify).

## Remove-label

```sh
./contacts-cli remove-label --contact c123456789 --label Recruiter --label Follow-up
```

Removes selected labels from one existing contact without deleting label definitions or changing
other contacts. Repeat `--label` with literal names or quoted `*` patterns:

```sh
./contacts-cli remove-label --contact c123456789 --label 'Recruit*' --label 'Follow-up'
```

### Label removal patterns

`*` matches zero or more characters across the whole name, ignoring case. Other characters,
including `/`, `.`, `+`, `?` and brackets, are literal. Quote patterns to prevent shell expansion.
`--label '*'` offers every applied user label; Google system groups and deleted labels are excluded.
A name containing `*` is interpreted as a pattern, with no separate literal-star escape syntax.

### Matching labels on the contact

Literal names offer both exact and case-different matches without a case-choice prompt. The
preview groups Exact matches, Matching patterns, and Similar labels (case differs), omitting empty
groups. Only labels on this contact can be selected. Overlapping requests count a label once;
an exact literal match takes display priority over a pattern, then a case-only match. Numbering
is continuous. Labels absent from this contact are omitted, whether requested by name or
pattern. If none match, the command says `No matching labels on this contact; no changes made.`
Use `list-label` without `--contact` to inspect account labels separately.

### Selecting label removals

Choose `all`, numbers/ranges such as `1,3-5`, or `q`. A subset preview keeps original numbers;
final confirmation uses the selected count. `n` or Enter returns to selection; `q` or EOF cancels.
One eligible label uses a simple `[y/N]` confirmation; no candidates means no write. `--apply`
removes all candidates, including case variants, without selection or confirmation. Noninteractive
runs without it preview only. Patterns expand once for the preview, never again during writes.

### Saving label removals

Each request removes only this contact from one label. A fresh contact read checks identity and
current memberships before the write; a label removed since preview is skipped. Independent
readback verifies the removed label is absent and other memberships remain. Other contact fields
are never sent for replacement. Labels themselves remain, even if empty. Google may refuse removal
of a contact's last contact-group membership; that refusal is reported and processing stops.

On errors or interruption, verified removals remain saved and later removals stop. Mutation requests
retry only explicit transient rate-limit rejections. Inspect the contact before retrying; a fresh preview skips labels
already removed. Shared [error logs](error-logs.md) capture failed HTTP responses.

## Label choices and output

For `add-label --contact`, label lookup distinguishes existence anywhere in Google
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
  1. Keep 'Recruiter' already on this contact; add nothing
  2. Create 'recruiter' and add it to this contact
  3. Cancel command
Choose 1–3 (Enter = 1, q = cancel):
```

For a case-only match not on the contact:

```text
Label 'Recruiter' exists in Google Contacts, but isn't on this contact.
Its spelling differs only by case from 'recruiter'.
  1. Add existing 'Recruiter' to this contact
  2. Create 'recruiter' and add it to this contact
  3. Cancel command
Choose 1–3 (Enter = 1, q = cancel):
```

If several case-only alternatives exist, each choice identifies whether the label is already
on this contact, exists elsewhere and can be added, or must be created and added. Existing labels
on the contact are preserved by every choice. The prompt shows the numbered range and the default
selected by Enter. In all label case-choice menus, `q` (also `Q`) and the numbered Cancel command option both cancel the entire command
before writes.

### Removing labels

Exact and case-different labels on the contact are both selectable. Pattern matches join the
same numbered removal plan. There is no preliminary case-resolution menu; labels absent from
the contact are omitted. See [remove-label](#remove-label) for matching and selection.

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
./contacts-cli add-custom-field --contact c123456789 --field 'Pipeline ID' P-001
./contacts-cli remove-custom-field --contact c123456789 --key 'Pipeline ID' --value P-001
./contacts-cli remove-custom-field --contact c123456789 --key Duplicate
```

### Adding custom fields

These commands edit custom key/value entries (`userDefined` in Google Person JSON).
Addition requires repeatable `--field KEY VALUE`, with exactly two arguments per occurrence:

```sh
./contacts-cli add-custom-field --contact c123456789 \
  --field status active --field Status active --field Status Active
```

Quote keys or values containing spaces. Missing arguments, empty/blank text, and control characters
are rejected before Google access. A following `--field` cannot supply a preceding pair's missing
value. The old addition syntax `--key KEY --value VALUE` is no longer accepted; replace it with
`--field KEY VALUE`. Repeated identical input pairs count once, preserving input order. Existing
exact pairs are skipped without consolidating their stored duplicates. Case-different pairs are
separate additions. All supplied pairs are validated, including any later left unselected.

### Removing custom fields

Removal retains required `--key` and optional `--value`. Supplying a value
limits candidates to that key/value pair and its case variants; omitting it offers all values
under the key and its case variants.
Removing a selected pair removes all its identical duplicates. Removing `Created` or `Duplicate`
affects only those stored custom fields, not the contact itself. These markers receive no special treatment.

### Custom-field matching rules

Addition matches exactly and case-sensitively; case-only similarities remain informational.
Adding an exact pair already present skips it, preserving stored duplicates. A different value
under the same key is appended, never used as a replacement. Removal offers both exact matches
and case-insensitive matches for the key and optional value, without a case-resolution prompt.
Whitespace is preserved; supplied keys and values must be nonblank and contain no control characters.
There is no file input, replacement option, or wildcard selector.

### Custom-field previews and selection

The removal preview shows the total candidate entry count, then **Exact matches** and
**Similar entries (case differs)**, omitting empty groups. Both groups are selectable with continuous
numbering and stored spelling preserved. Identical key/value duplicates share one number and
show their count, such as `Pipeline ID — P-001 (2 entries)`. Different spellings stay separate
choices. Totals count entries, not groups. Neither addition nor removal displays existing or
remaining custom-field counts. A removal with no candidates reports a no-op.

With multiple matching pairs, choose `all`, numbers/ranges such as `1,3-5`, or `q` to cancel. A
subset preview keeps original numbers. Final confirmation uses the full selected entry count;
`n` or Enter returns to selection, and `q` or end-of-input
cancels without writes. One matching pair uses a simple `[y/N]` confirmation, even when it has
duplicates. Selecting one pair from several still offers Return to selection. All its duplicate
entries are removed together. Unselected fields, including their order and metadata, are retained.

Addition also offers `all`, numbers/ranges, and `q` when multiple new pairs are proposed, followed
by confirmation. Subsets keep original numbers; `n` returns to selection. A single new pair uses
simple `[y/N]` confirmation; no new pairs means no prompt or update. `--apply` adds every new pair
without selection or confirmation. Unselected pairs are not added, and existing fields stay intact.

Noninteractive runs preview only unless `--apply` is supplied. For removal, `--apply` removes all exact and case-different matches without
selection or confirmation; headings use Adding/Removing. The silent aliases `add-custom-fields`
and `remove-custom-fields` are accepted; help uses singular names.
Both commands accept the [global options](#global-options) before or after the command.

### Saving custom-field changes

The update sends only the complete intended `userDefined` list and contact source metadata.
Unmatched custom fields are retained, as are other contact fields. A fresh read and source etag
protect against concurrent changes; conflicts stop rather than merging or retrying. The response
and an independent read must both match the expected custom fields (including duplicate counts)
and preserve the other fields in the contact read mask. Verification errors report an unverified
update: inspect the contact before retrying. The shared local size guards, API error logging,
interrupt handling, and exit codes apply. Only explicit transient rate-limit rejections can
retry; uncertain writes are never replayed.

API contract: [updateContact field masks and source etags](https://developers.google.com/people/api/rest/v1/people/updateContact).

## Validate-contact

`validate-contact --file PATH` checks a UTF-8 contact JSON file locally using the same validator as
`add-contact`, then reports the contact count. Authorization, prompts, and Google access are not
needed. Inline fields, labels and `--apply` are not supported. See [local validation](contact-input.md#validate-a-file-locally).

## Authorization

See [detailed Google setup instructions](google-setup.md). Existing `gmail.metadata` authorizations need upgrading to
`gmail.readonly`; the CLI detects insufficient permissions and offers browser reauthorization.
See [upgrading an existing authorization](google-setup.md#upgrading-an-existing-authorization).
If Google rejects an expired or revoked refresh token during initial connection, the CLI also
offers reauthorization. Connection and other refresh errors do not trigger that prompt.
Noninteractive runs print authorization options and exit; see [token recovery](google-setup.md#permissions-tokens-and-repeat-authorization).
The permission permits reading message bodies. This CLI reads message headers, labels, and sending
addresses; it does not request message bodies.

## Active timing

Operational commands end with `Active time: N.Ns`, including short runs, errors, and cancellation.
The total excludes time waiting for terminal answers and the browser authorization flow. It
includes API work, retries, and cleanup, and uses a monotonic clock. Help and argument-parser
errors do not show a total. The line goes to stderr, leaving redirected data output unchanged.
Sender-sync's stored metrics retain their existing wall-duration meaning, including input waits.

## Network timeouts

Each Google API read attempt has a 15-second overall deadline, including connection setup, DNS lookup,
response download, and retry delays. An expired-token refresh before the command has its own
15-second deadline. These are per-operation limits, not a limit on the entire command.
A timed-out read stops the command and names the operation, for example:

```text
Error: Reading contact timed out after 15 seconds. Check your connection and retry.
```

DNS resolution failures stop without retrying. Other eligible read failures can retry within the
same deadline. Reads reuse a worker and HTTP connections within the command to reduce repeated
startup and connection overhead. The worker is closed when the command ends, and discarded on
failure or Ctrl+C. Brief process cleanup can add a fraction of a second. Use `--diagnostics` with sender-sync to record details.

Writes retain their existing transport behavior. Only explicit transient rate-limit rejections
are retried; uncertain writes are never replayed. A timeout while verifying
an already-submitted write still reports an unverified result; it does not imply the write failed.
Photo downloads retain their separate limits. Browser authorization keeps its separate five-minute
waiting period; `--auth-timeout` only controls that authorization wait.

## Global options

`--token PATH` appears in `contacts-cli --help`. Command help shows
command-specific options and points to top-level help for global options. Both positions work:

```sh
./contacts-cli --token /path/token.json list-email --contact 'c123456789'
./contacts-cli list-email --contact 'c123456789' --token /path/token.json
```

If supplied both before and after the command, the value after the command takes precedence.

## Email input validation

Email addresses supplied inline or through files for add-contact, duplicate, add-email,
remove-email, and sender-sync exclusions must have a dotted domain, such as `name@example.com`.
Single-component
domains such as `name@localhost` or `name@1` are rejected. Validation does not check whether a
domain or mailbox exists. Removal and sender-exclusion patterns containing `*` are an exception:
they match whole addresses and need not themselves be complete email addresses.

## API error details

Sender-sync email-preservation failures show before/saved field values when entries can be
paired unambiguously. Missing entries or duplicates show unmatched entry counts instead of
guessing which entry replaced another. Update verification failures identify whether the failure
occurred in the update response or independent readback. The update was already submitted;
these diagnostics do not imply rollback or relax preservation checks. Verification details appear
in the terminal and in a separate local verification log. The 20 most recent verification logs
are retained; HTTP error logs remain separate. See [verification logs](error-logs.md#email-verification-failures).

Failed Google API HTTP responses are saved locally, and the terminal prints the log path. See
[diagnostic logs](error-logs.md) for locations, recorded fields, and troubleshooting details.
Use `sender-sync --diagnostics` to record detailed [run diagnostics](error-logs.md#sender-sync-run-diagnostics),
including successful requests and transport failures. Normal runs omit these traces.

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

## Google Contacts request pacing

The CLI shares a conservative budget of 80 People API requests per rolling 60 seconds across
reads and writes within one command. Creation and updates also consume Google's read quota.
This is a local guard, not a complete model of Google's quota buckets: other running commands,
applications, and earlier runs are not counted. Gmail requests are unaffected. Current contact
batch reads request one contact at a time.

Before exceeding this budget, the CLI reports how long it will wait. An explicit HTTP 429 with
Google's structured `RATE_LIMIT_EXCEEDED` reason can retry the same request up to three times,
waiting approximately 30, 60, then 120 seconds with a small random delay. `Retry-After` is honored;
if it requests more than 121 seconds, the command stops rather than retrying early. Daily quota
exhaustion, unclassified 429 errors, authorization errors, and uncertain writes are not retried.
Completed work and reviewed decisions remain in place during these waits. Ctrl+C cancels.
Quota waits are outside each read attempt's 15-second network deadline and count as active time.
People API requests use these explicit retries rather than hidden client-library retries;
other People API failures stop normally. Gmail's bounded read retry behavior is unchanged.

See Google's [contact quota accounting](https://developers.google.com/people/v1/contacts)
and [quota retry guidance](https://docs.cloud.google.com/service-usage/docs/troubleshooting).
