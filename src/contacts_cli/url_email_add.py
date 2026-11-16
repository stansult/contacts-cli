"""Review unlabeled webpage addresses without altering existing email entries."""

from .core import address_key, email_update_body
from .email_edit import make_edit_plan, verify_edit
from .output import emit, emit_list
from .selection import select_numbers


def confirm_selection(count):
    while True:
        emit(
            f"Add these {count} addresses to this contact?"
            if count != 1
            else "Add this address to this contact?"
        )
        emit("  y   Add selected addresses\n  n   Return to selection\n  q   Cancel", primary=False)
        emit("Confirm [n]: ", end="", primary=False)
        try:
            answer = input().strip().casefold()
        except EOFError:
            return "q"
        if answer in {"", "n", "no"}:
            return "n"
        if answer in {"y", "yes"}:
            return "y"
        if answer == "q":
            return "q"
        emit("Choose y, n, or q.")


def run_url_add(args, api, person, *, interactive):
    existing = {address_key(entry["value"]) for entry in person.get("emailAddresses", [])}
    candidates = [entry for entry in args.entries if address_key(entry[0]) not in existing]
    rows = [(i, entry[0]) for i, entry in enumerate(candidates, 1)]
    skipped = len(args.entries) - len(candidates)
    if skipped:
        emit(f"Already on this contact: {skipped}; existing entries and labels kept.")
    emit_list("Adding" if args.apply else "Proposed additions", rows, unit=("address", "addresses"))
    if not rows:
        emit("No additions needed; no update made.")
        return 0
    selected = list(range(1, len(rows) + 1))
    if interactive and not args.apply:
        while True:
            emit("", primary=False)
            selected = select_numbers(range(1, len(rows) + 1), noun="addresses")
            if selected is None:
                emit("Cancelled; no changes made.")
                return 0
            emit_list(
                "Selected additions",
                [(i, rows[i - 1][1]) for i in selected],
                unit=("address", "addresses"),
            )
            decision = confirm_selection(len(selected))
            if decision == "y":
                break
            if decision == "q":
                emit("Cancelled; no changes made.")
                return 0
    elif not args.apply:
        emit("Preview only; no changes made. Use --apply to add all proposed addresses.")
        return 0
    plan = make_edit_plan(person, [candidates[i - 1] for i in selected])
    body = email_update_body(plan.person, plan.emails)
    api.apply_email_change(plan.person, body, lambda saved: verify_edit(plan, saved))
    count = len(plan.changes)
    emit(f"Saved and verified {count} addition{'s' if count != 1 else ''}.")
    return 0
