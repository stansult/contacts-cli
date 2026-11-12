"""Command-line interface with preview, interactive consent, and explicit apply."""

import argparse
import shlex
import sys
from pathlib import Path

from .auth import authorize, connect, default_credentials_path, default_token_path
from .core import addition_entry, contact_resource, make_plan, update_body
from .duplicate import READ_FIELDS, make_duplicate_plan, replacement_name
from .errors import InsufficientScopes, MissingToken, SyncError, WriteUnverified
from .metrics import ACTIVE, RunMetrics, counts, outcome
from .output import OperationalOutput, emit
from .progress import ScanProgress


def positive_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer in seconds") from exc
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer in seconds")
    return seconds


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Work with Google contacts.")
    commands = result.add_subparsers(dest="command", required=True)
    sync = commands.add_parser(
        "sender-sync",
        help="Preview or append Gmail label senders to an existing contact",
        description="Preview missing From addresses from a Gmail label for one existing contact.",
    )
    sync.add_argument(
        "--label", required=True, help="Exact Gmail label name (includes labeled Spam and Trash)"
    )
    sync.add_argument(
        "--contact", required=True, help="Google Contacts person URL or people/c… resource"
    )
    sync.add_argument(
        "--apply",
        action="store_true",
        help="Append missing emails without asking and verify the result",
    )
    duplicate = commands.add_parser("duplicate", help="Preview or create a copy of a contact")
    duplicate.add_argument(
        "--contact", required=True, help="Google Contacts URL or people/c… resource"
    )
    duplicate.add_argument("--name", help="Optional replacement name (stored as the given name)")
    duplicate.add_argument(
        "--apply", action="store_true", help="Create and verify a new contact without asking"
    )
    setup = commands.add_parser("authorize", help="Run explicit initial OAuth setup")
    setup.add_argument(
        "--credentials",
        type=Path,
        default=default_credentials_path(),
        help="Desktop OAuth client JSON, outside Git (default: %(default)s)",
    )
    setup.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorization URL without opening a browser",
    )
    for command in (sync, setup, duplicate):
        command.add_argument(
            "--auth-timeout",
            type=positive_seconds,
            default=300,
            metavar="SECONDS",
            help="Browser authorization wait in seconds (default: %(default)s)",
        )
        command.add_argument(
            "--token", type=Path, default=default_token_path(), help="Token path outside Git"
        )
    return result


