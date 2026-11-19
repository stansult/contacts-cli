"""Removal patterns and selection affect only chosen contact memberships."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.label_edit import memberships

from .test_label_edit import group
from .test_remove_label import apply_group


def setup(api, server, monkeypatch, answers=None):
    resources = {
        name: group(server, name)
        for name in ("Recruit", "Recruiter", "recruit", "Keep", "Recruit/Old")
    }
    for name, resource in resources.items():
        if name != "Recruit/Old":
            apply_group(server, resource)
    monkeypatch.setattr(cli, "connect_with_authorization", lambda *a: api)
    for stream in (cli.sys.stdin, cli.sys.stdout, cli.sys.stderr):
        monkeypatch.setattr(stream, "isatty", lambda: answers is not None)
    baseline = server.writes
    replies = iter(answers or [])

    def answer():
        assert server.writes == baseline
        value = next(replies)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr("builtins.input", answer)
    return resources, baseline


@pytest.mark.parametrize(
    "pattern,names",
    [
        ("Recruit*", {"Recruit", "Recruiter", "recruit"}),
        ("*cruit", {"Recruit", "recruit"}),
        ("Recruit", {"Recruit", "recruit"}),
        ("*", {"Recruit", "Recruiter", "recruit", "Keep"}),
        ("cruit", set()),
        ("Recruit/Old", set()),
    ],
)
def test_pattern_apply(api, server, monkeypatch, pattern, names):
    resources, baseline = setup(api, server, monkeypatch, [])
    before = deepcopy(server.person)
    groups = deepcopy(server.groups)
    assert cli.main(["remove-label", "--contact", "c123", "--label", pattern, "--apply"]) == 0
    assert memberships(server.person) == memberships(before) - {resources[n] for n in names}
    assert server.groups == groups
    assert server.writes == baseline + len(names)
    for key in before.keys() - {"memberships", "metadata"}:
        assert server.person[key] == before[key]


@pytest.mark.parametrize(
    "answers,removed",
    [
        (["2", "y"], {"Recruiter"}),
        (["all", "n", "1,3", "y"], {"Recruit", "recruit"}),
        (["q"], set()),
        ([EOFError()], set()),
        (None, set()),
    ],
)
def test_partial(api, server, monkeypatch, answers, removed, capsys):
    resources, baseline = setup(api, server, monkeypatch, answers)
    before = memberships(server.person)
    assert (
        cli.main(["remove-label", "--contact", "c123", "--label", "Recruit*", "--label", "Recruit"])
        == 0
    )
    assert memberships(server.person) == before - {resources[n] for n in removed}
    assert server.writes == baseline + len(removed)
    output = capsys.readouterr().out
    assert "Proposed label removals: 3 labels" in output


def test_case_variants_selectable_without_resolution_prompt(api, server, monkeypatch, capsys):
    resources, _ = setup(api, server, monkeypatch, ["2", "y"])
    assert cli.main(["remove-label", "--contact", "c123", "--label", "Recruit"]) == 0
    output = capsys.readouterr().out
    assert "Exact matches: 1 label" in output
    assert "Similar labels (case differs): 1 label" in output
    assert "Choose a label:" not in output
    assert resources["Recruit"] in memberships(server.person)
    assert resources["recruit"] not in memberships(server.person)


@pytest.mark.parametrize("pattern", ["System", "*"])
def test_system_groups_excluded(api, server, monkeypatch, pattern):
    _, baseline = setup(api, server, monkeypatch, [])
    resource = group(server, "System")
    server.groups[resource]["groupType"] = "SYSTEM_CONTACT_GROUP"
    apply_group(server, resource)
    baseline = server.writes
    assert cli.main(["remove-label", "--contact", "c123", "--label", pattern, "--apply"]) == 0
    assert server.writes == baseline + (4 if pattern == "*" else 0)
    assert resource in memberships(server.person)


def test_membership_changes_do_not_expand_preview(api, server, monkeypatch, capsys):
    resources, baseline = setup(api, server, monkeypatch, [])
    original = api.get_contact
    calls = 0

    def changed(*a, **kw):
        nonlocal calls
        calls += 1
        if calls == 2:
            server.person["memberships"] = [
                e
                for e in server.person["memberships"]
                if e["contactGroupMembership"]["contactGroupResourceName"] != resources["Recruit"]
            ]
            server.person["memberships"].append(
                {"contactGroupMembership": {"contactGroupResourceName": resources["Recruit/Old"]}}
            )
        return original(*a, **kw)

    monkeypatch.setattr(api, "get_contact", changed)
    assert cli.main(["remove-label", "--contact", "c123", "--label", "Recruit*", "--apply"]) == 0
    assert resources["Recruit/Old"] in memberships(server.person)
    assert server.writes == baseline + 2
    output = capsys.readouterr().out
    assert "Already removed since preview: Recruit; skipped." in output
    assert "Removed and verified 2 labels" in output


@pytest.mark.parametrize("pattern", ["A+B*", "A.B*", "*/*"])
def test_pattern_metacharacters_and_slashes_are_literal(pattern, api, server, monkeypatch):
    from contacts_cli.label_removal import resolve_removals

    for name in ("A+B", "A.B", "AxB", "A/B"):
        group(server, name)
    labels, missing, _ = resolve_removals(api, [pattern])
    assert list(labels) == [{"A+B*": "A+B", "A.B*": "A.B", "*/*": "A/B"}[pattern]]
    assert not missing
