"""Conservative international phone formatting and selectable, verified updates."""

import sys
from copy import deepcopy

import phonenumbers

from .contact_matches import phone_key
from .contact_resolution import describe_contact, resolve_contacts
from .core import field_update_body
from .errors import ContactFailure, ContactVerificationFailure, SyncError, WriteUnverified
from .output import emit, emit_list
from .phone_edit import phone_entries, phone_text, verify_phones
from .selection import review_selection


def formatted_phone(entry):
    """Return (formatted value, skip reason); never infer a country or discard an extension."""
    raw = phone_key(entry["value"])
    if raw is None:
        return None, "unsupported phone text"
    canonical_text = entry.get("canonicalForm", "")
    canonical = phone_key(canonical_text) if canonical_text else None
    if canonical_text and (canonical is None or not canonical[0].startswith("+")):
        return None, "unsupported canonical number"
    if canonical and raw[1] and canonical[1] and raw[1] != canonical[1]:
        return None, "conflicting extensions"
    if canonical and raw[0].startswith("+") and raw[0] != canonical[0]:
        return None, "stored and canonical numbers disagree"
    base, extension = canonical or raw
    extension = raw[1] or extension
    if not base.startswith("+"):
        return None, "country code is unknown"
    try:
        number = phonenumbers.parse(base, None)
    except phonenumbers.NumberParseException:
        return None, "unrecognized international number"
    if not phonenumbers.is_possible_number(number):
        return None, "unsupported number length"
    if phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164) != base:
        return None, "formatting would change the number digits"
    value = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    if extension:
        value += " ext. " + extension
    return value, None


def formatting_plan(person, start):
    """Keep global entry numbers, including gaps, and preserve unselected occurrences."""
    entries = phone_entries(person)
    changes, skipped = {}, []
    for n, entry in enumerate(entries, start):
        value, reason = formatted_phone(entry)
        if reason:
            skipped.append((n, f"{phone_text(entry)} — {reason}"))
        elif value != entry["value"]:
            changes[n] = dict(deepcopy(entry), value=value)
    return {
        "person": person,
        "entries": entries,
        "start": start,
        "changes": changes,
        "skipped": skipped,
    }


def formatted_values(plan, selected):
    return [
        deepcopy(plan["changes"][n] if n in selected else entry)
        for n, entry in enumerate(plan["entries"], plan["start"])
    ]


def plan_rows(plan, selected):
    return [
        (n, f"{phone_text(plan['entries'][n - plan['start']])}\n     To: {phone_text(entry)}")
        for n, entry in plan["changes"].items()
        if n in selected
    ]


