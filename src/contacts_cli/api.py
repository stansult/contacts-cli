"""Google API boundary for Gmail metadata reads and explicit contact writes."""

import base64
import json
import re
from urllib.parse import quote

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

from .core import (
    CONTACT_FIELDS,
    Plan,
    Scan,
    address_key,
    contact_source,
    parse_from_details,
    update_body,
    validate_contact,
    verify_saved,
)
from .duplicate import READ_FIELDS, download_photo, verify_duplicate
from .errors import SyncError, WriteUnverified
from .metrics import ACTIVE, counts, execute_measured

# Conservative application guard, not a claimed Gmail server limit.
MAX_QUERY_BYTES = 6000


def exclusion_query(addresses):
    terms = []
    for address in sorted(addresses):
        # Restrict to common addr-spec syntax; never interpolate search operators,
        # quotes, backslashes, display names, or controls from contact/header data.
        if not re.fullmatch(r"[a-z0-9_%+-]+(?:\.[a-z0-9_%+-]+)*@[a-z0-9][a-z0-9.-]*", address):
            raise SyncError(
                "An email address has unsupported syntax for safe sender exclusion; "
                "no changes made."
            )
        terms.append(f'-from:"{address}"')
    query = " ".join(terms)
    if len(quote(query, safe="")) > MAX_QUERY_BYTES:
        raise SyncError(
            "Sender exclusion query exceeds the local 6,000-byte limit; no changes made."
        )
    return query


def execute(request, *, write: bool = False, operation: str = "update"):
    try:
        # Never retry a mutation whose outcome may be unknown.
        return execute_measured(request, num_retries=0 if write else 3)
    except HttpError as exc:
        status = exc.resp.status
        if write and status >= 500:
            raise WriteUnverified(
                "Update outcome is unknown; inspect a new preview before retrying."
            ) from exc
        if write and status in {400, 409, 412}:
            raise SyncError(
                f"Contact {operation} rejected (possible conflict, limit, or bad data); "
                "rerun preview."
            ) from exc
        raise SyncError(
            f"Google API returned HTTP {status}; check access, API setup, and quotas."
        ) from exc
    except (OSError, GoogleAuthError, HttpLib2Error, ValueError) as exc:
        if write:
            raise WriteUnverified(
                "Update outcome is unknown; inspect a new preview before retrying."
            ) from exc
        raise SyncError("Google API read failed; check connectivity and authorization.") from exc


