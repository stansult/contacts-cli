"""Reusable selection of displayed numbers, independent of item type or action."""

import re

from .output import emit


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
        first, last = int(match[1]), int(match[2] or match[1])
        # Bound ranges before expanding, including sparse displayed numbering.
        if first > last or last - first + 1 > len(available):
            raise ValueError("Use displayed numbers and ranges in ascending order.")
        chosen = set(range(first, last + 1))
        if not chosen <= available:
            raise ValueError("Use only displayed item numbers.")
        selected.update(chosen)
    return [number for number in numbers if number in selected]


def select_numbers(numbers, *, noun="items"):
    """Prompt for a subset; return None for q/EOF. Caller owns preview and confirmation."""
    numbers = list(numbers)
    emit(f"Select {noun}:")
    emit(
        "  all     Select all\n  3-5,8   Example: select items 3, 4, 5, and 8\n  q       Cancel",
        primary=False,
    )
    while True:
        emit("Selection: ", end="", primary=False)
        try:
            answer = input().strip()
        except EOFError:
            return None
        if answer.casefold() == "q":
            return None
        if not answer:
            continue
        try:
            return parse_selection(answer, numbers)
        except ValueError as exc:
            emit(str(exc))
