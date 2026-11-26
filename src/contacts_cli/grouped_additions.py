"""Review independent, conflict-free saved-contact merges as a batch of plans."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass

from .contact_matches import contact_title
from .contact_merge import MergePlan, add_memberships
from .duplicate import copy_body
from .errors import SyncError
from .merge_conflicts import merge_values
from .output import emit, emit_list
from .selection import parse_selection
from .timing import read_input


@dataclass
class AdditiveMerge:
    number: int
    title: str
    resource: str
    reasons: list
    plan: MergePlan
    changes: list

    def row(self):
        target = contact_title(self.plan.original)
        lines = [
            self.title,
            f"Target: {target} ({self.resource.removeprefix('people/')})",
            "Matching " + ", ".join(self.reasons),
        ]
        lines.extend(line for change in self.changes for line in change.splitlines())
        return self.number, lines[0] + "\n" + "\n".join("     " + line for line in lines[1:])


def additive_candidates(selected, contacts, matches, details, schemas, labels, missing, review):
    references = Counter(resource for n in selected for resource, _, _ in matches[n])
    candidates = []
    for number in selected:
        found = matches[number]
        if len(found) != 1:
            continue
        resource, _, reasons = found[0]
        if (
            resource.startswith("input #")
            or references[resource] != 1
            or resource not in details
            or resource in review.merges
        ):
            continue
        original = details[resource]
        try:
            before = copy_body(original, schemas)
            expected, changes, conflicts = merge_values(before, contacts[number - 1])
        except SyncError:
            continue
        if conflicts:
            continue
        plan = MergePlan(original, expected, [number])
        changes += [f"Add contact label: {name}" for name in add_memberships(plan, labels)]
        changes += [f"Add contact label: {name} (new label)" for name in missing]
        if changes:
            candidates.append(
                AdditiveMerge(
                    number, contact_title(contacts[number - 1]), resource, reasons, plan, changes
                )
            )
    return candidates


def review_additions(
    selected, contacts, matches, details, api, labels, missing, review, *, apply=False
):
    items = additive_candidates(
        selected,
        contacts,
        matches,
        details,
        api.people._rootDesc["schemas"],
        labels,
        missing,
        review,
    )
    if len(items) < 2:
        return selected, review
    review.grouped_review = True
    handled, merged = set(), 0

    def preview(items, heading="Available merges without conflicts"):
        emit_list(heading, [item.row() for item in items], unit=("contact", "contacts"))

    emit("", primary=False)
    preview(items)
    emit(
        "\nWith --apply, changes are saved after review without final confirmation."
        if apply
        else "\nChanges will be saved after final confirmation.",
        primary=False,
    )
    chosen = [item.number for item in items]
    subset = False
    while True:
        numbers = [item.number for item in items]
        emit("", primary=False)
        if subset:
            emit(
                "  m   Merge selected contacts\n  s   Skip selected inputs\n"
                "  n   Return to selection\n  q   Cancel command",
                primary=False,
            )
        else:
            example = ",".join(str(n) for n in numbers[:2])
            emit(
                "  m       Merge all listed contacts\n  s       Skip all listed inputs\n"
                f"  {example:<7} Select contacts by number or range\n"
                "  i       Review individually\n  q       Cancel command",
                primary=False,
            )
        emit("Choice [n]: " if subset else "Choice [i]: ", primary=False, end="")
        try:
            answer = read_input().strip().casefold()
        except EOFError:
            return None
        finally:
            emit("", primary=False)
        if answer in {"q", "cancel"}:
            return None
        if subset and answer in {"n", ""}:
            chosen, subset = numbers, False
            preview(items)
            continue
        if not subset and answer in {"i", ""}:
            break
        if answer not in {"m", "s"}:
            if subset:
                emit("Choose m, s, n, or q.")
                continue
            try:
                chosen = parse_selection(answer, numbers)
            except ValueError as exc:
                emit(
                    str(exc)
                    if answer[:1].isdigit()
                    else "Enter m, s, i, q, or displayed numbers/ranges."
                )
                continue
            preview([item for item in items if item.number in chosen], "Reviewing selection")
            subset = True
            continue
        for item in items:
            if item.number in chosen:
                handled.add(item.number)
                if answer == "m":
                    review.merges[item.resource] = deepcopy(item.plan)
        count = len(chosen)
        if answer == "m":
            merged += count
            emit(
                f"Selected merges: {count} "
                + ("contact" if count == 1 else "contacts")
                + ". Not saved yet."
            )
        else:
            emit(f"Skipped {count} " + ("input." if count == 1 else "inputs."))
        items = [item for item in items if item.number not in chosen]
        if len(items) < 2:
            if items:
                emit("One entry remains for individual review.")
            break
        chosen, subset = [item.number for item in items], False
        emit("", primary=False)
        preview(items)
    if merged:
        emit(
            f"Total selected conflict-free merges: {merged} "
            + ("contact" if merged == 1 else "contacts")
            + ". Not saved yet."
        )
    return [n for n in selected if n not in handled], review
