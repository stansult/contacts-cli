"""Reviewed contact merge plans, explicit conflicts, and verified sequential writes."""

import json
from copy import deepcopy
from dataclasses import dataclass, field

from .contact_inputs import SINGLETONS, names_match, validate_date
from .contact_matches import (
    MatchIndex,
    contact_title,
    display_matches,
    identity_keys,
    match_rows,
    normalized,
    phone_key,
)
from .core import _stable, address_key, contact_source, validate_contact
from .duplicate import COPY_FIELDS, READ_FIELDS, copy_body
from .errors import ContactFailure, ContactVerificationFailure, SyncError, WriteUnverified
from .import_failures import ImportFailures, contact_specific
from .merge_conflicts import MergeCancelled, choose_conflict, conflict_summary, merge_values
from .output import emit, emit_list
from .progress import StageProgress
from .timing import read_input

URL_TYPES = {
    s.casefold(): s
    for s in (
        "home",
        "work",
        "blog",
        "profile",
        "homePage",
        "ftp",
        "reservations",
        "appInstallPage",
        "other",
    )
}


def comparable(field_name, entries):
    result = deepcopy(entries)
    for entry in result:
        entry.pop("metadata", None)
        if field_name == "urls" and isinstance(entry.get("type"), str):
            entry["type"] = URL_TYPES.get(entry["type"].casefold(), entry["type"])
        if field_name == "nicknames":
            entry.setdefault("type", "DEFAULT")
    return result


def entry_key(field_name, entry):
    if field_name == "emailAddresses":
        return address_key(entry.get("value", ""))
    if field_name == "phoneNumbers":
        return phone_key(entry.get("value", "")) or entry.get("value")
    if field_name in {"urls", "nicknames"}:
        return entry.get("value")
    if field_name == "organizations":
        return normalized(entry.get("name", "")) or None
    if field_name == "userDefined":
        return entry.get("key"), entry.get("value")
    return None


def _merge_values_keep(existing, incoming):
    """Fill unambiguous gaps; never replace an existing nonempty value."""
    from .contact_create import FIELD_NAMES, contains, format_entry

    result, changes, conflicts = deepcopy(existing), [], []
    for field_name, supplied in incoming.items():
        values = result.setdefault(field_name, [])
        for new in supplied:
            title = FIELD_NAMES.get(field_name, field_name)
            if any(
                contains(comparable(field_name, [new])[0], item)
                for item in comparable(field_name, values)
            ):
                continue
            if field_name == "userDefined" and new.get("key") == "Created":
                markers = [e for e in values if e.get("key") == "Created"]
                if markers:
                    conflicts.append(
                        f"{title}: keep existing Created marker; not imported: {new['value']}"
                    )
                    continue
            if field_name in SINGLETONS:
                matches = values
            else:
                key = entry_key(field_name, new)
                matches = [e for e in values if key is not None and entry_key(field_name, e) == key]
            if not matches:
                values.append(deepcopy(new))
                changes.append(f"Add {title}: {format_entry(field_name, new)}")
                continue
            if len(matches) != 1:
                conflicts.append(
                    f"{title}: multiple existing entries; not imported: "
                    f"{format_entry(field_name, new)}"
                )
                continue
            old = matches[0]
            if field_name == "names":
                # An existing name is atomic: do not create contradictory full/part names.
                equivalent = all(
                    normalized(str(value)) == normalized(str(old.get(key, "")))
                    or (
                        key == "unstructuredName"
                        and normalized(str(value)) == normalized(contact_title({"names": [old]}))
                    )
                    for key, value in new.items()
                    if key != "metadata"
                )
                if not equivalent:
                    conflicts.append(
                        f"Name: keep {format_entry(field_name, old)}; "
                        f"not imported: {format_entry(field_name, new)}"
                    )
                continue

            def fill(target, source, path, field_name=field_name, old=old):
                for key, value in source.items():
                    if key == "metadata":
                        continue
                    place = f"{path}.{key}"
                    if (
                        key not in target
                        or target[key] in ("", None, {}, [])
                        or (
                            field_name in {"birthdays", "events"}
                            and key in {"year", "month", "day"}
                            and target[key] == 0
                        )
                    ):
                        target[key] = deepcopy(value)
                        if field_name == "emailAddresses" and key == "type" and target is old:
                            changes.append(
                                f"Add email label: {old['value']}\n"
                                f"     Label: {value} (currently none)"
                            )
                        else:
                            changes.append(f"Fill {place}: {value}")
                    elif isinstance(value, dict) and isinstance(target[key], dict):
                        fill(target[key], value, place)
                    elif target[key] != value:
                        # Equivalent identity spelling/formatting is deliberately preserved.
                        if key == "value" and field_name in {"emailAddresses", "phoneNumbers"}:
                            continue
                        if (
                            key == "name"
                            and field_name == "organizations"
                            and normalized(target[key]) == normalized(value)
                        ):
                            continue
                        if key == "type" and comparable(
                            field_name, [{"type": target[key]}]
                        ) == comparable(field_name, [{"type": value}]):
                            continue
                        conflicts.append(f"{place}: keep {target[key]}; not imported: {value}")

            fill(old, new, f"{title} ({format_entry(field_name, new)})")
            if field_name == "birthdays":
                validate_date(old["date"], "Merged birthday")
    guard_size(result)
    return result, changes, conflicts


