# Email editing design rationale

The [command reference](command-reference.md#add-email-and-remove-email) defines current usage,
matching, conflict choices, and output. This document records why the editing model works that way.

## Normalize before resolving conflicts

Addition normalizes addresses and labels, suppresses labels duplicating the address or contact
identity, and deduplicates the resulting entries before comparing them with stored data.
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
for a conflict decision; `list-email` provides the complete list. Each displayed list starts at 1.
Help and examples use singular commands in list, add, remove order; plural forms are accepted
silently for convenience.
