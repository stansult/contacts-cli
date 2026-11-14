"""Offline validation of new contacts in Google Person JSON format."""

import json
import re
from calendar import monthrange
from copy import deepcopy
from urllib.parse import urlsplit

from googleapiclient.discovery_cache import get_static_doc

from .address_inputs import bare_address
from .errors import SyncError

FIELDS = {
    "names",
    "emailAddresses",
    "phoneNumbers",
    "organizations",
    "addresses",
    "urls",
    "userDefined",
    "biographies",
    "birthdays",
    "events",
    "nicknames",
}
SINGLETONS = {"names", "biographies", "birthdays"}


def invalid(path, message):
    raise SyncError(f"{path}: {message}")


def text_value(value, path, *, multiline=False):
    if not isinstance(value, str) or not value.strip():
        invalid(path, "expected nonblank text")
    if any(
        (ord(c) < 32 and not (multiline and c in "\n\r\t"))
        or ord(c) == 127
        or 0xD800 <= ord(c) <= 0xDFFF
        for c in value
    ):
        invalid(path, "unsupported control character or Unicode surrogate")


def validate_date(value, path):
    year, month, day = (value.get(key, 0) for key in ("year", "month", "day"))
    if not 0 <= year <= 9999 or not 0 <= month <= 12 or not 0 <= day <= 31:
        invalid(path, "date components are out of range")
    if not ((year and not month and not day) or (year and month and not day) or (month and day)):
        invalid(path, "expected a full date, month/day, year, or year/month")
    if month and day and day > monthrange(year or 2000, month)[1]:
        invalid(path, "invalid calendar date")


def validate_schema(value, schema, schemas, path):
    ref = schema.get("$ref")
    if ref:
        schema = schemas[ref]
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict) or not value:
            invalid(path, "expected a nonempty object")
        props = schema.get("properties", {})
        for key, item in value.items():
            prop = props.get(key)
            child = f"{path}.{key}"
            if prop is None or prop.get("readOnly") or key == "metadata":
                invalid(child, "unsupported or generated field")
            if ref == "Birthday" and key == "text":
                invalid(child, "use a structured date instead of deprecated birthday text")
            validate_schema(item, prop, schemas, child)
        if ref == "Date":
            validate_date(value, path)
    elif kind == "string":
        text_value(
            value,
            path,
            multiline=path.endswith(
                (
                    ".value",
                    ".streetAddress",
                    ".formattedValue",
                    ".extendedAddress",
                    ".jobDescription",
                )
            ),
        )
    elif kind == "integer":
        if type(value) is not int or not -(2**31) <= value < 2**31:
            invalid(path, "expected a 32-bit integer")
    elif kind == "boolean":
        if type(value) is not bool:
            invalid(path, "expected true or false")
    else:
        invalid(path, "unsupported field type")
    if "enum" in schema and value not in schema["enum"]:
        invalid(path, "expected one of " + ", ".join(schema["enum"]))


def validate_entry(field, entry, path):
    required = {
        "emailAddresses": "value",
        "phoneNumbers": "value",
        "urls": "value",
        "biographies": "value",
        "nicknames": "value",
        "events": "date",
        "birthdays": "date",
    }
    if field in required and required[field] not in entry:
        invalid(f"{path}.{required[field]}", "required field is missing")
    if field == "userDefined":
        for key in ("key", "value"):
            if key not in entry:
                invalid(f"{path}.{key}", "required field is missing")
    if field == "emailAddresses":
        try:
            bare_address(entry["value"])
        except SyncError:
            invalid(f"{path}.value", "invalid or unsupported email address")
    if field == "phoneNumbers":
        phone = entry["value"].strip()
        if (
            not re.fullmatch(
                r"\+?[0-9 ()./-]+(?:(?:\s*(?:ext\.?|x|#)\s*|;ext=)[0-9]+)?", phone, re.I
            )
            or len(re.findall(r"[0-9]", phone)) < 3
        ):
            invalid(f"{path}.value", "expected a phone number with optional extension")
    if field == "urls":
        try:
            url = urlsplit(entry["value"])
            valid = (
                url.scheme in {"http", "https"}
                and url.hostname
                and not url.username
                and not url.password
                and not any(c.isspace() for c in entry["value"])
            )
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            invalid(f"{path}.value", "expected an http:// or https:// URL with a host")
    if field == "names" and not any(
        entry.get(k) for k in ("givenName", "familyName", "middleName", "unstructuredName")
    ):
        invalid(path, "provide a given, family, middle, or unstructured name")
    if field == "addresses" and not any(k != "type" for k in entry):
        invalid(path, "provide at least one address component")
    if field == "organizations" and not any(entry.get(k) for k in ("name", "title", "department")):
        invalid(path, "provide a company, title, or department")
    if (
        field == "addresses"
        and "countryCode" in entry
        and not re.fullmatch(r"[A-Z]{2}", entry["countryCode"])
    ):
        invalid(f"{path}.countryCode", "expected a two-letter uppercase country code")


def validate_contacts(data):
    contacts = data if isinstance(data, list) else [data]
    if not contacts:
        invalid("contacts", "expected at least one contact")
    schemas = json.loads(get_static_doc("people", "v1"))["schemas"]
    props = schemas["Person"]["properties"]
    for number, person in enumerate(contacts, 1):
        path = f"Contact #{number}"
        if not isinstance(person, dict) or not person:
            invalid(path, "expected a nonempty Person object")
        for field, entries in person.items():
            if field not in FIELDS:
                invalid(f"{path} → {field}", "unsupported or generated field")
            if not isinstance(entries, list):
                invalid(f"{path} → {field}", "expected an array")
            if field in SINGLETONS and len(entries) > 1:
                invalid(f"{path} → {field}", "only one entry is allowed")
            for i, entry in enumerate(entries):
                location = f"{path} → {field}[{i}]"
                validate_schema(entry, props[field]["items"], schemas, location)
                validate_entry(field, entry, location)
        if not (
            person.get("names")
            or person.get("emailAddresses")
            or person.get("phoneNumbers")
            or any(org.get("name") for org in person.get("organizations", []))
        ):
            invalid(path, "provide at least a name, email, phone, or company")
        if (
            sum(map(len, person.values())) > 500
            or len(json.dumps(person, ensure_ascii=False).encode("utf-8")) > 128 * 1024
        ):
            invalid(path, "exceeds the local 500-entry or 128-KiB size guard")
    return deepcopy(contacts)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_contact_inputs(*, name=None, emails=(), file=None, labels=()):
    for i, label in enumerate(labels, 1):
        text_value(label, f"--label #{i}")
    if file is not None:
        try:
            data = json.loads(
                file.expanduser().read_text(encoding="utf-8"),
                object_pairs_hook=unique_keys,
                parse_constant=lambda value: invalid("JSON", f"invalid constant {value}"),
            )
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            raise SyncError(f"{file}: could not read valid UTF-8 JSON: {exc}") from exc
    else:
        data = {}
        if name is not None:
            data["names"] = [{"unstructuredName": name}]
        if emails:
            data["emailAddresses"] = [{"value": email} for email in emails]
    return validate_contacts(data)
