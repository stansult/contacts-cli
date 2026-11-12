"""Plan and verify contact copies using the bundled People schema."""

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .core import contact_source, validate_contact
from .errors import SyncError

COPY_FIELDS = (
    "addresses,biographies,birthdays,calendarUrls,clientData,emailAddresses,events,"
    "externalIds,fileAses,genders,imClients,interests,locales,locations,memberships,"
    "miscKeywords,names,nicknames,occupations,organizations,phoneNumbers,relations,"
    "sipAddresses,skills,urls,userDefined"
)
READ_FIELDS = COPY_FIELDS + ",metadata,photos"
PHOTO_LIMIT = 10 * 1024 * 1024


def duplicate_marker(now=None):
    now = now if now is not None else datetime.now().astimezone()
    months = (
        "January February March April May June July August September October November December"
    ).split()
    offset = now.strftime("%z")
    offset = (offset[:3] + ":" + offset[3:5]).replace("-", "−")
    hour = now.hour % 12 or 12
    period = "AM" if now.hour < 12 else "PM"
    return {
        "key": "Duplicate",
        "value": (
            f"Created by contacts-cli on {months[now.month - 1]} {now.day}, {now.year} "
            f"at {hour}:{now.minute:02d} {period} (UTC{offset})"
        ),
    }


def replacement_name(value):
    if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
        raise SyncError("Replacement name must be nonblank and contain no control characters.")
    return value


def clean(value, schema, schemas):
    """Strip generated fields recursively, retaining editable source-primary flags."""
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref == "FieldMetadata":
            return {"sourcePrimary": True} if value.get("sourcePrimary") else {}
        schema = schemas[ref]
    if schema.get("type") == "array":
        return [clean(item, schema["items"], schemas) for item in value]
    if schema.get("type") == "object":
        result = {}
        for key, item in value.items():
            prop = schema.get("properties", {}).get(key)
            if prop is None:
                raise SyncError(f"Unknown contact field {key!r}; update the client before copying.")
            if prop.get("readOnly"):
                continue
            copied = clean(item, prop, schemas)
            if copied not in ({}, [], None):
                result[key] = copied
        return result
    return deepcopy(value)


def copy_body(person, schemas):
    props = schemas["Person"]["properties"]
    source = contact_source(person)
    body = {}
    for field in COPY_FIELDS.split(","):
        values = person.get(field, [])
        if not isinstance(values, list):
            raise SyncError(f"Invalid contact field {field}; copy aborted.")
        for item in values:
            origin = item.get("metadata", {}).get("source")
            if origin and (origin.get("type"), origin.get("id")) != ("CONTACT", source["id"]):
                raise SyncError("Contact contains fields from another source; copy aborted.")
        copied = clean(values, props[field], schemas)
        # Read-only memberships (e.g. domain memberships) are not copied.
        if field == "memberships":
            copied = [item for item in copied if item.get("contactGroupMembership")]
        if copied:
            body[field] = copied
    return body


def stable(value):
    if isinstance(value, dict):
        return {key: stable(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return sorted(
            (stable(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True)
        )
    return value


@dataclass
class DuplicatePlan:
    person: dict
    body: dict
    photo_url: str | None


def make_duplicate_plan(person, schemas, name=None):
    validate_contact(person)
    replacement_name(name)
    body = copy_body(person, schemas)
    body.setdefault("userDefined", []).append(duplicate_marker())
    if name is not None:
        body["names"] = [{"givenName": name}]
    for field in ("names", "birthdays", "biographies", "genders"):
        if len(body.get(field, [])) > 1:
            raise SyncError(f"Google allows only one {field} entry in a new contact.")
    if sum(len(items) for items in body.values()) > 500 or len(json.dumps(body).encode()) > 131072:
        raise SyncError("Copy exceeds the local safety limit (500 entries or 128 KiB).")
    photos = [photo for photo in person.get("photos", []) if not photo.get("default", False)]
    if len(photos) > 1:
        raise SyncError("Multiple contact photos found; cannot select a complete copy safely.")
    photo_url = photos[0].get("url") if photos else None
    if photos and not photo_url:
        raise SyncError("Contact photo has no download URL; copy aborted.")
    return DuplicatePlan(deepcopy(person), body, photo_url)


def verify_duplicate(plan, person, schemas):
    validate_contact(person)
    if contact_source(person)["id"] == contact_source(plan.person)["id"]:
        raise SyncError("Google returned the original contact instead of a new contact.")
    saved = copy_body(person, schemas)

    def without_metadata(body):
        return {
            field: [{k: v for k, v in entry.items() if k != "metadata"} for entry in entries]
            for field, entries in body.items()
        }

    if stable(without_metadata(saved)) != stable(without_metadata(plan.body)):
        raise SyncError("The saved contact does not match the editable fields in the preview.")
    for field, entries in plan.body.items():
        requested = [entry for entry in entries if entry.get("metadata", {}).get("sourcePrimary")]
        if requested:
            actual = [
                entry for entry in saved[field] if entry.get("metadata", {}).get("sourcePrimary")
            ]
            if stable(actual) != stable(requested):
                raise SyncError(f"The saved {field} primary choice differs from the preview.")
    if plan.photo_url and not any(not p.get("default", False) for p in person.get("photos", [])):
        raise SyncError("The saved contact photo is missing.")


def download_photo(url):
    """Download without account credentials or redirects, with bounded size/time."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not (host == "googleusercontent.com" or host.endswith(".googleusercontent.com"))
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise SyncError("Unsupported contact photo URL; no contact created.")
    # Google serves thumbnails through either /s100/ or =s100[-options].
    # s0 retrieved the full-size source in the read-only investigation for #1.
    path, count = re.subn(r"([=/])s[0-9]+(?=(?:-[a-z0-9]+)*(?:/|$))", r"\g<1>s0", parsed.path)
    if count != 1:
        raise SyncError("Cannot select a full-size contact photo URL; no contact created.")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "sz"
    ]
    url = urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query), parsed.fragment))
    try:
        with requests.get(url, stream=True, timeout=(10, 30), allow_redirects=False) as response:
            if response.status_code != 200 or not response.headers.get(
                "Content-Type", ""
            ).startswith("image/"):
                raise SyncError("Contact photo could not be downloaded; no contact created.")
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > PHOTO_LIMIT:
                    raise SyncError(
                        "Contact photo exceeds the 10 MiB local limit; no contact created."
                    )
            if not data:
                raise SyncError("Contact photo is empty; no contact created.")
            return bytes(data)
    except requests.RequestException as exc:
        raise SyncError("Contact photo download failed; no contact created.") from exc
