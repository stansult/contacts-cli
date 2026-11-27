"""Compact review of independent membership-only import plans."""

from collections import defaultdict
from copy import deepcopy

from .contact_matches import contact_title
from .contact_merge import ImportReview, changed_fields
from .grouped_additions import additive_candidates
from .output import emit, emit_list
from .selection import select_numbers


def candidates(selected, contacts, matches, details, api, labels, missing):
    schemas = api.people._rootDesc["schemas"]
    return [
        item
        for item in additive_candidates(
            selected, contacts, matches, details, schemas, labels, missing, ImportReview()
        )
        if not (set(changed_fields(item.plan, schemas)) - {"memberships"})
    ]


def missing_labels(plan, labels, missing):
    saved = {
        m.get("contactGroupMembership", {}).get("contactGroupResourceName")
        for m in plan.original.get("memberships", [])
    }
    return tuple(name for name, resource in labels.items() if resource not in saved) + tuple(
        missing
    )


def show_groups(items, labels, missing, *, heading="Add"):
    groups = defaultdict(list)
    for item in items:
        groups[missing_labels(item.plan, labels, missing)].append(item)
    for names, group in groups.items():
        emit("", primary=False)
        emit_list(
            f"{heading} {'label' if len(names) == 1 else 'labels'} {', '.join(names)}",
            [(item.number, contact_title(item.plan.original)) for item in group],
            unit=("contact", "contacts"),
        )
    return groups


def review_labels(items, selected, labels, missing, *, apply=False):
    review = ImportReview()
    if not items:
        return selected, review
    review.grouped_review = True
    groups = show_groups(items, labels, missing, heading="Available: add")
    emit(
        "Changes will be saved after review."
        if apply
        else "Changes will be saved after final confirmation.",
        primary=False,
    )
    handled = set()
    for names, group in groups.items():
        chosen = select_numbers(
            [item.number for item in group],
            noun=f"contacts to label {', '.join(names)}",
            separate_response=True,
            skip_label="Skip these label additions",
            cancel_label="Cancel command",
        )
        if chosen is None:
            return None
        handled.update(item.number for item in group)
        for item in group:
            if item.number in chosen:
                review.merges[item.resource] = deepcopy(item.plan)
        unit = "contact" if len(chosen) == 1 else "contacts"
        emit(f"Selected label additions: {len(chosen)} {unit}. Not saved yet.")
    return [n for n in selected if n not in handled], review