def run_format_contacts(args, api, confirm):
    resources = resolve_contacts(api, args.contact_identifiers)
    if resources is None:
        emit("Cancelled; no changes made.")
        return 0
    if not resources:
        emit("No contacts selected; no changes made.")
        return 0
    plans, unchanged, missing = {}, [], []
    next_number = 1
    for resource, contact_number in resources.items():
        emit(f"Reading contact {contact_number}: {resource.split('/')[-1]}…")
        try:
            person = api.get_contact(resource)
        except ContactFailure:
            missing.append((contact_number, resource.split("/")[-1]))
            continue
        plan = formatting_plan(person, next_number)
        next_number += len(plan["entries"])
        # Validate every proposed update before any approval or write.
        if plan["changes"]:
            field_update_body(person, "phoneNumbers", formatted_values(plan, plan["changes"]))
        else:
            unchanged.append((contact_number, describe_contact(person)))
        plans[contact_number] = plan
    selected = [n for plan in plans.values() for n in plan["changes"]]
    selectable_contacts = [i for i, plan in plans.items() if plan["changes"]]
    if missing:
        emit_list("Contacts not found; skipped", missing, unit=("contact", "contacts"))
    if unchanged:
        emit_list("No formatting changes needed", unchanged, unit=("contact", "contacts"))

    def show(numbers, heading):
        count = sum(bool(set(numbers) & p["changes"].keys()) for p in plans.values())
        emit(
            f"{heading}: {len(numbers)} phone {'entry' if len(numbers) == 1 else 'entries'} "
            f"on {count} {'contact' if count == 1 else 'contacts'}"
        )
        for i, plan in plans.items():
            rows = plan_rows(plan, numbers)
            if rows:
                emit("", primary=False)
                emit_list(f"Contact #{i}: {describe_contact(plan['person'])}", rows)

    if selected:
        show(selected, "Formatting phones" if args.apply else "Proposed phone formatting")
    for i, plan in plans.items():
        if plan["skipped"]:
            emit_list(
                f"Left unchanged on contact #{i}",
                plan["skipped"],
                note="Informational only; these numbers cannot be selected." if selected else None,
            )
    if not selected:
        emit("No phone formatting changes needed; no update made.")
        return 0
    chosen = list(selected)

    def preview(numbers):
        nonlocal chosen
        chosen = numbers
        if numbers != selected:
            show(numbers, "Selected phone formatting")
        emit("", primary=False)

    def question(_):
        contacts = sum(bool(set(chosen) & p["changes"].keys()) for p in plans.values())
        return (
            f"Format {len(chosen)} phone {'entry' if len(chosen) == 1 else 'entries'} "
            f"on {contacts} {'contact' if contacts == 1 else 'contacts'}?"
        )

    if not args.apply:
        if all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
            chosen = review_selection(
                [(n, text) for p in plans.values() for n, text in plan_rows(p, selected)],
                noun="phone entries",
                heading="Selected phone formatting",
                unit=("entry", "entries"),
                preview=preview,
                question=question,
                action="Format selected phone entries",
            )
            if chosen is None:
                emit("Cancelled; no changes made.")
                return 0
        elif not confirm(question(chosen)):
            emit("Preview only; no changes made. Use --apply to format phone entries.")
            return 0
    targets = [(i, p) for i, p in plans.items() if set(chosen) & p["changes"].keys()]
    verified = failed = unverified = attempted = entries_verified = 0
    status = 0
    for position, (i, plan) in enumerate(targets, 1):
        attempted += 1
        emit(
            f"Formatting contact {position} of {len(targets)}: {describe_contact(plan['person'])}…"
        )
        api.write_started = False
        values = formatted_values(plan, chosen)

        def verify(saved, plan=plan, values=values):
            try:
                verify_phones(plan["person"], values, saved)
            except SyncError as exc:
                raise ContactVerificationFailure(str(exc)) from exc

        try:
            api.apply_field_change(
                plan["person"],
                field_update_body(plan["person"], "phoneNumbers", values),
                verify,
                "phoneNumbers",
            )
        except ContactVerificationFailure as exc:
            unverified += 1
            status = 3
            emit(f"Contact #{i} unverified: {exc}")
        except ContactFailure as exc:
            failed += 1
            status = status or 1
            emit(f"Contact #{i} failed: {exc}")
        except (SyncError, KeyboardInterrupt) as exc:
            uncertain = isinstance(exc, WriteUnverified) or (
                isinstance(exc, KeyboardInterrupt) and api.write_started
            )
            unverified += int(uncertain)
            failed += int(not uncertain)
            status = 130 if isinstance(exc, KeyboardInterrupt) else 3 if unverified else 1
            emit(f"Stopped at contact #{i}: {str(exc) or 'Interrupted'}")
            break
        else:
            verified += 1
            entries_verified += len(set(chosen) & plan["changes"].keys())
    if verified:
        emit(
            f"Formatted and verified {entries_verified} phone "
            f"{'entry' if entries_verified == 1 else 'entries'}."
        )
    emit(
        f"Contacts: verified: {verified}; failed: {failed}; unverified: {unverified}; "
        f"unattempted: {len(targets) - attempted}."
    )
    emit(
        f"No changes needed: {len(unchanged)}; "
        f"not selected: {len(selectable_contacts) - len(targets)}; not found: {len(missing)}.",
        primary=False,
    )
    if status:
        emit(
            "Completed changes remain saved. Review failed or unverified contacts before retrying.",
            primary=False,
        )
    return status
