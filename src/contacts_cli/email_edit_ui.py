"""Display and select indivisible email-address changes from an approved plan."""

from .core import address_key, email_update_body
from .email_edit import describe, is_primary, make_edit_plan, verify_edit
from .output import email_rows, emit, emit_list
from .selection import review_selection


def edit_choices(plan, *, remove):
    """Return (address, display text, kind), additions before updates."""
    if remove:
        result = []
        for address in plan.changes:
            matches = [e for e in plan.removed if address_key(e["value"]) == address_key(address)]
            if len(matches) == 1:
                text = email_rows(matches)[0][1]
            else:
                text = f"{address} — {len(matches)} entries" + "".join(
                    "\n     " + describe(e) + (" (primary)" if is_primary(e) else "")
                    for e in matches
                )
            result.append((address, text, "remove"))
        return result
    added = {address_key(e["value"]) for e in plan.added}
    updates = [address for address in plan.changes if address_key(address) not in added]
    return [
        (e["value"], row[1], "add")
        for e, row in zip(plan.added, email_rows(plan.added), strict=True)
    ] + [(address, text, "update") for address, text in zip(updates, plan.updates, strict=True)]


def show_changes(plan, choices, numbers, *, remove, apply=False, subset=False):
    rows = [(i, choices[i - 1][1]) for i in numbers]
    if remove:
        count = len(numbers)
        emit_list(
            "Selected removals" if subset else "Removing" if apply else "Proposed removals",
            rows,
            total=len(plan.removed),
            suffix=f" ({count} {'address' if count == 1 else 'addresses'})",
        )
    else:
        for kind, noun, verb in [("add", "additions", "Adding"), ("update", "updates", "Updating")]:
            group = [(i, text) for i, text in rows if choices[i - 1][2] == kind]
            if group or (kind == "add" and not subset):
                emit_list(
                    f"Selected {noun}" if subset else verb if apply else f"Proposed {noun}",
                    group,
                    unit=("entry", "entries") if kind == "add" else ("change", "changes"),
                )


def finish_email_edit(args, api, plan, *, interactive):
    remove = args.command == "remove-email"
    choices = edit_choices(plan, remove=remove)
    numbers = list(range(1, len(choices) + 1))
    show_changes(plan, choices, numbers, remove=remove, apply=args.apply)
    next_number = len(choices) + 1
    for heading, values, unit in [
        (
            "Not found",
            plan.absent,
            ("address or pattern", "addresses or patterns")
            if any("*" in x for x in plan.absent)
            else ("address", "addresses"),
        ),
        ("Skipped conflicts", plan.skipped, ("conflict", "conflicts")),
    ]:
        if values:
            emit_list(
                heading,
                enumerate(values, next_number),
                unit=unit,
                note="Informational only; these numbers cannot be selected.",
            )
            next_number += len(values)
    emit(f"Remaining email entries: {len(plan.emails)}", primary=False)
    if not choices:
        emit("No changes selected; no update made.")
        return 0
    selected_plan = plan
    last_selection = numbers

    def preview(selected):
        nonlocal selected_plan, last_selection
        keys = {address_key(choices[i - 1][0]) for i in selected}
        # Only changes already approved in the original plan may be rebuilt; no new decisions.
        entries = (
            [(choices[i - 1][0], "", "selection") for i in selected]
            if remove
            else [entry for entry in args.entries if address_key(entry[0]) in keys]
        )
        selected_plan = make_edit_plan(
            plan.person, entries, remove=remove, resolve=lambda *a: True, expand_patterns=False
        )
        email_update_body(selected_plan.person, selected_plan.emails)
        if selected != numbers:
            show_changes(selected_plan, choices, selected, remove=remove, subset=True)
        if selected != numbers or selected != last_selection:
            emit(f"Remaining email entries: {len(selected_plan.emails)}", primary=False)
        last_selection = selected

    def question(count):
        if remove:
            size = len(selected_plan.removed)
            return (
                "Remove this email entry?" if size == 1 else f"Remove these {size} email entries?"
            )
        return "Apply this email change?" if count == 1 else f"Apply these {count} email changes?"

    if interactive and not args.apply:
        selected = review_selection(
            [(i, choices[i - 1][1]) for i in numbers],
            noun="addresses" if remove else "changes",
            heading="Selected changes",
            unit=("change", "changes"),
            question=question,
            action="Remove selected addresses" if remove else "Apply selected changes",
            preview=preview,
        )
        if selected is None:
            emit("Cancelled; no changes made.")
            return 0
    body = email_update_body(selected_plan.person, selected_plan.emails)
    if args.apply or interactive:
        api.apply_email_change(
            selected_plan.person, body, lambda saved: verify_edit(selected_plan, saved)
        )
        emit(f"Saved and verified {len(selected_plan.changes)} change(s).")
    else:
        emit("Preview only; no changes made. Use --apply to save changes.")
    return 0
