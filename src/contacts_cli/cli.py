"""Command-line interface with preview, interactive consent, and explicit apply."""

import argparse
import shlex
import sys
from pathlib import Path

from .address_inputs import bare_address, edit_inputs, file_lines, split_entry
from .api import exclusion_query
from .auth import authorize, connect, default_credentials_path, default_token_path
from .contact_create import run_create
from .contact_inputs import load_contact_inputs, text_value
from .core import (
    addition_entry,
    address_key,
    contact_resource,
    email_update_body,
    make_plan,
    update_body,
)
from .custom_fields import run_custom_field
from .duplicate import READ_FIELDS, make_duplicate_plan, replacement_name
from .email_edit import make_edit_plan, verify_edit
from .error_logs import COMMAND as ERROR_LOG_COMMAND
from .errors import InsufficientScopes, MissingToken, SyncError, WriteUnverified
from .label_edit import run_label_edit
from .metrics import ACTIVE, RunMetrics, counts, outcome
from .output import OperationalOutput, email_rows, emit, emit_list
from .progress import ScanProgress


def positive_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer in seconds") from exc
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer in seconds")
    return seconds


def excluded_address(value):
    address = address_key(value)
    try:
        bare_address(address)
        exclusion_query({address})
    except SyncError as exc:
        raise argparse.ArgumentTypeError(
            "--exclude requires one supported email address, without a name or wildcard"
        ) from exc
    return address


