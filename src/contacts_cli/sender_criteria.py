"""Conservative search criteria extraction, independent of sender grouping.

This is not a Gmail query evaluator. Unsupported criteria contribute nothing;
unbalanced or excessively nested syntax disables grouping for the whole query.
"""

import re
from dataclasses import dataclass

TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[(){}:]|-|[^\s(){}:"]+')
DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
LOCAL = re.compile(r"[a-z0-9_%+-]+(?:\.[a-z0-9_%+-]+)*")


@dataclass(frozen=True)
class AddressCriteria:
    addresses: frozenset[str] = frozenset()
    domains: frozenset[str] = frozenset()

    def __bool__(self):
        return bool(self.addresses or self.domains)

    def matches(self, address):
        address = address.strip().casefold()
        if address in self.addresses:
            return True
        if "@" not in address:
            return False
        domain = address.rsplit("@", 1)[1]
        return any(domain == item or domain.endswith("." + item) for item in self.domains)

    def partition(self, entries):
        matching, other = [], []
        for entry in entries:
            (matching if self.matches(entry["value"]) else other).append(entry)
        return matching, other


def _tree(query):
    tokens, end = [], 0
    for match in TOKEN.finditer(query):
        if query[end : match.start()].strip():
            raise ValueError("unsupported token")
        tokens.append(match.group())
        end = match.end()
    if query[end:].strip():
        raise ValueError("unsupported token")
    index = 0

    def node(depth=0):
        nonlocal index
        if depth > 32 or index >= len(tokens):
            raise ValueError("incomplete or deeply nested expression")
        token = tokens[index]
        index += 1
        if token in {"-", "NOT"}:
            return ("negative", node(depth + 1))
        if token in {"(", "{"}:
            closing = ")" if token == "(" else "}"
            children = []
            while index < len(tokens) and tokens[index] != closing:
                children.append(node(depth + 1))
            if index == len(tokens):
                raise ValueError("unclosed group")
            index += 1
            return ("group", children)
        if token in {")", "}", ":"}:
            raise ValueError("unexpected delimiter")
        if index < len(tokens) and tokens[index] == ":":
            index += 1
            return ("field", token, node(depth + 1))
        return ("word", token)

    result = []
    while index < len(tokens):
        result.append(node())
    return ("group", result)


def _values(node):
    """Accept only simple values/alternatives in a field's scope, all or nothing."""
    kind, value, *rest = node
    if kind == "word":
        return [] if value == "OR" else [value]
    if kind == "group":
        return [word for child in value for word in _values(child)]
    raise ValueError("unsupported field expression")


def _criterion(value):
    value = value.removeprefix('"').removesuffix('"').casefold()
    if "@" in value:
        local, domain = value.rsplit("@", 1)
        if LOCAL.fullmatch(local) and DOMAIN.fullmatch(domain):
            return "address", value
    elif DOMAIN.fullmatch(value):
        return "domain", value
    raise ValueError("not a supported address or domain")


def extract_search_criteria(query):
    if not query:
        return AddressCriteria()
    try:
        tree = _tree(query)
    except ValueError:
        return AddressCriteria()
    addresses, domains = set(), set()

    def visit(node):
        kind, value, *rest = node
        if kind == "group":
            for child in value:
                visit(child)
        elif kind == "field" and value in {"from", "to"}:
            try:
                criteria = [_criterion(word) for word in _values(rest[0])]
            except ValueError:
                return
            for category, text in criteria:
                (addresses if category == "address" else domains).add(text)
        # Do not descend into negation, quoted text, or any other field's scope.

    visit(tree)
    return AddressCriteria(frozenset(addresses), frozenset(domains))


def extract_filter_criteria(filters):
    """Union supported positive criteria; other filter conditions are not provenance."""
    addresses, domains = set(), set()
    for criteria in filters:
        query = extract_search_criteria(criteria.get("query"))
        addresses.update(query.addresses)
        domains.update(query.domains)
        for field in ("from", "to"):
            if not criteria.get(field):
                continue
            try:
                values = [_criterion(word) for word in _values(_tree(criteria[field]))]
            except ValueError:
                continue
            for category, text in values:
                (addresses if category == "address" else domains).add(text)
    return AddressCriteria(frozenset(addresses), frozenset(domains))
