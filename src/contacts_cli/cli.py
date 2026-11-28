"""Command-line interface with preview, interactive consent, and explicit apply."""

import argparse
import shlex
import sys
from dataclasses import replace
from pathlib import Path

from .address_inputs import address_pattern_input, edit_inputs, file_lines, split_entry
from .api import exclusion_query
from .auth import authorize, connect, default_credentials_path, default_token_path
from .contact_create import LabelChoiceCancelled, run_create
from .contact_inputs import load_contact_inputs, text_value
from .contact_listing import run_list_contacts
from .core import (
    addition_entry,
    address_key,
    contact_resource,
    make_plan,
    update_body,
)
from .custom_fields import run_custom_field
from .duplicate import READ_FIELDS, make_duplicate_plan, replacement_fields
from .email_edit import make_duplicate_removal_plan, make_edit_plan
from .email_edit_ui import finish_email_edit
from .error_logs import COMMAND as ERROR_LOG_COMMAND
from .error_logs import TRACE, RunDiagnostics
from .errors import (
    InsufficientScopes,
    MissingToken,
    ReauthorizationRequired,
    SyncError,
    WriteUnverified,
)
from .label_edit import run_label_edit, run_list_labels
from .metrics import ACTIVE, RunMetrics, counts, outcome
from .output import OperationalOutput, email_rows, emit, emit_list
from .progress import ScanProgress, StageProgress
from .selection import review_address_additions
from .sender_criteria import extract_search_criteria
from .timing import CommandTimer, read_input
from .url_email_add import run_url_add
from .web_emails import fetch_addresses, validate_url


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
        address_pattern_input(address)
        if "*" not in address:
            exclusion_query({address})
    except SyncError as exc:
        raise argparse.ArgumentTypeError(
            "--exclude requires one supported email address or * pattern, "
            "without a name or other wildcards"
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
                f"{origin}: expected one supported email address or * pattern "
                "(optionally followed by ' - Display Name')."
            ) from exc
    return addresses


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Work with Google contacts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Use contacts-cli COMMAND --help for options.\n"
        "Guide: https://github.com/stansult/contacts-cli/blob/main/docs/command-reference.md",
    )
    commands = result.add_subparsers(dest="command", required=True)
    contact_listing = commands.add_parser(
        "list-contact",
        help="Find saved contacts by identity, company, or label",
        description="List every matching contact without selection or changes.\n"
        "Names contain the search text; phones end with the supplied digits.\n"
        "Use --exact for a complete name or phone number, and complete company.\n"
        "Filters combine with AND. --search combines only with --company and --label.",
    )
    contact_listing.add_argument(
        "--search",
        help="Name text, complete email, phone number or suffix, contact ID, or URL",
    )
    for option, description in (
        ("name", "Name contains text; --exact requires the complete name"),
        ("email", "Complete email address, ignoring case"),
        ("phone", "Phone number suffix; --exact requires all base-number digits"),
        ("company", "Company contains text; --exact requires the complete company"),
        ("label", "Complete existing contact label; case differences offer a choice"),
    ):
        contact_listing.add_argument(f"--{option}", help=description)
    contact_listing.add_argument(
        "--exact",
        action="store_true",
        help="Match the complete name or phone number (including country code), and company",
    )
    creation = commands.add_parser(
        "add-contact",
        help="Preview or create new contacts",
        description=(
            "Create contacts from inline fields or a JSON file.\n"
            "Preview and select contacts before saving.\nPossible duplicates offer "
            "skip, merge, or create separately.\n"
            "A single-part name alone does not suggest a duplicate."
            "\nLabel-only matches use compact numbered review."
        ),
    )
    creation.add_argument(
        "--name", help="Full name for Google to parse; excludes explicit name parts"
    )
    creation.add_argument("--first-name", help="Explicit first name; may be used with --last-name")
    creation.add_argument("--last-name", help="Explicit last name; may be used with --first-name")
    creation.add_argument(
        "--email", action="append", default=[], help="Email for that contact (repeatable)"
    )
    creation.add_argument(
        "--file",
        type=Path,
        help=(
            "UTF-8 JSON Person object or array; choose contacts interactively; "
            "excludes inline fields"
        ),
    )
    creation.add_argument(
        "--label",
        action="append",
        default=[],
        help=(
            "Exact, case-sensitive label for every selected contact; create if missing (repeatable)"
        ),
    )
    creation.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Process all inputs without final confirmation; "
            "duplicate and label choices still prompt"
        ),
    )
    duplicate = commands.add_parser("duplicate", help="Preview or create a copy of a contact")
    duplicate.add_argument(
        "--contact",
        required=True,
        help="Contact URL, ID, full name, email, or complete phone number",
    )
    for option, label in (
        ("name", "name"),
        ("email", "email addresses"),
        ("phone", "phone numbers"),
    ):
        overrides = duplicate.add_mutually_exclusive_group()
        if option == "name":
            overrides.add_argument(
                "--name", help="Replace the whole name with a full name for Google to parse"
            )
        else:
            overrides.add_argument(
                f"--{option}",
                action="append",
                help=f"Replace all {label} with these unlabeled values (repeatable)",
            )
        overrides.add_argument(
            f"--clear-{option}", action="store_true", help=f"Leave the duplicate's {label} empty"
        )
    duplicate.add_argument(
        "--first-name",
        help="Replace the whole name using explicit parts; omit last name to leave it empty",
    )
    duplicate.add_argument(
        "--last-name",
        help="Replace the whole name using explicit parts; omit first name to leave it empty",
    )
    duplicate.add_argument(
        "--no-photo", action="store_true", help="Skip the source photo; use a default avatar"
    )
    duplicate.add_argument(
        "--apply", action="store_true", help="Create and verify a new contact without asking"
    )
    sync = commands.add_parser(
        "sender-sync",
        help="Preview or append Gmail senders to an existing contact",
        description=(
            "Preview missing From addresses from a Gmail label or search for one contact.\n"
            "Select addresses and confirm before saving."
        ),
    )
    sync.add_argument(
        "--diagnostics", action="store_true", help="Save detailed local API run diagnostics"
    )
    source = sync.add_mutually_exclusive_group(required=True)
    source.add_argument("--label", help="Find sender addresses in messages with this Gmail label")
    source.add_argument(
        "--search", help="Find sender addresses in messages matching this Gmail search"
    )
    sync.add_argument(
        "--contact",
        required=True,
        help="Contact URL, ID, full name, email, or complete phone number",
    )
    sync.add_argument(
        "--apply",
        action="store_true",
        help="Add all eligible addresses without asking; label choices still prompt",
    )
    sync.add_argument(
        "--exclude-other",
        action="store_true",
        help="Only add addresses matching from:/to: criteria in --search",
    )
    sync.add_argument(
        "--exclude",
        action="append",
        default=[],
        type=excluded_address,
        metavar="ADDRESS_OR_PATTERN",
        help=(
            "Exclude a sender or quoted * pattern; * matches zero or more characters "
            "across the whole address, ignoring case (repeatable)"
        ),
    )
    sync.add_argument(
        "--exclude-file",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help=(
            "Read excluded addresses or * patterns, one per UTF-8 line; "
            "no shell quotes (repeatable)"
        ),
    )
    listing = commands.add_parser("list-email", help="List a contact's existing email entries")
    listing.add_argument(
        "--contact",
        required=True,
        help="Contact URL, ID, full name, email, or complete phone number",
    )
    editing = []
    for action in ("add", "remove"):
        command = commands.add_parser(
            f"{action}-email",
            help=f"{action.title()} contact email entries",
            description=(
                "Select individual matching email entries, including duplicates. "
                "--apply removes all proposed entries."
                if action == "remove"
                else None
            ),
        )
        command.add_argument(
            "--contact",
            required=True,
            help="Contact URL, ID, full name, email, or complete phone number",
        )
        inputs = command.add_argument_group("Email inputs (at least one required)")
        if action == "remove":
            inputs.add_argument(
                "--duplicates",
                action="store_true",
                help="Remove extra copies of repeated addresses; keep the primary or first entry",
            )
        inputs.add_argument(
            f"--{action}",
            action="append",
            default=[],
            metavar="ADDRESS",
            help=(
                "Email address or quoted * pattern; * matches zero or more characters, "
                "case-insensitively across the whole address (repeatable; e.g. '*@example.com')"
                if action == "remove"
                else "Email address, optionally followed by ' - Label' (repeatable)"
            ),
        )
        inputs.add_argument(
            f"--{action}-file",
            action="append",
            default=[],
            type=Path,
            metavar="PATH",
            help=(
                "UTF-8 addresses or * patterns, one per line without quotes (repeatable)"
                if action == "remove"
                else "UTF-8 address list (repeatable; combines with individual addresses)"
            ),
        )
        command.add_argument(
            "--apply",
            action="store_true",
            help="Save all eligible changes without selection or final confirmation",
        )
        if action == "add":
            inputs.add_argument(
                "--from-url",
                metavar="URL",
                help="Extract unlabeled emails from one HTML page; preserve existing entries",
            )
            command.add_argument(
                "--replace-existing",
                action="store_true",
                help="Approve label changes/removals and consolidate matching duplicate entries",
            )
        editing.append(command)
    phone_commands = []
    for action in ("list", "remove", "format"):
        command = commands.add_parser(
            f"{action}-phone",
            help={
                "list": "List phone entries",
                "remove": "Remove duplicate phone entries",
                "format": "Standardize phone formatting",
            }[action],
            description=(
                "Preview readable international formatting with ext. N for extensions.\n"
                "Select phone changes across contacts, then confirm once.\n"
                "Ambiguous numbers stay unchanged."
                if action == "format"
                else "Phone duplicates ignore formatting and use Google's canonical number "
                "when available.\nDifferent extensions stay separate; no country is guessed."
            ),
        )
        command.add_argument(
            "--contact",
            required=action != "format",
            action="append" if action == "format" else "store",
            help="Contact URL, ID, full name, email, or complete phone number"
            + (" (repeatable; combines with --contact-file)" if action == "format" else ""),
        )
        if action == "format":
            command.add_argument(
                "--contact-file",
                type=Path,
                help="UTF-8 identifiers, one per line; combines with --contact",
            )
        if action == "remove":
            command.add_argument(
                "--duplicates",
                action="store_true",
                required=True,
                help="Keep the primary or first entry per number; select extra entries to remove",
            )
        if action in {"remove", "format"}:
            command.add_argument(
                "--apply",
                action="store_true",
                help="Save all proposed changes without final confirmation"
                + ("; ambiguous contacts still prompt" if action == "format" else ""),
            )
        phone_commands.append(command)
    label_listing = commands.add_parser(
        "list-label", help="List account labels with contact counts, or labels on one contact"
    )
    label_listing.add_argument(
        "--contact",
        help="Contact URL, ID, full name, email, or complete phone number; "
        "omit for all account labels with contact counts",
    )
    label_commands = [label_listing]
    for action in ("add", "remove"):
        labeling = commands.add_parser(
            f"{action}-label",
            help=(
                "Create labels or add them to a contact"
                if action == "add"
                else "Remove labels from a contact"
            ),
            description=(
                "Choose all or numbers/ranges from matching labels, then confirm removal."
                if action == "remove"
                else (
                    "Add labels to saved contacts identified inline or in a file.\n"
                    "Choose among multiple matches; unmatched identifiers are skipped.\n"
                    "Without contact inputs, create account labels."
                )
            ),
        )
        targets = labeling.add_mutually_exclusive_group() if action == "add" else labeling
        targets.add_argument(
            "--contact",
            required=action == "remove",
            help=(
                "Contact URL, ID, full name, email, or phone; omit to create account labels"
                if action == "add"
                else "Contact URL, ID, full name, email, or complete phone number"
            ),
        )
        if action == "add":
            targets.add_argument(
                "--contact-file",
                help="UTF-8 file: one contact identifier per line; blanks and # comments ignored",
            )
        labeling.add_argument(
            "--label",
            required=True,
            action="append",
            help=(
                "Label name or quoted * pattern; * matches zero or more characters, "
                "ignoring case across the whole name (repeatable)"
                if action == "remove"
                else "Exact, case-sensitive contact label (repeatable)"
            ),
        )
        labeling.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Remove all matching user labels on this contact without selection or confirmation"
                if action == "remove"
                else "Apply to all resolved contacts; "
                "ambiguous contacts and label choices still require resolution"
            ),
        )
        label_commands.append(labeling)
    custom_commands = []
    for action in ("add", "remove"):
        custom = commands.add_parser(
            f"{action}-custom-field",
            help=f"{action.title()} custom fields on a contact",
            description=(
                "Choose all or numbers/ranges from exact and case-different matches;\n"
                "identical duplicates are removed together."
                if action == "remove"
                else None
            ),
        )
        custom.add_argument(
            "--contact",
            required=True,
            help="Contact URL, ID, full name, email, or complete phone number",
        )
        if action == "add":
            custom.add_argument(
                "--field",
                nargs=2,
                action="append",
                required=True,
                metavar=("KEY", "VALUE"),
                help="Nonblank key and value to add (repeatable); choose new pairs before saving",
            )
        else:
            custom.add_argument(
                "--key", required=True, help="Custom field name; case variants also offered"
            )
            custom.add_argument(
                "--value",
                help="Value, including case variants; omit to offer all values for the key",
            )
        custom.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Remove all matches, including case variants, without selection or confirmation"
                if action == "remove"
                else "Add all new pairs without selection or final confirmation"
            ),
        )
        custom_commands.append(custom)
    validation = commands.add_parser(
        "validate-contact", help="Validate a contact JSON file locally without Google access"
    )
    validation.add_argument(
        "--file", type=Path, required=True, help="UTF-8 JSON Person object or array"
    )
    setup = commands.add_parser("authorize", help="Authorize or reauthorize Google access")
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
    reference_sections = {
        contact_listing: "list-contact",
        creation: "add-contact",
        duplicate: "duplicate-a-contact",
        sync: "sender-sync-preview-and-apply",
        listing: "list-email",
        **dict.fromkeys(phone_commands[:2], "list-phone-and-remove-phone"),
        phone_commands[2]: "format-phone",
        **dict.fromkeys(editing, "add-email-and-remove-email"),
        **dict(zip(label_commands, ("list-label", "add-label", "remove-label"), strict=True)),
        **dict.fromkeys(custom_commands, "add-custom-field-and-remove-custom-field"),
        validation: "validate-contact",
        setup: "authorization",
    }
    for command in (
        result,
        contact_listing,
        sync,
        setup,
        duplicate,
        listing,
        creation,
        *phone_commands,
        *label_commands,
        *custom_commands,
        validation,
        *editing,
    ):
        top_level = command is result
        if not top_level:
            command.formatter_class = argparse.RawDescriptionHelpFormatter
            command.epilog = (
                "See contacts-cli --help for global options.\n"
                "Details: https://github.com/stansult/contacts-cli/blob/main/"
                f"docs/command-reference.md#{reference_sections[command]}"
            )
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
        return read_input().strip().casefold() in {"y", "yes"}
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


