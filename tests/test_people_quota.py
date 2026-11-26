"""Scripted HTTP rejection contracts and virtual time; no Google access or real waits."""

import json
from copy import deepcopy

import httplib2
import pytest
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest

from contacts_cli.api import execute
from contacts_cli.contact_create import format_entry
from contacts_cli.errors import SyncError, WriteUnverified
from contacts_cli.quota import PeopleQuota, retry_delay


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds

    def __call__(self):
        return self.now


def rate_error(status=429, reason="RATE_LIMIT_EXCEEDED", header=None, unit="1/min/{user}"):
    resp = httplib2.Response({"status": str(status), **({"retry-after": header} if header else {})})
    body = {
        "error": {
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": reason,
                    "metadata": {"quota_unit": unit},
                }
            ]
        }
    }
    return HttpError(resp, json.dumps(body).encode())


class ScriptedHTTP:
    def __init__(self, outcomes, clock):
        self.outcomes = iter(outcomes)
        self.calls = 0
        self.contacts_quota = PeopleQuota(clock=clock, sleep=clock.sleep)

    def request(self, *args, **kwargs):
        self.calls += 1
        result = next(self.outcomes)
        if isinstance(result, HttpError):
            return result.resp, result.content
        if isinstance(result, BaseException):
            raise result
        return httplib2.Response({"status": "200"}), b'{"saved": true}'


def req(http, method="people.people.createContact"):
    return HttpRequest(
        http,
        lambda r, b: json.loads(b),
        "https://people.googleapis.com/v1/people:createContact",
        method="POST",
        methodId=method,
        body="{}",
    )


def test_scripted_rejection_has_no_success_payload():
    http = ScriptedHTTP([rate_error(), None], Clock())
    response, body = http.request()
    assert response.status == 429
    assert json.loads(body)["error"]["details"][0]["reason"] == "RATE_LIMIT_EXCEEDED"
    response, body = http.request()
    assert response.status == 200 and json.loads(body) == {"saved": True}


def test_budget_boundary_and_expiration(capsys):
    clock = Clock()
    quota = PeopleQuota(clock=clock, sleep=clock.sleep)
    for _ in range(80):
        quota.acquire()
    assert clock.waits == []
    clock.now = 10
    quota.acquire()
    assert clock.waits == [50]
    assert list(quota.sent) == [60]
    assert "Pacing Google Contacts" in capsys.readouterr().out


@pytest.mark.parametrize("write", [True, False])
def test_explicit_rate_retry_resumes_same_request(write):
    clock = Clock()
    http = ScriptedHTTP([rate_error(header="65"), None], clock)
    assert execute(req(http), write=write) == {"saved": True}
    assert http.calls == 2 and clock.waits == [65]


def test_retries_are_bounded():
    clock = Clock()
    http = ScriptedHTTP([rate_error()] * 4, clock)
    with pytest.raises(SyncError, match="HTTP 429"):
        execute(req(http), write=True)
    assert http.calls == 4 and len(clock.waits) == 3
    assert all(low <= wait <= low + 1 for low, wait in zip([30, 60, 120], clock.waits, strict=True))


@pytest.mark.parametrize(
    "error",
    [
        rate_error(reason="QUOTA_EXCEEDED"),
        rate_error(unit="1/day/{user}"),
        rate_error(header="600"),
        rate_error(status=403),
        rate_error(header="garbage"),
    ],
)
def test_nontransient_or_excessive_delay_not_retried(error):
    clock = Clock()
    http = ScriptedHTTP([error], clock)
    with pytest.raises(SyncError):
        execute(req(http), write=True)
    assert http.calls == 1 and not clock.waits


@pytest.mark.parametrize("error", [TimeoutError(), rate_error(status=503)])
def test_uncertain_writes_never_replayed(error):
    clock = Clock()
    http = ScriptedHTTP([error], clock)
    with pytest.raises(WriteUnverified):
        execute(req(http), write=True)
    assert http.calls == 1 and not clock.waits


def test_interruption_during_retry_sends_no_second_write():
    http = ScriptedHTTP([rate_error(), None], Clock())

    def interrupt(_):
        raise KeyboardInterrupt

    http.contacts_quota.sleep = interrupt
    with pytest.raises(KeyboardInterrupt):
        execute(req(http), write=True)
    assert http.calls == 1


def test_reads_and_writes_share_budget():
    clock = Clock()
    http = ScriptedHTTP([None] * 81, clock)
    for i in range(81):
        execute(
            req(http, "people.people.get" if i % 2 else "people.people.createContact"),
            write=not i % 2,
        )
    assert clock.waits == [60]


def test_gmail_does_not_use_people_budget():
    clock = Clock()
    http = ScriptedHTTP([None] * 81, clock)
    for _ in range(81):
        execute(req(http, "gmail.users.labels.list"))
    assert not clock.waits and not http.contacts_quota.sent


def test_missing_error_details_do_not_authorize_write_retry():
    assert retry_delay(HttpError(httplib2.Response({"status": "429"}), b"{}"), 0) is None


@pytest.mark.parametrize("name,shown", [("User@EXAMPLE.com", False), ("Jane", True)])
def test_redundant_display_name_hidden_without_data_change(name, shown):
    entry = {"value": "user@example.com", "type": "home", "displayName": name}
    before = deepcopy(entry)
    text = format_entry("emailAddresses", entry)
    assert ("Display name:" in text) is shown
    assert "user@example.com — home" in text
    assert entry == before
