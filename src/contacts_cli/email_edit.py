"""Plan add/remove email operations and verify the complete remaining email list."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace

from .address_inputs import matches_address_pattern, normalized_entries
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


@dataclass
class EmailUpdate:
    before: list
    after: dict


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
    removal_candidates: tuple | None = None
    duplicate_kept: tuple = ()


def expand_removals(person, entries):
    """Expand against the original snapshot, keeping unmatched requests for reporting."""
    for address, label, origin in entries:
        if "*" not in address:
            yield address, label, origin
            continue
        matches = [
            e["value"]
            for e in person.get("emailAddresses", [])
            if matches_address_pattern(e["value"], address)
        ]
        for value in matches or [address]:
            yield value, "", origin


def make_edit_plan(person, entries, *, remove=False, resolve=None, expand_patterns=True):
    validate_contact(person)
    if remove and expand_patterns:
        entries = expand_removals(person, entries)
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
            skipped.extend(deepcopy(matches))
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
        updates.append(EmailUpdate(deepcopy(matches), deepcopy(replacement)))
        changes.append(address)
    return EmailEditPlan(
        deepcopy(person), emails, changes, skipped, absent, removed, added, updates
    )


def make_duplicate_removal_plan(person):
    """Offer surplus occurrences, keeping the first primary or first stored entry."""
    validate_contact(person)
    emails = person.get("emailAddresses", [])
    groups = {}
    for i, entry in enumerate(emails):
        groups.setdefault(address_key(entry["value"]), []).append(i)
    candidates, kept = [], []
    for key in sorted(groups):
        indexes = groups[key]
        if len(indexes) < 2:
            continue
        survivor = next((i for i in indexes if is_primary(emails[i])), indexes[0])
        kept.append(survivor)
        candidates.extend(i for i in indexes if i != survivor)
    plan = EmailEditPlan(
        deepcopy(person),
        deepcopy(emails),
        [],
        [],
        [],
        [],
        [],
        [],
        removal_candidates=tuple(candidates),
        duplicate_kept=tuple(kept),
    )
    return select_removals(plan, candidates)


def removal_indexes(plan):
    """Identify each eligible occurrence in the original snapshot, in preview order."""
    if plan.removal_candidates is not None:
        return list(plan.removal_candidates)
    keys = {address_key(entry["value"]) for entry in plan.removed}
    emails = plan.person.get("emailAddresses", [])
    return sorted(
        (i for i, entry in enumerate(emails) if address_key(entry["value"]) in keys),
        key=lambda i: address_key(emails[i]["value"]),
    )


def select_removals(plan, indexes):
    """Remove selected snapshot occurrences, retaining every other entry unchanged."""
    selected = set(indexes)
    if not selected <= set(removal_indexes(plan)):
        raise SyncError("Select only email entries in the removal preview.")
    emails = plan.person.get("emailAddresses", [])
    removed = [deepcopy(emails[i]) for i in removal_indexes(plan) if i in selected]
    changes = list(dict.fromkeys(address_key(entry["value"]) for entry in removed))
    return replace(
        plan,
        emails=[deepcopy(entry) for i, entry in enumerate(emails) if i not in selected],
        removed=removed,
        changes=changes,
        removal_candidates=tuple(i for i in removal_indexes(plan) if i in selected),
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
