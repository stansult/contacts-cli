"""Plan add/remove email operations and verify the complete remaining email list."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass

from .address_inputs import normalized_entries
from .core import (
    CONTACT_FIELDS,
    _email_signature,
    _stable,
    address_key,
    contact_source,
    email_label,
    validate_contact,
)
from .errors import SyncError


def is_primary(entry):
    metadata = entry.get("metadata", {})
    return bool(metadata.get("sourcePrimary") or metadata.get("primary"))


def describe(entry):
    return entry["value"] + (f" — {entry['type']}" if entry.get("type") else " — (no label)")


@dataclass
class EmailEditPlan:
    person: dict
    emails: list
    changes: list
    skipped: list
    absent: list
    removed: list
    added: list
    updates: list


def make_edit_plan(person, entries, *, remove=False, resolve=None):
    validate_contact(person)
    incoming = normalized_entries(entries, person, email_label, remove=remove)
    emails = deepcopy(person.get("emailAddresses", []))
    changes, skipped, absent, removed = [], [], [], []
    added, updates = [], []
    for key, (address, label, _) in sorted(incoming.items()):
        matches = [entry for entry in emails if address_key(entry["value"]) == key]
        if remove:
            if not matches:
                absent.append(address)
                continue
            emails = [entry for entry in emails if address_key(entry["value"]) != key]
            removed.extend(matches)
            changes.append(address)
            continue
        if not matches:
            entry = {"value": address}
            if label:
                entry["type"] = label
            emails.append(entry)
            added.append(deepcopy(entry))
            changes.append(address)
            continue
        old_label = matches[0].get("type", "")
        if len(matches) == 1 and address_key(old_label) == address_key(label):
            continue
        conflict = len(matches) > 1 or bool(old_label)
        if conflict and (resolve is None or not resolve(address, matches, label)):
            skipped.append(
                f"{address}: kept {len(matches)} existing entry(s); "
                f"requested label: {label or '(no label)'}; existing: "
                + "; ".join(map(describe, matches))
            )
            continue
        survivor = next((entry for entry in matches if is_primary(entry)), matches[0])
        replacement = deepcopy(survivor)
        replacement.pop("type", None)
        replacement.pop("formattedType", None)
        if label:
            replacement["type"] = label
        if any(is_primary(entry) for entry in matches):
            replacement.setdefault("metadata", {})["sourcePrimary"] = True
        index = next(i for i, entry in enumerate(emails) if address_key(entry["value"]) == key)
        emails = [entry for entry in emails if address_key(entry["value"]) != key]
        emails.insert(index, replacement)
        updates.append(
            f"{address}: {len(matches)} entry(s) → 1; "
            + "; ".join(map(describe, matches))
            + f" → {describe(replacement)}"
        )
        changes.append(address)
    return EmailEditPlan(
        deepcopy(person), emails, changes, skipped, absent, removed, added, updates
    )


def verify_edit(plan, saved):
    validate_contact(saved)
    if contact_source(saved)["id"] != contact_source(plan.person)["id"]:
        raise SyncError("Saved result refers to a different contact source.")
    # Primary can be reassigned by Google when its previous entry is removed.
    expected = Counter(_email_signature(entry)[:3] for entry in plan.emails)
    actual = Counter(_email_signature(entry)[:3] for entry in saved.get("emailAddresses", []))
    if actual != expected:
        raise SyncError("Saved email entries or labels do not match the preview.")
    for entry in plan.emails:
        if is_primary(entry) and not any(
            _email_signature(other)[:3] == _email_signature(entry)[:3] and is_primary(other)
            for other in saved.get("emailAddresses", [])
        ):
            raise SyncError("A retained primary email choice changed.")
    for field in CONTACT_FIELDS.split(","):
        if field not in {"emailAddresses", "metadata"} and _stable(
            plan.person.get(field, [])
        ) != _stable(saved.get(field, [])):
            raise SyncError(f"Contact field {field} changed during the update.")
