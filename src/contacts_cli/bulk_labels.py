"""Plan label additions to resolved contacts before performing any writes."""

import sys

from .contact_create import CreationState, LabelChoiceCancelled, create_label, resolve_labels
from .contact_resolution import describe_contact, read_resolved_contact
from .errors import SyncError, WriteUnverified
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
        f"{'Adding' if args.apply else 'Add'} {label_noun} {label_names}"
        if common
        else "Adding labels to contacts"
        if args.apply
        else "Proposed label additions to contacts"
    )
    emit_list(title, rows, unit=("contact", "contacts"))
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
    verified = 0
    state = CreationState()
    try:
        for i in selected:
            person, additions = plans[i]
            emit(f"Adding labels to {describe_contact(person)}…")
            for name in additions:
                if name not in labels:
                    state = CreationState()
                    labels[name] = create_label(api, name, state)
                add_membership(api, person, labels[name])
                verified += 1
            emit(f"Verified labels for {person['resourceName'].split('/')[-1]}.")
    except (SyncError, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        emit(
            ("\n" if interrupted else "")
            + f"Stopped; {verified} label {'addition' if verified == 1 else 'additions'} verified."
        )
        if not interrupted:
            emit(str(exc), primary=False)
        if state.phase == "created":
            emit(f"Label created but unverified: {state.location}.", primary=False)
        if api.write_started:
            emit(
                "Completed changes remain saved. "
                "Inspect the listed contacts and labels before retrying.",
                primary=False,
            )
        return 130 if interrupted else (3 if isinstance(exc, WriteUnverified) else 1)
    emit(
        f"Added and verified labels on {len(selected)} "
        f"{'contact' if len(selected) == 1 else 'contacts'}."
    )
    return 0
