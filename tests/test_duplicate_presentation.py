"""Input numbers remain distinct from informational duplicate-match bullets."""

from contacts_cli import cli
from contacts_cli.contact_matches import display_matches
from contacts_cli.contact_merge import choose_target

from .test_contact_matches import person, setup


def test_match_bullets_preserve_input_number_and_target_identity(capsys):
    matches = [
        ("people/c41", person(name="Jane"), ["email", "name"]),
        ("input #2", person(name="Other"), ["phone"]),
    ]
    display_matches(4, person(name="Jane"), matches)
    assert capsys.readouterr().out.splitlines() == [
        "4. Jane — possible matches:",
        "   - Jane (c41) — matching email, name",
        "   - Other (input #2) — matching phone",
    ]


def test_overview_uses_original_input_numbers(api, server, monkeypatch, tmp_path, capsys):
    args = setup(
        api,
        server,
        monkeypatch,
        tmp_path,
        [
            person(name="Unique"),
            person(name="Jane Doe"),
            person(name="Bob Smith", email="bob@example.com"),
        ],
        [person(name="Jane Doe"), person(name="Jane Doe"), person(name="Bob Smith")],
        answers=["q"],
    )
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Contacts to review: 3 contacts" in output
    assert "Name: Full name:" not in output
    assert (
        output.index("2. Jane Doe") < output.index("- Jane Doe (c1)") < output.index("3. Bob Smith")
    )
    assert output.index("3. Bob Smith") < output.index("- Bob Smith (c3)")
    assert output.count("2. Jane Doe") == 1
    assert "Choose contacts to import:" in output
    assert "skip, merge, or create separately" in output
    assert "•" not in output
    assert "Merge targets" not in output
    assert server.writes == 0


def test_merge_target_choice_displays_numbered_targets(monkeypatch, capsys):
    matches = [
        ("people/c41", person(name="Jane"), ["name"]),
        ("people/c42", person(name="Other"), ["phone"]),
    ]
    answers = iter(["bad", "2"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert choose_target(matches) == "people/c42"
    output = capsys.readouterr().out
    assert "  1. Jane (c41) — matching name\n" in output
    assert "  2. Other (c42) — matching phone\n" in output
    assert output.index("Merge targets") < output.index("Merge into match number")


def test_name_preview_omits_only_redundant_full_name():
    from contacts_cli.contact_create import contact_preview

    assert contact_preview(person(name="Jane Doe")) == "Jane Doe"
    structured = {"names": [{"givenName": "Jane", "familyName": "Doe"}]}
    assert "Name: First name: Jane; Last name: Doe" in contact_preview(structured)
    extra = {"names": [{"unstructuredName": "Jane Doe", "phoneticGivenName": "Jayne"}]}
    assert "Jayne" in contact_preview(extra)
