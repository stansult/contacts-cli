"""One private network read. The parent owns deadlines, retries, logging, and cleanup."""

import base64
import json
import socket
import ssl
import sys

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp

from .deadline import is_read
from .error_logs import exception_details


def perform(payload):
    credentials = Credentials.from_authorized_user_info(payload["credentials"])
    if payload["action"] == "refresh":
        credentials.refresh(Request())
        return {"credentials": json.loads(credentials.to_json())}
    if payload["action"] != "read" or not is_read(payload["method"], payload["headers"]):
        raise ValueError("Worker only accepts reads or token refresh")
    http = AuthorizedHttp(
        credentials, http=httplib2.Http(timeout=payload["timeout"]), max_refresh_attempts=0
    )
    try:
        response, content = http.request(
            payload["uri"],
            payload["method"],
            body=base64.b64decode(payload["body"]) if payload["body"] is not None else None,
            headers=payload["headers"],
            redirections=payload["redirections"],
        )
        return {
            "headers": dict(response),
            "content": base64.b64encode(content).decode(),
            "credentials": json.loads(credentials.to_json()),
        }
    finally:
        http.close()


def main():
    try:
        result = perform(json.load(sys.stdin))
    except Exception as exc:
        kind = "read"
        if isinstance(exc, (socket.gaierror, httplib2.ServerNotFoundError)):
            kind = "dns"
        elif isinstance(exc, TimeoutError):
            kind = "timeout"
        elif isinstance(exc, (ConnectionError, ssl.SSLError)):
            kind = "connection"
        result = {"error": {"kind": kind, "details": exception_details(exc)}}
    json.dump(result, sys.stdout)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
