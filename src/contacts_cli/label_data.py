"""Shared contact-label reads, eligibility, and identity validation."""

from .api import execute
from .errors import SyncError


def contact_groups(api, *, include_counts=False):
    """Read all contact-label definitions using the shared paginated request."""
    fields = "name,groupType,metadata" + (",memberCount" if include_counts else "")
    groups, seen, token = [], set(), None
    while True:
        result = execute(
            api.people.contactGroups().list(pageSize=1000, pageToken=token, groupFields=fields)
        )
        groups.extend(result.get("contactGroups", []))
        token = result.get("nextPageToken")
        if not token:
            break
        if token in seen:
            raise SyncError("Repeated contact-label page token; stopped before creation.")
        seen.add(token)
    return groups


def is_active_user_label(group):
    return group.get("groupType") == "USER_CONTACT_GROUP" and not group.get("metadata", {}).get(
        "deleted"
    )


def active_user_labels(groups):
    return [group for group in groups if is_active_user_label(group)]


def label_identity(group):
    name, resource = group.get("name"), group.get("resourceName")
    if not isinstance(name, str) or not name:
        raise SyncError("Contact label has no valid name; label data is incomplete.")
    if not isinstance(resource, str) or not resource.startswith("contactGroups/"):
        raise SyncError("Invalid contact label resource returned by Google.")
    return name, resource
