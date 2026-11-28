"""Plan label additions to resolved contacts before performing any writes."""

import sys

from .contact_create import CreationState, LabelChoiceCancelled, create_label, resolve_labels
from .contact_resolution import describe_contact, read_resolved_contact
from .errors import ContactFailure, ContactVerificationFailure, SyncError, WriteUnverified
from .label_edit import LABEL_FIELDS, add_membership, memberships
from .output import emit, emit_list
from .selection import review_selection


def run_bulk_labels(args, api, resources, confirm):
    emit("Reading selected contacts…")
    people = [
        person
        for resource in resources
        if (person := read_resolved_contact(api, resource, LABEL_FIELDS)) is not None
    ]
    if not people:
        emit("No contacts selected; no changes made.")
        return 0
    # Resolve spelling once for the batch; preview shows exactly where each label will be added.
    try:
        labels, missing = resolve_labels(api, args.label)
    except LabelChoiceCancelled:
        emit("Cancelled; no changes made.")
        return 0
    plans = {}
    unchanged = []
    for person in people:
        number = resources[person["resourceName"]]
        current = memberships(person)
        additions = [name for name, resource in labels.items() if resource not in current] + missing
        if additions:
            plans[number] = (person, additions)
        else:
            unchanged.append((number, describe_contact(person)))
    if unchanged:
        emit("", primary=False)
        emit_list(
            "Already have all requested labels",
            unchanged,
            unit=("contact", "contacts"),
        )
    if not plans:
        emit("All requested labels are already on these contacts; no changes made.")
        return 0
    common = next(iter(plans.values()))[1]
    if any(additions != common for _, additions in plans.values()):
        common = None
    label_names = ", ".join(repr(name) for name in (common or []))
    label_noun = "label" if common and len(common) == 1 else "labels"
    rows = [
        (
            i,
            describe_contact(person)
            + (
                ""
                if common
                else "\n     Add: "
                + ", ".join(
                    f"{name} (new label)" if name in missing else name for name in additions
                )
            ),
        )
        for i, (person, additions) in plans.items()
    ]
    emit("", primary=False)
    title = (
        (
            f"Adding {label_noun} {label_names}"
            if args.apply
            else f"Proposed label additions: {label_names}"
        )
        if common
        else "Adding labels to contacts"
        if args.apply
        else "Proposed label additions to contacts"
    )
    emit_list(
        title,
        rows,
        unit=("contact", "contacts"),
        separator=" — " if common and not args.apply else ": ",
    )
    if common and missing:
        emit("New labels to create: " + ", ".join(repr(name) for name in missing), primary=False)
    selected = list(plans)

    def question(count):
        target = f"{count} {'contact' if count == 1 else 'contacts'}"
        if common:
            return f"Add {label_noun} {label_names} to {target}?"
        names = ", ".join(repr(name) for name in [*labels, *missing])
        return f"Add labels {names} as shown to {target}?"

    if not args.apply:
        if all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
            selected = review_selection(
                rows,
                noun="contacts to label",
                heading="Selected contacts",
                unit=("contact", "contacts"),
                question=question,
                action="Add selected labels",
            )
            if selected is None:
                emit("Cancelled; no changes made.")
                return 0
        elif not confirm(question(len(plans))):
            emit("Preview only; no changes made. Use --apply to add labels.")
            return 0
    return save_label_plans(
        api,
        plans,
        selected,
        labels,
        unchanged=len(unchanged),
        unselected=len(plans) - len(selected),
    )


def save_label_plans(api, plans, selected, labels, *, unchanged=0, unselected=0):
    """Save shared labels first; retain per-label evidence if a contact partly succeeds."""
    created = []
    state = CreationState()
    try:
        for number in selected:
            for name in plans[number][1]:
                if name in labels:
                    continue
                state = CreationState()
                api.write_started = False
                emit(f"Creating label: {name}…")
                labels[name] = create_label(api, name, state)
                created.append(name)
    except (SyncError, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        emit(("\n" if interrupted else "") + "Stopped while creating shared labels.")
        if not interrupted:
            emit(str(exc), primary=False)
        if created:
            emit("New labels verified: " + ", ".join(created) + ". They remain saved.")
        if state.phase == "created":
            emit(f"Label created but unverified: {state.location}.")
        elif state.phase == "writing" and api.write_started:
            emit("Label creation outcome is unknown; inspect account labels before retrying.")
        emit(f"Contacts: 0 verified; 0 failed; 0 unverified; {len(selected)} not attempted.")
        return 130 if interrupted else 3 if isinstance(exc, WriteUnverified) else 1

    verified = failed = unverified = completed = additions_verified = added = 0
    status = 0
    for position, number in enumerate(selected, 1):
        person, names = plans[number]
        satisfied = []
        current_name = ""
        emit(f"Adding labels to contact {position} of {len(selected)}: {describe_contact(person)}…")
        try:
            for current_name in names:
                api.write_started = False
                changed = add_membership(api, person, labels[current_name])
                satisfied.append(current_name)
                additions_verified += 1
                added += bool(changed)
            verified += 1
            completed += 1
        except (SyncError, KeyboardInterrupt) as exc:
            completed += 1
            interrupted = isinstance(exc, KeyboardInterrupt)
            uncertain = isinstance(exc, WriteUnverified) or (interrupted and api.write_started)
            if uncertain:
                unverified += 1
            else:
                failed += 1
            status = 130 if interrupted else max(status, 3 if uncertain else 1)
            emit(
                ("\n" if interrupted else "")
                + f"Contact #{number}: "
                + ("interrupted." if interrupted else str(exc))
            )
            if satisfied:
                emit("Labels verified on this contact: " + ", ".join(satisfied), primary=False)
            emit(
                f"Label {'unverified' if uncertain else 'not applied'}: {current_name}",
                primary=False,
            )
            remaining = names[len(satisfied) + 1 :]
            if remaining:
                emit("Labels not attempted on this contact: " + ", ".join(remaining), primary=False)
            if not isinstance(exc, (ContactFailure, ContactVerificationFailure)):
                break
    emit(
        f"Contacts: {verified} verified; {failed} failed; {unverified} unverified; "
        f"{len(selected) - completed} not attempted."
    )
    emit(
        f"Label additions: {added} saved; "
        f"{additions_verified - added} already applied since preview."
    )
    if unchanged or unselected:
        emit(f"Contacts unchanged: {unchanged}; not selected: {unselected}.")
    if status and (added or unverified or created):
        emit("Completed changes remain saved. Inspect unverified results before retrying.")
    return status