def choose_gmail_label(name, similar):
    spellings = ", ".join(repr(label) for label in similar)
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        raise SyncError(
            f"Gmail label {name!r} differs only by case from {spellings}. "
            "Use an exact spelling with --label, or run interactively to choose. "
            "--apply does not resolve label choices; no changes made."
        )
    emit(f"Gmail label {name!r} differs only by case from {spellings}.")
    if len(similar) == 1:
        while True:
            emit(
                f"Use existing Gmail label {similar[0]!r}? [Y/n] ",
                file=sys.stderr,
                end="",
                flush=True,
            )
            try:
                answer = read_input().strip().casefold()
            except EOFError:
                raise LabelChoiceCancelled from None
            if answer in {"", "y", "yes"}:
                return similar[0]
            if answer in {"n", "no"}:
                raise LabelChoiceCancelled
            emit("Enter y or n.", file=sys.stderr)
    options = [f"Use existing Gmail label {label!r}" for label in similar] + ["Cancel command"]
    emit_list("Options", enumerate(options, 1), unit=("option", "options"))
    while True:
        emit(f"Choose 1–{len(options)} (Enter = 1): ", file=sys.stderr, end="", flush=True)
        try:
            answer = read_input().strip() or "1"
        except EOFError:
            raise LabelChoiceCancelled from None
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            choice = int(answer)
            if choice == len(options):
                raise LabelChoiceCancelled
            return similar[choice - 1]
        emit(f"Enter a number from 1 to {len(options)}.", file=sys.stderr)


