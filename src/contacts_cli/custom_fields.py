"""Exact custom-field edits with full-list preservation and verified writes."""

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


def run_custom_field(args, api, confirm, heading):
    remove = args.command == "remove-custom-field"
    emit("Reading contact…")
    person = api.get_contact(contact_resource(args.contact))
    current = entries(person)
    emit(heading(person) + "\n", primary=False)
    emit(f"Existing custom field entries: {len(current)}", primary=False)
    emit("", primary=False)
    matches = [
        entry
        for entry in current
        if entry["key"] == args.key and (args.value is None or entry["value"] == args.value)
    ]
    similar = [
        entry
        for entry in current
        if entry not in matches
        and entry["key"].casefold() == args.key.casefold()
        and (args.value is None or entry["value"].casefold() == args.value.casefold())
    ]
    if similar:
        emit_list("Similar entries (case differs)", rows(similar))
        emit("Matching is exact and case-sensitive; these entries are not matches.", primary=False)
        emit("", primary=False)
    if remove:
        changes = matches
        expected = [entry for entry in current if entry not in matches]
    else:
        changes = [] if matches else [{"key": args.key, "value": args.value}]
        expected = current + changes
    if not changes:
        emit(
            "No matching custom fields found; no changes made."
            if remove
            else "This custom field and value already exist; no changes made."
        )
        return 0
    # Validate projected size before offering an apply action.
    body = field_update_body(person, "userDefined", expected)
    heading_text = (
        ("Removing custom fields" if remove else "Adding custom fields")
        if args.apply
        else ("Proposed custom field removals" if remove else "Proposed custom field additions")
    )
    emit_list(heading_text, rows(changes))
    emit(f"Remaining custom field entries: {len(expected)}", primary=False)
    count = len(changes)
    noun = "entry" if count == 1 else "entries"
    if not args.apply and not confirm(
        f"{'Remove' if remove else 'Add'} {count} custom field {noun}?"
    ):
        emit("Preview only; no changes made. Use --apply to save changes.")
        return 0
    api.apply_field_change(
        person, body, lambda saved: verify_custom_fields(person, expected, saved), "userDefined"
    )
    emit(f"{'Removed' if remove else 'Added'} and verified {count} custom field {noun}.")
    return 0
