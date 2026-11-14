"""Preview and sequentially create contacts with verified contact labels."""

import json
import re
import sys
from calendar import month_name
from copy import deepcopy
from dataclasses import dataclass

from .api import execute
from .core import contact_source, validate_contact
from .duplicate import READ_FIELDS, creation_marker
from .errors import SyncError, WriteUnverified
from .output import emit, emit_list


class LabelChoiceCancelled(Exception):
    """The user declined label resolution before any writes."""


def choose_label(name, similar, *, allow_create=True, on_contact=None):
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        spellings = ", ".join(repr(label) for label in similar)
        raise SyncError(
            f"Label {name!r} differs only by case from {spellings}. "
            "Use an exact existing spelling with --label, or run interactively to choose. "
            "--apply does not resolve label choices; no changes made."
        )
    if on_contact is None:
        emit(f"Label {name!r} differs only by case from existing labels.")
        options = [f"Use existing {label!r}" for label in similar]
        if allow_create:
            options.append(f"Create new {name!r}")
    else:
        if len(similar) == 1:
            label = similar[0]
            if label in on_contact:
                emit(
                    f"This contact {'already has' if allow_create else 'has'} {label!r}, "
                    f"which differs only by case from {name!r}."
                )
            else:
                emit(f"Label {label!r} exists in Google Contacts, but isn't on this contact.")
                emit(f"Its spelling differs only by case from {name!r}.", primary=False)
        else:
            emit(f"Labels differing only by case from {name!r} exist in Google Contacts.")
        options = [
            f"Remove {label!r} from this contact"
            if not allow_create
            else f"Keep {label!r}; skip adding {name!r}"
            if label in on_contact
            else f"Add {label!r}"
            for label in similar
        ]
        if allow_create:
            suffix = "too" if any(label in on_contact for label in similar) else "instead"
            options.append(f"Create {name!r} and add it {suffix}")
    options.append("Cancel command")
    emit_list("Options", enumerate(options, 1), unit=("option", "options"))
    while True:
        emit(f"Choose 1–{len(options)} (Enter = 1): ", file=sys.stderr, end="", flush=True)
        try:
            answer = input().strip() or "1"
        except EOFError:
            raise LabelChoiceCancelled from None
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            choice = int(answer)
            if choice == len(options):
                raise LabelChoiceCancelled
            return similar[choice - 1] if choice <= len(similar) else name
        emit(f"Enter a number from 1 to {len(options)}.", file=sys.stderr)


def resolve_labels(api, names, *, allow_create=True, memberships=None):
    names = list(dict.fromkeys(names))
    if not names:
        return {}, []
    emit("Checking contact labels…")
    groups, seen, token = [], set(), None
    while True:
        result = execute(
            api.people.contactGroups().list(
                pageSize=1000, pageToken=token, groupFields="name,groupType,metadata"
            )
        )
        groups.extend(result.get("contactGroups", []))
        token = result.get("nextPageToken")
        if not token:
            break
        if token in seen:
            raise SyncError("Repeated contact-label page token; stopped before creation.")
        seen.add(token)
    existing, missing = {}, []
    for name in names:
        matches = [
            g for g in groups if g.get("name") == name and not g.get("metadata", {}).get("deleted")
        ]
        if len(matches) > 1 or any(g.get("groupType") != "USER_CONTACT_GROUP" for g in matches):
            raise SyncError(f"Contact label {name!r} is ambiguous or a system label.")
        if matches:
            resource = matches[0].get("resourceName")
            if not isinstance(resource, str) or not resource.startswith("contactGroups/"):
                raise SyncError("Invalid contact label resource returned by Google.")
            existing[name] = resource
        else:
            similar = list(
                dict.fromkeys(
                    g["name"]
                    for g in groups
                    if isinstance(g.get("name"), str)
                    and g["name"].casefold() == name.casefold()
                    and g.get("groupType") == "USER_CONTACT_GROUP"
                    and not g.get("metadata", {}).get("deleted")
                )
            )
            if similar:
                if memberships is not None:
                    on_contact = {g["name"] for g in groups if g.get("resourceName") in memberships}
                    if not allow_create:
                        absent = [label for label in similar if label not in on_contact]
                        for label in absent:
                            existing[label] = next(
                                g["resourceName"] for g in groups if g.get("name") == label
                            )
                        similar = [label for label in similar if label in on_contact]
                        if not similar:
                            continue
                    selected = choose_label(
                        name, similar, allow_create=allow_create, on_contact=on_contact
                    )
                else:
                    selected = choose_label(name, similar, allow_create=allow_create)
                if selected != name:
                    candidates = [
                        g
                        for g in groups
                        if g.get("name") == selected and not g.get("metadata", {}).get("deleted")
                    ]
                    if len(candidates) != 1:
                        raise SyncError(f"Contact label {selected!r} is ambiguous.")
                    resource = candidates[0].get("resourceName")
                    if not isinstance(resource, str) or not resource.startswith("contactGroups/"):
                        raise SyncError("Invalid contact label resource returned by Google.")
                    existing[selected] = resource
                    continue
            missing.append(name)
    return existing, missing


