# Importing contacts

Use `add-contact` to create contacts or review information to merge into saved contacts.
For JSON structure and field validation, see [contact input](contact-input.md).
For command options, see [add-contact](command-reference.md#add-contact).

## Import workflow

1. Validate the entire input locally. Invalid records must be corrected even if you would not
   select them for import.
2. Read saved contact matching fields, then full details only for possible matches.
3. Resolve requested contact-label spellings and review the preview.
4. Select inputs by their original numbers. Skip already-complete inputs when offered.
5. Review label-only groups, email-label changes, conflict-free merges, and individual matches.
   Every choice builds an unsaved plan.
6. Confirm the final plan. The command creates shared labels, updates saved contacts, and creates
   new contacts, verifying each result.

`--apply` skips initial input selection and final confirmation, but duplicate and grouped-review
choices still prompt. A noninteractive run without `--apply` only previews; with it, possible
matches stop the import before writes.

## Contents

- [Possible duplicates](#possible-duplicates)
- [Skipping unchanged inputs](#skipping-unchanged-inputs)
- [Merging information](#merging-information)
- [Grouped review](#grouped-review)
- [Contact labels](#contact-labels)
- [Creation and failures](#creation-and-failures)

## Possible duplicates

Before creation, the command reads all saved contacts' matching fields and compares them with
input records; input records are also compared with one another. Contacts reaching the list API's 100-email/phone limit get a
complete individual read before comparison. It shows possible matches, their IDs or original input
numbers, and the matching criteria. These are review signals, not proof that two records identify one person.

- Names and company names ignore case, Unicode compatibility differences, and extra whitespace.
  Full names compare as a whole; nicknames, reordered names, and missing components are not inferred.
  A single-part name alone does not suggest a duplicate. Structured names require both a first
  and last name; names supplied only as full text require at least two words. A compound first
  name without a last name does not qualify when structured parts are available.
  Email or phone matches still qualify regardless of name completeness. For example, an incoming
  `Josh` can match a saved Josh by phone, but not another Josh solely by name. These rules apply
  to saved contacts and other inputs in the same import; contact search is unchanged.
- Email addresses ignore case. Dots and plus suffixes remain significant.
- Phone numbers ignore formatting separators but retain country codes and extensions. The CLI
  does not infer a country, equate local and international numbers, or interpret vanity numbers.
- Company alone matches only when **both** records have no name or their name equals a company
  name. Two named people at the same company do not match solely through their employer.

The duplicate overview numbers each input contact using its original file position and lists
possible matches directly beneath its details as indented dashes. The matches are informational;
the input numbers are the choices for contact selection. Saved-contact IDs, earlier input references and
matching criteria remain visible. A full-name detail that only repeats the heading is omitted;
structured name components and additional name details remain visible. The selection prompt
explains that possible matches will be reviewed for skipping, merging, or separate creation.

Select the input contacts first. For each selected possible duplicate, choose `s` to skip (the
default), `m` to merge, `c` to create separately, or `q` to cancel the whole command. Inputs are
reviewed individually in file order against saved contacts and earlier inputs retained for creation. Skipped and unselected
inputs cannot cause a later conflict. All decisions happen before any labels or contacts are created.
After duplicate review, a final yes/no confirmation applies the reviewed creations and merges;
No cancels.

`--apply` skips selection and final confirmation, but still requires interactive duplicate choices.
Noninteractive preview reports matches without writing. Noninteractive `--apply` stops with an
error if any possible duplicates exist, before creating anything. `validate-contact` remains local
and does not look for saved contacts. Automatic resume is not implemented.

Matching uses a snapshot read at the beginning of the run. Concurrent account changes and identities
that differ beyond these rules can escape detection. This is not a uniqueness guarantee.

## Skipping unchanged inputs

Before individual duplicate review, a default-Yes **Skip these inputs? [Y/n]** prompt offers to
skip all selected inputs where every possible match is a saved contact with nothing new and no
requested labels to add. The count includes only selected inputs. No keeps individual review;
`q` or end-of-input cancels the command without writes. Conflicts, useful merges, invalid merge
comparisons, and matches to other input records remain in individual review. If nothing remains,
the command finishes without writes; otherwise, normal review and final approval still apply.
Interactive `--apply` still asks this question. Noninteractive preview and duplicate rejection
with `--apply` remain unchanged; there is no automatic skip in noninteractive mode.

## Merging information

Choose `m` during duplicate review. With one eligible match it becomes the target; with several, choose
one number from the separate **Merge targets** list, or `q` to cancel. That numbered list appears
only after choosing Merge; the earlier overview keeps possible matches as dash-marked lists.
A target can be a saved contact or an earlier input retained for creation. This imports information
into one chosen target; it does not delete or combine existing Google contact records automatically.

Individual duplicate review repeats each matching contact’s comparison result before the choice.
Merge is offered when at least one target has additions, conflicts, or requested labels;
only those targets can be selected for merging. Conflicting entries show Saved and Incoming
values before the choice. Unchanged targets remain visible, with Skip, Create separately, and
Cancel available. Labels alone can make a merge useful.
Comparisons include earlier merge decisions in this run, so a later input with no additions
or unresolved conflicts no longer offers Merge. No extra Google read is needed for these comparisons.

### Understanding comparison results

The initial account scan requests only matching fields. Before displaying the preview, the CLI
reads full details once per matched saved contact, with progress, and compares each possible target
separately. Unmatched saved contacts receive no additional detail reads. The preview shows
**Nothing new**, **New information available**, **Conflicts to resolve**, or **New information and
conflicts** beneath each match. Requested labels that are absent appear as **labels to add**;
already-present labels do not count as changes. A merge that fails local validation is marked
**Cannot merge**; you can still skip that input or create it separately.

These are hypothetical comparisons, not automatic merge decisions. Input-to-input results are
marked **If combined with this input**. They describe the original input records; selected inputs
are reviewed in order, so earlier choices can change the eventual result. Nothing is skipped
automatically. Select only the inputs you want to review, or cancel if nothing is useful.

### Resolving conflicts

Full details are kept only for this run and reused during review. Each conflicting entry is identified once, then shows
only differing properties with **Saved** and **Incoming** values before the Skip/Merge/Create choice. Conflicts alone make Merge
available. Email capitalization and unchanged or unsupplied properties are omitted from conflict
details. Single-entry replacements explicitly show properties omitted from the incoming entry
that Replace would remove. After choosing Merge and a target, resolve each conflicting entry:

| Choice | Result |
| --- | --- |
| **Keep** (`k`, default) | Preserve conflicting saved values; nonconflicting gaps can still be filled |
| **Replace** (`r`) | Use incoming values, following the field rules below |
| **Keep both** (`b`) | Preserve the complete saved entry and append the complete incoming entry |
| **Cancel** (`q` or end-of-input) | Discard the entire import plan, including earlier decisions |

Replace retains unsupplied properties for repeating fields. For birthdays, Notes, and ambiguous
names, it replaces the whole entry to avoid combining incompatible components. The anchored
first-name case below preserves the surname.

Keep both is unavailable for names, birthdays, and Notes. For emails or phones, it explicitly
creates duplicate addresses or numbers with their incoming labels. No primary metadata is copied
to the appended entry.

A label-only conflict uses **Keep saved label**, **Use incoming label**, and, for an email,
**Keep both labels as two email entries**. Multiple conflicting properties use values/entries wording.
Choices apply to a complete entry, such as one company and its title/location. If several saved
entries match, Replace asks which numbered saved entry to change; the others remain intact.
Invalid choices reprompt. Available additions are listed before choosing Merge. Conflict prompts
identify the field and decision number (for example, “Review name difference (1 of 2)”). If repeated
incoming entries could change later conflicts, prompts use a decision number without a fixed total.
Contact reviews and responses are separated by blank lines. After review, **Selected merge changes**
describes decisions and the final
approval lists resulting values for changed fields. Declining final approval makes no changes.
`--apply` skips final approval but still requires interactive duplicate and conflict choices.

### Field-specific merge rules

#### Emails, phones, URLs, and companies

- Empty fields receive supplied values. Repeated identical values are not added again.
  An existing email without a label shows **Add email label: address**, followed by
  **Label: incoming label (currently none)** in both available and selected changes.
  This adds a label to the existing email; it does not add another email entry.
- Emails match ignoring case; phones use the same formatting comparison as duplicate detection.
  Email capitalization alone is never a conflict or a requested change. Replacing an email label
  or other properties preserves the saved address spelling. Equivalent phone formatting alone
  is not a conflict. Labels and other
  differing supplied properties can be resolved; missing properties can be filled.
- URLs match by exact URL, nicknames by exact value, and companies by normalized company name.

#### Names

Name comparison can recognize a narrow first-name change: the saved name has one given-name
token and a known surname, and the incoming full name is one token followed by that same surname.
For example, Andrew Example → Drew Example shows only **First name: Andrew → Drew**,
with Keep Andrew / Replace Andrew with Drew. Replace sends the new given name and preserves the
saved surname; it does not send a contradictory old full-name string. Keep is summarized simply
as “Kept first name: Andrew.” Compound saved surnames
are supported. Additional saved name components, extra incoming tokens, a different surname,
or missing saved name parts keep whole-name review; the CLI does not guess a general name split.
New-contact full-name input still uses Google's parsing.

#### Notes, dates, addresses, and events

Notes conflicts concern their text/format.
Missing birthday date components can be filled only if the result is valid. Other distinct
addresses and events are appended rather than guessed to be the same entry.

#### Custom fields, labels, and preserved data

- Custom fields deduplicate exact key/value pairs. Different values for the same key are retained.
  A differing **Created** marker is a conflict: Keep preserves the existing marker; explicit Replace
  or Keep both is also available. Merging into a saved contact generates no new Created marker.
  Combining inputs into one new contact adds no automatic marker.
- Requested `--label` labels apply to merge targets and new contacts. Existing memberships,
  photos, unrelated fields, and explicit primary choices are preserved. Replacing an entry retains
  its primary metadata; keeping both leaves the existing entry primary.

### Combining inputs and unchanged targets

Several inputs merging into the same target are combined into one update; later conflicts are resolved
against the earlier planned values. Combined new contacts retain their original first input number. Skipped
inputs do not contribute information. A target that already contains all supplied information and
labels is left unchanged and omitted from the final approval list. Requested labels can still
require an update even when the contact details add nothing; these appear as **Labels to add**.
The final summary lists only contacts to create or update. If neither is needed, the command
finishes without final approval: **Nothing to create, update, or label; no changes made.**
An unchanged input combined into an earlier new contact still leaves that new contact awaiting
creation approval. Choosing Merge itself remains a preliminary decision, not a write.

### Saving merges

All choices occur before writes. Targets with planned updates are reread before any writes and
again immediately before each update; a changed target is not updated and is reported as failed. Source etags also protect the write.
Missing shared labels are created first, then existing contacts are updated, then new contacts are
created. Updates replace only changed fields, retaining entries except for explicitly approved replacements. Each update is
verified in the response and an independent readback. Changed fields permit generated properties
(such as a formatted address), but must retain all expected values and entry counts. Standard URL
label capitalization, such as `Profile` becoming `profile`, is accepted; custom label spelling
remains significant.

### Merge failures

Contact-specific failures are reported and independent contacts continue by default. This includes
rejected contact data, a target changed since preview, and saved-field verification mismatches.
Several inputs combined into one target are one operation: failure affects that whole target.
Authorization, unrecovered rate/quota limits, connectivity or server failures, unknown failure types, and
interruption stop the batch. A shared-label creation or verification failure also stops processing.
Completed changes remain saved; there is no rollback. Writes retry only explicit transient
rate-limit rejections. An unverified
contact is not counted as a successful merge. Inspect it before retrying. A no-change merge makes
no update request.

## Grouped review

| Changes | Group review | What happens to unselected entries |
| --- | --- | --- |
| Only contact labels are missing | Select all, numbers/ranges, or skip | Skipped for this import |
| Only email labels differ | Replace, Keep, numbers/ranges, or individual review | Stay grouped until one remains or individual review is chosen |
| Contact information can be added without conflicts | Merge, Skip, numbers/ranges, or individual review | Stay grouped until one remains or individual review is chosen |

These are separate review stages. A contact label groups contacts in Google Contacts; an email
label describes one email entry, such as `work`. None of these choices saves changes immediately.

### Compact label-only imports

With `--label`, an input that matches one independent saved contact and adds only labels gets
a compact name-only row under the labels it needs. Original input numbers stay selectable.
Choose `all`, numbers/ranges, `s` to skip that label group, or `q` to cancel the command.
Unselected entries in that group are skipped. These decisions only build the plan; the final
confirmation saves it. Interactive `--apply` still requires this review but skips final confirmation.

Contacts missing different label sets have separate groups. Already-complete inputs are listed
compactly and retain the existing skip prompt. Ambiguous matches, repeated targets, input-to-input
matches, conflicts, and new contact information retain detailed review.

The final plan counts new contacts, existing contacts receiving only labels, information updates,
and already-complete inputs skipped. Label-only saves use one progress counter; completion counts
include only verified successes. Failures retain the contact identity and explanation. Contact
changes after preview, interruption, and verification failures retain the usual safeguards.

### Grouped email-label changes

After input selection and the unchanged-input skip prompt, similar email-label changes can be
reviewed together. Groups contain at least two selected inputs with the same incoming email label
(exact spelling), regardless of their saved labels. A group can include `work`, `WORK`, and `OTHER`.
When saved labels differ beyond case, each contact row shows its saved label, including subset
previews. Otherwise, a shared saved-label heading shows the spellings, such as `work / WORK`.
The “Available email label changes” preview shows saved spellings, the incoming label, contact names,
saved email addresses, and original input numbers. Blank lines separate responses and action menus
from the next output. A saving reminder explains final confirmation, or its absence with `--apply`.

“Reviewing selection” identifies a subset being considered, before choosing Replace or Keep.
“Selected label replacements” reports a decision, with “more” for subsequent subsets. The total
counts all grouped replacements selected during this review and explicitly says “Not saved yet.”
Keeping labels selects no replacement. When other matching inputs need individual review, a
separate transition explains the next step. These summaries describe plans, not completed writes;
the later saved-and-verified result reports completed changes.

- `r`: replace saved labels with the incoming label for every listed entry; no per-contact prompts.
- `k`: keep the saved labels and finish review of those inputs without updates.
- Enter original input numbers/ranges directly, then choose Replace or Keep for that subset.
  There is no intermediate selection menu. Ranges select remaining displayed entries within
  their bounds, even with gaps or endpoints not displayed: `1-100` selects remaining rows in
  that interval. Explicit unavailable numbers still error. The example uses current group numbers.
  `n` or Enter returns to the current group without deciding that subset. After Replace or Keep,
  unselected entries stay grouped with their original numbers and can be reviewed in more subsets.
  Already decided entries are no longer selectable. When one entry remains, it moves to individual
  review; otherwise, only `i` or Enter at the group menu switches to individual review.
- `i` or Enter: review the group’s inputs individually.
- `q` or end-of-input, including during number selection: cancel the entire command without writes.

Grouping requires exactly one saved-contact match, one unambiguous email-label conflict, no
other additions or property changes, and no missing requested contact labels. A target referenced
by another selected input, an input-to-input match, multiple saved matches, duplicate matching
email entries, or several label conflicts remains in individual review. Groups with fewer than
two eligible inputs also use individual review. Contact-label membership changes are distinct
from email labels and are not grouped by this feature.

Group choices only build the import plan. Individual review follows for remaining inputs, and
final approval covers grouped changes, individual merges, and new contacts together. Declining or
cancelling discards all plans; approved writes use the same fresh-contact checks and independent
verification. `--apply` still requires group choices but skips final approval. Noninteractive
behavior is unchanged. Grouping uses the cached comparison data and makes no extra Google reads.

### Grouped merges without conflicts

After grouped email-label replacements, two or more independent saved-contact matches with
additions and no conflicts offer **Available merges without conflicts**. Each original input
number shows its name, saved target name and ID, match reasons (including name-only matches),
and every addition. These can include emails, companies, missing email labels, and requested
contact labels. Newly requested contact labels are marked as new.

- `m`: select merges for all listed contacts.
- `s`: skip all listed inputs.
- Enter numbers/ranges directly to review a subset, then choose Merge or Skip. `n` or Enter
  returns to selection without deciding that subset.
- `i` or Enter at the group menu: review these inputs individually, including the option to
  create separately.
- `q` or end-of-input: cancel the entire import, including earlier plans, without writes.

Remaining entries stay grouped with their original numbers; a single remainder moves to
individual review. Selected merges are explicitly unsaved. No-op inputs, conflicting changes,
multiple possible matches, input-to-input matches, targets shared by selected inputs, and targets
already in a merge plan are excluded. They retain the existing individual-review behavior.
Grouping uses cached matched-contact details and adds no Google reads. It never treats a
name-only match as proof that two people are the same; the displayed target is for your review.

Final approval covers label replacements, conflict-free merges, individual merges, and new
contacts together. `--apply` still prompts for group decisions but skips final approval.
Noninteractive behavior is unchanged. Every approved merge keeps the usual fresh-contact checks
and independent readback verification. A failure or cancellation during review saves nothing.

## Contact labels

Repeat `--label` to apply contact labels to every selected contact. Label text must be nonblank.
Label names match exactly, including case; repeated identical names are deduplicated. With no
exact match, a case-only collision offers each existing label, Create new, or Cancel command.
Enter selects the first existing label. `q`, `Q`, the numbered Cancel option, or end-of-input
cancels. Invalid answers repeat the prompt. The final preview shows the selected spelling.
Choosing an existing label does not rename it.

These choices require terminal input, output, and error streams. Noninteractive runs stop on a
case-only collision and show the exact existing spellings to use with `--label`. `--apply` skips
contact selection and final write confirmation; it still prompts for a label choice interactively
and stops on a collision noninteractively. There is no extra flag to bypass this choice.

Existing user labels are reused, and missing labels appear under Labels to create. Ambiguous or
system labels are rejected. Resolving a label choice makes no changes. Labels and contacts are
created only after final confirmation, or with `--apply`.

## Creation and failures

The numbered preview includes all supplied fields with readable property names, dates, and
yes/no values, plus the labels applied to every contact.
Without duplicate conflicts, multiple contacts offer `all`, numbers/ranges such as `2,4-6`, or `q`
to cancel. Overlapping selections count once, and creation follows original input order. A subset preview keeps original
numbers and shows all supplied fields for the selected contacts. At final confirmation, `y`
creates the selected contacts and any missing labels; `n` or Enter returns to selection; `q` or
end-of-input cancels without writes. One input contact uses a simple `[y/N]` confirmation instead.
Selecting just one from a larger list still offers Return to selection in this flow. With possible
duplicates, the review flow described above ends with a yes/no confirmation; No cancels.

All inputs are validated before selection; an invalid unselected record still needs correcting.
Labels are shared across the input, not specified per record. They apply to every selected contact;
cancellation creates no labels. `--apply` processes retained inputs after any required duplicate
review; noninteractive runs without it only preview. Selection does not edit the source JSON file.

### Creation progress

For a subset, progress includes the original number, such as `Creating contact 1 of 2 (input #4)`.
Errors identify the original input number too. Batch totals and not-attempted counts refer only
to selected contacts; unselected records are not failures or pending creations.

Timestamped progress identifies each label and contact being created. Created contact, followed
by a Google Contacts link, confirms creation before readback verification begins. A later
Verification failed message means the contact exists but its saved fields could not be verified.
Created and verified confirms both stages. With `--apply`, the preview heading is Creating contacts.

### Creation outcomes

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

### Batch summaries

For creation batches, the summary separates created and verified contacts. Created includes known
creations whose verification failed; unknown write outcomes are not counted as created. Mixed
imports report verified creations and merges. On failure, a separate summary counts contacts that failed before saving,
unverified contacts, and unattempted contacts, followed by a list of contacts needing review with
input numbers or target IDs and known creation links. Single-contact failures state the outcome
directly. Previously created contacts and labels remain saved.

### Continuing or stopping after an error

Contact-specific rejections and verification mismatches do not prevent independent contacts from
being processed. Authorization, unrecovered quota/rate limits, connectivity/server errors, unknown errors,
and interruption stop further operations. Shared-label failures stop the batch before dependent
contacts are written. Input validation and duplicate review still finish before writes begin.
There is no rollback or automatic retry file. Only explicit transient rate-limit rejections
are retried automatically; uncertain writes are never replayed. An unverified creation
may already exist; inspect it before retrying. Do not rerun the full input after partial success.
A label created by another process between preview and creation causes a conflict and stops the run.

Exit status is `0` only when there are no failures, `1` for failures without uncertain contact
writes, `3` when any write remains unverified, and `130` for interruption. A successful later
contact does not reset an earlier failure status.

Sources: [Google Person fields](https://developers.google.com/people/api/rest/v1/people),
[contact creation restrictions](https://developers.google.com/people/api/rest/v1/people/createContact),
[contact updates and singleton limits](https://developers.google.com/people/api/rest/v1/people/updateContact),
[contact label creation](https://developers.google.com/people/api/rest/v1/contactGroups/create).
