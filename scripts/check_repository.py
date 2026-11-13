"""Local documentation links and distribution file checks used by CI."""

import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def check_links(root=ROOT):
    files = [root / "README.md", root / "CONTRIBUTING.md", *sorted((root / "docs").glob("*.md"))]
    for source in files:
        for target in re.findall(r"\]\(([^)]+)\)", source.read_text()):
            if "://" in target or target.startswith("mailto:"):
                continue
            name, _, anchor = target.partition("#")
            destination = source.parent / name if name else source
            if not destination.exists():
                raise ValueError(f"{source.name}: missing link {target}")
            if anchor and destination.suffix == ".md":
                headings = [
                    re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
                    for h in re.findall(r"^#+ (.+)$", destination.read_text(), re.M)
                ]
                if anchor not in headings:
                    raise ValueError(f"{source.name}: missing heading {target}")


def check_archive(path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    else:
        with tarfile.open(path) as archive:
            names = archive.getnames()
    for name in names:
        parts = PurePosixPath(name).parts
        for part in parts:
            lower = part.lower()
            if (
                lower
                in {
                    "handoff.md",
                    ".venv",
                    "venv",
                    "__pycache__",
                    ".git",
                    "secrets",
                    ".contacts-cli",
                }
                or lower.startswith(("credentials", "client_secret", "tokens", ".env"))
                or lower == "token.json"
                or lower.startswith("token.")
                or lower.endswith((".pem", ".key", ".local.json", ".local.toml"))
            ):
                raise ValueError(f"{path.name}: forbidden packaged file {name}")
    for module in (
        "cli.py",
        "auth.py",
        "api.py",
        "core.py",
        "duplicate.py",
        "errors.py",
        "progress.py",
        "metrics.py",
        "output.py",
        "address_inputs.py",
        "email_edit.py",
    ):
        if not any(PurePosixPath(name).parts[-2:] == ("contacts_cli", module) for name in names):
            raise ValueError(f"{path.name}: missing module {module}")


if __name__ == "__main__":
    check_links()
    print("Local documentation links passed.")
