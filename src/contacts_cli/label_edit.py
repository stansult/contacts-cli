"""Edit contact labels without replacing existing memberships or contact fields."""

from .contact_create import CreationState, LabelChoiceCancelled, create_label, resolve_labels
from .core import contact_resource, contact_source
from .errors import SyncError, WriteUnverified
from .output import emit, emit_list

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
    remove = args.command == "remove-label"
    verb, participle = ("Remove", "Removed") if remove else ("Add", "Applied")
    operation = "removals" if remove else "additions"
    emit("Reading contact…")
    person = api.get_contact(contact_resource(args.contact), LABEL_FIELDS)
    emit(heading(person), primary=False)
    current = memberships(person)
    try:
        labels, missing = resolve_labels(api, args.label, allow_create=not remove)
    except LabelChoiceCancelled:
        emit("Cancelled; no changes made.")
        return 0
    already = [name for name, resource in labels.items() if resource in current]
    if remove:
        additions = already
        absent = [name for name in labels if name not in already]
        if missing:
            emit_list("Labels not found", enumerate(missing, 1), unit=("label", "labels"))
        if absent:
            emit_list("Not applied to this contact", enumerate(absent, 1), unit=("label", "labels"))
    else:
        additions = [name for name in labels if name not in already] + missing
        if already:
            emit_list("Already applied", enumerate(already, 1), unit=("label", "labels"))
        if missing:
            emit_list("Labels to create", enumerate(missing, 1), unit=("label", "labels"))
    emit_list(
        (
            ("Removing labels" if remove else "Adding labels")
            if args.apply
            else f"Proposed label {operation}"
        ),
        enumerate(additions, 1),
        unit=("label", "labels"),
    )
    if not additions:
        emit(
            "None of the requested labels are applied; no changes made."
            if remove
            else "All requested labels are already applied; no changes made."
        )
        return 0
    question = (
        f"{verb} these labels"
        + (" and create the missing labels" if missing and not remove else "")
        + "?"
    )
    if not args.apply and not confirm(question):
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
            edit_membership(api, person, labels[name], remove=remove)
            verified += 1
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
