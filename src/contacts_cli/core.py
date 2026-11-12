"""Pure parsing, comparison, and preservation rules; no network access."""

import json
import re
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from email import policy
from email.parser import HeaderParser
from urllib.parse import urlsplit

from .errors import SyncError

# Explicit read mask for contact data, including fields we never update.
CONTACT_FIELDS = (
    "addresses,biographies,birthdays,calendarUrls,clientData,emailAddresses,events,"
    "externalIds,genders,imClients,interests,locales,locations,memberships,metadata,"
    "miscKeywords,names,nicknames,occupations,organizations,phoneNumbers,relations,"
    "sipAddresses,urls,userDefined"
)


def contact_resource(value: str) -> str:
    """Accept a contact resource or a Contacts URL, never an arbitrary endpoint."""
    if re.fullmatch(r"people/c[0-9]+", value):
        return value
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise SyncError("Malformed Google Contacts URL.") from exc
    if parsed.scheme == "https" and parsed.netloc == "contacts.google.com":
        match = re.fullmatch(r"/(?:u/[0-9]+/)?person/(c[0-9]+)/?", parsed.path)
        if match and not parsed.fragment:
            return f"people/{match[1]}"
    raise SyncError("Use a Google Contacts person URL or a resource such as people/c123456789.")


def address_key(value: str) -> str:
    # Deliberately do not collapse provider-specific dots or plus tags.
    return value.strip().casefold()


def parse_from(values: list[str]) -> tuple[str, ...]:
    """Reject ambiguous headers instead of accepting a partial parser recovery."""
    if len(values) != 1 or not isinstance(values[0], str):
        raise SyncError("expected exactly one From header")
    value = values[0]
    # Permit RFC header folding, but reject header injection and other controls.
    value = re.sub(r"\r?\n[ \t]+", " ", value)
    if any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in value):
        raise SyncError("invalid control character in From header")
    try:
        header = HeaderParser(policy=policy.default).parsestr(f"From: {value}\n\n")["From"]
        if header.defects or not header.addresses:
            raise ValueError
        addresses = []
        for address in header.addresses:
            if not address.username or not address.domain:
                raise ValueError
            result = address.addr_spec
            if len(result) > 1024:
                raise ValueError
            addresses.append(result)
        return tuple(addresses)
    except (ValueError, IndexError, AttributeError) as exc:
        raise SyncError("malformed or unsupported From header") from exc


def contact_source(person: dict) -> dict:
    metadata = person.get("metadata", {})
    sources = metadata.get("sources", [])
    if metadata.get("deleted") or len(sources) != 1:
        raise SyncError(
            "Expected one editable contact source; merged or deleted contacts are unsafe."
        )
    source = sources[0]
    if source.get("type") != "CONTACT" or not source.get("id") or not source.get("etag"):
        raise SyncError("Contact source ID or etag is missing; refusing an unsafe update.")
    return source


def validate_contact(person: dict) -> None:
    if not isinstance(person, dict) or not re.fullmatch(
        r"people/[A-Za-z0-9_-]+", person.get("resourceName", "")
    ):
        raise SyncError("Incomplete contact response.")
    source = contact_source(person)
    emails = person.get("emailAddresses", [])
    if not isinstance(emails, list):
        raise SyncError("Incomplete contact email list.")
    for email in emails:
        if not isinstance(email, dict) or not isinstance(email.get("value"), str):
            raise SyncError("Incomplete contact email entry.")
        if not email["value"].strip():
            raise SyncError("Empty contact email entry.")
        field_source = email.get("metadata", {}).get("source", {})
        if field_source and (
            field_source.get("type") != "CONTACT" or field_source.get("id") != source["id"]
        ):
            raise SyncError("Contact contains email entries from another source.")


@dataclass(frozen=True)
class Scan:
    messages: int
    senders: tuple[str, ...]
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    person: dict
    scan: Scan
    additions: tuple[str, ...]


def make_plan(person: dict, scan: Scan) -> Plan:
    validate_contact(person)
    existing = {address_key(email["value"]) for email in person.get("emailAddresses", [])}
    candidates = {}
    for sender in scan.senders:
        candidates.setdefault(address_key(sender), sender)
    additions = tuple(candidates[key] for key in sorted(candidates) if key not in existing)
    return Plan(deepcopy(person), scan, additions)


def update_body(plan: Plan) -> dict:
    """Only replace emailAddresses; retain every existing entry verbatim."""
    if plan.scan.problems:
        raise SyncError("Unparseable messages make this preview incomplete; no update is allowed.")
    emails = deepcopy(plan.person.get("emailAddresses", []))
    emails.extend({"value": value} for value in plan.additions)
    projected = deepcopy(plan.person)
    projected["emailAddresses"] = emails
    # These are conservative local estimates, not Google's internal storage accounting.
    entries = sum(len(value) for value in projected.values() if isinstance(value, list))
    if entries > 500 or len(json.dumps(projected, ensure_ascii=False).encode()) > 128 * 1024:
        raise SyncError("Projected contact exceeds the local 500-entry or 128-KiB size guard.")
    return {
        "resourceName": plan.person["resourceName"],
        "metadata": {"sources": [deepcopy(contact_source(plan.person))]},
        "emailAddresses": emails,
    }


def _email_signature(email: dict) -> tuple:
    return (
        email["value"],
        email.get("type", ""),
        email.get("displayName", ""),
        bool(email.get("metadata", {}).get("sourcePrimary", False)),
    )


def _stable(value):
    """Compare contact content independently of field order and generated metadata."""
    if isinstance(value, dict):
        return {
            key: _stable(item)
            for key, item in value.items()
            if key not in {"metadata", "etag", "resourceName"}
        }
    if isinstance(value, list):
        return sorted(
            (_stable(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True)
        )
    return value


def verify_saved(plan: Plan, saved: dict) -> None:
    validate_contact(saved)
    if contact_source(saved)["id"] != contact_source(plan.person)["id"]:
        raise SyncError("Saved result refers to a different contact source.")
    before = Counter(_email_signature(item) for item in plan.person.get("emailAddresses", []))
    after = Counter(_email_signature(item) for item in saved.get("emailAddresses", []))
    if before - after:
        raise SyncError("An existing email value, label, display name, or primary choice changed.")
    saved_keys = {address_key(item["value"]) for item in saved.get("emailAddresses", [])}
    if any(address_key(value) not in saved_keys for value in plan.additions):
        raise SyncError("Some proposed email additions were not found in the saved contact.")
    for field in CONTACT_FIELDS.split(","):
        if field not in {"emailAddresses", "metadata"}:
            if _stable(plan.person.get(field, [])) != _stable(saved.get(field, [])):
                raise SyncError(f"Contact field {field} changed during the update.")
