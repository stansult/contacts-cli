"""Local OAuth authorization and token storage; loading tokens never launches a browser."""

import json
import os
import tempfile
from pathlib import Path

import httplib2
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError
from googleapiclient.discovery import build
from oauthlib.oauth2 import OAuth2Error
from requests.exceptions import RequestException

from .api import GoogleAPI
from .errors import InsufficientScopes, MissingToken, SyncError

SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/contacts",
)


def default_credentials_path() -> Path:
    return Path.home() / ".config" / "contacts-cli" / "credentials.json"


def default_token_path() -> Path:
    return Path.home() / ".config" / "contacts-cli" / "token.json"


def private_path(path: Path) -> Path:
    """Disallow credentials in a Git worktree, regardless of ignore rules."""
    resolved = path.expanduser().resolve()
    for parent in resolved.parents:
        if (parent / ".git").exists():
            raise SyncError("Store OAuth credentials and tokens outside Git repositories.")
    return resolved


def save_credentials(credentials: Credentials, path: Path) -> None:
    path = private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".token-", dir=path.parent)
        with os.fdopen(fd, "w") as stream:
            stream.write(credentials.to_json())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def authorize(
    client_path: Path, token_path: Path, *, open_browser: bool = True, timeout_seconds: int = 300
) -> None:
    client_path, token_path = private_path(client_path), private_path(token_path)
    try:
        config = json.loads(client_path.read_text())
        if not isinstance(config, dict) or "installed" not in config:
            raise SyncError("OAuth client JSON must be for a Desktop app.")
        flow = InstalledAppFlow.from_client_config(
            config, scopes=SCOPES, autogenerate_code_verifier=True
        )
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=open_browser,
            timeout_seconds=timeout_seconds,
            prompt="consent",
            authorization_prompt_message=(
                "\nAuthorization URL (open manually if needed):\n{url}\n"
            ),
        )
        granted = credentials.granted_scopes or credentials.scopes or ()
        if not set(SCOPES).issubset(granted) or not credentials.refresh_token:
            raise SyncError(
                "Required scopes or refresh token missing; repeat explicit authorization."
            )
        save_credentials(credentials, token_path)
    except WSGITimeoutError as exc:
        duration = "5 minutes" if timeout_seconds == 300 else f"{timeout_seconds} seconds"
        raise SyncError(
            f"Authorization timed out after {duration}. Run the command again to retry."
        ) from exc
    except (
        OSError,
        ValueError,
        GoogleAuthError,
        OAuth2Error,
        RequestException,
    ) as exc:
        raise SyncError(
            "Authorization failed; check the Desktop client file and retry setup."
        ) from exc


def load_credentials(token_path: Path) -> Credentials:
    token_path = private_path(token_path)
    if not token_path.is_file():
        raise MissingToken("No token found. Run contacts-cli authorize first.")
    try:
        # Do not pass scopes here: that could mask missing scopes in the saved token.
        credentials = Credentials.from_authorized_user_file(str(token_path))
        if not credentials.has_scopes(SCOPES):
            raise InsufficientScopes(
                "Saved token lacks required scopes. This CLI requires gmail.readonly for sender "
                "search and contacts access. Reauthorization is required."
            )
        if not credentials.valid:
            if not credentials.refresh_token:
                raise SyncError("No refresh token available; repeat explicit authorization.")
            credentials.refresh(Request())
            save_credentials(credentials, token_path)
        return credentials
    except (OSError, ValueError, GoogleAuthError, RequestException) as exc:
        raise SyncError(
            "Token could not be loaded or refreshed; repeat explicit authorization."
        ) from exc


def connect(token_path: Path) -> GoogleAPI:
    credentials = load_credentials(token_path)
    # Refresh expired tokens before requests, but do not replay a write after a 401.
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=30), max_refresh_attempts=0)
    # The client library bundles discovery documents; no discovery network request.
    return GoogleAPI(
        build("gmail", "v1", http=http, cache_discovery=False, static_discovery=True),
        build("people", "v1", http=http, cache_discovery=False, static_discovery=True),
    )
