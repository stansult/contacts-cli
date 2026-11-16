"""Local HTTP errors and bounded email-verification evidence, without credentials."""

import base64
import json
import os
import sys
import tempfile
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

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
