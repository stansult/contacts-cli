"""Resolve literal or star-pattern label candidates without case-choice prompts."""

import re

from .errors import SyncError
from .label_data import active_user_labels, contact_groups, label_identity
from .output import emit


def resolve_removals(api, requests, *, memberships=None):
    emit("Checking contact labels…")
    groups = active_user_labels(contact_groups(api))
    if memberships is not None:
        groups = [g for g in groups if g.get("resourceName") in memberships]
    labels, kinds, missing = {}, {}, []
    for request in dict.fromkeys(requests):
        pattern = "*" in request
        regex = re.compile(re.escape(request.casefold()).replace(r"\*", ".*"), re.DOTALL)
        matches = [
            g
            for g in groups
            if isinstance(g.get("name"), str) and regex.fullmatch(g["name"].casefold())
        ]
        if not matches:
            missing.append(request)
        for g in matches:
            name, resource = label_identity(g)
            if name in labels and labels[name] != resource:
                raise SyncError(f"Contact label {name!r} is ambiguous.")
            labels[name] = resource
            kind = 1 if pattern else 0 if name == request else 2
            kinds[name] = min(kind, kinds.get(name, kind))
    labels = dict(sorted(labels.items(), key=lambda item: kinds[item[0]]))
    return labels, missing, kinds
