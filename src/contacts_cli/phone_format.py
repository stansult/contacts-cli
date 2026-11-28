"""Conservative international phone formatting and selectable, verified updates."""

import sys
from copy import deepcopy

import phonenumbers

from .contact_matches import phone_key
from .core import field_update_body
from .output import emit, emit_list
from .phone_edit import phone_text, verify_phones
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


def run_format_phone(args, api, person, entries, confirm):
    changes, skipped = {}, []
    for number, entry in enumerate(entries, 1):
        value, reason = formatted_phone(entry)
        if reason:
            skipped.append((number, f"{phone_text(entry)} — {reason}"))
        elif value != entry["value"]:
            replacement = deepcopy(entry)
            replacement["value"] = value
            changes[number] = replacement
    choices = [
        (number, f"{phone_text(entries[number - 1])}\n     To: {phone_text(entry)}")
        for number, entry in changes.items()
    ]
    if choices:
        emit_list("Formatting phones" if args.apply else "Proposed phone formatting", choices)
    if skipped:
        emit("", primary=False)
        emit_list(
            "Left unchanged",
            skipped,
            note="Informational only; these numbers cannot be selected." if choices else None,
        )
    if not choices:
        emit("No phone formatting changes needed; no update made.")
        return 0
    selected = list(changes)

    def expected(numbers):
        return [
            deepcopy(changes[n] if n in numbers else entry) for n, entry in enumerate(entries, 1)
        ]

    def question(numbers):
        count = len(numbers) if isinstance(numbers, list) else numbers
        return f"Format {count} phone {'entry' if count == 1 else 'entries'}?"

    def preview(numbers):
        field_update_body(person, "phoneNumbers", expected(numbers))
        if numbers != list(changes):
            emit_list(
                "Selected phone formatting", [(n, text) for n, text in choices if n in numbers]
            )
        emit("", primary=False)

    field_update_body(person, "phoneNumbers", expected(selected))
    if (
        not args.apply
        and len(choices) > 1
        and all(s.isatty() for s in (sys.stdin, sys.stdout, sys.stderr))
    ):
        selected = review_selection(
            choices,
            noun="phone entries",
            heading="Selected phone formatting",
            unit=("entry", "entries"),
            preview=preview,
            question=question,
            action="Format selected phone entries",
        )
        if selected is None:
            emit("Cancelled; no changes made.")
            return 0
    elif not args.apply and not confirm(question(selected)):
        emit("Preview only; no changes made. Use --apply to format phone entries.")
        return 0
    values = expected(selected)
    body = field_update_body(person, "phoneNumbers", values)
    api.apply_field_change(
        person, body, lambda saved: verify_phones(person, values, saved), "phoneNumbers"
    )
    count = len(selected)
    emit(f"Formatted and verified {count} phone {'entry' if count == 1 else 'entries'}.")
    return 0
