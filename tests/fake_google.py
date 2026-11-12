"""Offline HTTP fixture behind the real Google client; contract-tested separately.

It models label filtering, small pages, field masks, and etag replacement semantics.
It does not emulate all Google behavior or claim to validate real account permissions.
"""

import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httplib2
from googleapiclient.discovery import build

FIXTURES = Path(__file__).parent / "fixtures"


class FakeGoogle:
    def __init__(self):
        self.person = json.loads((FIXTURES / "contact.json").read_text())
        self.mailbox = json.loads((FIXTURES / "mailbox.json").read_text())
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
            offset = int(query.get("pageToken", ["0"])[0])
            result = {
                "messages": [
                    {"id": item["id"], "threadId": item["threadId"]}
                    for item in matches[offset : offset + 2]
                ]
            }
            if offset + 2 < len(matches) or self.repeat_token:
                result["nextPageToken"] = "2" if self.repeat_token else str(offset + 2)
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
            result = {key: value for key, value in self.person.items() if key in fields}
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
