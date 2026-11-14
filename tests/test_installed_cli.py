"""Run the real entry point outside the checkout with synthetic files only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CASES = json.loads((Path(__file__).parent / "fixtures/auth-errors.json").read_text())


@pytest.fixture
def guarded_cli(tmp_path, request):
    executable = Path(
        request.config.getoption("--installed-cli") or Path(sys.executable).parent / "contacts-cli"
    )
    assert executable.is_file(), executable
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        Path(__file__).with_name("subprocess_guard.py").read_text()
    )
    log = tmp_path / "guard.log"
    env = dict(os.environ, PYTHONPATH=str(guard), CONTACTS_CLI_GUARD_LOG=str(log))

    def run(args, *, python=False):
        command = [str(executable.parent / "python")] if python else [str(executable)]
        result = subprocess.run(
            command + args,
            cwd=tmp_path,
            env=env,
            input="",
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert log.is_file(), "Subprocess guard did not load"
        return result, log.read_text()

    return run


@pytest.mark.parametrize(
    "code",
    ["import socket; socket.socket()", "import webbrowser; webbrowser.open('https://example.com')"],
)
def test_subprocess_guard_contract(guarded_cli, code):
    result, log = guarded_cli(["-c", code], python=True)
    assert result.returncode != 0
    assert "External action blocked" in result.stderr
    assert log == "guard ready\nblocked external action\n"


@pytest.mark.parametrize(
    "command",
    [
        [],
        ["authorize"],
        ["sender-sync"],
        ["duplicate"],
        ["add-custom-field"],
        ["remove-custom-field"],
    ],
)
def test_installed_help(guarded_cli, command):
    result, log = guarded_cli(command + ["--help"])
    assert result.returncode == 0
    assert "usage: contacts-cli" in result.stdout
    assert log == "guard ready\n"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case"])
def test_authorization_file_errors(guarded_cli, tmp_path, case):
    client, token = tmp_path / "client.json", tmp_path / "token.json"
    target = client if case["file"] == "client" else token
    if case["content"] is not None:
        target.write_text(case["content"])
    args = [case["command"], "--token", str(token)]
    if case["command"] == "authorize":
        args += ["--credentials", str(client)]
    else:
        args += ["--contact", "people/c123"]
        if case["command"] == "sender-sync":
            args += ["--label", "Example/Delivery"]
    result, log = guarded_cli(args)
    assert result.returncode == 1, result.stderr
    assert case["message"] in result.stderr
    assert "Traceback" not in result.stderr
    assert "Authorize now in your browser?" not in result.stderr
    assert log == "guard ready\n"
    if case["file"] == "token" and case["content"] is not None:
        assert token.read_text() == case["content"]
    else:
        assert not token.exists()