def guard_size(body):
    if (
        sum(len(v) for v in body.values() if isinstance(v, list)) > 500
        or len(json.dumps(body).encode()) > 131072
    ):
        raise SyncError("Merged contact exceeds the local 500-entry or 128-KiB size guard.")


@dataclass
class MergePlan:
    original: dict
    expected: dict
    inputs: list = field(default_factory=list)
    phase: str = "not started"


@dataclass
class ImportReview:
    creates: dict = field(default_factory=dict)
    merges: dict = field(default_factory=dict)
    combined_inputs: bool = False
    grouped_review: bool = False
    skipped_unchanged: int = 0


def read_matched_details(matches, api):
    """One full read per matched saved target; no reads for input-to-input matches."""
    targets = sorted(
        {r for found in matches.values() for r, _, _ in found if not r.startswith("input #")}
    )
    details = {}
    if targets:
        with StageProgress() as progress:
            progress.start("Reading matching contacts", details=f"0 of {len(targets)}")
            for resource in targets:
                person = api.get_contact(resource, READ_FIELDS)
                if person["resourceName"] != resource:
                    raise SyncError(
                        "Matching contact read returned a different contact; rerun preview."
                    )
                details[resource] = person
                progress.update(f"{len(details)} of {len(targets)}", force=True)
            progress.finish("Finished reading matching contacts")
    return details


def assess_match(incoming, existing, api, labels, missing, *, saved):
    """Describe a hypothetical merge without changing either record or choosing a target."""
    before = copy_body(existing, api.people._rootDesc["schemas"]) if saved else existing
    try:
        _, changes, conflicts = merge_values(before, incoming)
    except SyncError as exc:
        return f"Cannot merge: {exc}", False, False
    label_changes = []
    if saved:
        plan = MergePlan(existing, deepcopy(before))
        label_changes = add_memberships(plan, labels) + list(missing)
    if changes:
        text = "New information and conflicts" if conflicts else "New information available"
    elif conflicts:
        text = "Conflicts to resolve"
    else:
        text = "No new contact details" if label_changes else "Nothing new"
    if label_changes:
        text += "; labels to add: " + ", ".join(label_changes)
    if changes:
        text += "\nAvailable additions:\n" + "\n".join(
            "  " + line for change in changes for line in change.splitlines()
        )
    if not saved:
        text = "If combined with this input: " + text
    return (
        text,
        bool(changes or conflicts or label_changes),
        not (changes or conflicts or label_changes),
    )


def match_summary(incoming, existing, api, labels, missing, *, saved):
    return assess_match(incoming, existing, api, labels, missing, saved=saved)[0]


