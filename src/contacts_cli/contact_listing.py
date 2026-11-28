"""Read-only lookup using the shared contact resolver's matching rules."""

from .contact_create import format_entry
from .contact_matches import MATCH_FIELDS, normalized, read_match_contacts
from .contact_resolution import describe_contact
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


def run_list_contacts(api, filters):
    label_resource = None
    if filters.label is not None:
        from .contact_create import resolve_labels

        labels, missing = resolve_labels(api, [filters.label], allow_create=False)
        if not missing:
            label_resource = next(iter(labels.values()))
    people = []
    if filters.label is None or label_resource is not None:
        with StageProgress() as progress:
            progress.start(
                "Reading contact" if filters.resource else "Reading contacts for matching"
            )
            if filters.resource:
                fields = MATCH_FIELDS + (",memberships" if filters.label is not None else "")
                try:
                    people = [api.get_contact(filters.resource, fields)]
                except ContactFailure:
                    people = []
            elif filters.label is not None:
                people = read_match_contacts(api, include_memberships=True)
            else:
                people = read_match_contacts(api)
        people = [
            person for person in people if filters.matches(person, label_resource=label_resource)
        ]
    people.sort(key=lambda person: (normalized(describe_contact(person)), person["resourceName"]))
    emit_list(
        "Matching contacts",
        ((number, contact_row(person)) for number, person in enumerate(people, 1)),
        unit=("contact", "contacts"),
    )
    return 0
