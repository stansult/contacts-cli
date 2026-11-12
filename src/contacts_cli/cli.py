"""Command-line interface with preview, interactive consent, and explicit apply."""

import argparse
import shlex
import sys
from pathlib import Path

from .auth import authorize, connect, default_credentials_path, default_token_path
from .core import contact_resource, make_plan, update_body
from .duplicate import READ_FIELDS, make_duplicate_plan, replacement_name
from .errors import MissingToken, SyncError, WriteUnverified


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
    print(f"\n{question} [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def run(args, api) -> int:
    resource = contact_resource(args.contact)
    person = api.get_contact(resource)
    scan = api.scan(args.label)
    plan = make_plan(person, scan)
    names = person.get("names", [])
    name = names[0].get("displayName", "Unnamed contact") if names else "Unnamed contact"
    print(f"Contact: {name!r} ({person['resourceName']})")
    print(f"Label: {args.label!r} (including Spam and Trash)")
    print(f"Scanned messages: {scan.messages}")
    print(f"Unique senders: {len(scan.senders)}")
    print(f"Existing email entries: {len(person.get('emailAddresses', []))}")
    print(f"Proposed additions: {len(plan.additions)}")
    for address in plan.additions:
        print(f"  + {address}")
    for problem in scan.problems:
        print(f"Warning: {problem}", file=sys.stderr)
    if scan.problems:
        raise SyncError("Preview is incomplete because of invalid From headers; no changes made.")
    # Check local limits in preview too, so users can review an actionable result.
    if plan.additions:
        update_body(plan)
    if not plan.additions:
        print("No additions needed; no update made.")
        return 0
    if args.apply or confirm_apply("Apply these additions?"):
        if api.apply(plan):
            print(f"Saved and verified {len(plan.additions)} additions.")
        else:
            print("No additions needed; no update made.")
    else:
        print("Preview only; no changes made. Use --apply to save additions.")
    return 0


def run_duplicate(args, api):
    person = api.get_contact(contact_resource(args.contact), READ_FIELDS)
    plan = make_duplicate_plan(person, api.people._rootDesc["schemas"], args.name)
    names = person.get("names", [])
    name = names[0].get("displayName", "Unnamed contact") if names else "Unnamed contact"
    print(f"Source contact: {name!r} ({person['resourceName']})")
    if args.name is not None:
        print(f"Replacement name: {args.name!r}")
    for field, values in plan.body.items():
        print(f"  {field}: {len(values)}")
    print("Photo: " + ("copy custom photo" if plan.photo_url else "use default avatar"))
    if args.apply or confirm_apply("Create this duplicate?"):
        location = api.duplicate(plan)
        print(f"Created and verified: {location}")
    else:
        print("Preview only; no changes made. Use --apply to create a new contact.")
    return 0


def connect_with_authorization(token: Path, timeout_seconds: int = 300):
    try:
        return connect(token)
    except MissingToken:
        token_option = f" --token {shlex.quote(str(token))}"
        command = f"./contacts-cli authorize{token_option}"
        if timeout_seconds != 300:
            command += f" --auth-timeout {timeout_seconds}"
        print(
            "You're not authorized: no token file was found.\n\n"
            "Options:\n"
            f"  - Authorize in your browser: {command}\n"
            f"    Requires the Desktop OAuth client file at {default_credentials_path()}.\n"
            f"  - Use a different client file: {command} --credentials /path/to/client.json\n"
            f"  - Open the URL manually: {command} --no-browser",
            file=sys.stderr,
        )
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            return None
        print("\nAuthorize now in your browser? [y/N] ", end="", file=sys.stderr, flush=True)
        try:
            answer = input().strip().casefold()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Authorization skipped; no changes made.", file=sys.stderr)
            return None
        authorize(
            default_credentials_path(), token, open_browser=True, timeout_seconds=timeout_seconds
        )
        print("Authorization succeeded.\n", flush=True)
        return connect(token)


def main(argv=None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    try:
        if args.command == "authorize":
            authorize(
                args.credentials,
                args.token,
                open_browser=not args.no_browser,
                timeout_seconds=args.auth_timeout,
            )
            print("Authorization saved. Future sync runs use the saved token without a browser.")
            return 0
        # Reject bad input before touching credentials or the network.
        contact_resource(args.contact)
        if args.command == "duplicate":
            replacement_name(args.name)
        api = connect_with_authorization(args.token, args.auth_timeout)
        if api is None:
            return 1
        return run_duplicate(args, api) if args.command == "duplicate" else run(args, api)
    except WriteUnverified as exc:
        label = "Unverified copy" if args.command == "duplicate" else "Unverified update"
        print(f"{label}: {exc}", file=sys.stderr)
        return 3
    except SyncError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "Interrupted. If a write was in progress, inspect Google Contacts before retrying.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    sys.exit(main())