def skip_unchanged_inputs(selected, matches, assessments):
    """Offer one reversible skip decision; input matches and conflicts stay in review."""
    unchanged = {
        number
        for number in selected
        if matches[number]
        and all(
            not identifier.startswith("input #") and assessments[number][identifier][2]
            for identifier, _, _ in matches[number]
        )
    }
    if not unchanged:
        return selected
    count = len(unchanged)
    unit = "input" if count == 1 else "inputs"
    emit(f"Already contain all supplied information: {count} {unit}")
    while True:
        emit("Skip these inputs? [Y/n] ", end="")
        try:
            answer = read_input().strip().casefold()
        except EOFError:
            return None
        finally:
            emit("", primary=False)
        if answer in ("q", "cancel"):
            return None
        if answer in ("n", "no"):
            return selected
        if answer in ("", "y", "yes"):
            emit(f"Skipped {count} unchanged {unit}.")
            return [number for number in selected if number not in unchanged]
        emit("Enter y to skip, n to review individually, or q to cancel.")


def choose_target(matches):
    if len(matches) == 1:
        return matches[0][0]
    emit_list("Merge targets", enumerate(match_rows(matches), 1), unit=("contact", "contacts"))
    while True:
        emit("Merge into match number (q = cancel): ", primary=False, end="")
        try:
            answer = read_input().strip().casefold()
        except EOFError:
            return None
        if answer == "q":
            return None
        if answer.isdecimal() and 1 <= int(answer) <= len(matches):
            return matches[int(answer) - 1][0]
        emit("Choose one displayed match number, or q to cancel.")


def review_import(
    selected, contacts, existing, api, details=None, labels=None, missing=(), review=None
):
    from .contact_matches import choose_duplicate

    details = {} if details is None else details
    labels = {} if labels is None else labels
    index = MatchIndex()
    review = ImportReview() if review is None else review
    for person in existing:
        index.add(person["resourceName"], person)
    for number in selected:
        person = deepcopy(contacts[number - 1])
        found = index.find(person)
        choice = "c"
        eligible, summaries = [], {}
        if found:
            for identifier, candidate, reasons in found:
                saved = not identifier.startswith("input #")
                if saved:
                    if identifier not in details:
                        details[identifier] = api.get_contact(identifier, READ_FIELDS)
                    candidate = details[identifier]
                    if identifier in review.merges:
                        planned = deepcopy(review.merges[identifier])
                        add_memberships(planned, labels)
                        candidate = {**candidate, **planned.expected}
                summary, useful, _ = assess_match(
                    person,
                    candidate,
                    api,
                    labels,
                    () if identifier in review.merges else missing,
                    saved=saved,
                )
                before_summary = (
                    copy_body(candidate, api.people._rootDesc["schemas"]) if saved else candidate
                )
                try:
                    differences = conflict_summary(before_summary, person)
                except SyncError:
                    differences = ""
                summaries[identifier] = summary + ("\n" + differences if differences else "")
                if useful:
                    eligible.append((identifier, candidate, reasons))
            emit("", primary=False)
            display_matches(number, person, found, summaries)
            choice = choose_duplicate(allow_merge=bool(eligible))
        if choice == "q":
            return None
        if choice == "s":
            emit(f"Skipped input #{number}.")
            continue
        if choice == "c":
            review.creates[number] = person
            index.add(f"input #{number}", person)
            continue
        target = choose_target(eligible)
        if target is None:
            return None
        if target.startswith("input #"):
            destination = int(target.removeprefix("input #"))
            before = review.creates[destination]
        else:
            if target not in review.merges:
                if target not in details:
                    emit(f"Reading merge target: {target.removeprefix('people/')}…")
                    details[target] = api.get_contact(target, READ_FIELDS)
                original = details[target]
                # The short match snapshot must still identify this selected target.
                if not identity_keys(original).intersection(identity_keys(person)):
                    raise SyncError("Merge target changed; rerun the preview.")
                review.merges[target] = MergePlan(
                    original, copy_body(original, api.people._rootDesc["schemas"])
                )
            plan = review.merges[target]
            before = plan.expected
        pending = []
        merge_values(before, person, details=pending)
        decision = 0
        identities = [
            (field, "singleton" if field in SINGLETONS else entry_key(field, entry))
            for field, entries in person.items()
            for entry in entries
        ]
        total = len(pending) if len(set(identities)) == len(identities) else None

        def resolve(conflict, total=total):
            nonlocal decision
            decision += 1
            return choose_conflict(conflict, position=decision, total=total)

        try:
            after, changes, conflicts = merge_values(before, person, resolver=resolve)
        except MergeCancelled:
            return None
        emit(f"Merge input #{number} into {target.removeprefix('people/')}")
        if changes:
            emit_list("Selected merge changes", enumerate(changes, 1), unit=("change", "changes"))
        elif conflicts:
            emit("No new contact details; conflicting information will remain unchanged.")
        else:
            emit("Contact details already present; requested labels will be added.")
        if conflicts:
            emit_list(
                "Kept existing; not imported",
                enumerate(conflicts, 1),
                unit=("conflict", "conflicts"),
            )
        if target.startswith("input #"):
            review.creates[destination] = after
            review.combined_inputs = True
        else:
            plan.expected = after
            plan.inputs.append(number)
        index.add(target, after)
    return review


