"""Local sender-sync measurements; only explicitly selected aggregate fields are saved."""

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from contextvars import ContextVar
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

ACTIVE = ContextVar("run_metrics", default=None)
METHODS = {
    "gmail.users.settings.sendAs.list": "sending_addresses",
    "gmail.users.labels.list": "labels",
    "gmail.users.messages.list": "message_list",
    "gmail.users.messages.get": "headers",
    "people.people.getBatchGet": "contact_reads",
    "people.people.updateContact": "contact_writes",
}


def default_path():
    override = os.environ.get("CONTACTS_CLI_METRICS_DIR")
    if override:
        return Path(override) / "runs.jsonl"
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file() and (root / "contacts-cli").is_file():
        return root / ".contacts-cli" / "runs.jsonl"
    return Path.home() / ".local" / "state" / "contacts-cli" / "runs.jsonl"


def code_version():
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()[:16]


class RunMetrics:
    def __init__(self):
        self.started = time.monotonic()
        self.record = {
            "schema": 1,
            "started_at": datetime.now(UTC).isoformat(),
            "algorithm": "sender-exclusion-v1",
            "version": version("contacts-cli"),
            "code_version": code_version(),
            "outcome": "failed",
            "scan_complete": False,
            "counts": {},
            "api": {},
        }

    def finish(self, exit_code):
        self.record["exit_code"] = exit_code
        if exit_code:
            self.record["outcome"] = {130: "interrupted", 3: "unverified_write"}.get(
                exit_code, "failed"
            )
        self.record["elapsed_seconds"] = round(time.monotonic() - self.started, 6)
        try:
            path = default_path()
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
            fd = os.open(path, flags, 0o600)
            try:
                data = (json.dumps(self.record, sort_keys=True) + "\n").encode()
                if os.write(fd, data) != len(data):
                    raise OSError("Incomplete metrics write")
            finally:
                os.close(fd)
        except OSError:
            print("Warning: local run metrics could not be saved.", file=sys.stderr)


def counts(**values):
    current = ACTIVE.get()
    if current is not None:
        allowed = {"messages", "senders", "invalid_headers", "existing_entries", "additions"}
        for key, value in values.items():
            if key in allowed and type(value) is int:
                current.record["counts"][key] = value


def outcome(value):
    current = ACTIVE.get()
    if current is not None and value in {"preview", "applied", "no_changes"}:
        current.record["outcome"] = value


class CountingHTTP:
    def __init__(self, http, counters):
        self.http = http
        self.counters = counters
        self.attempts = 0

    def request(self, *args, **kwargs):
        self.counters["attempts"] += 1
        if self.attempts:
            self.counters["retries"] += 1
        self.attempts += 1
        return self.http.request(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.http, name)


def execute_measured(request, *, num_retries):
    current = ACTIVE.get()
    if current is None:
        return request.execute(num_retries=num_retries)
    operation = METHODS.get(getattr(request, "methodId", None), "other")
    counters = current.record["api"].setdefault(
        operation, {"calls": 0, "attempts": 0, "retries": 0, "seconds": 0.0}
    )
    counters["calls"] += 1
    started = time.monotonic()
    try:
        return request.execute(http=CountingHTTP(request.http, counters), num_retries=num_retries)
    finally:
        counters["seconds"] = round(counters["seconds"] + time.monotonic() - started, 6)


def summarize(path, stream=sys.stdout):
    groups = defaultdict(list)
    skipped = 0
    try:
        source = path.open()
    except FileNotFoundError:
        print("No local run metrics yet.", file=stream)
        return
    with source:
        for line in source:
            try:
                row = json.loads(line)
                if row["schema"] != 1:
                    raise ValueError("Unsupported schema")
                key = tuple(row[k] for k in ("algorithm", "version", "code_version", "outcome"))
                if not all(isinstance(value, str) for value in key):
                    raise ValueError("Invalid grouping")
                elapsed = row["elapsed_seconds"]
                if not isinstance(elapsed, (int, float)) or not 0 <= elapsed < float("inf"):
                    raise ValueError("Invalid duration")
                api = row["api"]
                totals = [
                    sum(item[field] for item in api.values()) for field in ("calls", "retries")
                ]
                if not all(type(value) is int and value >= 0 for value in totals):
                    raise ValueError("Invalid counters")
                api_seconds = sum(item["seconds"] for item in api.values())
                if not isinstance(api_seconds, (int, float)) or not 0 <= api_seconds < float("inf"):
                    raise ValueError("Invalid API duration")
                groups[key].append((elapsed, *totals, api_seconds))
            except (ValueError, KeyError, TypeError, AttributeError):
                skipped += 1
    print(
        "Algorithm / version / code / outcome | runs | median seconds | "
        "median API seconds | calls | retries",
        file=stream,
    )
    for key, rows in sorted(groups.items()):
        print(
            f"{' / '.join(key)} | {len(rows)} | "
            f"{statistics.median(row[0] for row in rows):.3f} | "
            f"{statistics.median(row[3] for row in rows):.3f} | "
            f"{sum(row[1] for row in rows)} | {sum(row[2] for row in rows)}",
            file=stream,
        )
    if skipped:
        print(f"Skipped {skipped} invalid or unsupported records.", file=stream)


def main():
    parser = argparse.ArgumentParser(description="Summarize local sender-sync run metrics.")
    parser.add_argument("path", nargs="?", type=Path, default=default_path())
    args = parser.parse_args()
    summarize(args.path)


if __name__ == "__main__":
    main()
