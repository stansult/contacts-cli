# Email editing design rationale

The [command reference](command-reference.md#add-email-and-remove-email) defines current usage,
matching, conflict choices, and output. This document records why the editing model works that way.

## Normalize before resolving conflicts

Inline and file addition normalizes addresses and labels, suppresses labels duplicating the
address or contact identity, and deduplicates the resulting entries before comparing them
with stored data.
A bare address and the same address with a suppressed label therefore express the same request:
an email without a label. Conflicting resulting labels in the input are rejected rather than
resolved through prompts, so the meaning of a file does not depend on interactive choices.

Address parsing and file handling are shared with sender exclusions. Email removal matches only
the address; labels in a removal list do not identify individual stored entries.

## Preserve or explicitly consolidate

A stored address can appear more than once. Keep preserves the entire matching group; Replace
consolidates it into one entry with the requested label or no label. This gives duplicate entries
a defined outcome without silently discarding them. When present, the primary matching entry
survives; otherwise the first match survives. Primary status comes from Google metadata, not
array position. The survivor retains its address spelling and applicable metadata.

Removing an address removes all matching entries. It is not an undo of an earlier addition;
[issue #5](https://github.com/stansult/contacts-cli/issues/5) tracks a separate command-history/undo proposal.

## Separate conflict decisions from write approval

Replace/Keep choices determine the plan; the final confirmation approves the resulting changes.
“All” applies to current and remaining stored-entry conflicts, not unrelated new addresses.
`--apply` alone preserves conflicts; `--replace-existing` explicitly authorizes replacement and
duplicate consolidation. This keeps scripted operations predictable without new prompt policies.

## Share display and naming conventions

Email lists use the shared numbered renderer. Editing displays existing entries only when needed
for a conflict decision; `list-email` provides the complete list. Additions and updates share continuous numbering; removals number whole address groups.
Informational numbers follow proposed changes and cannot be selected. Conflict lists start at 1.
Help and examples use singular commands in list, add, remove order; plural forms are accepted
silently for convenience.


## Webpage input carries no label-change intent

URL extraction supplies addresses without labels. It skips existing addresses, preserving their
labels and duplicate entries, instead of treating missing page context as a request to remove labels.
New addresses are reviewed through reusable numbered selection before final confirmation. Label
inference is deferred until representative pages establish useful behavior.

## Select approved address changes

Conflict decisions establish eligible changes before selection. Each selected update includes
its complete duplicate consolidation; removal always selects all entries matching one address.
Rebuild the selected result from the original contact and selected approved inputs, preserving
unselected entries and avoiding repeated conflict prompts. Validate the selected contact size
and retain the existing fresh-read/etag checks before writing.

## Removal patterns

Expand `*` patterns once against the original contact snapshot, then deduplicate overlapping
matches into concrete address groups. Selection must use those concrete addresses literally,
even if a stored address contains a `*`. Never expand again after selection or against a newer
contact. Existing concurrency checks still reject a changed contact before writing.
