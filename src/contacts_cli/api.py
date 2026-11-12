"""Google API boundary for Gmail metadata reads and explicit contact writes."""

import base64
import json

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

from .core import (
    CONTACT_FIELDS,
    Plan,
    Scan,
    address_key,
    contact_source,
    parse_from,
    update_body,
    validate_contact,
    verify_saved,
)
from .duplicate import READ_FIELDS, download_photo, verify_duplicate
from .errors import SyncError, WriteUnverified


def execute(request, *, write: bool = False, operation: str = "update"):
    try:
        # Never retry a mutation whose outcome may be unknown.
        return request.execute(num_retries=0 if write else 3)
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

    def scan(self, label_name: str) -> Scan:
        response = execute(self.gmail.users().labels().list(userId="me"))
        matches = [label for label in response.get("labels", []) if label.get("name") == label_name]
        if len(matches) != 1 or not matches[0].get("id"):
            raise SyncError("Label name must match exactly one existing Gmail label.")
        label_id = matches[0]["id"]
        messages = self.gmail.users().messages()
        seen_ids, seen_tokens = set(), set()
        senders, problems = {}, []
        page_token = None
        while True:
            kwargs = dict(userId="me", labelIds=[label_id], includeSpamTrash=True, maxResults=500)
            if page_token:
                kwargs["pageToken"] = page_token
            page = execute(messages.list(**kwargs))
            for item in page.get("messages", []):
                message_id = item.get("id")
                if not message_id:
                    raise SyncError("Gmail returned a message without an ID; scan aborted.")
                if message_id in seen_ids:
                    continue
                seen_ids.add(message_id)
                message = execute(
                    messages.get(
                        userId="me", id=message_id, format="metadata", metadataHeaders=["From"]
                    )
                )
                if message.get("id") != message_id or label_id not in message.get("labelIds", []):
                    raise SyncError(
                        "A message changed or lost its label during the scan; rerun preview."
                    )
                headers = message.get("payload", {}).get("headers", [])
                values = [h.get("value") for h in headers if h.get("name", "").lower() == "from"]
                try:
                    for sender in parse_from(values):
                        senders.setdefault(address_key(sender), sender)
                except SyncError as exc:
                    problems.append(f"Message {message_id}: {exc}")
            page_token = page.get("nextPageToken")
            if not page_token:
                break
            if page_token in seen_tokens:
                raise SyncError("Gmail repeated a pagination token; scan aborted.")
            seen_tokens.add(page_token)
        return Scan(len(seen_ids), tuple(senders[key] for key in sorted(senders)), tuple(problems))

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
        latest = self.get_contact(plan.person["resourceName"])
        # A second read catches changes during preview generation; source etag also
        # protects the interval between this read and the PATCH on Google's side.
        if contact_source(latest) != contact_source(plan.person) or json.dumps(
            latest.get("emailAddresses", []), sort_keys=True
        ) != json.dumps(plan.person.get("emailAddresses", []), sort_keys=True):
            raise SyncError("Contact changed since preview; no update made. Rerun preview.")
        result = self.write(
            self.people.people().updateContact(
                resourceName=plan.person["resourceName"],
                updatePersonFields="emailAddresses",
                personFields=CONTACT_FIELDS,
                sources=["READ_SOURCE_TYPE_CONTACT"],
                body=body,
            ),
        )
        try:
            verify_saved(plan, result)
            # Resource names can change when a contact links to a profile.
            verify_saved(plan, self.get_contact(result["resourceName"]))
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
