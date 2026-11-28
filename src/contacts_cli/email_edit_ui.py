"""Select individual removals and indivisible addition/update changes."""

from .core import address_key, email_update_body
from .email_edit import is_primary, make_edit_plan, removal_indexes, select_removals, verify_edit
from .output import email_rows, emit, emit_list
from .selection import review_selection


def update_kind(update):
    if len(update.before) > 1:
        return "combine"
    return "label" if update.after.get("type") else "remove-label"


def update_text(update):
    address = update.after["value"]
    label = update.after.get("type", "")
    old = update.before[0].get("type", "")
    if update_kind(update) == "combine":
        detail = (
            f"Combine {len(update.before)} entries into one"
            f"\n     Resulting label: {label or 'none'}"
        )
    elif not label:
        detail = f"Remove label: {old}"
    elif old:
        detail = f"Change label: {old} → {label}"
    else:
        detail = f"Add label: {label}"
    return f"{address}\n     {detail}"


def update_question(update):
    address = update.after["value"]
    label = update.after.get("type", "")
    old = update.before[0].get("type", "")
    if update_kind(update) == "combine":
        result = f"labeled {label!r}" if label else "with no label"
        return f"Combine {len(update.before)} entries for {address} into one {result}?"
    if not label:
        return f"Remove the {old!r} label from {address}?"
    if old:
        return f"Change the label on {address} from {old!r} to {label!r}?"
    return f"Add the {label!r} label to {address}?"


def edit_choices(plan, *, remove):
    """Return (snapshot index or address, display text, kind) for each choice."""
    if remove:
        emails = plan.person.get("emailAddresses", [])
        return [
            (
                i,
                email_rows([emails[i]])[0][1] + (" (primary)" if is_primary(emails[i]) else ""),
                "remove",
            )
            for i in removal_indexes(plan)
        ]
    return [
        (e["value"], row[1], "add")
        for e, row in zip(plan.added, email_rows(plan.added), strict=True)
    ] + [(update.after["value"], update_text(update), "update") for update in plan.updates]


def show_changes(plan, choices, numbers, *, remove, apply=False, subset=False):
    rows = [(i, choices[i - 1][1]) for i in numbers]
    if remove:
        count = len({address_key(e["value"]) for e in plan.removed})
        emit_list(
            "Selected removals" if subset else "Removing" if apply else "Proposed removals",
            rows,
            total=len(plan.removed),
            suffix=f" ({count} {'address' if count == 1 else 'addresses'})",
        )
    else:
        for kind, noun, verb in [("add", "additions", "Adding"), ("update", "updates", "Updating")]:
            group = [(i, text) for i, text in rows if choices[i - 1][2] == kind]
            if group or (kind == "add" and not subset and not rows):
                if kind == "update" and all(update_kind(u) == "remove-label" for u in plan.updates):
                    noun = "label removal" if len(group) == 1 else "label removals"
                    verb = "Removing labels"
                    unit = ("email", "emails")
                else:
                    unit = ("entry", "entries") if kind == "add" else ("change", "changes")
                emit_list(
                    f"Selected {noun}" if subset else verb if apply else f"Proposed {noun}",
                    group,
                    unit=unit,
                )


def finish_email_edit(args, api, plan, *, interactive):
    remove = args.command == "remove-email"
    choices = edit_choices(plan, remove=remove)
    numbers = list(range(1, len(choices) + 1))
    if plan.skipped:
        emit(f"Unchanged: {len(plan.skipped)} {'entry' if len(plan.skipped) == 1 else 'entries'}")
        for entry in plan.skipped:
            emit("  " + email_rows([entry])[0][1], primary=False)
        emit("", primary=False)
    show_changes(plan, choices, numbers, remove=remove, apply=args.apply)
    next_number = len(choices) + 1
    if plan.duplicate_kept:
        emails = plan.person.get("emailAddresses", [])
        emit_list(
            "Kept entries",
            [
                (
                    next_number + offset,
                    email_rows([emails[i]])[0][1] + (" (primary)" if is_primary(emails[i]) else ""),
                )
                for offset, i in enumerate(plan.duplicate_kept)
            ],
            note="Informational only; these numbers cannot be selected.",
        )
        next_number += len(plan.duplicate_kept)
    for heading, values, unit in [
        (
            "Not found",
            plan.absent,
            ("address or pattern", "addresses or patterns")
            if any("*" in x for x in plan.absent)
            else ("address", "addresses"),
        ),
    ]:
        if values:
            emit_list(
                heading,
                enumerate(values, next_number),
                unit=unit,
                note="Informational only; these numbers cannot be selected." if choices else None,
            )
            next_number += len(values)
    emit(f"Remaining email entries: {len(plan.emails)}", primary=False)
    if not choices:
        emit(
            "No duplicate email entries found; no changes made."
            if getattr(args, "duplicates", False)
            else "No changes selected; no update made."
        )
        return 0
    selected_plan = plan
    last_selection = numbers

    def preview(selected):
        nonlocal selected_plan, last_selection
        if remove:
            selected_plan = select_removals(plan, [choices[i - 1][0] for i in selected])
        else:
            keys = {address_key(choices[i - 1][0]) for i in selected}
            # Rebuild only previously approved additions/updates; no new decisions.
            entries = [entry for entry in args.entries if address_key(entry[0]) in keys]
            selected_plan = make_edit_plan(
                plan.person, entries, resolve=lambda *a: True, expand_patterns=False
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
        if count == 1 and len(selected_plan.added) == 1 and not selected_plan.updates:
            return f"Add {selected_plan.added[0]['value']} to this contact?"
        if count == 1 and len(selected_plan.updates) == 1 and not selected_plan.added:
            return update_question(selected_plan.updates[0])
        return f"Apply these {count} email changes?"

    if interactive and not args.apply:
        selected = review_selection(
            [(i, choices[i - 1][1]) for i in numbers],
            noun="email entries" if remove else "changes",
            heading="Selected changes",
            unit=("change", "changes"),
            question=question,
            action="Remove selected email entries" if remove else "Apply selected changes",
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
