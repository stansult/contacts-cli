"""Offline HTTP fixture behind the real Google client; contract-tested separately.

It models label filtering, small pages, field masks, and etag replacement semantics.
It does not emulate all Google behavior or claim to validate real account permissions.
"""

import json
import re
from copy import deepcopy
from email.utils import getaddresses
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httplib2
from googleapiclient.discovery import build

FIXTURES = Path(__file__).parent / "fixtures"


class FakeGoogle:
    def __init__(self):
        self.person = json.loads((FIXTURES / "contact.json").read_text())
        self.mailbox = json.loads((FIXTURES / "mailbox.json").read_text())
        self.send_as = json.loads((FIXTURES / "send-as.json").read_text())
        self.send_as_status = 200
        self.groups = {}
        self.created = {}
        self.create_status = 200
        self.photo_status = 200
        self.drop_copy_field = None
        self.calls = []
        self.writes = 0
        self.batch_reads = 0
        self.batch_status = 0
        self.missing_message = None
        self.repeat_token = False
        self.concurrent_edit = False
        self.reject_write = False
        self.lose_additions = False
        self.fail_verification = False

    def clients(self):
        return (
            build("gmail", "v1", http=self, static_discovery=True),
            build("people", "v1", http=self, static_discovery=True),
        )

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        url = urlsplit(uri)
        query = parse_qs(url.query)
        data = json.loads(body) if body else None
        self.calls.append((method, url.path, query, deepcopy(data)))

        def reply(payload, status=200):
            return httplib2.Response({"status": str(status)}), json.dumps(payload).encode()

        if method == "GET" and url.path == "/gmail/v1/users/me/settings/sendAs":
            return reply(self.send_as, self.send_as_status)
        if method == "GET" and url.path == "/gmail/v1/users/me/labels":
            return reply({"labels": self.mailbox["labels"]})
        if method == "GET" and url.path == "/gmail/v1/users/me/messages":
            labels = set(query.get("labelIds", []))
            include_spam = query.get("includeSpamTrash") == ["true"]
            matches = [
                item
                for item in self.mailbox["messages"]
                if labels.issubset(item["labelIds"])
                and (include_spam or not {"SPAM", "TRASH"}.intersection(item["labelIds"]))
            ]
            search = query.get("q", [""])[0]
            terms = re.findall(r'-from:"([^"\\]+)"', search)
            assert " ".join(f'-from:"{term}"' for term in terms) == search
            excluded = {term.casefold() for term in terms}
            matches = [
                item
                for item in matches
                if not excluded.intersection(
                    address.casefold()
                    for _, address in getaddresses(
                        [
                            h["value"]
                            for h in item["payload"]["headers"]
                            if h["name"].lower() == "from"
                        ]
                    )
                )
            ]
            page_size = min(2, int(query.get("maxResults", ["2"])[0]))
            offset = int(query.get("pageToken", ["0"])[0])
            result = {
                "messages": [
                    {"id": item["id"], "threadId": item["threadId"]}
                    for item in matches[offset : offset + page_size]
                ]
            }
            if offset + page_size < len(matches) or self.repeat_token:
                result["nextPageToken"] = "2" if self.repeat_token else str(offset + page_size)
            return reply(result)
        if method == "GET" and url.path.startswith("/gmail/v1/users/me/messages/"):
            message_id = url.path.rsplit("/", 1)[-1]
            if message_id == self.missing_message:
                return reply({"error": {"message": "Synthetic missing message"}}, 404)
            message = next(item for item in self.mailbox["messages"] if item["id"] == message_id)
            assert query.get("format") == ["metadata"]
            assert query.get("metadataHeaders") == ["From"]
            return reply(message)
        if method == "GET" and url.path == "/v1/people:batchGet":
            self.batch_reads += 1
            if self.concurrent_edit and self.batch_reads == 2:
                self.person["metadata"]["sources"][0]["etag"] = "changed-elsewhere"
                self.person["emailAddresses"].append({"value": "concurrent@example.com"})
            if self.fail_verification and self.writes:
                return reply({"error": {"message": "Synthetic read failure"}}, 403)
            assert query.get("sources") == ["READ_SOURCE_TYPE_CONTACT"]
            fields = set(query["personFields"][0].split(",")) | {"resourceName", "etag"}
            resource = query["resourceNames"][0]
            person = (
                self.person
                if resource == self.person["resourceName"]
                else self.created.get(resource)
            )
            if person is None:
                return reply(
                    {"responses": [{"requestedResourceName": resource, "status": {"code": 5}}]}
                )
            result = {key: value for key, value in person.items() if key in fields}
            return reply(
                {
                    "responses": [
                        {
                            "requestedResourceName": query["resourceNames"][0],
                            "status": {"code": self.batch_status},
                            "person": result,
                        }
                    ]
                }
            )
        if method == "POST" and url.path.endswith("/members:modify"):
            resource = url.path.removeprefix("/v1/").removesuffix("/members:modify")
            assert set(data) in ({"resourceNamesToAdd"}, {"resourceNamesToRemove"})
            remove = "resourceNamesToRemove" in data
            if resource not in self.groups:
                return reply({"error": {"message": "Missing group"}}, 404)
            missing, blocked = [], []
            for name in data["resourceNamesToRemove" if remove else "resourceNamesToAdd"]:
                person = (
                    self.person if name == self.person["resourceName"] else self.created.get(name)
                )
                if person is None:
                    missing.append(name)
                    continue
                membership = {"contactGroupMembership": {"contactGroupResourceName": resource}}
                entries = person.setdefault("memberships", [])
                if remove and membership in entries:
                    if len(entries) == 1:
                        blocked.append(name)
                    else:
                        entries.remove(membership)
                elif not remove and membership not in entries:
                    entries.append(membership)
            self.writes += 1
            result = {"notFoundResourceNames": missing} if missing else {}
            if blocked:
                result["canNotRemoveLastContactGroupResourceNames"] = blocked
            return reply(result)
        if url.path == "/v1/contactGroups":
            if method == "GET":
                offset = int(query.get("pageToken", ["0"])[0])
                groups = list(self.groups.values())
                result = {"contactGroups": groups[offset : offset + 1]}
                if offset + 1 < len(groups):
                    result["nextPageToken"] = str(offset + 1)
                return reply(result)
            if method == "POST":
                name = data["contactGroup"]["name"]
                if any(group["name"] == name for group in self.groups.values()):
                    return reply({"error": {"message": "Duplicate name"}}, 409)
                resource = f"contactGroups/created{len(self.groups)}"
                self.groups[resource] = {
                    "resourceName": resource,
                    "name": name,
                    "groupType": "USER_CONTACT_GROUP",
                }
                self.writes += 1
                return reply(self.groups[resource])
        if method == "GET" and url.path.startswith("/v1/contactGroups/"):
            resource = url.path.removeprefix("/v1/")
            if resource in self.groups:
                return reply(self.groups[resource])
            kind = (
                "SYSTEM_CONTACT_GROUP"
                if resource
                in {"contactGroups/myContacts", "contactGroups/starred", "contactGroups/friends"}
                else "USER_CONTACT_GROUP"
            )
            return reply({"resourceName": resource, "groupType": kind})
        if method == "POST" and url.path == "/v1/people:createContact":
            if self.create_status != 200:
                return reply({"error": {"message": "Synthetic create failure"}}, self.create_status)
            assert not {"resourceName", "etag", "metadata", "photos"}.intersection(data)
            self.writes += 1
            identity = str(456 + len(self.created))
            resource = "people/c" + identity
            person = deepcopy(data)
            if self.drop_copy_field:
                person.pop(self.drop_copy_field, None)
            person.update(
                resourceName=resource,
                etag="new-person",
                metadata={
                    "sources": [
                        {"type": "CONTACT", "id": format(int(identity), "x"), "etag": "new-source"}
                    ]
                },
            )
            self.created[resource] = person
            return reply(person)
        if method == "PATCH" and url.path.endswith(":updateContactPhoto"):
            if self.photo_status != 200:
                return reply({"error": {"message": "Synthetic photo failure"}}, self.photo_status)
            resource = url.path.removeprefix("/v1/").removesuffix(":updateContactPhoto")
            assert data["photoBytes"]
            self.writes += 1
            self.created[resource]["photos"] = [
                {"url": "https://lh3.googleusercontent.com/copy", "default": False}
            ]
            return reply({"person": self.created[resource]})
        if method == "PATCH" and url.path.endswith(":updateContact"):
            incoming = data.get("metadata", {}).get("sources", [{}])[0].get("etag")
            current = self.person["metadata"]["sources"][0]["etag"]
            if self.reject_write or incoming != current:
                return reply({"error": {"message": "Synthetic failedPrecondition"}}, 400)
            self.writes += 1
            # Replacement, not append: the fixture exposes destructive request bodies.
            for field in query["updatePersonFields"][0].split(","):
                if not self.lose_additions:
                    self.person[field] = deepcopy(data.get(field, []))
            self.person["metadata"]["sources"][0]["etag"] = f"written-{self.writes}"
            return reply(self.person)
        raise AssertionError(f"Unexpected offline request: {method} {url.path}")
