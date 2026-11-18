"""Private network reads. The parent owns deadlines, retries, logging, and cleanup."""

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


class ReadSession:
    """Retain HTTP connection cache; credentials travel only through private pipes."""

    def __init__(self, http_factory=None):
        self.factory = http_factory or httplib2.Http
        self.http = None

    def perform(self, payload):
        if payload.get("action") != "read" or not is_read(payload["method"], payload["headers"]):
            raise ValueError("Only reads are allowed")
        credentials = Credentials.from_authorized_user_info(payload["credentials"])
        if self.http is None:
            self.http = AuthorizedHttp(
                credentials,
                http=self.factory(timeout=payload["timeout"]),
                max_refresh_attempts=0,
            )
        else:
            self.http.credentials = credentials
        transport = self.http.http
        transport.timeout = payload["timeout"]
        for connection in transport.connections.values():
            connection.timeout = payload["timeout"]
            if connection.sock is not None:
                connection.sock.settimeout(payload["timeout"])
        response, content = self.http.request(
            payload["uri"],
            payload["method"],
            body=base64.b64decode(payload["body"]) if payload.get("body") is not None else None,
            headers=payload["headers"],
            redirections=payload.get("redirections", httplib2.DEFAULT_MAX_REDIRECTS),
        )
        return {
            "headers": dict(response),
            "content": base64.b64encode(content).decode(),
            "credentials": json.loads(self.http.credentials.to_json()),
        }

    def close(self):
        if self.http is not None:
            self.http.close()
            self.http = None


def perform(payload):
    if payload["action"] == "refresh":
        credentials = Credentials.from_authorized_user_info(payload["credentials"])
        credentials.refresh(Request())
        return {"credentials": json.loads(credentials.to_json())}
    session = ReadSession()
    try:
        return session.perform(payload)
    finally:
        session.close()


def error_reply(exc):
    kind = "read"
    if isinstance(exc, (socket.gaierror, httplib2.ServerNotFoundError)):
        kind = "dns"
    elif isinstance(exc, TimeoutError):
        kind = "timeout"
    elif isinstance(exc, (ConnectionError, ssl.SSLError)):
        kind = "connection"
    return {"error": {"kind": kind, "details": exception_details(exc)}}


def serve(session):
    try:
        for line in sys.stdin.buffer:
            packet = json.loads(line)
            try:
                result = session.perform(packet["payload"])
            except Exception as exc:
                session.close()
                result = error_reply(exc)
            reply = {"id": packet["id"]}
            if "error" in result:
                reply.update(result)
            else:
                reply["result"] = result
            print(json.dumps(reply), flush=True)
    finally:
        session.close()


def main():
    if sys.argv[1:] == ["--persistent"]:
        serve(ReadSession())
        return
    try:
        result = perform(json.load(sys.stdin))
    except Exception as exc:
        result = error_reply(exc)
    json.dump(result, sys.stdout)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
