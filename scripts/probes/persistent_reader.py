"""Compatibility entry point for isolated transport benchmarks."""

from contacts_cli.persistent_reader import PersistentReader  # noqa: F401
from contacts_cli.read_worker import ReadSession, serve  # noqa: F401

if __name__ == "__main__":
    serve(ReadSession())
