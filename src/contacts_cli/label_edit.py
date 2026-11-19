"""Edit contact labels without replacing existing memberships or contact fields."""

import sys

from .contact_create import (
    CreationState,
    LabelChoiceCancelled,
    create_label,
    resolve_labels,
)
from .core import contact_resource, contact_source
from .errors import SyncError, WriteUnverified
from .label_data import active_user_labels, contact_groups, label_identity
from .label_removal import resolve_removals
from .output import emit, emit_list
from .selection import review_selection

LABEL_FIELDS = "names,organizations,memberships,metadata"


def memberships(person):
    entries = person.get("memberships", [])
    if not isinstance(entries, list):
        raise SyncError("Incomplete contact memberships; no labels changed.")
    result = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SyncError("Invalid contact membership.")
        group = entry.get("contactGroupMembership")
        if group is not None:
            resource = group.get("contactGroupResourceName") if isinstance(group, dict) else None
            if not isinstance(resource, str) or not resource.startswith("contactGroups/"):
                raise SyncError("Invalid contact label resource.")
            result.add(resource)
    return result


def edit_membership(api, person, group, *, remove=False):
    action = "removal" if remove else "addition"
    resource = person["resourceName"]
    latest = api.get_contact(resource, LABEL_FIELDS)
    if contact_source(latest)["id"] != contact_source(person)["id"]:
        raise SyncError("Contact identity changed since preview; stopped before changing labels.")
    before = memberships(latest)
    if (group in before) != remove:
        return False
    result = api.write(
        api.people.contactGroups()
        .members()
        .modify(
            resourceName=group,
            body={"resourceNamesToRemove" if remove else "resourceNamesToAdd": [resource]},
        ),
        operation=f"label {action}",
    )
    if not isinstance(result, dict):
        raise WriteUnverified(f"Label {action} returned an incomplete response.")
    if result.get("notFoundResourceNames"):
        raise SyncError(f"Google could not find the contact; label {action} was not applied.")
    if result.get("canNotRemoveLastContactGroupResourceNames"):
        raise SyncError("Google refused to remove the contact’s last contact-group membership.")
    try:
        saved = api.get_contact(resource, LABEL_FIELDS)
        if contact_source(saved)["id"] != contact_source(person)["id"]:
            raise SyncError("Contact identity changed during verification.")
        after = memberships(saved)
        expected = before - {group} if remove else before | {group}
        if not expected.issubset(after) or (remove and group in after):
            raise SyncError(
                "The label remains applied or another existing label is missing."
                if remove
                else "The added label or an existing label is missing from the saved contact."
            )
    except SyncError as exc:
        raise WriteUnverified(
            f"Label {action} was submitted but verification failed: {exc}"
        ) from exc
    return True


def add_membership(api, person, group):
    return edit_membership(api, person, group)