def file_exclusions(paths):
    addresses = set()
    for line, origin in file_lines(paths):
        address, _ = split_entry(line)
        try:
            addresses.add(excluded_address(address))
        except argparse.ArgumentTypeError as exc:
            raise SyncError(
                f"{origin}: expected one supported email address "
                "(optionally followed by ' — Display Name')."
            ) from exc
    return addresses


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Work with Google contacts.")
    commands = result.add_subparsers(dest="command", required=True)
    creation = commands.add_parser("add-contact", help="Preview or create new contacts")
    creation.add_argument("--name", help="Full name for one contact")
    creation.add_argument(
        "--email", action="append", default=[], help="Email for that contact (repeatable)"
    )
    creation.add_argument(
        "--file", type=Path, help="UTF-8 JSON Person object or array; excludes inline fields"
    )
    creation.add_argument(
        "--label",
        action="append",
        default=[],
        help="Exact, case-sensitive contact label for all inputs; create if missing (repeatable)",
    )
    creation.add_argument(
        "--apply", action="store_true", help="Skip final confirmation; label choices still prompt"
    )
    duplicate = commands.add_parser("duplicate", help="Preview or create a copy of a contact")
    duplicate.add_argument(
        "--contact", required=True, help="Google Contacts URL or bare ID such as c123456789"
    )
    duplicate.add_argument("--name", help="Optional replacement name (stored as the given name)")
    duplicate.add_argument(
        "--apply", action="store_true", help="Create and verify a new contact without asking"
    )
    sync = commands.add_parser(
        "sender-sync",
        help="Preview or append Gmail label senders to an existing contact",
        description="Preview missing From addresses from a Gmail label for one existing contact.",
    )
    sync.add_argument(
        "--label", required=True, help="Exact Gmail label name (includes labeled Spam and Trash)"
    )
    sync.add_argument(
        "--contact", required=True, help="Google Contacts URL or bare ID such as c123456789"
    )
    sync.add_argument(
        "--apply",
        action="store_true",
        help="Append missing emails without asking and verify the result",
    )
    sync.add_argument(
        "--exclude",
        action="append",
        default=[],
        type=excluded_address,
        metavar="ADDRESS",
        help="Exclude one sender address for this run (repeat for multiple addresses)",
    )
    sync.add_argument(
        "--exclude-file",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="Read excluded senders from a UTF-8 file (repeat for multiple files)",
    )
    listing = commands.add_parser("list-email", help="List a contact's existing email entries")
    listing.add_argument(
        "--contact", required=True, help="Google Contacts URL or bare ID such as c123456789"
    )
    editing = []
    for action in ("add", "remove"):
        command = commands.add_parser(
            f"{action}-email", help=f"{action.title()} contact email entries"
        )
        command.add_argument(
            "--contact",
            required=True,
            help="Google Contacts URL or bare ID such as c123456789",
        )
        inputs = command.add_argument_group("Email inputs (at least one required)")
        inputs.add_argument(
            f"--{action}",
            action="append",
            default=[],
            metavar="ADDRESS",
            help="Email address, optionally followed by ' — Label' (repeatable)",
        )
        inputs.add_argument(
            f"--{action}-file",
            action="append",
            default=[],
            type=Path,
            metavar="PATH",
            help="UTF-8 address list (repeatable; combines with individual addresses)",
        )
        command.add_argument(
            "--apply", action="store_true", help="Save without the final confirmation"
        )
        if action == "add":
            command.add_argument(
                "--replace-existing",
                action="store_true",
                help="Approve label changes/removals and consolidate matching duplicate entries",
            )
        editing.append(command)
    label_commands = []
    for action in ("add", "remove"):
        labeling = commands.add_parser(
            f"{action}-label", help=f"{action.title()} labels on an existing contact"
        )
        labeling.add_argument("--contact", required=True, help="Google Contacts URL or bare ID")
        labeling.add_argument(
            "--label",
            required=True,
            action="append",
            help="Exact, case-sensitive contact label (repeatable)",
        )
        labeling.add_argument(
            "--apply",
            action="store_true",
            help="Skip final confirmation; label choices still prompt",
        )
        label_commands.append(labeling)
    custom_commands = []
    for action in ("add", "remove"):
        custom = commands.add_parser(
            f"{action}-custom-field", help=f"{action.title()} custom fields on a contact"
        )
        custom.add_argument("--contact", required=True, help="Google Contacts URL or bare ID")
        custom.add_argument("--key", required=True, help="Exact, case-sensitive custom field name")
        custom.add_argument(
            "--value",
            required=action == "add",
            help=(
                "Exact, case-sensitive value to add"
                if action == "add"
                else "Exact, case-sensitive value; omit to remove all entries with this key"
            ),
        )
        custom.add_argument("--apply", action="store_true", help="Save without final confirmation")
        custom_commands.append(custom)
    validation = commands.add_parser(
        "validate-contact", help="Validate a contact JSON file locally without Google access"
    )
    validation.add_argument(
        "--file", type=Path, required=True, help="UTF-8 JSON Person object or array"
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
    for command in (
        result,
        sync,
        setup,
        duplicate,
        listing,
        creation,
        *label_commands,
        *custom_commands,
        validation,
        *editing,
    ):
        top_level = command is result
        if not top_level:
            command.epilog = "See contacts-cli --help for global options."
        command.add_argument(
            "--auth-timeout",
            type=positive_seconds,
            default=300 if top_level else argparse.SUPPRESS,
            metavar="SECONDS",
            help=argparse.SUPPRESS,
        )
        command.add_argument(
            "--token",
            type=Path,
            default=default_token_path() if top_level else argparse.SUPPRESS,
            help="Token path outside Git" if top_level else argparse.SUPPRESS,
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
    contact_id = person["resourceName"].removeprefix("people/")
    for field, key, label in (
        ("names", "displayName", "name"),
        ("organizations", "name", "company"),
    ):
        for entry in person.get(field, []):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return f"Contact: {f'{label}: {value.strip()}'!r} ({contact_id})"
    return f"Contact: 'Unnamed' ({contact_id})"


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
            excluded_emails=args.exclude,
            progress=progress,
            label_found=label_found,
        )
    plan = make_plan(person, scan)
    counts(existing_entries=len(person.get("emailAddresses", [])), additions=len(plan.additions))
    emit(f"Existing email entries: {len(person.get('emailAddresses', []))}", primary=False)
    emit_list(
        "\nAdding" if args.apply else "\nProposed additions",
        email_rows([addition_entry(plan, address) for address in plan.additions]),
    )
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


def run_list_email(args, api):
    emit("Reading contact…", file=sys.stderr)
    person = api.get_contact(contact_resource(args.contact))
    emit(contact_heading(person) + "\n", primary=False)
    emit_list("Email addresses", email_rows(person.get("emailAddresses", [])))
    return 0


def run_email_edit(args, api):
    emit("Reading contact…", file=sys.stderr)
    person = api.get_contact(contact_resource(args.contact))
    emit(contact_heading(person) + "\n", primary=False)
    existing = person.get("emailAddresses", [])
    emit(f"Existing email entries: {len(existing)}", primary=False)
    emit("", primary=False)
    interactive = all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr))
    all_choice = None

    def resolve(address, matches, label):
        nonlocal all_choice
        if args.replace_existing:
            return True
        if args.apply or not interactive:
            return False
        if all_choice is not None:
            return all_choice
        emit_list("Existing matches", email_rows(matches))
        while True:
            emit(
                f"Replace with one entry labeled {label!r}?"
                if label
                else "Replace with one entry with no label?",
                file=sys.stderr,
            )
            emit(
                "[y] Replace  [n] Keep  [a] Replace all conflicts  [s] Keep all conflicts [n]: ",
                file=sys.stderr,
                end="",
                primary=False,
            )
            try:
                choice = input().strip().casefold()
            except EOFError:
                all_choice = False
                return False
            if choice in {"a", "s"}:
                all_choice = choice == "a"
                return all_choice
            if choice in {"", "n", "no", "y", "yes"}:
                return choice in {"y", "yes"}
            emit("Choose y, n, a, or s.", file=sys.stderr)

    plan = make_edit_plan(
        person, args.entries, remove=args.command == "remove-email", resolve=resolve
    )
    if args.command == "remove-email":
        addresses = len(plan.changes)
        emit_list(
            "Removing" if args.apply else "Proposed removals",
            email_rows(plan.removed),
            suffix=f" ({addresses} {'address' if addresses == 1 else 'addresses'})",
        )
    else:
        emit_list("Adding" if args.apply else "Proposed additions", email_rows(plan.added))
        if plan.updates:
            emit_list(
                "Updating" if args.apply else "Proposed updates",
                enumerate(plan.updates, 1),
                unit=("change", "changes"),
            )
    if plan.absent:
        emit_list("Not found", enumerate(plan.absent, 1), unit=("address", "addresses"))
    if plan.skipped:
        emit_list("Skipped conflicts", enumerate(plan.skipped, 1), unit=("conflict", "conflicts"))
    emit(f"Remaining email entries: {len(plan.emails)}", primary=False)
    if not plan.changes:
        emit("No changes selected; no update made.")
        return 0
    body = email_update_body(plan.person, plan.emails)
    question = (
        "Remove these email entries?"
        if args.command == "remove-email"
        else "Apply these email changes?"
    )
    if args.apply or confirm_apply(question):
        api.apply_email_change(plan.person, body, lambda saved: verify_edit(plan, saved))
        emit(f"Saved and verified {len(plan.changes)} change(s).")
    else:
        emit("Preview only; no changes made. Use --apply to save changes.")
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
    argv = list(sys.argv[1:] if argv is None else argv)
    # Accept forgiving spellings without adding plural forms to help or usage.
    aliases = {f"{action}-emails": f"{action}-email" for action in ("add", "remove", "list")}
    aliases.update(
        {f"{action}-custom-fields": f"{action}-custom-field" for action in ("add", "remove")}
    )
    aliases["add-contacts"] = "add-contact"
    aliases["add-labels"] = "add-label"
    aliases["remove-labels"] = "remove-label"
    aliases["validate-contacts"] = "validate-contact"
    index = 0
    while index < len(argv):
        option = argv[index].split("=", 1)[0]
        if option.startswith("--") and any(
            name.startswith(option) for name in ("--token", "--auth-timeout")
        ):
            index += 1 if "=" in argv[index] else 2
            continue
        argv[index] = aliases.get(argv[index], argv[index])
        break
    args = arguments.parse_args(argv)
    if args.command in {"add-email", "remove-email"}:
        action = args.command.split("-")[0]
        if not getattr(args, action) and not getattr(args, action + "_file"):
            arguments.error(f"{args.command} requires --{action} or --{action}-file")
    if args.command == "add-contact":
        if args.file is not None and (args.name is not None or args.email):
            arguments.error("--file cannot be combined with --name or --email")
        if args.file is None and args.name is None and not args.email:
            arguments.error("add-contact requires --name, --email, or --file")
    token = ERROR_LOG_COMMAND.set(args.command)
    try:
        with OperationalOutput():
            return execute_command(args)
    finally:
        ERROR_LOG_COMMAND.reset(token)


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
        if args.command == "validate-contact":
            contacts = load_contact_inputs(file=args.file)
            emit(
                f"Valid: {len(contacts)} contact{'s' if len(contacts) != 1 else ''}. "
                "No Google access or changes."
            )
            return 0
        if args.command == "add-contact":
            contacts = load_contact_inputs(
                name=args.name, emails=args.email, file=args.file, labels=args.label
            )
            api = connect_with_authorization(args.token, args.auth_timeout)
            if api is None:
                return 1
            api.write_started = False
            return run_create(args, api, contacts, confirm_apply)
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
        if args.command in {"add-custom-field", "remove-custom-field"}:
            text_value(args.key, "--key")
            if args.value is not None:
                text_value(args.value, "--value")
        elif args.command in {"add-label", "remove-label"}:
            for number, label in enumerate(args.label, 1):
                text_value(label, f"--label #{number}")
        elif args.command == "duplicate":
            replacement_name(args.name)
        elif args.command == "sender-sync":
            args.exclude = sorted(set(args.exclude) | file_exclusions(args.exclude_file))
            exclusion_query(set(args.exclude))
        elif args.command in {"add-email", "remove-email"}:
            action = args.command.split("-")[0]
            args.entries = edit_inputs(
                getattr(args, action), getattr(args, action + "_file"), f"--{action}"
            )
        api = connect_with_authorization(args.token, args.auth_timeout)
        if api is None:
            return 1
        api.write_started = False
        if args.command in {"add-custom-field", "remove-custom-field"}:
            return run_custom_field(args, api, confirm_apply, contact_heading)
        if args.command in {"add-label", "remove-label"}:
            return run_label_edit(args, api, confirm_apply, contact_heading)
        if args.command == "list-email":
            return run_list_email(args, api)
        if args.command in {"add-email", "remove-email"}:
            return run_email_edit(args, api)
        return run_duplicate(args, api) if args.command == "duplicate" else run(args, api)
    except WriteUnverified as exc:
        label = {"duplicate": "Unverified copy", "add-contact": "Unverified creation"}.get(
            args.command, "Unverified update"
        )
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
