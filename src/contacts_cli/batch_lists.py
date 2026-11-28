"""Read-only batch field listings with shared contact resolution and outcome reporting."""

from .contact_resolution import read_resolved_contact, resolve_contacts
from .core import CONTACT_FIELDS
from .errors import SyncError
from .label_data import contact_groups, memberships
from .label_edit import LABEL_FIELDS, label_rows
from .output import email_rows, emit, emit_list
from .phone_edit import phone_entries, phone_rows

LIST_COMMANDS = {"list-email", "list-phone", "list-label"}


def run_field_lists(args, api, heading):
    resources = resolve_contacts(api, args.contact_identifiers)
    if resources is None:
        emit("Cancelled; no changes made.")
        return 0
    if not resources:
        emit("No contacts selected; nothing to list.")
        return 0
    multiple = len(resources) > 1
    listed = skipped = failed = 0
    labels = None
    status = 0
    for resource, number in resources.items():
        try:
            emit("Reading contact…")
            fields = LABEL_FIELDS if args.command == "list-label" else CONTACT_FIELDS
            person = read_resolved_contact(api, resource, fields)
            if person is None:
                skipped += 1
                continue
            if args.command == "list-email":
                title, rows, unit = (
                    "Email addresses",
                    email_rows(person.get("emailAddresses", [])),
                    ("entry", "entries"),
                )
            elif args.command == "list-phone":
                title, rows, unit = (
                    "Phone numbers",
                    phone_rows(phone_entries(person)),
                    ("entry", "entries"),
                )
            else:
                if labels is None:
                    emit("Reading contact labels…")
                    labels = contact_groups(api)
                title, rows, unit = (
                    "Labels",
                    label_rows(labels, memberships(person)),
                    ("label", "labels"),
                )
            # Render each complete result together; a failed read never leaves an empty heading.
            contact_title = heading(person)
            if multiple:
                contact_title = contact_title.replace("Contact:", f"Contact #{number}:", 1)
            emit(contact_title + "\n", primary=False)
            emit_list(title, rows, unit=unit)
            listed += 1
            if multiple:
                emit("", primary=False)
        except (SyncError, KeyboardInterrupt) as exc:
            failed += 1
            interrupted = isinstance(exc, KeyboardInterrupt)
            status = 130 if interrupted else 1
            emit(
                ("\n" if interrupted else "")
                + f"Listing incomplete at contact #{number}: "
                + ("interrupted." if interrupted else str(exc))
            )
            break
    if multiple or status:
        emit(
            f"Contacts: {listed} listed; {skipped} skipped; {failed} failed; "
            f"{len(resources) - listed - skipped - failed} not attempted."
        )
    return status
