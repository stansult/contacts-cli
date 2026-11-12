"""Build fresh archives, inspect them, and test a clean wheel installation."""

import subprocess
import sys
import tempfile
from pathlib import Path

from check_repository import ROOT, check_archive


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def main():
    with tempfile.TemporaryDirectory(prefix="contacts-cli-package-") as directory:
        work = Path(directory)
        artifacts = work / "artifacts"
        run("uv", "build", "--out-dir", artifacts)
        wheels = list(artifacts.glob("*.whl"))
        sources = list(artifacts.glob("*.tar.gz"))
        assert len(wheels) == len(sources) == 1, list(artifacts.iterdir())
        archives = wheels + sources
        assert all(path in archives or path.name == ".gitignore" for path in artifacts.iterdir()), (
            list(artifacts.iterdir())
        )
        for archive in archives:
            check_archive(archive)
        environment = work / "venv"
        run("uv", "venv", "--python", sys.executable, environment)
        python = environment / "bin/python"
        requirements = work / "requirements.txt"
        run(
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--output-file",
            requirements,
            "--quiet",
        )
        run("uv", "pip", "install", "--python", python, "-r", requirements)
        wheel = next(artifacts.glob("*.whl"))
        run("uv", "pip", "install", "--python", python, "--no-deps", wheel)
        # Assert imports come from the installed wheel, not this checkout.
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "import contacts_cli.cli, sys; "
                "assert contacts_cli.cli.__file__.startswith(sys.prefix)",
            ],
            cwd=work,
            check=True,
        )
        run(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_installed_cli.py",
            "--installed-cli",
            environment / "bin/contacts-cli",
        )
    print("Archive contents and clean wheel installation passed.")


if __name__ == "__main__":
    main()
