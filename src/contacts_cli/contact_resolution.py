"""Resolve explicit identifiers to saved contacts without mutating account data."""

import sys
from pathlib import Path

from .contact_matches import contact_title, normalized, phone_key, read_match_contacts
from .core import address_key, contact_resource
from .errors import ContactFailure, SyncError
from .output import emit, emit_list
from .progress import StageProgress
from .selection import select_numbers


def load_identifiers(contact=None, file=None):
    if file is not None:
        try:
            lines = Path(file).read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError) as exc:
            raise SyncError(f"Could not read contact file: {exc}") from exc
        values = [
            line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")
        ]
    else:
        values = [contact.strip()] if contact is not None else []
    if not values or any(not value or any(ord(c) < 32 for c in value) for value in values):
        raise SyncError("Supply at least one nonempty contact identifier, one per line.")
    return list(dict.fromkeys(values))


def resolution_phone_key(value):
    """Ignore an optional plus for lookup, preserving every digit and extension."""
    key = phone_key(value)
    return (key[0].removeprefix("+"), key[1]) if key else None


def identifier_kind(value):
    try:
        return "id", contact_resource(value)
    except SyncError:
        if "://" in value or value.startswith(("people/", "person/")):
            raise
    if "@" in value:
        return "email", address_key(value)
    phone = resolution_phone_key(value)
    if phone:
        return "phone", phone
    return "name", normalized(value)


def matches(person, kind, value, *, partial_name=False, phone_suffix=False):
    if kind == "email":
        return any(
            address_key(e.get("value", "")) == value for e in person.get("emailAddresses", [])
        )
    if kind == "phone":
        return any(
            (saved := resolution_phone_key(e.get("value", ""))) is not None
            and (saved[0].endswith(value[0]) if phone_suffix else saved[0] == value[0])
            and (not value[1] or saved[1] == value[1])
            for e in person.get("phoneNumbers", [])
        )
    names = (normalized(contact_title({"names": [entry]})) for entry in person.get("names", []))
    return any(value in name if partial_name else value == name for name in names)


def describe_contact(person):
    """One-line identity; only the matching input is added by the resolver."""
    title = " ".join(contact_title(person).split())
    details = [f"{title} ({person['resourceName'].split('/')[-1]})"]
    company = next((o.get("name") for o in person.get("organizations", []) if o.get("name")), None)
    if company:
        details.append(" ".join(company.split()))
    return " — ".join(details)


def resolve_contacts(api, identifiers):
    """Return resources mapped to stable review numbers, or None on cancellation."""
    parsed = [(value, *identifier_kind(value)) for value in identifiers]
    people = []
    if any(kind != "id" for _, kind, _ in parsed):
        with StageProgress() as progress:
            progress.start("Reading contacts for matching")
            people = read_match_contacts(api)
    resolved, numbers = {}, {}
    pending, skipped_contacts = {}, {}
    unmatched = []
    matched_count = skipped_count = id_count = 0
    shown = False

    def flush_matches():
        nonlocal shown
        if pending:
            emit("", primary=False)
            emit_list(
                "More matched contacts" if shown else "Matched contacts",
                sorted(pending.items()),
                unit=("contact", "contacts"),
            )
            pending.clear()
            shown = True

    def number(resource):
        if resource not in numbers:
            numbers[resource] = len(numbers) + 1
        return numbers[resource]

    for original, kind, value in parsed:
        if kind == "id":
            resolved[value] = number(value)
            id_count += 1
            if value in skipped_contacts:
                flush_matches()
                earlier = skipped_contacts.pop(value)
                emit(
                    f"#{numbers[value]} selected through {original!r}; "
                    f"only the earlier identifier {earlier!r} was skipped.",
                    primary=False,
                )
            continue
        candidates = [p for p in people if matches(p, kind, value)]
        if not candidates:
            unmatched.append(original)
            continue
        rows = [(number(p["resourceName"]), describe_contact(p)) for p in candidates]
        if len(candidates) > 1:
            flush_matches()
            emit("", primary=False)
            shown = True
            emit_list(
                f"Multiple contacts match {original!r}",
                rows,
                unit=("contact", "contacts"),
            )
            if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
                raise SyncError(
                    "Multiple contacts match; rerun interactively or use contact IDs. "
                    "No changes made."
                )
            emit("", primary=False)
            selected = select_numbers(
                [i for i, _ in rows],
                noun="matching contacts",
                separate_response=True,
                skip_label="Skip this identifier",
                cancel_label="Cancel command",
            )
            if selected is None:
                return None
            if not selected:
                emit(f"Skipped {original!r} by choice.", primary=False)
                skipped_count += 1
                for person in candidates:
                    skipped_contacts[person["resourceName"]] = original
                continue
            candidates = [p for p in candidates if numbers[p["resourceName"]] in selected]
        else:
            person = candidates[0]
            n = numbers[person["resourceName"]]
            text = pending.get(n, describe_contact(person))
            if kind in {"email", "phone"} or normalized(original) != normalized(
                contact_title(person)
            ):
                text += f" — {original}"
            pending[n] = text
        matched_count += 1
        for person in candidates:
            resource = person["resourceName"]
            resolved[resource] = numbers[resource]
            if resource in skipped_contacts:
                flush_matches()
                earlier = skipped_contacts.pop(resource)
                emit(
                    f"#{numbers[resource]} matched through {original!r}; "
                    f"only the earlier identifier {earlier!r} was skipped.",
                    primary=False,
                )
    flush_matches()
    if unmatched:
        emit("", primary=False)
        emit_list("Unmatched inputs", enumerate(unmatched, 1), unit=("input", "inputs"))
        emit("Skipped these inputs; no matching saved contacts.", primary=False)
    emit("", primary=False)
    summary = (
        f"Inputs reviewed: {len(parsed)}; matched: {matched_count}; "
        f"unmatched: {len(unmatched)}; skipped by choice: {skipped_count}."
    )
    if id_count:
        summary += f" IDs supplied: {id_count} (checked next)."
    emit(summary)
    emit(f"Contacts resolved: {len(resolved)}.", primary=False)
    emit("", primary=False)
    return dict(sorted(resolved.items(), key=lambda item: item[1]))


def read_resolved_contact(api, resource, fields):
    """Skip a missing target; transport, authorization and incomplete reads still fail."""
    try:
        return api.get_contact(resource, fields)
    except ContactFailure:
        # get_contact uses ContactFailure only for an explicit not-found response.
        emit(f"Skipped {resource.split('/')[-1]!r}: contact not found.")
        return None
