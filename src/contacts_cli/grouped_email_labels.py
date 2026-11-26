"""Plan batches of independent, email-label-only changes without additional reads."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass

from .contact_matches import contact_title
from .contact_merge import ImportReview, MergePlan, add_memberships
from .duplicate import copy_body
from .errors import SyncError
from .merge_conflicts import merge_values
from .output import emit, emit_list
from .selection import parse_selection
from .timing import read_input


@dataclass
class LabelChange:
    number: int
    resource: str
    original: dict
    expected: dict
    address: str
    saved_label: str
    incoming_label: str

    def row(self, show_saved=False):
        suffix = f" — saved label: {self.saved_label}" if show_saved else ""
        return self.number, f"{contact_title(self.original)} — {self.address}{suffix}"


def label_groups(selected, contacts, matches, details, schemas, labels, missing):
    if missing:
        return []
    references = Counter(resource for n in selected for resource, _, _ in matches[n])
    groups = {}
    for number in selected:
        found = matches[number]
        if len(found) != 1:
            continue
        resource = found[0][0]
        if resource.startswith("input #") or references[resource] != 1 or resource not in details:
            continue
        original = details[resource]
        before = copy_body(original, schemas)
        if add_memberships(MergePlan(original, deepcopy(before)), labels):
            continue
        conflicts = []
        try:
            _, additions, _ = merge_values(before, contacts[number - 1], details=conflicts)
            if additions or len(conflicts) != 1:
                continue
            conflict = conflicts[0]
            if conflict.field != "emailAddresses" or len(conflict.saved) != 1:
                continue
            old = conflict.saved[0]
            incoming = conflict.incoming
            if not isinstance(old.get("type"), str) or not isinstance(incoming.get("type"), str):
                continue
            # Property comparison is structural; UI wording is not an eligibility contract.
            expected, _, _ = merge_values(before, contacts[number - 1], resolver=lambda c: "r")
            label_only = deepcopy(before)
            label_only["emailAddresses"][conflict.indices[0]]["type"] = incoming["type"]
            if expected != label_only:
                continue
        except SyncError:
            continue
        item = LabelChange(
            number, resource, original, expected, old["value"], old["type"], incoming["type"]
        )
        groups.setdefault(incoming["type"], []).append(item)
    return [items for items in groups.values() if len(items) >= 2]


def review_label_groups(selected, contacts, matches, details, api, labels, missing, *, apply=False):
    review = ImportReview()
    handled = set()
    replacements = 0
    groups = label_groups(
        selected, contacts, matches, details, api.people._rootDesc["schemas"], labels, missing
    )
    review.grouped_review = bool(groups)
    for items in groups:
        numbers = [item.number for item in items]

        def preview(items):
            saved_labels = list(dict.fromkeys(item.saved_label for item in items))
            mixed = len({label.casefold() for label in saved_labels}) > 1
            note = "" if mixed else "Saved label: " + " / ".join(saved_labels) + "\n"
            note += "Incoming label: " + items[0].incoming_label
            emit_list(
                "Available email label changes",
                [item.row(show_saved=mixed) for item in items],
                unit=("contact", "contacts"),
                note=note,
            )

        preview(items)
        emit("", primary=False)
        emit(
            "With --apply, changes are saved after review without final confirmation."
            if apply
            else "Changes will be saved after final confirmation.",
            primary=False,
        )
        chosen = numbers
        subset = False
        while True:
            emit("", primary=False)
            if subset:
                menu = (
                    "  r   Replace saved labels with incoming label for selected entries\n"
                    "  k   Keep saved labels for selected entries\n"
                    "  n   Return to selection\n"
                    "  q   Cancel command"
                )
            else:
                example = (
                    f"{numbers[0]}-{numbers[-1]}"
                    if numbers == list(range(numbers[0], numbers[-1] + 1))
                    else ",".join(str(n) for n in numbers[:2])
                )
                menu = (
                    "  r       Replace saved labels with incoming label for all listed entries\n"
                    "  k       Keep saved labels for all listed entries\n"
                    f"  {example:<7} Select entries by number or range\n"
                    "  i       Review individually\n"
                    "  q       Cancel command"
                )
            emit(menu, primary=False)
            emit("Choice [n]: " if subset else "Choice [i]: ", primary=False, end="")
            try:
                answer = read_input().strip().casefold()
            except EOFError:
                return None
            finally:
                emit("", primary=False)
            if answer in ("q", "cancel"):
                return None
            if subset and answer in ("", "n"):
                chosen, subset = numbers, False
                preview(items)
                continue
            if not subset and answer in ("", "i"):
                break
            if answer not in ("r", "k"):
                if subset:
                    emit("Choose r, k, n, or q.")
                    continue
                try:
                    chosen = parse_selection(answer, numbers)
                except ValueError as exc:
                    emit(
                        str(exc)
                        if answer[:1].isdigit()
                        else "Enter r, k, i, q, or displayed numbers/ranges."
                    )
                    continue
                emit_list(
                    "Reviewing selection",
                    [
                        item.row(show_saved=len({x.saved_label.casefold() for x in items}) > 1)
                        for item in items
                        if item.number in chosen
                    ],
                    unit=("contact", "contacts"),
                )
                subset = True
                continue
            for item in items:
                if item.number not in chosen:
                    continue
                handled.add(item.number)
                if answer == "r":
                    review.merges[item.resource] = MergePlan(
                        item.original, deepcopy(item.expected), [item.number]
                    )
            count = len(chosen)
            unit = "contact" if count == 1 else "contacts"
            if answer == "r":
                more = " more" if replacements else ""
                emit(f"Selected label replacements: {count}{more} {unit}.")
                replacements += count
            else:
                emit(f"Selected: keep saved labels for {count} {unit}.")
            items = [item for item in items if item.number not in chosen]
            if len(items) < 2:
                if items:
                    emit("One entry remains; continuing with individual review.")
                break
            numbers = [item.number for item in items]
            chosen, subset = numbers, False
            emit("", primary=False)
            preview(items)
    remaining = [n for n in selected if n not in handled]
    if replacements:
        unit = "contact" if replacements == 1 else "contacts"
        emit(f"Total selected label replacements: {replacements} {unit}. Not saved yet.")
    return remaining, review
