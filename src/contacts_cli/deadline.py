"""Bound network reads with a reusable process, including blocking DNS resolution."""

import base64
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar

import httplib2
from google.oauth2.credentials import Credentials

from .error_logs import TRACE
from .errors import SyncError
from .persistent_reader import PersistentReader

READ_TIMEOUT_SECONDS = 15
DEADLINE = ContextVar("read_deadline", default=None)


class ReadTimeout(SyncError):
    """An entire read exhausted its budget; not eligible for SDK retries."""


def remaining():
    state = DEADLINE.get()
    if state is None:
        raise RuntimeError("Network read requires a deadline")
    end, seconds, operation = state
    left = end - time.monotonic()
    if left <= 0:
        raise ReadTimeout(
            f"{operation} timed out after {seconds:g} seconds. Check your connection and retry."
        )
    return left


@contextmanager
def read_budget(operation, request=None):
    token = DEADLINE.set((time.monotonic() + READ_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS, operation))
    trace = TRACE.get()
    if trace:
        trace.event("read_deadline", operation=operation, timeout_seconds=READ_TIMEOUT_SECONDS)
    original_sleep = getattr(request, "_sleep", None)
    if callable(original_sleep):

        def bounded_sleep(seconds):
            left = remaining()
            original_sleep(min(seconds, left))
            remaining()

        request._sleep = bounded_sleep
    try:
        yield
        remaining()
    except BaseException:
        transport = getattr(request, "http", None)
        if isinstance(transport, DeadlineHTTP):
            transport.reader._stop()
        raise
    finally:
        if callable(original_sleep):
            request._sleep = original_sleep
        DEADLINE.reset(token)


def worker_call(payload, command=None):
    """Secrets travel only through anonymous pipes, never argv, files, or diagnostics."""
    remaining()
    process = subprocess.Popen(
        command or [sys.executable, "-m", "contacts_cli.read_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        try:
            output, _ = process.communicate(json.dumps(payload).encode(), timeout=remaining())
        except subprocess.TimeoutExpired:
            # Use the shared deadline's operation-specific message.
            remaining()
            raise AssertionError("Timeout returned before deadline") from None
        if process.returncode:
            raise SyncError("Google read worker failed; retry the command.")
        result = json.loads(output)
        check_worker_result(result)
        return result
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                process.kill()
        process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()


def check_worker_result(result):
    if "error" in result:
        error = result["error"]
        trace = TRACE.get()
        if trace:
            trace.event("read_worker_error", exceptions=error["details"])
        kind = error["kind"]
        if kind == "dns":
            raise SyncError(
                "Could not resolve the Google server address. Check your connection and retry."
            )
        if kind == "timeout":
            raise TimeoutError("Google read connection timed out")
        if kind == "connection":
            raise ConnectionError("Google read connection failed")
        raise SyncError("Google API read failed; check connectivity and authorization.")
    return result


def is_read(method, headers):
    # google-api-python-client encodes long GET queries as POST with this override.
    override = next(
        (v for k, v in (headers or {}).items() if k.lower() == "x-http-method-override"), None
    )
    return method in {"GET", "HEAD"} or (method == "POST" and override == "GET")


class DeadlineHTTP:
    """Read attempts run in a killable worker; writes use the original transport."""

    def __init__(self, http, *, worker_command=None):
        self.http = http
        self.worker_command = worker_command
        self.reader = PersistentReader(worker_command)
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.reader.close()
            finally:
                self.http.close()

    @property
    def credentials(self):
        return self.http.credentials

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        if self.closed:
            raise SyncError("Google transport is closed")
        if DEADLINE.get() is None:
            return self.http.request(uri, method, body=body, headers=headers, **kwargs)
        if not is_read(method, headers):
            raise SyncError("A network read attempted a write; no request sent.")
        if kwargs.get("connection_type") is not None:
            raise SyncError("Custom read connection types are unsupported.")
        result = self.read(
            {
                "action": "read",
                "credentials": json.loads(self.credentials.to_json()),
                "uri": uri,
                "method": method,
                "body": base64.b64encode(body.encode() if isinstance(body, str) else body).decode()
                if body is not None
                else None,
                "headers": dict(headers or {}),
                "timeout": remaining(),
                "redirections": kwargs.get("redirections", httplib2.DEFAULT_MAX_REDIRECTS),
            }
        )
        self.http.credentials = Credentials.from_authorized_user_info(result["credentials"])
        return httplib2.Response(result["headers"]), base64.b64decode(result["content"])

    def read(self, payload):
        try:
            result = self.reader.request(payload, seconds=remaining())
        except TimeoutError:
            remaining()
            raise ReadTimeout("Google API read timed out; retry the command.") from None
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            raise SyncError("Google read worker failed; retry the command.") from exc
        return check_worker_result(result)

    def __getattr__(self, name):
        return getattr(self.http, name)


def refresh_credentials(credentials):
    with read_budget("Refreshing authorization"):
        result = worker_call(
            {
                "action": "refresh",
                "credentials": json.loads(credentials.to_json()),
                "timeout": remaining(),
            }
        )
        return Credentials.from_authorized_user_info(result["credentials"])
