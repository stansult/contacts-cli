"""Generic possible-duplicate matching; no merging or account writes."""

import re
import unicodedata
from collections import defaultdict

from .api import execute
from .core import address_key
from .errors import SyncError
from .output import emit
from .timing import read_input

MATCH_FIELDS = "metadata,names,organizations,emailAddresses,phoneNumbers"


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def phone_key(value):
    """Compare formatting only; no inferred country code or dropped extension."""
    value = value.strip()
    extension = re.search(r"(?:ext\.?|x|#|;ext=)\s*([0-9]+)\s*$", value, re.I)
    suffix = extension[1] if extension else ""
    number = value[: extension.start()] if extension else value
    if not re.fullmatch(r"\+?[0-9 ()./-]+", number):
        return None
    digits = re.sub(r"[^0-9]", "", number)
    return (("+" if number.startswith("+") else "") + digits, suffix) if digits else None


def identity_keys(person):
    companies = {normalized(o["name"]) for o in person.get("organizations", []) if o.get("name")}
    names = set()
    matching_names = set()
    for entry in person.get("names", []):
        value = (
            entry.get("unstructuredName")
            or entry.get("displayName")
            or " ".join(
                entry.get(k, "")
                for k in (
                    "honorificPrefix",
                    "givenName",
                    "middleName",
                    "familyName",
                    "honorificSuffix",
                )
            )
        )
        if value.strip():
            name = normalized(value)
            names.add(name)
            # Structured parts distinguish a compound given name from a full name.
            parts = any(entry.get(k, "").strip() for k in ("givenName", "middleName", "familyName"))
            complete = (
                bool(entry.get("givenName", "").strip() and entry.get("familyName", "").strip())
                if parts
                else len(name.split()) >= 2
            )
            if complete:
                matching_names.add(name)
    keys = {("name", name) for name in matching_names - companies}
    if not names or names <= companies:
        keys.update(("company", company) for company in companies if company)
    keys.update(
        ("email", address_key(e["value"]))
        for e in person.get("emailAddresses", [])
        if e.get("value")
    )
    for entry in person.get("phoneNumbers", []):
        key = phone_key(entry.get("value", ""))
        if key:
            keys.add(("phone", key))
    return keys


def contact_title(person):
    names = person.get("names", [])
    if names:
        name = names[0]
        title = (
            name.get("unstructuredName")
            or name.get("displayName")
            or " ".join(name.get(k, "") for k in ("givenName", "middleName", "familyName")).strip()
        )
        if title:
            return title
    return next(
        (o["name"] for o in person.get("organizations", []) if o.get("name")), "Unnamed contact"
    )


class MatchIndex:
    def __init__(self):
        self.keys = defaultdict(set)
        self.contacts = {}

    def add(self, identifier, person):
        if identifier in self.contacts:
            for key in identity_keys(self.contacts[identifier]):
                self.keys[key].discard(identifier)
        self.contacts[identifier] = person
        for key in identity_keys(person):
            self.keys[key].add(identifier)

    def find(self, person, *, exclude=None):
        reasons = defaultdict(set)
        for kind, value in identity_keys(person):
            for identifier in self.keys[(kind, value)]:
                if identifier != exclude:
                    reasons[identifier].add(kind)
        return [
            (identifier, self.contacts[identifier], sorted(kinds))
            for identifier, kinds in sorted(reasons.items())
        ]


