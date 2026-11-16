"""Static extraction and URL-add selection, with no live webpage or Google access."""

import io
import subprocess
import sys
import time
from copy import deepcopy

import pytest

from contacts_cli import cli, web_emails
from contacts_cli.errors import SyncError
from contacts_cli.selection import parse_selection, select_numbers


@pytest.mark.parametrize(
    "answer,expected",
    [("all", [7, 3, 4, 5, 8]), ("3-5,8", [3, 4, 5, 8]), ("3,3-4", [3, 4]), (" 8 , 7 ", [7, 8])],
)
def test_selection_display_order_and_overlap(answer, expected):
    assert parse_selection(answer, [7, 3, 4, 5, 8]) == expected


@pytest.mark.parametrize(
    "answer", ["", "0", "1", "3-7", "8-3", "3,", "-1", "3.5", "1-999999999999999999999999999999"]
)
def test_selection_rejects_unavailable_and_invalid(answer):
    with pytest.raises(ValueError):
        parse_selection(answer, [3, 4, 5, 8])


def test_selector_retries_and_cancel(monkeypatch):
    answers = iter(["", "0", "2-3"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert select_numbers([1, 2, 3]) == [2, 3]
    monkeypatch.setattr("builtins.input", lambda: "q")
    assert select_numbers([1]) is None

    def eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert select_numbers([1]) is None


def test_extract_visible_and_mailto():
    html = """<head><title>head@example.com</title></head>
    <h2>Management</h2><p>info@example.com.</p>
    <a href="mailto:INFO@example.com,second%2Btag@example.com?cc=ignored@example.com">Email</a>
    <script>script@example.com</script><style>style@example.com</style>
    <template>template@example.com</template><noscript>no@example.com</noscript>
    <div hidden><a href="mailto:hidden@example.com">hidden@example.com</a></div>
    <span aria-hidden="true">aria@example.com</span>
    <p style="display: none">css@example.com</p>
    <p style="visibility:hidden">invisible@example.com</p>
    <!-- comment@example.com --><img alt="alt@example.com">
    <p>last&#64;example.com</p><a href="mailto:not-valid">Bad</a>"""
    assert web_emails.extract_addresses(html) == [
        "info@example.com",
        "last@example.com",
        "second+tag@example.com",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/test",
        "ftp://example.com",
        "https://a:b@example.com",
        "https://",
        "https://example.com:bad",
        "https://example.com/\n",
    ],
)
def test_url_validation(url):
    with pytest.raises(SyncError):
        web_emails.validate_url(url)


class Response:
    encoding = "utf-8"
    url = "https://example.com/contact"
    headers = {"Content-Type": "text/html; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        assert size == 65536
        yield b"<p>one@example.com</p>"


class Session:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url, **kwargs):
        assert url == "https://example.com/contact"
        assert kwargs["stream"] is True and kwargs["timeout"] == (5, 10)
        assert self.max_redirects == 5
        return Response()


def test_fetch_fixture_contract_and_limits(monkeypatch):
    import requests

    # Independently verify the fixture's exact body and content type.
    assert b"".join(Response().iter_content(65536)) == b"<p>one@example.com</p>"
    assert Response.headers["Content-Type"] == "text/html; charset=utf-8"
    monkeypatch.setattr(requests, "Session", Session)
    assert web_emails.fetch_page("https://example.com/contact")["addresses"] == ["one@example.com"]
    monkeypatch.setattr(web_emails, "MAX_BYTES", 4)
    with pytest.raises(SyncError, match="size limit"):
        web_emails.fetch_page("https://example.com/contact")
    monkeypatch.setattr(Response, "headers", {"Content-Type": "application/pdf"})
    with pytest.raises(SyncError, match="HTML"):
        web_emails.fetch_page("https://example.com/contact")


def test_deadline_terminates_worker(monkeypatch, tmp_path):
    marker = tmp_path / "started"
    real_popen = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = real_popen(
            [
                sys.executable,
                "-c",
                (
                    f'import pathlib,time; pathlib.Path({str(marker)!r}).write_text("ready"); '
                    "time.sleep(60)"
                ),
            ],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(web_emails.subprocess, "Popen", spawn)
    monkeypatch.setattr(web_emails, "FETCH_SECONDS", 1)
    started = time.monotonic()
    with pytest.raises(SyncError, match="timed out after 1 seconds"):
        web_emails.fetch_addresses("https://example.com")
    assert time.monotonic() - started < 2.5
    assert marker.read_text() == "ready"
    assert children[0].poll() is not None
    assert children[0].stdin.closed and children[0].stdout.closed


@pytest.fixture
def page_cli(api, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *args: api)
    monkeypatch.setattr(
        cli,
        "fetch_addresses",
        lambda url: {"url": url, "addresses": ["a@example.com", "b@example.com", "c@example.com"]},
    )
    return ["add-email", "--contact", "c123", "--from-url", "https://example.com/contact"]


def terminal(monkeypatch, answers):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    values = iter(answers)
    monkeypatch.setattr("builtins.input", lambda: next(values))


def test_url_apply_preserves_existing_labels_and_duplicates(page_cli, server):
    server.person["emailAddresses"] = [
        {"value": "a@example.com", "type": "Work"},
        {"value": "A@example.com", "type": "Other"},
    ]
    before = deepcopy(server.person["emailAddresses"])
    assert cli.main(page_cli + ["--apply"]) == 0
    assert server.person["emailAddresses"][:2] == before
    assert server.person["emailAddresses"][2:] == [
        {"value": "b@example.com"},
        {"value": "c@example.com"},
    ]
    assert server.writes == 1


def test_url_selection_back_and_save(page_cli, server, monkeypatch, capsys):
    before = deepcopy(server.person["emailAddresses"])
    terminal(monkeypatch, ["1-2", "n", "2-3", "y"])
    assert cli.main(page_cli) == 0
    assert server.person["emailAddresses"] == before + [
        {"value": "b@example.com"},
        {"value": "c@example.com"},
    ]
    output = capsys.readouterr().out
    assert "  2. b@example.com" in output and "  3. c@example.com" in output
    assert server.writes == 1


@pytest.mark.parametrize("answers", [["q"], ["all", "q"]])
def test_url_cancel_no_write(page_cli, server, monkeypatch, answers):
    terminal(monkeypatch, answers)
    assert cli.main(page_cli) == 0 and server.writes == 0


def test_url_noninteractive_preview(page_cli, server):
    assert cli.main(page_cli) == 0 and server.writes == 0


@pytest.mark.parametrize(
    "extra", [["--add", "x@example.com"], ["--add-file", "missing.txt"], ["--replace-existing"]]
)
def test_url_conflicting_inputs_before_fetch(extra, monkeypatch):
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *args: pytest.fail("auth called"))
    with pytest.raises(SystemExit) as error:
        cli.main(["add-email", "--contact", "c123", "--from-url", "https://example.com", *extra])
    assert error.value.code == 2


def test_empty_page_needs_no_google(page_cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_addresses", lambda url: {"url": url, "addresses": []})
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *args: pytest.fail("auth called"))
    assert cli.main(page_cli) == 0
    assert "No email addresses found" in capsys.readouterr().out


def test_worker_http_failure(monkeypatch, capsys):
    import requests

    response = requests.Response()
    response.status_code = 403

    def fail(url):
        raise requests.HTTPError(response=response)

    monkeypatch.setattr(web_emails, "fetch_page", fail)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"url":"https://example.com"}'))
    web_emails.main()
    assert "HTTP 403" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["all", "1"])
def test_url_confirmation_eof_cancels(page_cli, server, monkeypatch, answer):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: True)
    calls = iter([answer])

    def read():
        try:
            return next(calls)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", read)
    assert cli.main(page_cli) == 0 and server.writes == 0


def test_url_all_existing_no_prompt_or_write(page_cli, server, monkeypatch):
    server.person["emailAddresses"] = [
        {"value": f"{name}@example.com", "type": "Work"} for name in "abc"
    ]
    terminal(monkeypatch, [])
    assert cli.main(page_cli) == 0 and server.writes == 0


def test_url_fetch_failure_before_google(page_cli, monkeypatch):
    def fail(url):
        raise SyncError("Webpage returned HTTP 403.")

    monkeypatch.setattr(cli, "fetch_addresses", fail)
    monkeypatch.setattr(
        cli, "connect_with_authorization", lambda *args: pytest.fail("Google accessed")
    )
    assert cli.main(page_cli) == 1