def verify_merge(plan, saved, schemas):
    from .contact_create import verify_created

    validate_contact(saved)
    if contact_source(saved)["id"] != contact_source(plan.original)["id"]:
        raise SyncError("Merge returned a different contact source.")
    actual = copy_body(saved, schemas)
    wanted = {k: comparable(k, v) for k, v in plan.expected.items()}
    observed = {k: comparable(k, v) for k, v in actual.items()}
    before = copy_body(plan.original, schemas)
    verify_created(wanted, {**saved, **observed})
    for name in COPY_FIELDS.split(","):
        if name == "names":
            if not names_match(wanted.get(name, []), saved.get(name, [])):
                raise SyncError("Saved merge name differs from the preview.")
        elif plan.expected.get(name, []) != before.get(name, []):
            # Supplied values were checked above; permit generated properties, not extra entries.
            if len(wanted.get(name, [])) != len(observed.get(name, [])):
                raise SyncError(f"Saved merge field {name} differs from the preview.")
        elif _stable(wanted.get(name, [])) != _stable(observed.get(name, [])):
            raise SyncError(f"Saved merge field {name} differs from the preview.")
        for entry in plan.expected.get(name, []):
            if entry.get("metadata", {}).get("sourcePrimary"):
                primaries = [
                    e for e in actual.get(name, []) if e.get("metadata", {}).get("sourcePrimary")
                ]
                if not any(
                    _stable(comparable(name, [entry])) == _stable(comparable(name, [p]))
                    for p in primaries
                ):
                    raise SyncError(f"Existing primary choice for {name} changed.")
    if _stable(plan.original.get("photos", [])) != _stable(saved.get("photos", [])):
        raise SyncError("Contact photo changed during merge.")


def changed_fields(plan, schemas):
    before = copy_body(plan.original, schemas)
    return [k for k, v in plan.expected.items() if v != before.get(k, [])]


def add_memberships(plan, labels):
    additions = []
    for name, resource in labels.items():
        entry = {"contactGroupMembership": {"contactGroupResourceName": resource}}
        memberships = plan.expected.setdefault("memberships", [])
        if not any(
            e.get("contactGroupMembership") == entry["contactGroupMembership"] for e in memberships
        ):
            memberships.append(entry)
            additions.append(name)
    return additions