def read_match_contacts(api, *, include_memberships=False):
    """Read contact-only matching fields once; reject partial or ambiguous pagination."""
    people, ids, tokens, token = [], set(), set(), None
    while True:
        result = execute(
            api.people.people()
            .connections()
            .list(
                resourceName="people/me",
                pageSize=1000,
                personFields=MATCH_FIELDS + (",memberships" if include_memberships else ""),
                sources=["READ_SOURCE_TYPE_CONTACT"],
                **({"pageToken": token} if token else {}),
            )
        )
        if not isinstance(result, dict) or not isinstance(result.get("connections", []), list):
            raise SyncError("Incomplete contact list; duplicate checking stopped before creation.")
        for person in result.get("connections", []):
            if not isinstance(person, dict):
                raise SyncError("Invalid contact in duplicate-check response.")
            resource = person.get("resourceName")
            if (
                not isinstance(resource, str)
                or not re.fullmatch(r"people/[A-Za-z0-9_-]+", resource)
                or resource in ids
            ):
                raise SyncError("Missing or repeated contact identity; duplicate checking stopped.")
            ids.add(resource)
            metadata = person.get("metadata", {})
            if not isinstance(metadata, dict):
                raise SyncError("Invalid contact metadata; duplicate checking stopped.")
            if metadata.get("deleted"):
                continue
            for field, properties in (
                (
                    "names",
                    (
                        "unstructuredName",
                        "displayName",
                        "givenName",
                        "middleName",
                        "familyName",
                        "honorificPrefix",
                        "honorificSuffix",
                    ),
                ),
                ("organizations", ("name",)),
                ("emailAddresses", ("value",)),
                ("phoneNumbers", ("value",)),
            ):
                entries = person.get(field, [])
                if not isinstance(entries, list) or any(
                    not isinstance(e, dict)
                    or any(k in e and not isinstance(e[k], str) for k in properties)
                    for e in entries
                ):
                    raise SyncError("Invalid matching fields; duplicate checking stopped.")
            # connections.list caps emails/phones at 100; reuse the complete contact read.
            if any(len(person.get(f, [])) >= 100 for f in ("emailAddresses", "phoneNumbers")):
                person = (
                    api.get_contact(resource, MATCH_FIELDS + ",memberships")
                    if include_memberships
                    else api.get_contact(resource)
                )
            if include_memberships:
                from .label_data import memberships

                memberships(person)
            people.append(person)
        token = result.get("nextPageToken")
        if token is None:
            return people
        if not isinstance(token, str) or not token or token in tokens:
            raise SyncError("Invalid or repeated contact page token; duplicate checking stopped.")
        tokens.add(token)


def match_rows(matches):
    rows = []
    for identifier, existing, reasons in matches:
        location = (
            identifier if identifier.startswith("input #") else identifier.removeprefix("people/")
        )
        rows.append(f"{contact_title(existing)} ({location}) — matching " + ", ".join(reasons))
    return rows


def display_matches(number, person, matches, summaries=None):
    label = "possible match" if len(matches) == 1 else "possible matches"
    emit(f"{number}. {contact_title(person)} — {label}:", primary=False)
    for (identifier, _, _), row in zip(matches, match_rows(matches), strict=True):
        emit(f"   - {row}", primary=False)
        if summaries and identifier in summaries:
            emit(
                "\n".join("     " + line for line in summaries[identifier].splitlines()),
                primary=False,
            )


def choose_duplicate(*, allow_merge=False):
    if allow_merge:
        emit("  m   Merge and resolve differences", primary=False)
    emit("  s   Skip this input\n  c   Create separately\n  q   Cancel command", primary=False)
    while True:
        emit("Choose an option (Enter = skip this input): ", end="", primary=False)
        try:
            answer = read_input().strip().casefold()
        except EOFError:
            return "q"
        finally:
            emit("", primary=False)
        if answer in ("", "s", "skip"):
            return "s"
        if allow_merge and answer in ("m", "merge"):
            return "m"
        if answer in ("c", "create"):
            return "c"
        if answer in ("q", "cancel"):
            return "q"
        emit("Choose m, s, c, or q." if allow_merge else "Choose s, c, or q.")


def duplicate_matches(contacts, existing):
    index = MatchIndex()
    for person in existing:
        index.add(person["resourceName"], person)
    for number, person in enumerate(contacts, 1):
        index.add(f"input #{number}", person)
    return {n: index.find(p, exclude=f"input #{n}") for n, p in enumerate(contacts, 1)}
