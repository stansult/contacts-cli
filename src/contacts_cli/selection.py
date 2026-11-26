"""Reusable selection of displayed numbers, independent of item type or action."""

import re

from .output import emit, emit_list
from .timing import read_input


def parse_selection(answer, numbers):
    """Return unique selected numbers in displayed order (not numeric order)."""
    numbers = list(numbers)
    available = set(numbers)
    if answer.strip().casefold() == "all":
        return numbers
    selected = set()
    for part in answer.split(","):
        match = re.fullmatch(r"\s*([0-9]+)(?:\s*-\s*([0-9]+))?\s*", part)
        if not match:
            raise ValueError("Enter all, numbers or ranges such as 3-5,8, or q to cancel.")
        first = int(match[1])
        if match[2] is None:
            if first not in available:
                raise ValueError("Use only displayed item numbers.")
            selected.add(first)
            continue
        last = int(match[2])
        if first > last:
            raise ValueError("Use ranges in ascending order.")
        # Filter existing rows; never allocate a potentially enormous numeric span.
        selected.update(number for number in available if first <= number <= last)
    if not selected:
        raise ValueError("No displayed items fall within this selection.")
    return [number for number in numbers if number in selected]


def select_numbers(numbers, *, noun="items", separate_response=False):
    """Prompt for a subset; return None for q/EOF. Caller owns preview and confirmation."""
    numbers = list(numbers)
    emit(f"Choose {noun}:")
    emit(
        "  all     Select all\n  3-5,8   Select by number or range\n  q       Cancel",
        primary=False,
    )
    while True:
        emit("Selection: ", end="", primary=False)
        try:
            answer = read_input().strip()
        except EOFError:
            return None
        finally:
            if separate_response:
                emit("", primary=False)
        if answer.casefold() == "q":
            return None
        if not answer:
            continue
        try:
            return parse_selection(answer, numbers)
        except ValueError as exc:
            emit(str(exc))


def review_selection(rows, *, noun, heading, unit, question, action, preview=None):
    """Review displayed choices and confirm; return numbers or None, never write."""
    rows = list(rows)
    numbers = [number for number, _ in rows]
    if not numbers:
        return None
    if len(numbers) == 1:
        if preview:
            preview(numbers)
        emit(f"\n{question(1)} [y/N] ", end="")
        try:
            return numbers if read_input().strip().casefold() in {"y", "yes"} else None
        except EOFError:
            return None
    while True:
        emit("", primary=False)
        selected = select_numbers(numbers, noun=noun)
        if selected is None:
            return None
        if preview:
            preview(selected)
        elif selected != numbers:
            emit_list(heading, [(i, text) for i, text in rows if i in selected], unit=unit)
        while True:
            emit(question(len(selected)))
            emit(f"  y   {action}\n  n   Return to selection\n  q   Cancel", primary=False)
            emit("Confirm [n]: ", end="", primary=False)
            try:
                answer = read_input().strip().casefold()
            except EOFError:
                return None
            if answer in {"y", "yes"}:
                return selected
            if answer == "q":
                return None
            if answer in {"", "n", "no"}:
                break
            emit("Choose y, n, or q.")


def review_address_additions(rows):
    return review_selection(
        rows,
        noun="addresses",
        heading="Selected additions",
        unit=("address", "addresses"),
        question=lambda count: (
            "Add this address to this contact?"
            if count == 1
            else f"Add these {count} addresses to this contact?"
        ),
        action="Add selected addresses",
    )
