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


def test_fixture_search_excludes_addresses_and_honors_one_result(server):
    from urllib.parse import urlencode

    path = "/gmail/v1/users/me/messages?" + urlencode(
        {
            "labelIds": "Label_1",
            "includeSpamTrash": "true",
            "maxResults": 1,
            "q": '-from:"existing@example.com" -from:"NEW@EXAMPLE.COM"',
        }
    )
    _, result = fetch(server, path)
    assert result["messages"] == [{"id": "m4", "threadId": "t3"}]
    assert result["nextPageToken"] == "1"
    _, next_page = fetch(server, path + "&pageToken=1")
    assert next_page["messages"] == [{"id": "m5", "threadId": "t4"}]
    assert "nextPageToken" not in next_page
    _, empty = fetch(server, path.replace("includeSpamTrash=true", "includeSpamTrash=false"))
    assert empty == {"messages": []}


def test_fixture_search_does_not_collapse_plus_or_dot_variants(server):
    from urllib.parse import urlencode

    variants = ["a.b@example.com", "ab@example.com", "a.b+tag@example.com"]
    template = deepcopy(server.mailbox["messages"][0])
    server.mailbox["messages"] = []
    for index, address in enumerate(variants):
        message = deepcopy(template)
        message["id"] = str(index)
        message["payload"]["headers"][0]["value"] = address
        server.mailbox["messages"].append(message)
    _, result = fetch(
        server,
        "/gmail/v1/users/me/messages?"
        + urlencode(
            {
                "labelIds": "Label_1",
                "q": '-from:"a.b@example.com"',
            }
        ),
    )
    assert [item["id"] for item in result["messages"]] == ["1", "2"]