def confirm_exclude_other():
    while True:
        emit("\nExclude Other senders? [y/N] ", file=sys.stderr, end="", flush=True)
        try:
            answer = read_input().strip().casefold()
        except EOFError:
            raise LabelChoiceCancelled from None
        if answer in {"", "n", "no"}:
            return False
        if answer in {"y", "yes"}:
            return True
        emit("Enter y or n.", file=sys.stderr)


def run(args, api) -> int:
    resource = contact_resource(args.contact)
    criteria = extract_search_criteria(args.search)

    with ScanProgress() as progress:
        progress("Reading contact")
        person = api.get_contact(resource)
        progress.finish_line()
        emit(contact_heading(person) + "\n", primary=False)

        def label_found(name):
            progress.finish_line()
            emit(f"Label: {name!r} (including Spam and Trash)\n", primary=False)

        def choose_label(name, similar):
            progress.finish_line()
            return choose_gmail_label(name, similar)

        if args.search is not None:
            emit(f"Search: {args.search!r} (including Spam and Trash)\n", primary=False)
        counts(existing_entries=len(person.get("emailAddresses", [])))
        scan = api.scan(
            args.label,
            search=args.search,
            existing_emails=[entry["value"] for entry in person.get("emailAddresses", [])],
            excluded_emails=args.exclude,
            progress=progress,
            label_found=label_found,
            choose_label=choose_label,
        )
    plan = make_plan(person, scan)
    counts(existing_entries=len(person.get("emailAddresses", [])), additions=len(plan.additions))
    emit(f"Existing email entries: {len(person.get('emailAddresses', []))}", primary=False)
    entries = [addition_entry(plan, address) for address in plan.additions]
    heading = "\nAdding" if args.apply else "\nProposed additions"
    interactive = all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr))
    grouped = bool(criteria and entries)
    exclude_other = args.exclude_other
    if grouped:
        matching, other = criteria.partition(entries)
        rows = email_rows(matching + other)
        total = len(matching) if exclude_other else len(entries)
        emit(f"{heading}: {total} {'entry' if total == 1 else 'entries'}")
        emit("", primary=False)
        emit_list(
            "Matching address criteria",
            rows[: len(matching)],
            unit=("address", "addresses"),
            primary=False,
        )
        emit("", primary=False)
        emit_list(
            "Other senders (excluded)" if exclude_other else "Other senders",
            rows[len(matching) :],
            unit=("address", "addresses"),
            primary=False,
        )
    else:
        rows = email_rows(entries)
        emit_list(
            heading,
            rows,
            note=(
                "Ungrouped: no full addresses or domains in from:/to: criteria."
                if args.search is not None and entries
                else None
            ),
        )
    for problem in scan.problems:
        emit(f"Warning: {problem}", file=sys.stderr)
    if scan.problems:
        emit(
            "Skipped messages contributed no addresses; valid senders can still be added.",
            file=sys.stderr,
        )
    if grouped:
        if other and interactive and not args.apply and not exclude_other:
            exclude_other = confirm_exclude_other()
        if exclude_other:
            rows = rows[: len(matching)]
            plan = replace(plan, additions=tuple(entry["value"] for entry in matching))
        selected = len(plan.additions)
        excluded = len(other) if exclude_other else 0
        emit("", primary=False)
        if selected:
            group = (
                "only Matching address criteria"
                if exclude_other
                else "both groups"
                if matching and other
                else "Matching address criteria"
                if matching
                else "Other senders"
            )
            emit(
                f"Available from {group}: {selected} {'address' if selected == 1 else 'addresses'}."
            )
        if exclude_other:
            emit(
                f"Will skip Other senders: {excluded} "
                f"{'address' if excluded == 1 else 'addresses'}.",
                primary=False,
            )
        counts(additions=selected)
        if not selected:
            emit("No additions selected; no update made.")
            outcome("no_changes")
            return 0
    if not plan.additions:
        emit("No additions needed; no update made.")
        outcome("no_changes")
        return 0
    approved = args.apply
    if interactive and not args.apply:
        selected_numbers = review_address_additions(rows)
        if selected_numbers is None:
            emit("Cancelled; no changes made.")
            outcome("preview")
            return 0
        displayed = matching + other if grouped else entries
        plan = replace(plan, additions=tuple(displayed[i - 1]["value"] for i in selected_numbers))
        counts(additions=len(plan.additions))
        approved = True
    # Validate the selected plan (or all eligible additions for noninteractive preview).
    update_body(plan)
    if approved:
        if api.apply(plan):
            count = len(plan.additions)
            emit(f"Saved and verified {count} {'addition' if count == 1 else 'additions'}.")
            outcome("applied")
        else:
            emit("No additions needed; no update made.")
            outcome("no_changes")
    else:
        flags = "--exclude-other --apply" if exclude_other else "--apply"
        emit(f"Preview only; no changes made. Use {flags} to save additions.")
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
    if getattr(args, "from_url", None):
        return run_url_add(args, api, person, interactive=interactive)
    all_choice = None
    pending_decisions = set()
    if args.command == "add-email" and interactive and not args.apply:

        def collect_decision(address, matches, label):
            pending_decisions.add(address_key(address))
            return False

        # Reuse the planner's normalized conflict rules, without prompting or writing.
        make_edit_plan(person, args.entries, resolve=collect_decision)

    def resolve(address, matches, label):
        nonlocal all_choice
        pending_decisions.discard(address_key(address))
        if args.replace_existing:
            return True
        if args.apply or not interactive:
            return False
        if all_choice is not None:
            return all_choice
        emit_list("Already exists", email_rows(matches))
        if not label:
            emit("You supplied no label.", file=sys.stderr)
        if len(matches) > 1:
            replacement = (
                f"Combine {len(matches)} entries into one labeled {label!r}"
                if label
                else f"Combine {len(matches)} entries into one with no label"
            )
            keeping = f"Keep all {len(matches)} existing entries"
        else:
            old_label = matches[0].get("type", "")
            replacement = (
                f"Change the label to {label!r}" if label else f"Remove the {old_label!r} label"
            )
            keeping = (
                f"Keep the {old_label!r} label" if old_label else "Keep the entry without a label"
            )
        batch = bool(pending_decisions)
        indent = "     " if len(matches) == 1 else "  "
        while True:
            emit(
                f"\n{indent}r   {replacement}\n{indent}k   {keeping}",
                file=sys.stderr,
                primary=False,
            )
            if batch:
                emit(
                    "\n  a   Use requested labels and combine duplicates "
                    "for this and remaining conflicts\n"
                    "  s   Keep existing entries for this and remaining conflicts",
                    file=sys.stderr,
                    primary=False,
                )
            emit(
                "\nChoose an option (Enter = keep existing entries): ",
                file=sys.stderr,
                end="",
                primary=False,
            )
            try:
                choice = read_input().strip().casefold()
            except EOFError:
                all_choice = False
                return False
            finally:
                emit("", file=sys.stderr, primary=False)
            if choice in {"a", "s"}:
                all_choice = choice == "a"
                return all_choice
            # Preserve previously accepted keys for interactive compatibility.
            if choice in {"", "k", "keep", "n", "no", "r", "replace", "y", "yes"}:
                return choice in {"r", "replace", "y", "yes"}
            emit(
                "Choose r, k, a, or s." if batch else "Choose r or k.",
                file=sys.stderr,
            )

    plan = (
        make_duplicate_removal_plan(person)
        if getattr(args, "duplicates", False)
        else make_edit_plan(
            person, args.entries, remove=args.command == "remove-email", resolve=resolve
        )
    )
    return finish_email_edit(args, api, plan, interactive=interactive)