class GoogleAPI:
    def __init__(self, gmail, people):
        self.gmail = gmail
        self.people = people
        self.write_started = False

    def write(self, request, *, operation="update"):
        # Keep this set through subsequent reads: an interruption during
        # verification must not claim that no contact changes were made.
        self.write_started = True
        return execute(request, write=True, operation=operation)

    def sending_addresses(self):
        response = execute(
            self.gmail.users()
            .settings()
            .sendAs()
            .list(userId="me", fields="sendAs(sendAsEmail,isPrimary)")
        )
        aliases = response.get("sendAs") if isinstance(response, dict) else None
        if (
            not isinstance(aliases, list)
            or not aliases
            or any(not isinstance(alias, dict) for alias in aliases)
            or sum(alias.get("isPrimary") is True for alias in aliases) != 1
        ):
            raise SyncError("Incomplete Gmail sending-address list; no changes made.")
        addresses = set()
        for alias in aliases:
            address = alias.get("sendAsEmail")
            if not isinstance(address, str) or not address.strip():
                raise SyncError("Incomplete Gmail sending-address list; no changes made.")
            addresses.add(address_key(address))
        exclusion_query(addresses)
        return addresses

    def scan(
        self,
        label_name: str,
        *,
        existing_emails=(),
        excluded_emails=(),
        progress=None,
        label_found=None,
    ) -> Scan:
        def report(stage, processed=0, senders=0, problems=0):
            if stage in {"Searching senders", "Search finished", "Search stopped"}:
                counts(messages=processed, senders=senders, invalid_headers=problems)
            if stage == "Search finished" and ACTIVE.get() is not None:
                ACTIVE.get().record["scan_complete"] = True
            if progress is not None:
                progress(stage, processed, senders, problems)

        excluded = {address_key(address) for address in (*existing_emails, *excluded_emails)}
        query = exclusion_query(excluded)
        report("Reading sending addresses")
        excluded.update(self.sending_addresses())
        query = exclusion_query(excluded)
        report("Finding label")
        response = execute(self.gmail.users().labels().list(userId="me"))
        if not isinstance(response, dict) or not isinstance(response.get("labels", []), list):
            raise SyncError("Incomplete Gmail label response; search aborted.")
        labels = response.get("labels", [])
        if any(not isinstance(label, dict) for label in labels):
            raise SyncError("Incomplete Gmail label response; search aborted.")
        matches = [label for label in labels if label.get("name") == label_name]
        if len(matches) != 1 or not isinstance(matches[0].get("id"), str) or not matches[0]["id"]:
            raise SyncError("Label name must match exactly one existing Gmail label.")
        label_id = matches[0]["id"]
        if label_found is not None:
            label_found(label_name)
        messages = self.gmail.users().messages()
        seen_ids, senders = set(), {}
        labels = {}
        processed = 0
        report("Searching senders")
        while True:
            page = execute(
                messages.list(
                    userId="me", labelIds=[label_id], includeSpamTrash=True, maxResults=1, q=query
                )
            )
            if not isinstance(page, dict):
                raise SyncError("Incomplete Gmail search response; no changes made.")
            items = page.get("messages", [])
            if not isinstance(items, list) or len(items) > 1:
                raise SyncError("Unexpected Gmail search results; no changes made.")
            if not items:
                if page.get("nextPageToken"):
                    raise SyncError("Empty Gmail search page has more results; no changes made.")
                break
            item = items[0]
            message_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(message_id, str) or not message_id:
                raise SyncError("Gmail returned a message without an ID; search aborted.")
            if message_id in seen_ids:
                raise SyncError(
                    "Gmail repeated a message despite sender exclusions; no changes made."
                )
            seen_ids.add(message_id)
            message = execute(
                messages.get(
                    userId="me", id=message_id, format="metadata", metadataHeaders=["From"]
                )
            )
            if (
                not isinstance(message, dict)
                or message.get("id") != message_id
                or not isinstance(message.get("labelIds"), list)
                or label_id not in message["labelIds"]
            ):
                raise SyncError(
                    "A message changed or lost its label during the search; rerun preview."
                )
            payload = message.get("payload")
            headers = payload.get("headers") if isinstance(payload, dict) else None
            processed += 1
            try:
                if not isinstance(headers, list) or any(not isinstance(h, dict) for h in headers):
                    raise SyncError("incomplete From header metadata")
                values = [
                    h.get("value") for h in headers if str(h.get("name", "")).lower() == "from"
                ]
                addresses = parse_from_details(values)
            except SyncError as exc:
                report("Search stopped", processed, len(senders), 1)
                return Scan(
                    processed,
                    tuple(senders[key] for key in sorted(senders)),
                    (f"Message {message_id}: {exc}",),
                    tuple(sorted(labels.items())),
                )
            new = {
                address_key(address): address
                for address, label in reversed(addresses)
                if address_key(address) not in excluded
            }
            if not new:
                report("Search stopped", processed, len(senders))
                raise SyncError(
                    "Gmail search returned no new sender despite exclusions; no changes made."
                )
            for address, label in addresses:
                key = address_key(address)
                if key in new:
                    labels.setdefault(key, label)
            senders.update(new)
            excluded.update(new)
            report("Searching senders", processed, len(senders))
            query = exclusion_query(excluded)
        report("Search finished", processed, len(senders))
        return Scan(
            processed,
            tuple(senders[key] for key in sorted(senders)),
            labels=tuple(sorted(labels.items())),
        )

    def get_contact(self, resource: str, fields: str = CONTACT_FIELDS) -> dict:
        batch = execute(
            self.people.people().getBatchGet(
                resourceNames=[resource],
                personFields=fields,
                sources=["READ_SOURCE_TYPE_CONTACT"],
            )
        )
        responses = batch.get("responses", [])
        if len(responses) != 1:
            raise SyncError("Incomplete contact batch response.")
        response = responses[0]
        if (
            response.get("requestedResourceName") != resource
            or response.get("status", {}).get("code", 0) != 0
            or response.get("httpStatusCode", 200) != 200
        ):
            raise SyncError(
                "Contact could not be read completely; check its URL and authorized account."
            )
        person = response.get("person")
        validate_contact(person)
        return person

    def apply(self, plan: Plan) -> bool:
        if plan.scan.problems:
            raise SyncError("Incomplete scan; no update is allowed.")
        if not plan.additions:
            return False
        body = update_body(plan)
        return self.apply_email_change(plan.person, body, lambda saved: verify_saved(plan, saved))

    def apply_email_change(self, person, body, verify):
        """Shared conflict protection, email-only write, and two-stage verification."""
        latest = self.get_contact(person["resourceName"])
        # A second read catches changes during preview generation; source etag also
        # protects the interval between this read and the PATCH on Google's side.
        if contact_source(latest) != contact_source(person) or json.dumps(
            latest.get("emailAddresses", []), sort_keys=True
        ) != json.dumps(person.get("emailAddresses", []), sort_keys=True):
            raise SyncError("Contact changed since preview; no update made. Rerun preview.")
        result = self.write(
            self.people.people().updateContact(
                resourceName=person["resourceName"],
                updatePersonFields="emailAddresses",
                personFields=CONTACT_FIELDS,
                sources=["READ_SOURCE_TYPE_CONTACT"],
                body=body,
            ),
        )
        try:
            verify(result)
            # Resource names can change when a contact links to a profile.
            verify(self.get_contact(result["resourceName"]))
        except SyncError as exc:
            raise WriteUnverified(
                f"Update was submitted but verification failed: {exc} Inspect a new preview."
            ) from exc
        return True

    def duplicate(self, plan):
        schemas = self.people._rootDesc["schemas"]
        photo = download_photo(plan.photo_url) if plan.photo_url else None
        latest = self.get_contact(plan.person["resourceName"], READ_FIELDS)
        if latest != plan.person:
            raise SyncError("Contact changed since preview; no copy created. Rerun preview.")
        for membership in plan.body.get("memberships", []):
            resource = membership["contactGroupMembership"]["contactGroupResourceName"]
            group = execute(self.people.contactGroups().get(resourceName=resource))
            if group.get("groupType") != "USER_CONTACT_GROUP" and resource not in {
                "contactGroups/myContacts",
                "contactGroups/starred",
            }:
                raise SyncError(
                    "Contact has a system group Google cannot copy; no contact created."
                )
        try:
            result = self.write(
                self.people.people().createContact(
                    body=plan.body, personFields=READ_FIELDS, sources=["READ_SOURCE_TYPE_CONTACT"]
                ),
                operation="creation",
            )
        except WriteUnverified as exc:
            raise WriteUnverified(
                "Contact creation outcome is unknown. Inspect Google Contacts before retrying; "
                "another attempt may create another copy."
            ) from exc
        except SyncError as exc:
            raise SyncError(f"Contact creation failed: {exc}") from exc
        location = "Google Contacts"
        try:
            validate_contact(result)
            source = contact_source(result)
            if source["id"] == contact_source(plan.person)["id"]:
                raise SyncError(
                    "Creation returned the original contact; stopped before photo write."
                )
            resource = result["resourceName"]
            # The source ID and person ID are different identifiers. Use the
            # returned person resource for a /person/ link, without converting IDs.
            location = "https://contacts.google.com/person/" + resource.removeprefix("people/")
            if photo:
                self.write(
                    self.people.people().updateContactPhoto(
                        resourceName=resource,
                        body={
                            "photoBytes": base64.b64encode(photo).decode(),
                            "personFields": READ_FIELDS,
                            "sources": ["READ_SOURCE_TYPE_CONTACT"],
                        },
                    ),
                )
            saved = self.get_contact(resource, READ_FIELDS)
            if contact_source(saved)["id"] != source["id"]:
                raise SyncError("The saved contact identity changed during verification.")
            verify_duplicate(plan, saved, schemas)
        except (SyncError, KeyError, TypeError, ValueError) as exc:
            raise WriteUnverified(
                f"A copy was submitted but is not fully verified: {location}. "
                f"{exc} Inspect it before retrying; another attempt creates another copy."
            ) from exc
        return location
