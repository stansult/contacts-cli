# Command reference

[Back to usage](../README.md). Detailed command behavior, output, and limitations.

## Contents

- [Running the CLI](#running-the-cli), [contact identifiers](#contact-identifiers),
  [confirmation and conflicts](#previews-confirmation-and-conflicts), [output](#output-and-timestamps)
- [Add-contact](#add-contact), [duplicate](#duplicate-a-contact), [sender-sync](#sender-sync-preview-and-apply)
- [List-email](#list-email), [add-email and remove-email](#add-email-and-remove-email)
- [List-label](#list-label), [add-label](#add-label), [remove-label](#remove-label), [label choices](#label-choices-and-output)
- [Custom fields](#add-custom-field-and-remove-custom-field), [validate-contact](#validate-contact),
  [authorization](#authorization)
- [Active timing](#active-timing), [network timeouts](#network-timeouts)
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

Commands that change contacts or labels show their intended changes before saving. Interactive
confirmation requires terminal input, output, and error streams. A simple `[y/N]` prompt writes
only after `y` or `yes`. With multiple choices, contact creation, sender-sync, email edits,
custom-field edits, and label removal offer numbered selection followed by confirmation.
At that confirmation, Enter or `n` returns to selection; `q` or end-of-input cancels.
Piped or redirected runs without `--apply` do not write; unresolved label choices
may stop the run before a complete preview.

`--apply` selects all eligible items and skips final write confirmation, not every decision.
Label case choices still prompt in interactive runs and stop noninteractive runs. With `--apply`,
email conflicts are kept unless explicitly approved with `--replace-existing`. Each command's
section describes its matching and conflict rules.

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
no timestamp; the completion line includes the final counts and finish timestamp.

Sender-sync waiting and scanning stages share one progress helper. Interactive stderr shows an
immediate spinner with a fixed start timestamp for waiting stages. After 5 seconds, it also shows
`elapsed Ns`. Completion replaces the live line with a finish timestamp; stages lasting at least
10 seconds include `(took N.Ns)`. Durations use a monotonic clock, independently of clock changes.
Errors and interruptions end the stage as failed or interrupted, not finished. Progress stops
before prompts and other output. Redirected stderr has plain start/completion lines and throttled
counter updates, without animation or control codes. These thresholds require no CLI flags.

## Add-contact

`add-contact` accepts inline `--name` (or `--first-name` / `--last-name`) and repeatable `--email`,
or `--file` with one Person object
or an array. Repeatable `--label` reuses existing labels or previews missing labels for creation.
Case-only label collisions require choosing an existing label, creating new, or cancelling;
noninteractive collisions stop. `--apply` does not resolve this choice.
For multiple contacts, choose `all` or original preview numbers/ranges, such as `2,4-6`, then
confirm creation. A subset preview retains original numbers; `n` or Enter returns to selection,
and `q` cancels. One input contact uses a simple `[y/N]` confirmation. Labels apply to all selected
contacts and are created only after confirmation. `--apply` creates all input contacts without
selection or final confirmation. Noninteractive runs without `--apply` only preview.
See [contact creation](contact-input.md) for supported fields, validation, progress, verification,
and partial-failure behavior.

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

Replacement values must be nonblank; use the clear options instead of an empty string.
Emails use the same dotted-domain validation as contact creation; names and wildcard patterns are
not accepted as email values. Phones use the same format validation as contact creation and may
include an extension. Quote values containing spaces. Replacement and clearing options for the
same field are mutually exclusive. Invalid inputs are rejected before authorization.

Preview shows replacement values, explicitly marks cleared fields, lists resulting entry counts,
and states whether a photo will be copied. A cleared field has no entries in the new contact.
Success prints the new contact's link, using the person identifier returned by Google.

Each copy adds a **Duplicate** custom field, for example:
`Created by contacts-cli on November 11, 2026 at 2:30 PM (UTC−08:00)`.
The timestamp uses the computer's local time when that run prepares the copy, including its UTC
offset. Existing fields labeled exactly **Duplicate** are replaced with this one fresh marker;
other custom fields are preserved. A separate preview run does not fix the timestamp for a later
`--apply` run.

The copy includes editable contact fields exposed by the People API: names, emails and custom
labels, phones, addresses, notes, dates, organizations, relationships, URLs, custom fields, and
other editable details, including file-as and skills. User contact groups, My Contacts, and Starred
memberships are retained. Unsupported system groups stop creation. Profile-only data, generated
IDs, timestamps, verification flags, and read-only domain memberships are not copied.

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

The source contact is never updated. A fresh source read catches changes before creation, but the
read and creation are not atomic. Each `--apply` creates another contact, even with identical flags.
Creation and photo writes are never automatically retried. If the result is uncertain or a photo
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

Exactly one of `--label` or `--search` is required. Quote the search expression in your shell.
Blank searches are rejected before authorization. Search mode uses Gmail's
[search syntax](https://support.google.com/mail/answer/7190), groups the expression in parentheses,
and appends the same sender exclusions as label mode. Gmail evaluates the query; the CLI does
not validate its complete syntax or independently recheck it against message contents.
Both modes include matching Spam and Trash; explicit query restrictions still apply.
Search mode skips label lookup and label-membership checks. Raw queries are not stored in metrics.

Output identifies the contact and label or search,
shows inspected-message and new-sender counts in progress, then existing email entries and additions.

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

Use `--exclude-file PATH` to read a UTF-8 list, one address or pattern per line. Repeat the option
for multiple files and combine it with `--exclude`. Do not put shell quotes around file patterns.
Blank lines, surrounding whitespace, and lines starting with `#` are ignored. A line copied from
the preview may include ` — Display Name` after the address or pattern; that label is ignored.
Inline comments and comma-separated lists are not supported. Files use the same validation and
deduplication as `--exclude`. Missing, unreadable, non-UTF-8 files and invalid entries stop before
authorization; invalid entries report the file and line number. Relative paths use the current
working directory. Files are read fresh each run.

```text
# Excluded senders
ignore@example.com
*@notifications.example.com
another@example.com — Notifications
```

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
There is no estimated total or percentage. Invalid From headers stop the search and block all writes.
The complete preview stays on stdout. Proposed addresses appear one per line without a `+` prefix,
with a custom label after ` — ` when applicable. Counts describe inspected messages, not the total
number of matching messages.

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

Enter `all`, displayed numbers, or ascending ranges directly; overlaps count
once and displayed order is preserved. Excluded numbers cannot be selected. Invalid or blank
input asks again; `q` or end-of-input cancels without writes.

A subset preview keeps original numbers and shows its total. Selecting all does not repeat the
list. Final confirmation offers Yes to add, No or Enter to return to selection, and `q` to cancel.
With just one available address, only `Add this address to this contact? [y/N]` is shown;
No or Enter cancels. Selecting one address from several still offers Return to selection. Zero eligible addresses
means no selection or confirmation. Selection affects only this run and does not save exclusions.

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
  the search. Repeated valid message IDs or results with no new sender also stop it before any write.
  For malformed messages, the CLI follows the next result page with the same query, remembering
  skipped IDs to avoid repeated header reads/logs. After finding a valid sender, it restarts with
  updated sender exclusions. Page tokens are never reused with a changed query; repeated or invalid
  tokens stop the run. Skipped results can require additional searches after each restart.
- Exclusions use quoted full addresses. Unsupported address syntax stops the run instead of being
  inserted into the search query. A local guard limits the entire URL-encoded query, including the
  base search, to 6,000 bytes. This is a conservative CLI limit, not a documented Google maximum.
  Exceeding it stops before writing.
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
Both require `--contact`. Add-email also accepts `--from-url` instead of individual/file inputs.
Otherwise, at least one individual or file option is required. Use the same UTF-8 file
format as exclusions: one address per line, optional ` — Label`, blank lines and whole-line `#`
comments. Options combine; files are read fresh relative to the current directory. An empty file
requests no changes. Removal ignores labels and matches addresses case-insensitively.

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
and exact addresses produce one selectable group per distinct address; all its duplicate entries
stay together. Selection uses those concrete groups, not a new pattern search. A contact changed
after preview is rejected before writing. With `--apply`, every matched group is removed.
Add-email requires exact addresses. Sender-sync exclusions accept the same `*` patterns; see
[exclusion inputs](#sender-sync-preview-and-apply).

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
lists changes, skipped conflicts, and remaining email entries. Interactive runs then select
changes by number before final confirmation.

`--replace-existing` approves all stored-entry conflicts but still requires final confirmation
unless `--apply` is also supplied. With `--apply` alone, existing conflicts are preserved and
reported while non-conflicting changes are saved. Noninteractive runs do not ask conflict questions;
without `--apply` they only preview. Unresolved conflicts are shown under Skipped conflicts.

Removal deletes all entries matching each address, regardless of labels. Each distinct address
has one selectable number, including case-only duplicates. Duplicate groups show every stored
spelling and label on indented lines; empty labels say `(no label)`, and primary entries are
marked `(primary)`. Repeated labels are shown once per stored entry. A single unlabeled entry
shows only its address. The heading counts both entries and distinct addresses.
Absent addresses and unmatched patterns are listed under Not found. Removing every email is
allowed and leaves the contact intact with zero email entries. A no-op performs no update. Later
sender-sync runs can add matching senders again. Addresses and patterns from the removal list
can be reused with `--exclude-file` to skip those senders in later runs.

Interactive add/remove runs use `all`, numbers/ranges such as `3-5,8`, or `q` to cancel.
Additions and updates have continuous numbering; each update (including duplicate consolidation)
is indivisible. Removal numbers select whole address groups. Not found and Skipped conflicts
use separate, nonselectable numbers after the proposed changes and are marked informational.
Subset previews retain original numbers and recalculate remaining email entries. Only selected
changes are applied; unselected entries retain their original labels, duplicates, and metadata.

No or Enter at final confirmation returns to selection without repeating label-conflict decisions.
With one eligible change, a simple `[y/N]` confirmation replaces selection; for a duplicate removal
it states the full entry count. Zero changes means no prompt. A smaller selected subset is checked
against size limits independently of the full proposal. `--apply` saves all eligible changes,
respecting the existing conflict rules; noninteractive runs without it remain preview-only.

Only emailAddresses is written. Other contact fields and retained email metadata are preserved.
A fresh read and etag check reject concurrent changes; writes are not automatically retried.
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
including missing addresses and skipped conflicts. Addition rows do not repeat “Add.” Updates
have a separate section showing the old and new values.

Use `list-email` to see all existing entries. Add/remove commands show only the existing total;
existing entries are displayed when needed for a conflict decision. Conflict-match lists start at 1. Proposed additions and updates share continuous numbering;
removal previews number distinct addresses. Sender-sync numbering continues across
its two address groups. Duplicate references in list-email and conflict lists point to the first
occurrence within that list; removal previews use grouped details instead. Numbers do not identify a preferred or primary address.

Without `--apply`, change headings say Proposed additions, Proposed updates, or Proposed removals.
With `--apply`, they say Adding, Updating, or Removing. These headings describe the requested action;
only the final Saved and verified message confirms success.

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

Without `--contact`, creates account labels without reading or editing any contact. Existing
labels appear under `Already exists`; only missing labels are proposed for creation. If all
requested labels exist, no changes are made. Confirmation asks only about creation; `--apply`
creates all missing labels. Each creation is independently verified. On failure or interruption,
creation stops, reports verified and unattempted counts, and leaves completed creations saved.
List account labels before retrying. For case-only collisions, choices explicitly say
`Keep 'test1'; skip creating 'TEST1'`, `Create 'TEST1' as a separate label`, or `Cancel command`.
Keeping an existing label creates nothing; it is not applied to any contact.

With `--contact`, adds one or more contact labels to that contact. `--contact` accepts a URL or bare ID;
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

Removes selected labels from one existing contact without deleting label definitions or changing
other contacts. Repeat `--label` with literal names or quoted `*` patterns:

```sh
./contacts-cli remove-label --contact c123456789 --label 'Recruit*' --label 'Follow-up'
```

`*` matches zero or more characters across the whole name, ignoring case. Other characters,
including `/`, `.`, `+`, `?` and brackets, are literal. Quote patterns to prevent shell expansion.
`--label '*'` offers every applied user label; Google system groups and deleted labels are excluded.
A name containing `*` is interpreted as a pattern, with no separate literal-star escape syntax.

Literal names offer both exact and case-different matches without a case-choice prompt. The
preview groups Exact matches, Matching patterns, and Similar labels (case differs), omitting empty
groups. Only labels on this contact can be selected. Overlapping requests count a label once;
an exact literal match takes display priority over a pattern, then a case-only match. Numbering
is continuous. Labels absent from this contact are omitted, whether requested by name or
pattern. If none match, the command says `No matching labels on this contact; no changes made.`
Use `list-label` without `--contact` to inspect account labels separately.

Choose `all`, numbers/ranges such as `1,3-5`, or `q`. A subset preview keeps original numbers;
final confirmation uses the selected count. `n` or Enter returns to selection; `q` or EOF cancels.
One eligible label uses a simple `[y/N]` confirmation; no candidates means no write. `--apply`
removes all candidates, including case variants, without selection or confirmation. Noninteractive
runs without it preview only. Patterns expand once for the preview, never again during writes.

Each request removes only this contact from one label. A fresh contact read checks identity and
current memberships before the write; a label removed since preview is skipped. Independent
readback verifies the removed label is absent and other memberships remain. Other contact fields
are never sent for replacement. Labels themselves remain, even if empty. Google may refuse removal
of a contact's last contact-group membership; that refusal is reported and processing stops.

On errors or interruption, verified removals remain saved and later removals stop. Mutation requests
are not retried automatically. Inspect the contact before retrying; a fresh preview skips labels
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

Removal retains required `--key` and optional `--value`. Supplying a value
limits candidates to that key/value pair and its case variants; omitting it offers all values
under the key and its case variants.
Removing a selected pair removes all its identical duplicates. Removing `Created` or `Duplicate`
affects only those stored custom fields, not the contact itself. These markers receive no special treatment.

Addition matches exactly and case-sensitively; case-only similarities remain informational.
Adding an exact pair already present skips it, preserving stored duplicates. A different value
under the same key is appended, never used as a replacement. Removal offers both exact matches
and case-insensitive matches for the key and optional value, without a case-resolution prompt.
Whitespace is preserved; supplied keys and values must be nonblank and contain no control characters.
There is no file input, replacement option, or wildcard selector.

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

Each Google API read has a 15-second overall deadline, including connection setup, DNS lookup,
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

Writes are not retried and retain their existing transport behavior. A timeout while verifying
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
