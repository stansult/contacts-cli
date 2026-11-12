"""Verify the HTTP fixture independently of contacts-cli product assertions."""

import json
from copy import deepcopy


def fetch(server, path, method="GET", body=None):
    response, content = server.request(
        "https://offline.invalid" + path, method=method, body=json.dumps(body) if body else None
    )
    return response.status, json.loads(content)


def test_fixture_filters_messages_not_threads_and_pages(server):
    path = "/gmail/v1/users/me/messages?labelIds=Label_1&includeSpamTrash=true"
    _, first = fetch(server, path)
    assert [item["id"] for item in first["messages"]] == ["m1", "m2"]
    assert first["nextPageToken"] == "2"
    _, second = fetch(server, path + "&pageToken=2")
    assert [item["id"] for item in second["messages"]] == ["m3", "m4"]
    _, last = fetch(server, path + "&pageToken=4")
    assert [item["id"] for item in last["messages"]] == ["m5"]
    assert "nextPageToken" not in last
    _, regular = fetch(server, path.replace("true", "false"))
    assert [item["id"] for item in regular["messages"]] == ["m1", "m2"]
    assert "nextPageToken" not in regular
    assert server.mailbox["messages"][-1]["threadId"] == "t1"


def test_fixture_replaces_masked_field_and_enforces_source_etag(server):
    original = deepcopy(server.person)
    path = "/v1/people/c123:updateContact?updatePersonFields=emailAddresses"
    body = {"metadata": {"sources": [{"etag": "wrong"}]}, "emailAddresses": []}
    assert fetch(server, path, "PATCH", body)[0] == 400
    assert server.person == original
    body["metadata"]["sources"][0]["etag"] = "source-v1"
    assert fetch(server, path, "PATCH", body)[0] == 200
    assert server.person["emailAddresses"] == []
    assert server.person["phoneNumbers"] == original["phoneNumbers"]
    assert server.person["metadata"]["sources"][0]["etag"] != "source-v1"


def test_fixture_read_mask_and_full_email_list(server):
    server.person["emailAddresses"] = [{"value": f"sender{i}@example.com"} for i in range(150)]
    _, result = fetch(
        server,
        "/v1/people:batchGet?resourceNames=people/c123&personFields=emailAddresses"
        "&sources=READ_SOURCE_TYPE_CONTACT",
    )
    person = result["responses"][0]["person"]
    assert len(person["emailAddresses"]) == 150
    assert "phoneNumbers" not in person
