"""Entry-level conflict decisions shared by preview and interactive merge planning."""

from copy import deepcopy
from dataclasses import dataclass

from .contact_inputs import SINGLETONS, validate_date
from .errors import SyncError
from .output import emit
from .timing import read_input


class MergeCancelled(Exception):
    """Cancel all planned import operations before writing."""


def anchored_name(old, new):
    """Resolve only one given-name token before an already-known family name."""
    from .contact_matches import normalized

    allowed = {"givenName", "familyName", "unstructuredName", "metadata"}
    if set(new) != {"unstructuredName"} or set(old) - allowed:
        return None
    given, family = old.get("givenName", ""), old.get("familyName", "")
    if len(given.split()) != 1 or not family:
        return None
    if old.get("unstructuredName") and normalized(old["unstructuredName"]) != normalized(
        given + " " + family
    ):
        return None
    parts = new["unstructuredName"].split()
    if len(parts) != 1 + len(family.split()) or normalized(" ".join(parts[1:])) != normalized(
        family
    ):
        return None
    result = deepcopy(old)
    result.pop("unstructuredName", None)
    result["givenName"] = parts[0]
    return result


@dataclass
class Conflict:
    field: str
    indices: list
    saved: list
    incoming: dict
    reasons: list
    name_parts: bool = False

    @property
    def both(self):
        return self.field not in SINGLETONS

    def differences(self, saved):
        from .contact_create import human_key, readable
        from .contact_matches import normalized
        from .contact_merge import comparable

        rows = []
        atomic = self.field in SINGLETONS

        def walk(old, new, path=()):
            keys = list(new) + ([k for k in old if k not in new] if atomic else [])
            for key in keys:
                if key == "metadata" or (self.name_parts and key == "unstructuredName"):
                    continue
                previous, supplied = old.get(key), new.get(key)
                if previous == supplied:
                    continue
                if not path and key == "value" and self.field in {"emailAddresses", "phoneNumbers"}:
                    continue  # The identity already matched; spelling/formatting is context.
                if (
                    not path
                    and key == "name"
                    and self.field == "organizations"
                    and normalized(previous or "") == normalized(supplied or "")
                ):
                    continue
                if key == "type" and comparable(self.field, [{key: previous}]) == comparable(
                    self.field, [{key: supplied}]
                ):
                    continue
                if not atomic and len(self.saved) == 1 and previous in (None, "", {}, []):
                    continue  # A gap to fill, not a conflicting saved value.
                if isinstance(previous, dict) and isinstance(supplied, dict):
                    walk(previous, supplied, (*path, key))
                    continue
                label = "Label" if key == "type" else human_key(key)
                if path:
                    label = " / ".join([*(human_key(k) for k in path), label])
                old_text = readable(previous) if previous is not None else "(not set)"
                new_text = (
                    readable(supplied)
                    if supplied is not None
                    else "(not supplied; removed by Replace)"
                )
                rows.append((label, old_text, new_text))

        walk(saved, self.incoming)
        return rows

    def describe(self):
        from .contact_create import FIELD_NAMES

        title = FIELD_NAMES.get(self.field, self.field)
        identity_key = {"organizations": "name", "userDefined": "key"}.get(self.field, "value")
        context = self.saved[0].get(identity_key) if self.field not in SINGLETONS else None
        lines = [f"{title}: {context}" if context else f"{title}:"]
        for i, entry in enumerate(self.saved, 1):
            if len(self.saved) > 1:
                lines.append(f"Saved entry #{i}:")
            differences = self.differences(entry)
            for label, old, new in differences:
                lines.extend([f"{label} differs:", f"  Saved:    {old}", f"  Incoming: {new}"])
            if not differences:
                lines.append("  No differing supplied properties; multiple saved entries match.")
        if self.field in SINGLETONS and not self.name_parts:
            lines.append("Replace uses the complete incoming entry.")
        return "\n".join(lines)

    def choice_labels(self):
        if self.name_parts:
            old, new = self.saved[0]["givenName"], self.incoming["givenName"]
            return f"Keep {old}", f"Replace {old} with {new}", ""
        labels = {row[0] for saved in self.saved for row in self.differences(saved)}
        label_only = labels == {"Label"}
        subject = "label" if label_only else "values"
        both = "Keep both as separate entries"
        if self.field in {"emailAddresses", "phoneNumbers"}:
            kind = "email" if self.field == "emailAddresses" else "phone"
            article = "an" if kind == "email" else "a"
            both = (
                f"Keep both labels as two {kind} entries"
                if label_only and len(self.saved) == 1
                else f"Keep existing labels and add {article} {kind} entry with the incoming label"
                if label_only
                else f"Keep both as separate {kind} entries (duplicates the address or number)"
            )
        return f"Keep saved {subject}", f"Use incoming {subject}", both


def conflict_summary(existing, incoming):
    details = []
    merge_values(existing, incoming, details=details)
    return "\n".join(c.describe() for c in details)