def confirm_apply(question: str) -> bool:
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        return False
    sys.stdout.flush()
    emit(f"\n{question} [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def contact_heading(person):
    for field, key, label in (
        ("names", "displayName", "name"),
        ("organizations", "name", "company"),
    ):
        for entry in person.get(field, []):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return f"Contact: {f'{label}: {value.strip()}'!r} ({person['resourceName']})"
    return f"Contact: 'Unnamed' ({person['resourceName']})"


def run(args, api) -> int:
    resource = contact_resource(args.contact)
    with ScanProgress() as progress:
        progress("Reading contact")
        person = api.get_contact(resource)
        progress.finish_line()
        emit(contact_heading(person) + "\n", primary=False)

        def label_found(name):
            progress.finish_line()
            emit(f"Label: {name!r} (including Spam and Trash)\n", primary=False)

        counts(existing_entries=len(person.get("emailAddresses", [])))
        scan = api.scan(
            args.label,
            existing_emails=[entry["value"] for entry in person.get("emailAddresses", [])],
            progress=progress,
            label_found=label_found,
        )
    plan = make_plan(person, scan)
    counts(existing_entries=len(person.get("emailAddresses", [])), additions=len(plan.additions))
    emit(f"Existing email entries: {len(person.get('emailAddresses', []))}", primary=False)
    emit(f"\nProposed additions: {len(plan.additions)}")
    for address in plan.additions:
        label = addition_entry(plan, address).get("type")
        emit(f"  + {address}" + (f" — {label}" if label else ""), primary=False)
    for problem in scan.problems:
        emit(f"Warning: {problem}", file=sys.stderr)
    if scan.problems:
        raise SyncError("Preview is incomplete because of invalid From headers; no changes made.")
    # Check local limits in preview too, so users can review an actionable result.
    if plan.additions:
        update_body(plan)
    if not plan.additions:
        emit("No additions needed; no update made.")
        outcome("no_changes")
        return 0
    if args.apply or confirm_apply("Apply these additions?"):
        if api.apply(plan):
            emit(f"Saved and verified {len(plan.additions)} additions.")
            outcome("applied")
        else:
            emit("No additions needed; no update made.")
            outcome("no_changes")
    else:
        emit("Preview only; no changes made. Use --apply to save additions.")
        outcome("preview")
    return 0


def run_duplicate(args, api):
    person = api.get_contact(contact_resource(args.contact), READ_FIELDS)
    plan = make_duplicate_plan(person, api.people._rootDesc["schemas"], args.name)
    emit(contact_heading(person))
    if args.name is not None:
        emit(f"Replacement name: {args.name!r}", primary=False)
    for field, values in plan.body.items():
        emit(f"  {field}: {len(values)}", primary=False)
    emit(
        "Photo: " + ("copy custom photo" if plan.photo_url else "use default avatar"), primary=False
    )
    if args.apply or confirm_apply("Create this duplicate?"):
        location = api.duplicate(plan)
        emit(f"Created and verified: {location}")
    else:
        emit("Preview only; no changes made. Use --apply to create a new contact.")
    return 0


def connect_with_authorization(token: Path, timeout_seconds: int = 300):
    try:
        return connect(token)
    except (MissingToken, InsufficientScopes) as exc:
        reauthorize = isinstance(exc, InsufficientScopes)
        reason = (
            f"{exc}\nGmail read-only permission allows reading message bodies; "
            "this CLI requests only headers and labels."
            if reauthorize
            else "You're not authorized: no token file was found."
        )
        token_option = f" --token {shlex.quote(str(token))}"
        command = f"./contacts-cli authorize{token_option}"
        if timeout_seconds != 300:
            command += f" --auth-timeout {timeout_seconds}"
        emit(
            f"{reason}\n\n"
            "Options:\n"
            f"  - Authorize in your browser: {command}\n"
            f"    Requires the Desktop OAuth client file at {default_credentials_path()}.\n"
            f"  - Use a different client file: {command} --credentials /path/to/client.json\n"
            f"  - Open the URL manually: {command} --no-browser",
            file=sys.stderr,
        )
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            return None
        action = "Reauthorize" if reauthorize else "Authorize"
        emit(f"\n{action} now in your browser? [y/N] ", end="", file=sys.stderr, flush=True)
        try:
            answer = input().strip().casefold()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            emit("Authorization skipped; no changes made.", file=sys.stderr)
            return None
        authorize(
            default_credentials_path(), token, open_browser=True, timeout_seconds=timeout_seconds
        )
        emit("Authorization succeeded.\n", flush=True)
        return connect(token)


def main(argv=None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    with OperationalOutput():
        return execute_command(args)


def execute_command(args):
    if args.command != "sender-sync":
        return run_command(args)
    metrics = RunMetrics()
    token = ACTIVE.set(metrics)
    result = 1
    try:
        result = run_command(args)
        return result
    finally:
        ACTIVE.reset(token)
        metrics.finish(result)


def run_command(args):
    api = None
    try:
        if args.command == "authorize":
            authorize(
                args.credentials,
                args.token,
                open_browser=not args.no_browser,
                timeout_seconds=args.auth_timeout,
            )
            emit("Authorization saved. Future sync runs use the saved token without a browser.")
            return 0
        # Reject bad input before touching credentials or the network.
        contact_resource(args.contact)
        if args.command == "duplicate":
            replacement_name(args.name)
        api = connect_with_authorization(args.token, args.auth_timeout)
        if api is None:
            return 1
        api.write_started = False
        return run_duplicate(args, api) if args.command == "duplicate" else run(args, api)
    except WriteUnverified as exc:
        label = "Unverified copy" if args.command == "duplicate" else "Unverified update"
        emit(f"{label}: {exc}", file=sys.stderr)
        return 3
    except SyncError as exc:
        emit(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if api is not None and api.write_started:
            emit(
                "\nInterrupted. A contact write was started; "
                "inspect Google Contacts before retrying.",
                file=sys.stderr,
            )
        else:
            emit("\nInterrupted; no contact changes made.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
