"""Read-only lookup using the shared contact resolver's matching rules."""

from .contact_create import format_entry
from .contact_matches import MATCH_FIELDS, normalized, read_match_contacts
from .contact_resolution import describe_contact, matches
from .errors import ContactFailure
from .output import emit_list
from .progress import StageProgress


def contact_row(person):
    lines = [describe_contact(person)]
    for field, label in (("emailAddresses", "Email"), ("phoneNumbers", "Phone")):
        for entry in person.get(field, []):
            if field == "phoneNumbers" and entry.get("canonicalForm") == entry.get("value"):
                entry = {key: value for key, value in entry.items() if key != "canonicalForm"}
            lines.append(f"     {label}: {format_entry(field, entry)}")
    return "\n".join(lines)


def run_list_contacts(api, kind, value, *, exact=False):
    with StageProgress() as progress:
        progress.start("Reading contact" if kind == "id" else "Reading contacts for matching")
        if kind == "id":
            try:
                people = [api.get_contact(value, MATCH_FIELDS)]
            except ContactFailure:
                people = []
        else:
            people = [
                person
                for person in read_match_contacts(api)
                if matches(person, kind, value, partial_name=not exact)
            ]
    people.sort(key=lambda person: (normalized(describe_contact(person)), person["resourceName"]))
    emit_list(
        "Matching contacts",
        ((number, contact_row(person)) for number, person in enumerate(people, 1)),
        unit=("contact", "contacts"),
    )
    return 0
