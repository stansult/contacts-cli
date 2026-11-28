"""Review meaningful first-name changes using an existing surname as an anchor."""

from copy import deepcopy

import pytest

from contacts_cli import cli
from contacts_cli.merge_conflicts import merge_values

from .test_contact_merge import incoming, setup


@pytest.mark.parametrize("choice", ["k", "r"])
def test_anchored_name_preserves_surname_and_shows_only_first_name(choice):
    old = {
        "givenName": "Andrew",
        "familyName": "Example",
        "unstructuredName": "Andrew Example",
    }
    source = {"names": [old]}
    before = deepcopy(source)
    details = []
    result, changes, _ = merge_values(
        source,
        {"names": [{"unstructuredName": "Drew Example"}]},
        resolver=lambda c: choice,
        details=details,
    )
    assert source == before
    text = details[0].describe()
    assert "First name differs:" in text
    assert "Full name" not in text and "Last name" not in text and "removed" not in text
    assert details[0].choice_labels()[:2] == ("Keep Andrew", "Replace Andrew with Drew")
    expected = old if choice == "k" else {"givenName": "Drew", "familyName": "Example"}
    assert result["names"] == [expected]
    if choice == "r":
        assert changes == ["Replace First name: Andrew → Drew"]


@pytest.mark.parametrize(
    "old,new",
    [
        ({"givenName": "Andrew", "familyName": "Example"}, "Drew Other"),
        ({"givenName": "Andrew", "familyName": "Example"}, "Drew James Example"),
        (
            {"givenName": "Andrew", "familyName": "Example", "middleName": "James"},
            "Drew Example",
        ),
        ({"unstructuredName": "Andrew Example"}, "Drew Example"),
    ],
)
def test_ambiguous_names_do_not_infer_parts(old, new):
    result, _, _ = merge_values(
        {"names": [old]}, {"names": [{"unstructuredName": new}]}, resolver=lambda c: "r"
    )
    assert result["names"] == [{"unstructuredName": new}]


def test_compound_saved_surname_is_preserved():
    details = []
    result, _, _ = merge_values(
        {"names": [{"givenName": "Andrew", "familyName": "van Example"}]},
        {"names": [{"unstructuredName": "Drew van Example"}]},
        resolver=lambda c: "r",
        details=details,
    )
    assert result["names"] == [{"givenName": "Drew", "familyName": "van Example"}]
    assert "Last name" not in details[0].describe()


def test_name_and_email_review_decisions_and_write(api, server, monkeypatch, tmp_path, capsys):
    server.person["names"] = [{"givenName": "Andrew", "familyName": "Example"}]
    address = server.person["emailAddresses"][0]["value"]
    data = {
        "names": [{"unstructuredName": "Drew Example"}],
        "emailAddresses": [{"value": address, "type": "Event"}],
    }
    args = setup(api, server, monkeypatch, tmp_path, [data], ["m", "r", "r", "y"])
    assert cli.main(args) == 0 and server.writes == 1
    out = capsys.readouterr().out
    assert "Review name difference (1 of 2)" in out
    assert "Review email label difference (2 of 2)" in out
    assert "Selected merge changes: 2 changes" in out
    assert "First name differs:" in out and "Last name differs:" not in out
    assert server.person["names"][0]["givenName"] == "Drew"
    assert server.person["names"][0]["familyName"] == "Example"


def test_additions_visible_before_merge_choice(api, server, monkeypatch, tmp_path, capsys):
    data = incoming(server, organizations=[{"name": "Example"}])
    args = setup(api, server, monkeypatch, tmp_path, [data], [])

    def answer():
        out = capsys.readouterr().out
        assert "Available additions:" in out and "Add Company: Example" in out
        assert out.index("Add Company: Example") < out.index(
            "Choose an option (Enter = skip this input)"
        )
        return "q"

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(args) == 0 and server.writes == 0


@pytest.mark.parametrize("answers", [["m", "k", "k"], ["m", "r", "q"]])
def test_name_review_keep_or_cancel_never_writes(api, server, monkeypatch, tmp_path, answers):
    server.person["names"] = [{"givenName": "Andrew", "familyName": "Example"}]
    address = server.person["emailAddresses"][0]["value"]
    data = {
        "names": [{"unstructuredName": "Drew Example"}],
        "emailAddresses": [{"value": address, "type": "Event"}],
    }
    args = setup(api, server, monkeypatch, tmp_path, [data], answers)
    before = deepcopy(server.person)
    assert cli.main(args) == 0 and server.writes == 0 and server.person == before


def test_kept_name_summary_is_plain():
    result, changes, kept = merge_values(
        {
            "names": [
                {
                    "givenName": "Andrew",
                    "familyName": "Example",
                    "unstructuredName": "Andrew Example",
                }
            ]
        },
        {"names": [{"unstructuredName": "Drew Example"}]},
        resolver=lambda c: "k",
    )
    assert kept == ["Kept first name: Andrew."]
    assert changes == [] and result["names"][0]["givenName"] == "Andrew"


@pytest.mark.parametrize("label", [None, ""])
def test_missing_email_label_preview_and_selected_summary(
    api, server, monkeypatch, tmp_path, capsys, label
):
    entry = server.person["emailAddresses"][0]
    if label is None:
        entry.pop("type", None)
    else:
        entry["type"] = label
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [{"emailAddresses": [{"value": entry["value"], "type": "Event"}]}],
        ["m", "y"],
    )
    assert cli.main(args) == 0 and server.writes == 1
    out = capsys.readouterr().out
    assert "Add email label: " + entry["value"] in out
    assert "Label: Event (currently none)" in out
    assert ".type:" not in out and "Fill Email" not in out
    assert "Selected merge changes: 1 change" in out
    assert "\n         Available additions:" in out
    assert server.person["emailAddresses"][0]["type"] == "Event"
