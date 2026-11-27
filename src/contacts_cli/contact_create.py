"""Preview and sequentially create contacts with verified contact labels."""

import json
import re
import sys
from calendar import month_name
from copy import deepcopy
from dataclasses import dataclass

from .api import execute
from .contact_inputs import names_match
from .contact_matches import contact_title, duplicate_matches, match_rows, read_match_contacts
from .contact_merge import (
    assess_match,
    read_matched_details,
    review_import,
    run_merged_import,
    skip_unchanged_inputs,
)
from .core import contact_source, validate_contact
from .duplicate import READ_FIELDS
from .errors import ContactVerificationFailure, SyncError, WriteUnverified
from .grouped_additions import review_additions
from .grouped_email_labels import review_label_groups
from .import_failures import ImportFailures, contact_specific
from .label_data import contact_groups, is_active_user_label, label_identity
from .output import emit, emit_list
from .progress import StageProgress
from .selection import review_selection, select_numbers
from .timing import read_input


class LabelChoiceCancelled(Exception):
    """The user declined label resolution before any writes."""


def choose_label(name, similar, *, allow_create=True, on_contact=None, create_only=False):
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        spellings = ", ".join(repr(label) for label in similar)
        raise SyncError(
            f"Label {name!r} differs only by case from {spellings}. "
            "Use an exact existing spelling with --label, or run interactively to choose. "
            "--apply does not resolve label choices; no changes made."
        )
    if create_only:
        if len(similar) == 1:
            emit(f"Label {similar[0]!r} already exists; only its case differs from {name!r}.")
        else:
            emit(f"Labels differing only by case from {name!r} already exist.")
        options = [f"Keep {label!r}; skip creating {name!r}" for label in similar]
        options.append(f"Create {name!r} as a separate label")
    elif on_contact is None:
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
            else f"Keep {label!r} already on this contact; add nothing"
            if label in on_contact
            else f"Add existing {label!r} to this contact"
            for label in similar
        ]
        if allow_create:
            options.append(f"Create {name!r} and add it to this contact")
    options.append("Cancel command")
    emit_list("Options", enumerate(options, 1), unit=("option", "options"))
    while True:
        emit(
            f"Choose 1–{len(options)} (Enter = 1, q = cancel): ",
            file=sys.stderr,
            end="",
            flush=True,
        )
        try:
            answer = read_input().strip() or "1"
        except EOFError:
            raise LabelChoiceCancelled from None
        if answer.casefold() == "q":
            raise LabelChoiceCancelled
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            choice = int(answer)
            if choice == len(options):
                raise LabelChoiceCancelled
            return similar[choice - 1] if choice <= len(similar) else name
        emit(f"Enter a number from 1 to {len(options)}, or q to cancel.", file=sys.stderr)


