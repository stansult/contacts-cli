# Planned email editing commands

Status: design implemented locally; live verification remains separate.
Usage and command behavior are documented in the [command reference](command-reference.md).

## Interface

Use singular command names. Present commands in list, add, remove order in help and documentation.
`list-email` displays existing entries without editing. `add-email` accepts repeatable `--add`
and `--add-file` options;
`remove-email` accepts repeatable `--remove` and `--remove-file` options. Both target one contact
with `--contact`. Reuse address normalization and file parsing from exclusions wherever possible.
Files accept blank lines, whole-line `#` comments, and `address — Display Name` entries.
Removal matches only the address; the label does not identify a particular stored entry.

## Incoming entries

For addition, process entries in this order:

1. Normalize addresses and labels for comparison, ignoring case and surrounding whitespace.
2. Suppress labels matching the address, contact display name, or company.
3. Deduplicate incoming entries with the same address and resulting label.
4. Reject conflicting resulting labels for the same address, identifying the conflicting inputs.
5. Resolve conflicts with stored contact entries.

A bare address means no label. A bare address and the same address with a suppressed label become
one no-label request. A bare address and the same address with a different, non-suppressed label
are conflicting inputs. Stop before any write and let the user correct them; do not introduce
an incoming-label selection prompt.

## Existing entries

For an address already in the contact:

- Same label: no change, unless duplicate stored entries need consolidation.
- No existing label and an incoming label: propose adding the label.
- Different existing and incoming labels: ask whether to replace the existing label.
- Existing label and no incoming label: ask whether to remove the existing label.

For duplicate stored entries, treat all entries matching the normalized address as one group.
Keep preserves the whole group. Replace leaves exactly one entry with the incoming label or no
label, even when all previous labels already match. Show all existing labels and the entry-count
reduction in the preview. Preserve primary status if any matching entry was primary; use that
entry as the survivor, otherwise the first matching entry, retaining its address spelling.
Primary status comes from Google metadata, not array position.

Interactive conflicts offer Replace, Keep, Replace all conflicts, and Keep all conflicts.
“All” covers current and remaining stored-entry conflicts in this run, not new-address additions.
After resolving conflicts, show the final preview and one apply confirmation. Use the shared
numbered-list renderer for email lists. Show only the existing total during edits; list-email
provides the complete list separately. Number each conflict or preview list locally starting at 1.
Separate additions and updates; use action headings
instead of Proposed headings when --apply is supplied. See the command reference for display rules.

`remove-email` removes all entries matching each requested address and shows the entry count.

## Interactivity

As with existing commands, interactive confirmation requires terminal stdin, stdout, and stderr.
Redirecting or piping any of those streams makes the run noninteractive. `--apply` authorizes a
write without the final confirmation; it does not determine whether the streams are interactive.
Without `--apply`, a noninteractive run previews only and does not write.

With `--apply`, preserve conflicting entries and report skipped changes unless an explicit
`--replace-existing` option authorizes replacements, label removals, and duplicate consolidation.
Conflicting incoming labels remain errors regardless of `--apply`.

## Related enhancement

[Issue #5](https://github.com/stansult/contacts-cli/issues/5) tracks a separate future undo feature using bounded local command history and before/after
state. Email removal is not an automatic undo of a previous command.

## Command spelling

Accept silent plural aliases for list-email, add-email, and remove-email by normalizing the
command token before parsing. Keep singular spellings in user-facing help and usage examples.
