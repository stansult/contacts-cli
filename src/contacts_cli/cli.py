"""Command-line interface, with a preview default and explicit write switch."""

import argparse
import sys
from pathlib import Path

from .auth import authorize, connect, default_credentials_path, default_token_path
from .core import contact_resource, make_plan, update_body
from .errors import SyncError, WriteUnverified


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
        "--apply", action="store_true", help="Append missing emails and verify the result"
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
    for command in (sync, setup):
        command.add_argument(
            "--token", type=Path, default=default_token_path(), help="Token path outside Git"
        )
    return result


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
    if args.apply:
        if api.apply(plan):
            print(f"Saved and verified {len(plan.additions)} additions.")
        else:
            print("No additions needed; no update made.")
    else:
        print("Preview only; no changes made. Use --apply to save additions.")
    return 0


def main(argv=None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    try:
        if args.command == "authorize":
            authorize(args.credentials, args.token, open_browser=not args.no_browser)
            print("Authorization saved. Future sync runs use the saved token without a browser.")
            return 0
        # Reject bad input before touching credentials or the network.
        contact_resource(args.contact)
        return run(args, connect(args.token))
    except WriteUnverified as exc:
        print(f"Unverified update: {exc}", file=sys.stderr)
        return 3
    except SyncError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. If an update was in progress, inspect a new preview.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