def resolve_labels(api, names, *, allow_create=True, memberships=None, create_only=False):
    names = list(dict.fromkeys(names))
    if not names:
        return {}, []
    emit("Checking contact labels…")
    groups = contact_groups(api)
    existing, missing = {}, []
    for name in names:
        matches = [
            g for g in groups if g.get("name") == name and not g.get("metadata", {}).get("deleted")
        ]
        if len(matches) > 1 or any(g.get("groupType") != "USER_CONTACT_GROUP" for g in matches):
            raise SyncError(f"Contact label {name!r} is ambiguous or a system label.")
        if matches:
            _, resource = label_identity(matches[0])
            existing[name] = resource
        else:
            similar = list(
                dict.fromkeys(
                    g["name"]
                    for g in groups
                    if isinstance(g.get("name"), str)
                    and g["name"].casefold() == name.casefold()
                    and is_active_user_label(g)
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
                    selected = choose_label(
                        name, similar, allow_create=allow_create, create_only=create_only
                    )
                if selected != name:
                    candidates = [
                        g
                        for g in groups
                        if g.get("name") == selected and not g.get("metadata", {}).get("deleted")
                    ]
                    if len(candidates) != 1:
                        raise SyncError(f"Contact label {selected!r} is ambiguous.")
                    _, resource = label_identity(candidates[0])
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
        matches = names_match(entries, actual) if field == "names" else contains(entries, actual)
        if not matches:
            raise SyncError(
                f"{FIELD_NAMES.get(field, human_key(field))} differs from the input.\n"
                f"  Requested: {format_entries(field, entries)}\n"
                f"  Saved: {format_entries(field, saved.get(field, []))}"
            )


def create_contact(api, body, state=None):
    body = deepcopy(body)
    state = state or CreationState()
    state.phase = "writing"
    result = api.write(
        api.people.people().createContact(
            body=body, personFields=READ_FIELDS, sources=["READ_SOURCE_TYPE_CONTACT"]
        ),
        operation="creation",
    )
    state.phase = "returned"
    reading = False
    try:
        validate_contact(result)
        resource = result["resourceName"]
        state.location = "https://contacts.google.com/person/" + resource.removeprefix("people/")
        state.phase = "created"
        emit(f"Created contact: {state.location}")
        reading = True
        saved = api.get_contact(resource, READ_FIELDS)
        reading = False
        if contact_source(saved)["id"] != contact_source(result)["id"]:
            raise SyncError("Created contact identity changed during verification.")
        verify_created(body, saved)
    except (SyncError, KeyError, TypeError, ValueError) as exc:
        error = WriteUnverified if reading else ContactVerificationFailure
        raise error(str(exc)) from exc
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
    if (
        field == "emailAddresses"
        and str(remaining.get("displayName", "")).casefold() == str(main).casefold()
    ):
        remaining.pop("displayName", None)
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


def contact_preview(person, matches=(), summaries=None):
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
            if field == "names" and entry == {"unstructuredName": title}:
                continue
            value = format_entry(field, entry).replace("\n", "\n       ")
            rows.append(f"     {FIELD_NAMES[field]}: {value}")
    if matches:
        rows.append("\n     Possible match" + ("es:" if len(matches) != 1 else ":"))
        for (identifier, _, _), row in zip(matches, match_rows(matches), strict=True):
            rows.append(f"       - {row}")
            if summaries and identifier in summaries:
                rows.extend("         " + line for line in summaries[identifier].splitlines())
    return "\n".join(rows)


def run_create(args, api, contacts, confirm):
    with StageProgress() as progress:
        progress.start("Reading contacts for duplicate checking")
        existing_contacts = read_match_contacts(api)
    try:
        labels, missing = resolve_labels(api, args.label)
    except LabelChoiceCancelled:
        emit("Cancelled; no changes made.")
        return 0
    if labels:
        emit_list("Existing labels", enumerate(labels, 1), unit=("label", "labels"))
    if missing:
        emit_list("Labels to create", enumerate(missing, 1), unit=("label", "labels"))
    matches = duplicate_matches(contacts, existing_contacts)
    details = read_matched_details(matches, api)
    existing_contacts = [details.get(p["resourceName"], p) for p in existing_contacts]
    matches = duplicate_matches(contacts, existing_contacts)
    assessments = {
        number: {
            identifier: assess_match(
                contacts[number - 1],
                target,
                api,
                labels,
                missing,
                saved=not identifier.startswith("input #"),
            )
            for identifier, target, _ in found
        }
        for number, found in matches.items()
    }
    summaries = {
        n: {key: value[0] for key, value in found.items()} for n, found in assessments.items()
    }
    from .label_only_import import candidates, review_labels, show_groups

    compact = candidates(list(matches), contacts, matches, details, api, labels, missing)
    compact_numbers = {item.number for item in compact}
    complete_numbers = {
        number
        for number, found in matches.items()
        if args.label
        and len(found) == 1
        and not found[0][0].startswith("input #")
        and assessments[number][found[0][0]][2]
    }
    has_matches = any(matches.values())
    if len(compact_numbers | complete_numbers) != len(contacts):
        emit_list(
            "Contacts to review"
            if has_matches
            else ("Creating contacts" if args.apply else "Proposed contacts"),
            (
                (i, contact_preview(p, matches[i], summaries[i]) + "\n")
                for i, p in enumerate(contacts, 1)
                if i not in compact_numbers | complete_numbers
            ),
            unit=("contact", "contacts"),
        )
    show_groups(compact, labels, missing)
    if complete_numbers:
        emit_list(
            "Already complete",
            [(n, contact_title(details[matches[n][0][0]])) for n in sorted(complete_numbers)],
            unit=("input", "inputs"),
        )
    if args.label and len(compact_numbers) != len(contacts):
        emit("Labels for every contact: " + ", ".join([*labels, *missing]), primary=False)
    question = (
        "Create these contacts" + (f" and {len(missing)} new label(s)" if missing else "") + "?"
    )
    selected = list(range(1, len(contacts) + 1))
    interactive = all(s.isatty() for s in (sys.stdin, sys.stdout, sys.stderr))
    if has_matches:
        if not interactive:
            if args.apply:
                raise SyncError(
                    "Possible duplicates require interactive review; --apply does not resolve "
                    "them. No changes made."
                )
            emit("Preview only; possible duplicates require interactive review. No changes made.")
            return 0
        if len(contacts) > 1 and not args.apply:
            emit(
                "For possible matches, you’ll choose whether to skip, merge, or create separately.",
                primary=False,
            )
            selected = select_numbers(selected, noun="contacts to import", separate_response=True)
            if selected is None:
                emit("Cancelled; no changes made.")
                return 0
        before_skip = len(selected)
        selected = skip_unchanged_inputs(selected, matches, assessments)
        if selected is None:
            emit("Cancelled; no changes made.")
            return 0
        if not selected:
            emit("All selected inputs skipped; no changes made.")
            return 0
        skipped_unchanged = before_skip - len(selected)
        label_review = review_labels(
            [item for item in compact if item.number in selected],
            selected,
            labels,
            missing,
            apply=args.apply,
        )
        if label_review is None:
            emit("Cancelled; no changes made.")
            return 0
        selected, label_planned = label_review
        grouped = review_label_groups(
            selected, contacts, matches, details, api, labels, missing, apply=args.apply
        )
        if grouped is None:
            emit("Cancelled; no changes made.")
            return 0
        selected, planned = grouped
        planned.merges.update(label_planned.merges)
        planned.grouped_review |= label_planned.grouped_review
        planned.skipped_unchanged = skipped_unchanged
        additive = review_additions(
            selected, contacts, matches, details, api, labels, missing, planned, apply=args.apply
        )
        if additive is None:
            emit("Cancelled; no changes made.")
            return 0
        selected, planned = additive
        if planned.grouped_review and any(matches[n] for n in selected):
            emit("\nContinuing with individual contact review.\n", primary=False)
        reviewed = review_import(
            selected, contacts, existing_contacts, api, details, labels, missing, planned
        )
        if reviewed is None:
            emit("Cancelled; no changes made.")
            return 0
        if reviewed.merges or reviewed.combined_inputs or reviewed.skipped_unchanged:
            return run_merged_import(args, api, reviewed, labels, missing, confirm)
        selected = list(reviewed.creates)
        if not selected:
            emit("All selected inputs skipped; no changes made.")
            return 0
        if selected != list(range(1, len(contacts) + 1)):
            emit_list(
                "Selected contacts",
                ((i, contact_preview(contacts[i - 1])) for i in selected),
                unit=("contact", "contacts"),
            )
        question = (
            f"Create {len(selected)} contact{'s' if len(selected) != 1 else ''}"
            + (f" and {len(missing)} new label(s)" if missing else "")
            + "?"
        )
        if not args.apply and not confirm(question):
            emit("Cancelled; no changes made.")
            return 0
    elif not args.apply:
        if len(contacts) > 1 and all(s.isatty() for s in (sys.stdin, sys.stdout, sys.stderr)):
            selected = review_selection(
                [(i, contact_preview(p)) for i, p in enumerate(contacts, 1)],
                noun="contacts",
                heading="Selected contacts",
                unit=("contact", "contacts"),
                question=lambda count: (
                    ("Create this contact" if count == 1 else f"Create these {count} contacts")
                    + (f" and {len(missing)} new label(s)" if missing else "")
                    + "?"
                ),
                action="Create selected contacts",
            )
            if selected is None:
                emit("Cancelled; no changes made.")
                return 0
        elif not confirm(question):
            emit("Preview only; no changes made. Use --apply to create contacts.")
            return 0
    subset = len(selected) != len(contacts)
    selected_contacts = [(number, contacts[number - 1]) for number in selected]
    contacts = [person for _, person in selected_contacts]
    completed, created_labels, attempted, created_total = 0, 0, 0, 0
    failures = ImportFailures()
    state, subject, kind = CreationState(), "", "label"
    try:
        for name in missing:
            state, subject = CreationState(), f"Label {name!r}"
            emit(f"Creating label: {name}…")
            labels[name] = create_label(api, name, state)
            created_labels += 1
        kind = "contact"
        for i, (number, person) in enumerate(selected_contacts, 1):
            attempted = i
            state, subject = CreationState(), f"Contact #{number}"
            body = deepcopy(person)
            if labels:
                body["memberships"] = [
                    {"contactGroupMembership": {"contactGroupResourceName": resource}}
                    for resource in labels.values()
                ]
            origin = f" (input #{number})" if subset else ""
            emit(f"Creating contact {i} of {len(contacts)}{origin}…")
            try:
                create_contact(api, body, state)
            except SyncError as exc:
                if len(contacts) == 1 or not contact_specific(exc):
                    raise
                created_total += int(state.phase in {"created", "verified"})
                failures.record(
                    f"Contact #{number} — {contact_preview(person).splitlines()[0]}",
                    exc,
                    location=state.location,
                    remaining=len(contacts) - attempted,
                )
                continue
            created_total += 1
            completed += 1
            if len(contacts) > 1:
                emit(f"Verified contact {i} of {len(contacts)}{origin}.")
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
        if not interrupted:
            emit(str(exc), primary=False)
        contact_count = created_total + int(kind == "contact" and created)
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
                    "rerunning can create another contact."
                    if len(contacts) == 1
                    else "Created contacts remain saved. Do not rerun the full input; "
                    "it can create duplicates."
                ),
                primary=False,
            )
        if kind == "contact" and len(contacts) > 1:
            failures.record(
                subject, exc, location=state.location, unverified=created or unknown, announce=False
            )
        failures.summary(remaining)
        return 130 if interrupted else max(failures.exit_code, 3 if created or unknown else 1)
    if failures.rows:
        emit(f"Contacts: {created_total} created; {completed} verified.")
        failures.summary()
        emit(
            "Review failed/unverified contacts before retrying. "
            "Rerunning the full input can create duplicates."
        )
        return failures.exit_code
    emit(f"Created and verified {completed} contact{'s' if completed != 1 else ''}.")
    return 0
