# Shared rules for multiple-contact commands

[Back to command reference](command-reference.md).

These are the agreed rules for commands adopting multiple-contact input. `format-phone`,
`add-label`, `list-email`, `list-phone`, and `list-label` use this contract. Without contact inputs,
`add-label` creates account labels and `list-label` lists account labels with contact counts.
Other commands remain single-contact commands unless their help explicitly says otherwise.

## Inputs and matching

- Accept repeated `--contact` and one optional `--contact-file`, together or separately.
- Process inline identifiers in their supplied order, then file entries in file order.
- Files are UTF-8 (a BOM is accepted), one identifier per line. Ignore blank lines and lines
  whose first non-whitespace character is `#`. This is not a contact JSON file.
- Validate all inputs before account access. Missing inputs, malformed identifiers, unreadable
  files, and invalid file encoding stop the command. Empty files add no identifiers; another
  valid inline identifier may still supply the targets.
- Deduplicate identical identifiers before lookup, then deduplicate resolved contact IDs.
  Each contact is processed once, even if several identifiers select it.
- Use complete-name, complete-email, and complete-phone matching as described under
  [contact identifiers](command-reference.md#contact-identifiers). Do not guess countries.
- Read matching fields once when names, emails, or phones need resolution. ID-only inputs avoid
  that scan; each target is still read before its preview.

## Ambiguity and missing contacts

Multiple matches offer all or numbers/ranges. `s` skips only the current identifier; `q` or EOF
cancels the command before any writes. A skipped identifier does not exclude contacts selected
through another identifier. Noninteractive ambiguity stops before writes, even with `--apply`.

Report unmatched identifiers and explicitly missing IDs, then continue with resolved contacts.
If none remain, finish successfully without changes. Other read failures stop before any writes.
Input-resolution totals count identifiers; operation totals count distinct contacts. Keep these
separate because an identifier can match several contacts and several identifiers can match one.

## Review

Resolve all inputs and prepare previews before writing. Assign contact numbers when first
encountered and preserve them across matching, unchanged, proposed, and selected lists.

The command defines its selection unit: contacts for labeling, phone entries for formatting.
For commands selecting field changes, entry numbers must be unique across a batch. Prompts
identify what the numbers select; contact headings are not field-entry choices. Filtering leaves gaps instead of renumbering.

Offer one final confirmation for all selected changes. Selecting contacts during matching does
not approve changes. `--apply` selects all proposed changes and skips final confirmation, but
never resolves ambiguity automatically. Noninteractive runs without it only preview.

## Saving and outcomes

Process selected contacts sequentially, retaining each command's concurrency checks and response
and readback verification. Show contacts processed out of selected contacts.

| Result | Batch behavior |
| --- | --- |
| Explicit contact-specific rejection or stale preview | Report failure and continue |
| Saved content fails verification for one contact | Report unverified result and continue |
| Authorization, connection, unrecovered quota, or shared-resource failure | Stop |
| Write outcome unknown, or verification read cannot complete | Stop; do not replay the write |
| Interruption | Stop and report progress |

Completed changes remain saved; there is no batch rollback. A failure summary distinguishes
verified, failed-before-verification, unverified, and unattempted contacts. Report contacts needing
no changes and contacts omitted by selection separately. An interrupted contact whose write began
is unverified, not safely failed. Never automatically replay an uncertain write.

Deliberate skips and no-ops are successful. Any failed operation returns a nonzero exit status:
1 for failures, 3 if any write remains unverified, or 130 for interruption. Retry only explicit
transient rejections through the existing request policy, not uncertain writes.

## Shared labels and partial contact results

`add-label` creates and verifies all missing labels needed by selected contacts after final
approval, before applying any memberships. A shared-label failure stops and reports created
labels; all contacts remain unattempted. Labels already created remain saved.

Each contact can receive several labels. A later addition can fail after earlier additions were
verified. Report the verified labels, the failed or unverified label, and remaining unattempted
labels for that contact. Count a contact as verified only when all selected labels are satisfied.
A failed or unverified contact may therefore contain successful partial changes. The summary
separates saved additions from memberships already applied concurrently since preview.

A missing contact reported by the membership response is contact-specific; a rejected shared
label operation is not. A content mismatch after a successful verification read can continue;
a failed verification read leaves the write uncertain and stops.

## Read-only field listings

`list-email`, `list-phone`, and `list-label` share input validation, complete-identifier matching,
ambiguity selection, deduplication, and missing-contact skipping. `list-email` and `list-phone`
require contact inputs. Supplying an empty `--contact-file` to `list-label` is an input error,
not a request to list account labels.

There is no change preview, final confirmation, or `--apply`. After resolving all identifiers,
read each distinct contact once and display its entries. Multiple resolved contacts have separate
`Contact #N` headings retaining their original matching numbers. Entry numbers restart at 1 within
each contact; duplicate references stay within that contact. These numbers are informational, not
a second selection prompt. A single resolved contact retains the ordinary unnumbered heading.

Empty email, phone, and label lists show zero entries or labels. For contact-specific `list-label`,
read the paginated label names once and reuse them throughout the run; do not show account-wide
contact counts on these lists.

Explicitly missing contacts are skipped. Other read failures, including incomplete data, stop
the listing with exit status 1; interruption returns 130. Results already displayed remain visible,
and the command says the listing is incomplete. Multiple-contact runs and failures summarize
listed, skipped, failed, and not-attempted contacts. An interrupted read counts as failed.
Unmatched identifiers remain in the separate input-resolution summary. A successfully displayed
empty list counts as a listed contact. No matching contacts is a successful empty result.
