"""Local HTTP errors and bounded email-verification evidence, without credentials."""

import base64
import json
import os
import re
import sys
import tempfile
import time
import traceback
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from googleapiclient.errors import HttpError

from .output import emit

COMMAND = ContextVar("error_log_command", default=None)


def log_directory():
    override = os.environ.get("CONTACTS_CLI_ERROR_LOG_DIR")
    if override:
        return Path(override).expanduser()
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file() and (root / "contacts-cli").is_file():
        return root / ".contacts-cli" / "logs"
    return Path.home() / ".local" / "state" / "contacts-cli" / "logs"


def save_http_error(error, request, *, write, operation):
    now = datetime.now().astimezone()
    method = getattr(request, "methodId", None)
    record = {
        "timestamp": now.isoformat(),
        "command": COMMAND.get(),
        "operation": method if isinstance(method, str) else (operation if write else "read"),
        "write": write,
        "http_status": int(error.resp.status),
    }
    try:
        record["response_body"] = error.content.decode("utf-8")
        record["response_body_encoding"] = "utf-8"
    except UnicodeDecodeError:
        record["response_body"] = base64.b64encode(error.content).decode("ascii")
        record["response_body_encoding"] = "base64"
    path = None
    try:
        folder = log_directory()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, filename = tempfile.mkstemp(
            prefix=now.strftime("error-%Y-%m-%d-%H%M%S-"), suffix=".json", dir=folder
        )
        path = Path(filename)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
    except OSError:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        emit("Error details could not be saved locally.", file=sys.stderr)
        return None
    emit(f"Error details saved to: {path.resolve()}", file=sys.stderr)
    return path


def save_verification_error(error, *, stage, person, expected, saved):
    """Save email-update evidence; retain only the newest 20 verification logs."""
    now = datetime.now().astimezone()
    record = {
        "timestamp": now.isoformat(),
        "command": COMMAND.get(),
        "stage": stage,
        "resource_name": person.get("resourceName"),
        "mismatch": str(error),
        "before": person.get("emailAddresses", []),
        "expected": expected,
        "saved": saved.get("emailAddresses", []) if isinstance(saved, dict) else None,
    }
    path = None
    try:
        folder = log_directory()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, filename = tempfile.mkstemp(
            prefix=now.strftime("verification-%Y-%m-%d-%H%M%S-"), suffix=".json", dir=folder
        )
        path = Path(filename)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
    except (OSError, TypeError, ValueError):
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        emit("Verification details could not be saved locally.", file=sys.stderr)
        return None
    emit(f"Verification details saved to: {path.resolve()}", file=sys.stderr)
    try:
        # Always retain the just-written evidence, even if the system clock changed.
        older = sorted(
            (
                item
                for item in folder.glob("verification-*.json")
                if item != path and item.is_file() and not item.is_symlink()
            ),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
            reverse=True,
        )
        for item in older[19:]:
            item.unlink(missing_ok=True)
    except OSError:
        emit("Older verification logs could not be removed.", file=sys.stderr)
    return path


TRACE = ContextVar("run_diagnostics", default=None)


def exception_details(error):
    """Keep the exception chain and stack locations, never frame locals or requests."""
    result, seen = [], set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        raw_message = f"HTTP {error.resp.status}" if isinstance(error, HttpError) else str(error)
        message = re.sub(r"https?://[^\s<>]+", "<URL omitted>", raw_message)
        message = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", message)
        message = re.sub(
            r"(?i)((?:access_token|refresh_token|client_secret|authorization)\s*[:=]\s*)[^\s,;]+",
            r"\1<redacted>",
            message,
        )
        result.append(
            {
                "type": type(error).__name__,
                "module": type(error).__module__,
                "message": message,
                "errno": getattr(error, "errno", None),
                "frames": [
                    {
                        "file": Path(frame.filename).name,
                        "line": frame.lineno,
                        "function": frame.name,
                    }
                    for frame in traceback.extract_tb(error.__traceback__)
                ],
            }
        )
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return result


class RunDiagnostics:
    """Flush each event before continuing so a pending request is observable on disk."""

    def __init__(self, command, code_version):
        self.started = time.monotonic()
        self.stream = None
        self.path = None
        try:
            folder = log_directory()
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix="run-", suffix=".jsonl", dir=folder)
            self.path = Path(name).resolve()
            self.stream = os.fdopen(fd, "w", encoding="utf-8")
            self.event("command_start", command=command, pid=os.getpid(), code_version=code_version)
        except OSError:
            self.disable()
        if self.stream is not None:
            emit(f"Run diagnostics: {self.path}", file=sys.stderr)
            try:
                older = sorted(
                    (
                        p
                        for p in folder.glob("run-*.jsonl")
                        if p.resolve() != self.path and p.is_file() and not p.is_symlink()
                    ),
                    key=lambda p: (p.stat().st_mtime_ns, p.name),
                    reverse=True,
                )
                for old in older[19:]:
                    old.unlink(missing_ok=True)
            except OSError:
                emit("Older run diagnostics could not be removed.", file=sys.stderr)

    def disable(self):
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                pass
        self.stream = None
        emit("Run diagnostics could not be saved locally.", file=sys.stderr)

    def event(self, event, **fields):
        if self.stream is None:
            return
        try:
            self.stream.write(
                json.dumps(
                    {
                        "event": event,
                        "timestamp": datetime.now().astimezone().isoformat(),
                        "elapsed_seconds": round(time.monotonic() - self.started, 6),
                        **fields,
                    }
                )
                + "\n"
            )
            self.stream.flush()
        except (OSError, ValueError):
            self.disable()

    def finish(self, code):
        self.event("command_exit", exit_code=code)
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                self.disable()
                return
            self.stream = None
            emit(f"Run finished (exit code {code}). Diagnostics: {self.path}", file=sys.stderr)