def apply_merge(api, plan):
    schemas = api.people._rootDesc["schemas"]
    original = plan.original
    latest = api.get_contact(original["resourceName"], READ_FIELDS)
    if latest != original:
        raise ContactFailure("Contact changed since merge preview; no update made. Rerun preview.")
    fields = changed_fields(plan, schemas)
    if not fields:
        return False
    guard_size(plan.expected)
    body = {
        "resourceName": original["resourceName"],
        "metadata": {"sources": [deepcopy(contact_source(original))]},
        **{k: plan.expected[k] for k in fields},
    }
    plan.phase = "writing"
    result = api.write(
        api.people.people().updateContact(
            resourceName=original["resourceName"],
            updatePersonFields=",".join(fields),
            personFields=READ_FIELDS,
            sources=["READ_SOURCE_TYPE_CONTACT"],
            body=body,
        )
    )
    plan.phase = "submitted"
    reading = False
    try:
        verify_merge(plan, result, schemas)
        reading = True
        saved = api.get_contact(result["resourceName"], READ_FIELDS)
        reading = False
        verify_merge(plan, saved, schemas)
    except SyncError as exc:
        error = WriteUnverified if reading else ContactVerificationFailure
        raise error(f"Merge was submitted but verification failed: {exc}") from exc
    plan.phase = "verified"
    return True


