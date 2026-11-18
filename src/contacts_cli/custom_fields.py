"""Custom-field edits with selectable case variants and verified preservation."""

import sys
from copy import deepcopy

from .core import (
    CONTACT_FIELDS,
    _stable,
    contact_resource,
    contact_source,
    field_update_body,
    validate_contact,
)
from .errors import SyncError
from .output import emit, emit_list
from .selection import review_selection


def entries(person):
    validate_contact(person)
    values = person.get("userDefined", [])
    if not isinstance(values, list) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("key"), str)
        or not isinstance(entry.get("value"), str)
        for entry in values
    ):
        raise SyncError("Incomplete custom field entries.")
    source = contact_source(person)
    for entry in values:
        field_source = entry.get("metadata", {}).get("source", {})
        if field_source and (
            field_source.get("type") != "CONTACT" or field_source.get("id") != source["id"]
        ):
            raise SyncError("Contact contains custom fields from another source.")
    return deepcopy(values)


def verify_custom_fields(person, expected, saved):
    actual = entries(saved)
    if contact_source(person)["id"] != contact_source(saved)["id"]:
        raise SyncError("Saved result refers to a different contact source.")
    if _stable(expected) != _stable(actual):
        raise SyncError("Saved custom fields do not match the preview.")
    for field in CONTACT_FIELDS.split(","):
        if field not in {"userDefined", "metadata"} and _stable(person.get(field, [])) != _stable(
            saved.get(field, [])
        ):
            raise SyncError(f"Contact field {field} changed during the update.")


def rows(values):
    return enumerate((f"{entry['key']} — {entry['value']}" for entry in values), 1)


def removal_groups(values):
    """Keep exact duplicate pairs together, retaining first-appearance order."""
    groups = {}
    for entry in values:
        groups.setdefault((entry["key"], entry["value"]), []).append(entry)
    return list(groups.items())


def removal_rows(groups):
    return [
        (i, f"{key} — {value}" + (f" ({len(items)} entries)" if len(items) > 1 else ""))
        for i, ((key, value), items) in enumerate(groups, 1)
    ]


def run_custom_field(args, api, confirm, heading):
    remove = args.command == "remove-custom-field"
    emit("Reading contact…")
    person = api.get_contact(contact_resource(args.contact))
    current = entries(person)
    emit(heading(person) + "\n", primary=False)
    if remove:
        matches = [
            e
            for e in current
            if e["key"] == args.key and (args.value is None or e["value"] == args.value)
        ]
        similar = [
            e
            for e in current
            if e not in matches
            and e["key"].casefold() == args.key.casefold()
            and (args.value is None or e["value"].casefold() == args.value.casefold())
        ]
        changes = matches + similar
        expected = [e for e in current if e not in changes]
    else:
        pairs = list(dict.fromkeys(tuple(pair) for pair in args.field))
        existing = {(e["key"], e["value"]) for e in current}
        folded = {(key.casefold(), value.casefold()) for key, value in pairs}
        similar = [
            e
            for e in current
            if (e["key"], e["value"]) not in pairs
            and (e["key"].casefold(), e["value"].casefold()) in folded
        ]
        if similar:
            emit_list("Similar entries (case differs)", rows(similar))
            emit(
                "Matching is exact and case-sensitive; these entries are not matches.",
                primary=False,
            )
            emit("", primary=False)
        changes = [
            {"key": key, "value": value} for key, value in pairs if (key, value) not in existing
        ]
        expected = current + changes
    if not changes:
        emit(
            "No matching custom fields found; no changes made."
            if remove
            else "All supplied custom field pairs already exist; no changes made."
        )
        return 0
    # Validate projected size before offering an apply action.
    body = field_update_body(person, "userDefined", expected)
    heading_text = (
        ("Removing custom fields" if remove else "Adding custom fields")
        if args.apply
        else ("Proposed custom field removals" if remove else "Proposed custom field additions")
    )
    groups = removal_groups(changes) if remove else []
    choices = removal_rows(groups) if remove else list(rows(changes))
    if remove:
        emit_list(heading_text, [], total=len(changes))
        exact_count = len(removal_groups(matches))
        for title, group_rows, total in (
            ("Exact matches", choices[:exact_count], len(matches)),
            ("Similar entries (case differs)", choices[exact_count:], len(similar)),
        ):
            if group_rows:
                emit("", primary=False)
                emit_list(title, group_rows, total=total, primary=False)
    else:
        emit_list(heading_text, choices, total=len(changes))
    count = len(changes)
    noun = "entry" if count == 1 else "entries"
    if (
        not args.apply
        and len(choices) > 1
        and all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr))
    ):
        numbers = [i for i, _ in choices]

        def preview(selected):
            nonlocal expected, body, count, noun
            if remove:
                pairs = {groups[i - 1][0] for i in selected}
                expected = [e for e in current if (e["key"], e["value"]) not in pairs]
            else:
                expected = current + [changes[i - 1] for i in selected]
            body = field_update_body(person, "userDefined", expected)
            count = abs(len(current) - len(expected))
            noun = "entry" if count == 1 else "entries"
            if selected != numbers:
                emit_list(
                    "Selected custom field removals"
                    if remove
                    else "Selected custom field additions",
                    [(i, text) for i, text in choices if i in selected],
                    total=count,
                )
            emit("", primary=False)

        selected = review_selection(
            choices,
            noun="custom fields",
            heading="Selected custom field removals"
            if remove
            else "Selected custom field additions",
            unit=("entry", "entries"),
            preview=preview,
            question=lambda _: f"{'Remove' if remove else 'Add'} {count} custom field {noun}?",
            action="Remove selected custom fields" if remove else "Add selected custom fields",
        )
        if selected is None:
            emit("Cancelled; no changes made.")
            return 0
    elif not args.apply and not confirm(
        f"{'Remove' if remove else 'Add'} {count} custom field {noun}?"
    ):
        emit("Preview only; no changes made. Use --apply to save changes.")
        return 0
    api.apply_field_change(
        person, body, lambda saved: verify_custom_fields(person, expected, saved), "userDefined"
    )
    emit(f"{'Removed' if remove else 'Added'} and verified {count} custom field {noun}.")
    return 0