def run_duplicate(args, api):
    person = api.get_contact(contact_resource(args.contact), READ_FIELDS)
    plan = make_duplicate_plan(
        person, api.people._rootDesc["schemas"], **args.duplicate_options, no_photo=args.no_photo
    )
    emit(contact_heading(person))
    for field, entries in replacement_fields(**args.duplicate_options).items():
        label = {"names": "Name", "emailAddresses": "Emails", "phoneNumbers": "Phones"}[field]
        if entries:
            if field == "names":
                parts = {
                    "unstructuredName": "Full name",
                    "givenName": "First name",
                    "familyName": "Last name",
                }
                values = [f"{parts[key]}: {value}" for key, value in entries[0].items()]
            else:
                values = [item["value"] for item in entries]
            emit(f"{label}: replace with " + "; ".join(values), primary=False)
        else:
            emit(f"{label}: clear", primary=False)
    for field, values in plan.body.items():
        emit(f"  {field}: {len(values)}", primary=False)
    emit(
        "Photo: "
        + (
            "use default avatar (--no-photo)"
            if args.no_photo
            else "copy custom photo"
            if plan.photo_url
            else "use default avatar"
        ),
        primary=False,
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
    except (MissingToken, InsufficientScopes, ReauthorizationRequired) as exc:
        reauthorize = not isinstance(exc, MissingToken)
        if isinstance(exc, MissingToken):
            reason = "You're not authorized: no token file was found."
        elif isinstance(exc, InsufficientScopes):
            reason = (
                f"{exc}\nGmail read-only permission allows reading message bodies; "
                "this CLI reads message headers, labels, and sending addresses, not bodies."
            )
        else:
            reason = str(exc)
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
            answer = read_input().strip().casefold()
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
    aliases.update(
        {f"{action}-phones": f"{action}-phone" for action in ("list", "remove", "format")}
    )
    aliases["list-contacts"] = "list-contact"
    aliases["add-contacts"] = "add-contact"
    aliases["list-labels"] = "list-label"
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
        url = getattr(args, "from_url", None)
        if url is not None and (args.add or args.add_file or args.replace_existing):
            arguments.error(
                "--from-url cannot be combined with --add, --add-file, or --replace-existing"
            )
        duplicates = getattr(args, "duplicates", False)
        if duplicates and (args.remove or args.remove_file):
            arguments.error("--duplicates cannot be combined with --remove or --remove-file")
        if (
            not url
            and not duplicates
            and not getattr(args, action)
            and not getattr(args, action + "_file")
        ):
            alternatives = " or --from-url" if action == "add" else " or --duplicates"
            arguments.error(f"{args.command} requires --{action} or --{action}-file{alternatives}")
    if args.command in {"add-contact", "duplicate"}:
        explicit_name = args.first_name is not None or args.last_name is not None
        if args.name is not None and explicit_name:
            arguments.error("--name cannot be combined with --first-name or --last-name")
        if args.command == "duplicate" and args.clear_name and explicit_name:
            arguments.error("--clear-name cannot be combined with --first-name or --last-name")
        if args.command == "add-contact":
            if args.file is not None and (args.name is not None or explicit_name or args.email):
                arguments.error("--file cannot be combined with inline name or email options")
            if args.file is None and args.name is None and not explicit_name and not args.email:
                arguments.error(
                    "add-contact requires --name, --first-name, --last-name, --email, or --file"
                )
    token = ERROR_LOG_COMMAND.set(args.command)
    try:
        with OperationalOutput(), CommandTimer():
            return execute_command(args)
    finally:
        ERROR_LOG_COMMAND.reset(token)


def execute_command(args):
    if args.command != "sender-sync":
        return run_command(args)
    metrics = RunMetrics()
    token = ACTIVE.set(metrics)
    diagnostics = (
        RunDiagnostics(args.command, metrics.record["code_version"]) if args.diagnostics else None
    )
    trace_token = TRACE.set(diagnostics)
    result = 1
    try:
        result = run_command(args)
        return result
    finally:
        ACTIVE.reset(token)
        metrics.finish(result)
        if diagnostics is not None:
            diagnostics.finish(result)
        TRACE.reset(trace_token)


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
        if args.command == "list-contact":
            from .contact_resolution import contact_filters

            filters = contact_filters(
                **{
                    key: getattr(args, key)
                    for key in ("search", "name", "email", "phone", "company", "label", "exact")
                }
            )
            api = connect_with_authorization(args.token, args.auth_timeout)
            if api is None:
                return 1
            api.write_started = False
            return run_list_contacts(api, filters)
        if args.command == "add-contact":
            contacts = load_contact_inputs(
                name=args.name,
                first_name=args.first_name,
                last_name=args.last_name,
                emails=args.email,
                file=args.file,
                labels=args.label,
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
        if args.contact is not None and args.command not in {"add-label", "format-phone"}:
            from .contact_resolution import identifier_kind, load_identifiers

            args.contact = load_identifiers(args.contact)[0]
            identifier_kind(args.contact)
        if args.command == "format-phone":
            from .contact_resolution import load_batch_identifiers

            args.contact_identifiers = load_batch_identifiers(args.contact, args.contact_file)
        if args.command == "add-custom-field":
            for number, (key, value) in enumerate(args.field, 1):
                text_value(key, f"--field #{number} key")
                text_value(value, f"--field #{number} value")
        elif args.command == "remove-custom-field":
            text_value(args.key, "--key")
            if args.value is not None:
                text_value(args.value, "--value")
        elif args.command in {"add-label", "remove-label"}:
            if args.command == "add-label" and (
                args.contact is not None or args.contact_file is not None
            ):
                from .contact_resolution import identifier_kind, load_identifiers

                args.contact_identifiers = load_identifiers(args.contact, args.contact_file)
                for identifier in args.contact_identifiers:
                    identifier_kind(identifier)
            for number, label in enumerate(args.label, 1):
                text_value(label, f"--label #{number}")
        elif args.command == "duplicate":
            args.duplicate_options = {
                key: getattr(args, key)
                for key in (
                    "name",
                    "first_name",
                    "last_name",
                    "email",
                    "phone",
                    "clear_name",
                    "clear_email",
                    "clear_phone",
                )
            }
            replacement_fields(**args.duplicate_options)
        elif args.command == "sender-sync":
            if args.exclude_other and args.label is not None:
                raise SyncError(
                    "--exclude-other cannot be used with --label.\n"
                    "Use --search with from:/to: address criteria, "
                    "or exclude individual addresses with --exclude."
                )
            args.exclude = sorted(set(args.exclude) | file_exclusions(args.exclude_file))
            if args.search is not None:
                args.search = args.search.strip()
            exclusion_query(
                {value for value in args.exclude if "*" not in value}, search=args.search
            )
            if (
                args.exclude_other
                and args.search is not None
                and not extract_search_criteria(args.search)
            ):
                raise SyncError(
                    "--exclude-other requires full addresses or domains "
                    "in positive from:/to: criteria."
                )
        elif args.command in {"add-email", "remove-email"}:
            action = args.command.split("-")[0]
            if getattr(args, "from_url", None):
                validate_url(args.from_url)
                emit(f"Source: {args.from_url}")
                with StageProgress() as progress:
                    progress.start("Reading webpage")
                    page = fetch_addresses(args.from_url)
                if page["url"] != args.from_url:
                    emit(f"Final URL: {page['url']}", primary=False)
                args.entries = [(address, "", args.from_url) for address in page["addresses"]]
                if not args.entries:
                    emit("No email addresses found in the static HTML. No changes made.")
                    emit(
                        "JavaScript-rendered and obfuscated addresses are not supported.",
                        primary=False,
                    )
                    return 0
            else:
                args.entries = edit_inputs(
                    getattr(args, action), getattr(args, action + "_file"), f"--{action}"
                )
        api = connect_with_authorization(args.token, args.auth_timeout)
        if api is None:
            return 1
        api.write_started = False
        if args.command == "format-phone":
            from .phone_format import run_format_contacts

            return run_format_contacts(args, api, confirm_apply)
        if args.contact is not None and args.command not in {"add-label", "format-phone"}:
            from .contact_resolution import resolve_single_contact

            args.contact = resolve_single_contact(api, args.contact)
            if args.contact is None:
                emit("Cancelled; no changes made.")
                outcome("cancelled")
                return 0
        if args.command in {"add-custom-field", "remove-custom-field"}:
            return run_custom_field(args, api, confirm_apply, contact_heading)
        if args.command == "list-label":
            return run_list_labels(args, api, contact_heading)
        if args.command in {"add-label", "remove-label"}:
            return run_label_edit(args, api, confirm_apply, contact_heading)
        if args.command in {"list-phone", "remove-phone"}:
            from .phone_edit import run_phone

            return run_phone(args, api, confirm_apply, contact_heading)
        if args.command == "list-email":
            return run_list_email(args, api)
        if args.command in {"add-email", "remove-email"}:
            return run_email_edit(args, api)
        return run_duplicate(args, api) if args.command == "duplicate" else run(args, api)
    except LabelChoiceCancelled:
        emit("Cancelled; no changes made.")
        outcome("cancelled")
        return 0
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
    finally:
        close = getattr(api, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    sys.exit(main())