def overlay(old, new):
    result = deepcopy(old)
    for key, value in new.items():
        if key == "metadata":
            continue
        result[key] = (
            overlay(result[key], value)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else deepcopy(value)
        )
    return result


def merge_values(existing, incoming, *, resolver=None, details=None):
    from .contact_create import FIELD_NAMES, format_entry
    from .contact_merge import _merge_values_keep, entry_key, guard_size

    result, changes, conflicts = deepcopy(existing), [], []
    for field_name, supplied in incoming.items():
        for new in supplied:
            name_parts = False
            if field_name == "names" and len(result.get("names", [])) == 1:
                resolved = anchored_name(result["names"][0], new)
                if resolved is not None:
                    new, name_parts = resolved, True
            kept, added, problems = _merge_values_keep(result, {field_name: [new]})
            if not problems:
                result = kept
                changes.extend(added)
                continue
            values = result.get(field_name, [])
            key = entry_key(field_name, new)
            indices = [
                i
                for i, e in enumerate(values)
                if (
                    field_name in SINGLETONS
                    or (
                        field_name == "userDefined"
                        and new.get("key") == "Created"
                        and e.get("key") == "Created"
                    )
                    or (key is not None and entry_key(field_name, e) == key)
                )
            ]
            conflict = Conflict(
                field_name,
                indices,
                [deepcopy(values[i]) for i in indices],
                deepcopy(new),
                problems,
                name_parts,
            )
            if details is not None:
                details.append(conflict)
            choice = resolver(conflict) if resolver else "k"
            entry_number = 0
            if isinstance(choice, tuple):
                choice, entry_number = choice
            if choice == "q":
                raise MergeCancelled
            title = FIELD_NAMES.get(field_name, field_name)
            if choice == "k":
                result = kept
                changes.extend(added)
                conflicts.extend(
                    [f"Kept first name: {conflict.saved[0]['givenName']}."]
                    if name_parts
                    else problems
                )
            elif choice == "b" and conflict.both:
                # Keep both complete entries; do not also fill the old entry's gaps.
                result.setdefault(field_name, []).append(deepcopy(new))
                changes.append(f"Keep both {title} entries; add: {format_entry(field_name, new)}")
            elif choice == "r" and 0 <= entry_number < len(indices):
                position = indices[entry_number]
                old = values[position]
                replacement = deepcopy(new) if field_name in SINGLETONS else overlay(old, new)
                if field_name == "emailAddresses":
                    # Matching already established the address identity ignoring case.
                    replacement["value"] = old["value"]
                if old.get("metadata"):
                    replacement["metadata"] = deepcopy(old["metadata"])
                if field_name == "birthdays":
                    validate_date(replacement["date"], "Replacement birthday")
                result[field_name][position] = replacement
                if name_parts:
                    changes.append(
                        f"Replace First name: {old['givenName']} → {replacement['givenName']}"
                    )
                else:
                    changes.append(
                        f"Replace {title}: {format_entry(field_name, old)}\n"
                        f"     With: {format_entry(field_name, replacement)}"
                    )
            else:
                raise SyncError("Unsupported merge conflict choice.")
    guard_size(result)
    return result, changes, conflicts


def choose_conflict(conflict, *, position=None, total=None):
    if position is not None:
        from .contact_create import FIELD_NAMES

        kind = FIELD_NAMES.get(conflict.field, conflict.field).lower()
        if conflict.field == "emailAddresses" and all(
            row[0] == "Label" for saved in conflict.saved for row in conflict.differences(saved)
        ):
            kind = "email label"
        step = f"{position} of {total}" if total is not None else f"decision {position}"
        emit(f"Review {kind} difference ({step})")
    emit(conflict.describe())
    keep, replace, both = conflict.choice_labels()
    emit(f"  k   {keep}\n  r   {replace}", primary=False)
    if conflict.both:
        emit("  b   " + both, primary=False)
    emit("  q   Cancel command", primary=False)
    while True:
        emit("Choice [k]: ", primary=False, end="")
        try:
            answer = read_input().strip().casefold()
        except EOFError:
            raise MergeCancelled from None
        finally:
            emit("", primary=False)
        if answer in ("", "k", "keep"):
            return "k"
        if answer in ("q", "cancel"):
            raise MergeCancelled
        if answer in ("b", "both") and conflict.both:
            return "b"
        if answer in ("r", "replace"):
            if len(conflict.saved) == 1:
                return "r"
            while True:
                emit(f"Replace saved entry 1–{len(conflict.saved)} (q = cancel): ", end="")
                try:
                    target = read_input().strip().casefold()
                except EOFError:
                    raise MergeCancelled from None
                if target == "q":
                    raise MergeCancelled
                if target.isdecimal() and 1 <= int(target) <= len(conflict.saved):
                    return "r", int(target) - 1
                emit("Choose one displayed saved entry number, or q to cancel.")
        emit("Choose k, r, b, or q." if conflict.both else "Choose k, r, or q.")