def run_label_edit(args, api, confirm, heading):
    if args.contact is None:
        return run_create_labels(args, api, confirm)
    remove = args.command == "remove-label"
    verb, participle = ("Remove", "Removed") if remove else ("Add", "Added")
    operation = "removals" if remove else "additions"
    emit("Reading contact…")
    person = api.get_contact(contact_resource(args.contact), LABEL_FIELDS)
    emit(heading(person), primary=False)
    emit("", primary=False)
    current = memberships(person)
    try:
        if remove:
            labels, missing, kinds = resolve_removals(api, args.label, memberships=current)
        else:
            labels, missing = resolve_labels(api, args.label, memberships=current)
    except LabelChoiceCancelled:
        emit("Cancelled; no changes made.")
        return 0
    emit("", primary=False)
    already = [name for name, resource in labels.items() if resource in current]
    if remove:
        additions = already
    else:
        additions = [name for name in labels if name not in already] + missing
        if already:
            emit_list("Already on this contact", enumerate(already, 1), unit=("label", "labels"))
            emit("", primary=False)
    if remove:
        emit_list(
            "Removing labels" if args.apply else "Proposed label removals",
            [],
            total=len(additions),
            unit=("label", "labels"),
        )
        for kind, title in (
            (0, "Exact matches"),
            (1, "Matching patterns"),
            (2, "Similar labels (case differs)"),
        ):
            group_rows = [(i, name) for i, name in enumerate(additions, 1) if kinds[name] == kind]
            if group_rows:
                emit("", primary=False)
                emit_list(title, group_rows, unit=("label", "labels"), primary=False)
    else:
        emit_list(
            (
                ("Removing labels" if remove else "Adding labels")
                if args.apply
                else f"Proposed label {operation}"
            ),
            enumerate(
                [
                    f"{name} (new label)" if name in missing and not remove else name
                    for name in additions
                ],
                1,
            ),
            unit=("label", "labels"),
        )
    if not additions:
        emit(
            "No matching labels on this contact; no changes made."
            if remove
            else "All requested labels are already on this contact; no changes made."
        )
        return 0
    total = len(additions)
    noun = "label" if total == 1 else "labels"
    if missing and not remove:
        new = len(missing)
        new_noun = "label" if new == 1 else "labels"
        target = ("it" if total == 1 else "them") if new == total else f"{total} labels"
        question = f"Create {new} new {new_noun} and add {target} to this contact?"
    else:
        direction = "from" if remove else "to"
        question = f"{verb} {total} {noun} {direction} this contact?"
    if (
        remove
        and not args.apply
        and len(additions) > 1
        and all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr))
    ):
        selected = review_selection(
            enumerate(additions, 1),
            noun="labels",
            heading="Selected label removals",
            unit=("label", "labels"),
            question=lambda count: (
                f"Remove {count} {'label' if count == 1 else 'labels'} from this contact?"
            ),
            action="Remove selected labels",
        )
        if selected is None:
            emit("Cancelled; no changes made.")
            return 0
        additions = [additions[i - 1] for i in selected]
        total = len(additions)
    elif not args.apply and not confirm(question):
        emit(f"Preview only; no changes made. Use --apply to {verb.lower()} labels.")
        return 0
    verified, created = 0, 0
    stage, name, state = "", "", CreationState()
    try:
        for name in additions:
            if name in missing and not remove:
                stage, state = "creating label", CreationState()
                emit(f"Creating label: {name}…")
                labels[name] = create_label(api, name, state)
                created += 1
            stage = "removing label" if remove else "adding label"
            emit(f"{stage.capitalize()}: {name}…")
            changed = edit_membership(api, person, labels[name], remove=remove)
            if remove and not changed:
                emit(f"Already removed since preview: {name}; skipped.")
                continue
            verified += 1
            if total > 1:
                emit(f"{participle} and verified label: {name}")
    except (SyncError, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        emit(("\n" if interrupted else "") + f"Stopped while {stage} {name!r}.")
        if not interrupted:
            emit(str(exc), primary=False)
        emit(f"Label {operation} verified: {verified} of {len(additions)}.", primary=False)
        if stage == "creating label" and state.phase == "created":
            created += 1
        if created:
            emit(f"New labels created: {created}. They remain saved.", primary=False)
        if api.write_started:
            emit(
                "Completed changes remain saved. Check the contact before retrying.", primary=False
            )
        return 130 if interrupted else (3 if isinstance(exc, WriteUnverified) else 1)
    emit(f"{participle} and verified {verified} label{'s' if verified != 1 else ''}.")
    return 0


def run_list_labels(args, api, heading):
    """Read memberships and names; never change contact or label data."""
    current = None
    if args.contact is not None:
        emit("Reading contact…")
        person = api.get_contact(contact_resource(args.contact), LABEL_FIELDS)
        current = memberships(person)
        emit(heading(person) + "\n", primary=False)
    emit("Reading contact labels…")
    labels = {}
    for group in active_user_labels(contact_groups(api, include_counts=current is None)):
        if current is None or group.get("resourceName") in current:
            name, resource = label_identity(group)
            label = name
            if current is None:
                # Google omits memberCount for empty groups.
                count = group.get("memberCount", 0)
                suffix = (
                    f"{count} {'contact' if count == 1 else 'contacts'}"
                    if type(count) is int and count >= 0
                    else "count unavailable"
                )
                label = f"{name} — {suffix}"
            labels[resource] = (name, label)
    rows = sorted(labels.values(), key=lambda item: (item[0].casefold(), item[0]))
    emit_list("Labels", enumerate((label for _, label in rows), 1), unit=("label", "labels"))
    return 0


def run_create_labels(args, api, confirm):
    """Create account labels through the same resolver and verified writer as contacts."""
    try:
        existing, missing = resolve_labels(api, args.label, create_only=True)
    except LabelChoiceCancelled:
        emit("Cancelled; no changes made.")
        return 0
    if existing:
        emit_list("Already exists", enumerate(existing, 1), unit=("label", "labels"))
    if not missing:
        emit("All requested labels already exist; no changes made.")
        return 0
    emit_list(
        "Creating labels" if args.apply else "Proposed label creations",
        enumerate(missing, 1),
        unit=("label", "labels"),
    )
    total = len(missing)
    if not args.apply and not confirm(f"Create {total} {'label' if total == 1 else 'labels'}?"):
        emit("Preview only; no changes made. Use --apply to create labels.")
        return 0
    verified = 0
    for index, name in enumerate(missing):
        state = CreationState()
        try:
            emit(f"Creating label: {name}…")
            create_label(api, name, state)
            verified += 1
        except (SyncError, KeyboardInterrupt) as exc:
            interrupted = isinstance(exc, KeyboardInterrupt)
            emit(("\n" if interrupted else "") + f"Stopped while creating label {name!r}.")
            if not interrupted:
                emit(str(exc), primary=False)
            emit(f"Labels: {verified} verified; {total - index - 1} not attempted.", primary=False)
            if state.phase == "created":
                emit(
                    f"Label {name!r} was created, but verification did not complete.", primary=False
                )
            if api.write_started:
                emit(
                    "Created labels remain saved. List account labels before retrying.",
                    primary=False,
                )
            return 130 if interrupted else (3 if isinstance(exc, WriteUnverified) else 1)
    emit(f"Created and verified {verified} label{'s' if verified != 1 else ''}.")
    return 0