@dataclass
class CreationState:
    phase: str = "not started"
    location: str = ""


def create_label(api, name, state=None):
    state = state or CreationState()
    state.phase = "writing"
    result = api.write(
        api.people.contactGroups().create(body={"contactGroup": {"name": name}}),
        operation="label creation",
    )
    state.phase = "returned"
    resource = result.get("resourceName")
    if not isinstance(resource, str) or not resource.startswith("contactGroups/"):
        raise WriteUnverified("Google did not return a valid label identity.")
    state.phase, state.location = "created", resource
    emit(f"Created label: {name}")
    try:
        saved = execute(api.people.contactGroups().get(resourceName=resource))
        if saved.get("name") != name or saved.get("groupType") != "USER_CONTACT_GROUP":
            raise SyncError("Saved label does not match the requested name and label type.")
    except SyncError as exc:
        raise WriteUnverified(str(exc)) from exc
    state.phase = "verified"
    return resource


def contains(expected, actual):
    """Compare supplied values, allowing generated properties and entry reordering."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            contains(value, actual.get(key)) for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        remaining = list(actual)
        # Match more specific entries first, preserving repeated supplied values.
        for item in sorted(expected, key=lambda item: len(json.dumps(item)), reverse=True):
            for index, candidate in enumerate(remaining):
                if contains(item, candidate):
                    remaining.pop(index)
                    break
            else:
                return False
        return True
    return expected == actual


def verify_created(body, saved):
    validate_contact(saved)
    for field, entries in body.items():
        actual = deepcopy(saved.get(field, []))
        if field == "nicknames":
            for entry in actual:
                # Google may omit the generic nickname type in readback.
                entry.setdefault("type", "DEFAULT")
        if field == "names":
            for entry in actual:
                # Google may parse an unstructured name into components.
                if "unstructuredName" not in entry and "displayName" in entry:
                    entry["unstructuredName"] = entry["displayName"]
        if not contains(entries, actual):
            raise SyncError(
                f"{FIELD_NAMES.get(field, human_key(field))} differs from the input.\n"
                f"  Requested: {format_entries(field, entries)}\n"
                f"  Saved: {format_entries(field, saved.get(field, []))}"
            )


def create_contact(api, body, state=None):
    body = deepcopy(body)
    body.setdefault("userDefined", []).append(creation_marker("Created"))
    state = state or CreationState()
    state.phase = "writing"
    result = api.write(
        api.people.people().createContact(
            body=body, personFields=READ_FIELDS, sources=["READ_SOURCE_TYPE_CONTACT"]
        ),
        operation="creation",
    )
    state.phase = "returned"
    try:
        validate_contact(result)
        resource = result["resourceName"]
        state.location = "https://contacts.google.com/person/" + resource.removeprefix("people/")
        state.phase = "created"
        emit(f"Created contact: {state.location}")
        saved = api.get_contact(resource, READ_FIELDS)
        if contact_source(saved)["id"] != contact_source(result)["id"]:
            raise SyncError("Created contact identity changed during verification.")
        verify_created(body, saved)
    except (SyncError, KeyError, TypeError, ValueError) as exc:
        raise WriteUnverified(str(exc)) from exc
    state.phase = "verified"
    return state.location


FIELD_NAMES = {
    "names": "Name",
    "emailAddresses": "Email",
    "phoneNumbers": "Phone",
    "organizations": "Company",
    "addresses": "Address",
    "urls": "Website",
    "userDefined": "Custom field",
    "biographies": "Notes",
    "birthdays": "Birthday",
    "events": "Event",
    "nicknames": "Nickname",
    "memberships": "Contact labels",
}


def human_key(key):
    return {
        "givenName": "First name",
        "familyName": "Last name",
        "unstructuredName": "Full name",
        "countryCode": "Country code",
        "contentType": "Format",
    }.get(key, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key).capitalize())


def readable(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        return "; ".join(f"{human_key(k)}: {readable(v)}" for k, v in value.items())
    return {"DEFAULT": "Default", "TEXT_PLAIN": "Plain text", "HTML": "HTML"}.get(
        str(value), str(value)
    )


def format_date(date):
    year, month, day = (date.get(k, 0) for k in ("year", "month", "day"))
    if not isinstance(month, int) or not 0 <= month <= 12:
        return readable(date)
    parts = [month_name[month]] if month else []
    if day:
        parts.append(str(day))
    if year:
        parts.append(str(year))
    return " ".join(parts) or "Not specified"


def format_entry(field, entry):
    if not isinstance(entry, dict):
        return readable(entry)
    remaining = {
        k: v for k, v in entry.items() if k != "metadata" and not k.startswith("formatted")
    }
    main_key = {"organizations": "name", "userDefined": "key"}.get(field, "value")
    main = remaining.pop(main_key, "")
    label = remaining.pop("type", "")
    if field == "userDefined":
        main = f"{main}: {remaining.pop('value', '')}"
    if "date" in remaining:
        main = format_date(remaining.pop("date"))
    value = str(main)
    if label:
        value += (" — " if value else "") + readable(label)
    details = [f"{human_key(key)}: {readable(value)}" for key, value in remaining.items()]
    if details:
        if "\n" in value:
            value = "; ".join(details) + "\n" + value
        else:
            value += ("; " if value else "") + "; ".join(details)
    return value or "Empty entry"


def format_entries(field, entries):
    return (
        " | ".join(format_entry(field, entry).replace("\n", " / ") for entry in entries)
        or "Not present"
    )


def contact_preview(person):
    names = person.get("names", [])
    name = (
        " ".join(
            names[0][k] for k in ("givenName", "middleName", "familyName") if names[0].get(k)
        ).strip()
        if names
        else ""
    )
    title = (names[0].get("unstructuredName") or name) if names else ""
    title = title or next(
        (o["name"] for o in person.get("organizations", []) if o.get("name")), "New contact"
    )
    rows = [title]
    for field, entries in person.items():
        for entry in entries:
            value = format_entry(field, entry).replace("\n", "\n       ")
            rows.append(f"     {FIELD_NAMES[field]}: {value}")
    rows.append("     Custom field: Created: Created by contacts-cli (timestamp set at creation)")
    return "\n".join(rows)


def run_create(args, api, contacts, confirm):
    try:
        labels, missing = resolve_labels(api, args.label)
    except LabelChoiceCancelled:
        emit("Cancelled; no changes made.")
        return 0
    if labels:
        emit_list("Existing labels", enumerate(labels, 1), unit=("label", "labels"))
    if missing:
        emit_list("Labels to create", enumerate(missing, 1), unit=("label", "labels"))
    emit_list(
        "Creating contacts" if args.apply else "Proposed contacts",
        ((i, contact_preview(p)) for i, p in enumerate(contacts, 1)),
        unit=("contact", "contacts"),
    )
    if args.label:
        emit("Labels for every contact: " + ", ".join([*labels, *missing]), primary=False)
    question = (
        "Create these contacts" + (f" and {len(missing)} new label(s)" if missing else "") + "?"
    )
    if not args.apply and not confirm(question):
        emit("Preview only; no changes made. Use --apply to create contacts.")
        return 0
    completed, created_labels, attempted = 0, 0, 0
    state, subject, kind = CreationState(), "", "label"
    try:
        for name in missing:
            state, subject = CreationState(), f"Label {name!r}"
            emit(f"Creating label: {name}…")
            labels[name] = create_label(api, name, state)
            created_labels += 1
        kind = "contact"
        for i, person in enumerate(contacts, 1):
            attempted = i
            state, subject = CreationState(), f"Contact #{i}"
            body = deepcopy(person)
            if labels:
                body["memberships"] = [
                    {"contactGroupMembership": {"contactGroupResourceName": resource}}
                    for resource in labels.values()
                ]
            emit(f"Creating contact {i} of {len(contacts)}…")
            create_contact(api, body, state)
            completed += 1
            if len(contacts) > 1:
                emit(f"Verified contact {i} of {len(contacts)}.")
    except (SyncError, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        created = state.phase in {"created", "verified"}
        unknown = (
            not created
            and (interrupted or isinstance(exc, WriteUnverified))
            and state.phase != "not started"
        )
        if created:
            reason = "verification was interrupted" if interrupted else "verification failed"
            message = f"{subject} was created, but {reason}."
        elif unknown:
            message = f"{subject}: creation outcome is unknown."
        else:
            message = f"{subject} was not created." + (" Interrupted." if interrupted else "")
        emit(("\n" if interrupted else "") + message)
        if not interrupted and not unknown:
            emit(str(exc), primary=False)
        contact_count = completed + int(kind == "contact" and created and attempted > completed)
        label_count = created_labels + int(kind == "label" and created)
        remaining = len(contacts) - attempted
        if len(contacts) > 1 or kind == "label":
            parts = [f"{contact_count} created", f"{completed} verified"]
            if remaining:
                parts.append(f"{remaining} not attempted")
            emit("Contacts: " + "; ".join(parts) + ".", primary=False)
        if label_count:
            emit(f"New labels created: {label_count}. They remain saved.", primary=False)
        if unknown:
            emit(
                "Check Google Contacts before retrying; this attempt may have created "
                + ("a contact." if kind == "contact" else "a label."),
                primary=False,
            )
        if contact_count:
            emit(
                (
                    "The contact remains saved. Check it before retrying; "
                    "rerunning creates another contact."
                    if len(contacts) == 1
                    else "Created contacts remain saved. Do not rerun the full input; "
                    "it would create duplicates."
                ),
                primary=False,
            )
        return 130 if interrupted else (3 if created or unknown else 1)
    emit(f"Created and verified {completed} contact{'s' if completed != 1 else ''}.")
    return 0
