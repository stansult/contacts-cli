"""Total runtime uses monotonic time and excludes all interactive waits."""

import ast
from pathlib import Path

import pytest

from contacts_cli import cli, timing


@pytest.mark.parametrize("error", [None, EOFError, KeyboardInterrupt])
def test_input_wait_excluded_even_on_exception(monkeypatch, capsys, error):
    now = [0.0]

    def answer():
        now[0] += 100
        if error:
            raise error
        return "yes"

    monkeypatch.setattr("builtins.input", answer)
    with timing.CommandTimer(lambda: now[0]):
        now[0] += 2
        if error:
            with pytest.raises(error):
                timing.read_input()
        else:
            assert timing.read_input() == "yes"
        now[0] += 3
    assert capsys.readouterr().err == "Active time: 5.0s\n"
    assert timing.ACTIVE_TIMER.get() is None


def test_nested_wait_and_repeated_commands(capsys):
    now = [0.0]
    for _ in range(2):
        with timing.CommandTimer(lambda: now[0]):
            with timing.waiting_for_input():
                now[0] += 10
                with timing.waiting_for_input():
                    now[0] += 20
            now[0] += 1.25
    assert capsys.readouterr().err == "Active time: 1.2s\n" * 2


@pytest.mark.parametrize("error", [None, RuntimeError, KeyboardInterrupt])
def test_cli_footer_once_on_every_exit(monkeypatch, capsys, error):
    now = [0.0]
    monkeypatch.setattr(timing.time, "monotonic", lambda: now[0])

    def run(args):
        now[0] = 7.5
        if error:
            raise error
        return 0

    monkeypatch.setattr(cli, "execute_command", run)
    if error:
        with pytest.raises(error):
            cli.main(["list-email", "--contact", "c123"])
    else:
        assert cli.main(["list-email", "--contact", "c123"]) == 0
    output = capsys.readouterr()
    assert output.err.count("Active time: 7.5s") == 1
    assert not output.out
    assert timing.ACTIVE_TIMER.get() is None


def test_all_terminal_inputs_use_timing_wrapper():
    root = Path(cli.__file__).parent
    for path in root.glob("*.py"):
        if path.name == "timing.py":
            continue
        tree = ast.parse(path.read_text())
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "input"
            for node in ast.walk(tree)
        ), path


def test_help_has_no_total(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    output = capsys.readouterr()
    assert "Active time" not in output.out + output.err


def test_browser_authorization_wait_excluded(monkeypatch, tmp_path, capsys):
    from unittest.mock import Mock

    from contacts_cli import auth

    now = [0.0]
    client = tmp_path / "client.json"
    client.write_text('{"installed": {"client_id": "synthetic"}}')
    credentials = Mock(granted_scopes=auth.SCOPES, refresh_token="synthetic")

    def authorize(**kwargs):
        now[0] += 100
        return credentials

    flow = Mock()
    flow.run_local_server.side_effect = authorize
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_config", lambda *a, **k: flow)
    monkeypatch.setattr(auth, "save_credentials", Mock())
    with timing.CommandTimer(lambda: now[0]):
        now[0] += 2
        auth.authorize(client, tmp_path / "token.json")
        now[0] += 3
    assert capsys.readouterr().err == "Active time: 5.0s\n"
    auth.save_credentials.assert_called_once_with(credentials, tmp_path / "token.json")
