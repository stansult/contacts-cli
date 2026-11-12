"""Copied as sitecustomize.py into a temporary subprocess-only import directory."""

import os
import socket
import webbrowser
from pathlib import Path

# urllib3 probes local IPv6 support during import. Finish that initialization
# before guarding the CLI; no Google modules or credentials are loaded here.
from urllib3.util.connection import HAS_IPV6

del HAS_IPV6

LOG = Path(os.environ["CONTACTS_CLI_GUARD_LOG"])


def blocked(*args, **kwargs):
    with LOG.open("a") as stream:
        stream.write("blocked external action\n")
    raise RuntimeError("External action blocked by the CLI test guard")


class BlockedSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        return blocked(*args, **kwargs)


socket.socket = BlockedSocket
socket.create_connection = blocked
socket.getaddrinfo = blocked
webbrowser.open = blocked
webbrowser.open_new = blocked
webbrowser.open_new_tab = blocked
webbrowser.get = blocked
LOG.write_text("guard ready\n")
