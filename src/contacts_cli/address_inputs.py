"""Shared address and UTF-8 list parsing for exclusion and email editing."""

from .core import address_key, parse_from_details
from .errors import SyncError


def bare_address(value):
    address = value.strip()
    parsed = parse_from_details([address])
    if parsed != ((address, ""),) or "*" in address:
        raise SyncError("expected one supported email address without a name or wildcard")
    return address


def file_lines(paths):
    for raw_path in paths:
        path = raw_path.expanduser()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise SyncError(f"{path}: address file must be UTF-8 text.") from exc
        except OSError as exc:
            raise SyncError(f"{path}: address file could not be read.") from exc
        for number, raw_line in enumerate(content.splitlines(), 1):
            line = raw_line.strip()
            if line and not line.startswith("#"):
                yield line, f"{path}:{number}"


def split_entry(line):
    address, _, label = line.partition(" — ")
    return address.strip(), label.strip()


def edit_inputs(values, paths, option):
    lines = [(value, f"{option} #{i}") for i, value in enumerate(values, 1)]
    lines.extend(file_lines(paths))
    result = []
    for line, origin in lines:
        address, label = split_entry(line)
        try:
            address = bare_address(address)
            if any(ord(c) < 32 or ord(c) == 127 for c in label):
                raise SyncError("invalid control character in label")
        except SyncError as exc:
            raise SyncError(f"{origin}: {exc}") from exc
        result.append((address, label, origin))
    return result


def normalized_entries(entries, person, label_filter, *, remove=False):
    result = {}
    for address, label, origin in entries:
        key = address_key(address)
        label = "" if remove else label_filter(person, address, label)
        if key in result and address_key(result[key][1]) != address_key(label):
            raise SyncError(
                f"Conflicting incoming labels for {address}: {result[key][2]} and {origin}; "
                "correct the inputs before retrying."
            )
        result.setdefault(key, (address, label, origin))
    return result
