"""Synthetic transport inside the production read worker; no network allowed."""

import json
import os
import socket
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httplib2
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from contacts_cli import read_worker


def forbid(*args, **kwargs):
    raise AssertionError("Network forbidden in worker fixture")


socket.socket = forbid


def stalled(*args, **kwargs):
    reader, writer = os.pipe()
    try:
        os.read(reader, 1)
    finally:
        os.close(reader)
        os.close(writer)


REQUEST_COUNTS = {}


def request(self, uri, method="GET", *args, **kwargs):
    mode = urlsplit(uri).path.lstrip("/")
    REQUEST_COUNTS[mode] = REQUEST_COUNTS.get(mode, 0) + 1
    if mode == "retry-once" and REQUEST_COUNTS[mode] == 1:
        return httplib2.Response({"status": "503"}), b"{}"
    if mode == "connection-once":
        attempt = Path(os.environ["CONNECTION_ATTEMPT_FILE"])
        if not attempt.exists():
            attempt.write_text("connection failed")
            raise ConnectionResetError("synthetic disconnect")
    marker = os.environ.get("DEADLINE_TEST_MARKER")
    if marker:
        Path(marker).write_text(str(os.getpid()))
    if mode == "stubborn":
        import signal

        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stalled()
    if mode == "slow-body":
        while True:
            time.sleep(0.01)
    if mode == "http-error":
        return httplib2.Response({"status": "403"}), b'{"error":{"message":"synthetic denial"}}'
    if mode == "long-query":
        assert method == "POST"
        assert kwargs["headers"]["x-http-method-override"] == "GET"
    if mode == "success":
        assert kwargs["headers"]["authorization"] == "Bearer synthetic-refreshed"
    if mode == "dns-stall":
        socket.getaddrinfo = stalled
        socket.getaddrinfo("example.invalid", 443)
    if mode == "response-stall":
        stalled()
    if mode == "dns-error":
        raise socket.gaierror(-2, "synthetic resolution failure")
    if mode == "backoff":
        return httplib2.Response({"status": "503"}), b"{}"
    return httplib2.Response({"status": "200"}), json.dumps({"ok": True}).encode()


def refresh(self, request):
    if self.refresh_token == "revoked-refresh":
        raise RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
        )
    if self.refresh_token == "stall-refresh":
        stalled()
    assert self.token != "synthetic-refreshed", "Valid refreshed token should be reused"
    self.token = "synthetic-refreshed"
    self.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)


Credentials.refresh = refresh
httplib2.Http.request = request
read_worker.main()
