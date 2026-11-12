"""Choose lightweight CI only for explicitly known, non-executable documentation."""

import json
import os
import subprocess
from pathlib import Path

DOCUMENTS = {
    "README.md",
    "CONTRIBUTING.md",
    "docs/command-reference.md",
    "docs/google-setup.md",
    "docs/metrics.md",
    "docs/testing.md",
}


def docs_only(paths):
    return bool(paths) and all(path in DOCUMENTS for path in paths)


def changed_paths(event_name, event):
    if event_name == "push":
        base, head = event["before"], event["after"]
        separator = ".."
    elif event_name == "pull_request":
        pr = event["pull_request"]
        base, head = pr["base"]["sha"], pr["head"]["sha"]
        separator = "..."
    else:
        return []
    # New branches, missing history, and malformed event data must run full CI.
    if not all(
        len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) for sha in (base, head)
    ):
        return []
    if base == "0" * 40 or head == "0" * 40:
        return []
    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", base + separator + head],
        check=True,
        capture_output=True,
    )
    return result.stdout.decode().rstrip("\0").split("\0") if result.stdout else []


def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        lightweight = docs_only(changed_paths(os.environ["GITHUB_EVENT_NAME"], event))
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError):
        lightweight = False
    value = "true" if lightweight else "false"
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"docs_only={value}\n")
    print("Documentation-only checks" if lightweight else "Full checks")


if __name__ == "__main__":
    main()