def run_merged_import(args, api, review, labels, missing, confirm):
    from .contact_create import (
        FIELD_NAMES,
        CreationState,
        contact_preview,
        create_contact,
        create_label,
        format_entry,
    )

    updates, update_rows = {}, []
    label_updates = {}
    for resource, plan in review.merges.items():
        label_additions = add_memberships(plan, labels) + list(missing)
        if changed_fields(plan, api.people._rootDesc["schemas"]) or missing:
            updates[resource] = plan
            row = (
                f"{contact_title(plan.original)} ({resource.removeprefix('people/')}); inputs "
                + ", ".join(f"#{n}" for n in plan.inputs)
            )
            if label_additions:
                row += "\n     Labels to add: " + ", ".join(label_additions)
            for field_name in changed_fields(plan, api.people._rootDesc["schemas"]):
                if field_name == "memberships":
                    continue
                for entry in plan.expected[field_name]:
                    row += (
                        f"\n     {FIELD_NAMES.get(field_name, field_name)} after merge: "
                        + format_entry(field_name, entry)
                    )
            if not (set(changed_fields(plan, api.people._rootDesc["schemas"])) - {"memberships"}):
                label_updates[resource] = plan
            else:
                update_rows.append(row)
    unchanged = len(review.merges) - len(updates)
    if not review.creates and not updates:
        emit("Nothing to create, update, or label; no changes made.")
        return 0
    if review.creates:
        emit_list(
            "Contacts to create",
            ((n, contact_preview(p)) for n, p in review.creates.items()),
            unit=("contact", "contacts"),
        )
    if update_rows:
        emit_list("Contacts to update", enumerate(update_rows, 1), unit=("contact", "contacts"))
    if label_updates:
        from .grouped_additions import AdditiveMerge
        from .label_only_import import show_groups

        show_groups(
            [
                AdditiveMerge(
                    min(plan.inputs), contact_title(plan.original), resource, [], plan, []
                )
                for resource, plan in label_updates.items()
            ],
            labels,
            missing,
            heading="Selected: add",
        )
    if label_updates or review.skipped_unchanged:
        emit(f"Contacts to create: {len(review.creates)}", primary=False)
        emit(f"Existing contacts to label: {len(label_updates)}", primary=False)
        if update_rows:
            emit(f"Existing contacts with information changes: {len(update_rows)}", primary=False)
        emit(f"Already-complete inputs skipped: {review.skipped_unchanged}", primary=False)
    if not args.apply and not confirm("Apply these changes?"):
        emit("Cancelled; no changes made.")
        return 0
    created = merged = created_labels = labeled = 0
    failures = ImportFailures()
    attempted = 0
    total = len(updates) + len(review.creates)
    state = CreationState()
    phase, target = "preflight", ""
    try:
        # Preflight every target before even creating shared labels.
        for resource, plan in list(updates.items()):
            target = f"{contact_title(plan.original)} ({resource.removeprefix('people/')})"
            try:
                if api.get_contact(resource, READ_FIELDS) != plan.original:
                    raise ContactFailure("Contact changed since merge preview; no update made.")
            except SyncError as exc:
                if not contact_specific(exc):
                    raise
                attempted += 1
                failures.record(target, exc, remaining=total - attempted)
                del updates[resource]
        if not updates and not review.creates:
            failures.summary()
            return failures.exit_code
        phase = "label creation"
        for name in missing:
            target = name
            state = CreationState()
            labels[name] = create_label(api, name, state)
            created_labels += 1
        label_total = sum(resource in label_updates for resource in updates)
        label_attempted = 0
        with StageProgress() as progress:
            if label_total:
                progress.start("Saving contact labels", details=f"0 of {label_total} processed")
            ordered = sorted(updates, key=lambda resource: resource not in label_updates)
            for resource in ordered:
                plan = updates[resource]
                if resource not in label_updates:
                    progress.finish()
                phase, target = "merge", resource.removeprefix("people/")
                add_memberships(plan, labels)
                attempted += 1
                if resource not in label_updates:
                    emit(f"Merging into {target}…")
                try:
                    changed = apply_merge(api, plan)
                except SyncError as exc:
                    if not contact_specific(exc):
                        raise
                    failures.record(
                        f"{contact_title(plan.original)} ({target}); inputs "
                        + ", ".join(f"#{n}" for n in plan.inputs),
                        exc,
                        remaining=total - attempted,
                    )
                    continue
                finally:
                    if resource in label_updates:
                        label_attempted += 1
                        progress.update(f"{label_attempted} of {label_total} processed")
                if changed:
                    merged += 1
                    if resource in label_updates:
                        labeled += 1
                    else:
                        emit(f"Merged and verified: {target}")
                else:
                    unchanged += 1
                    emit(f"Already contains the supplied information: {target}; no update made.")
        phase = "contact creation"
        for number, person in review.creates.items():
            target = f"input #{number}"
            body = deepcopy(person)
            if labels:
                body["memberships"] = [
                    {"contactGroupMembership": {"contactGroupResourceName": r}}
                    for r in labels.values()
                ]
            state = CreationState()
            attempted += 1
            try:
                create_contact(api, body, state)
            except SyncError as exc:
                if not contact_specific(exc):
                    raise
                failures.record(
                    f"Input #{number} — {contact_title(person)}",
                    exc,
                    location=state.location,
                    remaining=total - attempted,
                )
                continue
            created += 1
    except (SyncError, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        emit(f"Stopped during {phase}" + (f" for {target}." if target else "."))
        if phase in {"contact creation", "label creation"} and state.phase in {
            "created",
            "verified",
        }:
            emit(f"{target} was created but was not fully verified.")
        uncertain = isinstance(exc, WriteUnverified) or (
            interrupted
            and (
                (phase == "merge" and plan.phase != "not started")
                or (
                    phase in {"contact creation", "label creation"} and state.phase != "not started"
                )
            )
        )
        if uncertain:
            emit("The current operation may have been saved; inspect it before retrying.")
        elif not (created or merged or created_labels or failures.unverified):
            emit("No changes made.")
        if not interrupted:
            emit(str(exc), primary=False)
        emit(
            (
                f"Completed and verified: {created} creations; {labeled} contacts labeled; "
                f"{merged - labeled} merges; {created_labels} new labels."
            )
            if label_updates
            else (
                f"Completed and verified: {created} creations; {merged} merges; "
                f"{created_labels} new labels."
            )
        )
        if phase in {"merge", "contact creation"}:
            failures.record(
                target,
                exc,
                unverified=uncertain,
                location=state.location if phase == "contact creation" else "",
                announce=False,
            )
        emit(f"Remaining contacts: {total - attempted} not attempted.")
        failures.summary(total - attempted)
        emit("Completed changes remain saved. Remaining operations were not attempted.")
        return (
            130
            if interrupted
            else max(failures.exit_code, 3 if isinstance(exc, WriteUnverified) else 1)
        )
    failures.summary()
    if label_updates:
        emit(
            f"Completed: {created} contacts created and verified; "
            f"{labeled} {'contact' if labeled == 1 else 'contacts'} labeled and verified; "
            f"{merged - labeled} merged and verified; "
            f"{review.skipped_unchanged} already-complete inputs skipped."
        )
    else:
        emit(
            f"Completed: {created} contacts created and verified; "
            f"{merged} merged and verified; {unchanged} unchanged."
        )
    return failures.exit_code
