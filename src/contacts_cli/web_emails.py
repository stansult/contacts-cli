"""Extract unlabeled email addresses from one bounded, static HTML page."""

import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from .address_inputs import bare_address
from .errors import SyncError

FETCH_SECONDS = 15
MAX_BYTES = 2 * 1024 * 1024
EMAIL = re.compile(
    r"(?<![\w@.+%-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z0-9-]+(?![\w@-])"
)
VOID = set("area base br col embed hr img input link meta param source track wbr".split())
HIDDEN = {"script", "style", "head", "template", "noscript"}


def validate_url(url):
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme in {"http", "https"}
            and parts.hostname
            and not parts.username
            and not parts.password
        )
        _ = parts.port  # Validate malformed ports before any network access.
    except ValueError:
        valid = False
    if not valid or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise SyncError("--from-url requires an HTTP or HTTPS URL without embedded credentials.")
    return url


class EmailHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.addresses = {}

    def add(self, address):
        try:
            address = bare_address(address)
        except SyncError:
            return
        self.addresses.setdefault(address.casefold(), address)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = re.sub(r"\s+", "", attrs.get("style") or "").lower()
        hidden = (
            any(h for _, h in self.stack)
            or tag in HIDDEN
            or "hidden" in attrs
            or (attrs.get("aria-hidden") or "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        if not hidden and tag == "a":
            href = attrs.get("href") or ""
            if href.lower().startswith("mailto:"):
                for address in unquote(href[7:].split("?", 1)[0]).split(","):
                    self.add(address.strip())
        if tag not in VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not any(hidden for _, hidden in self.stack):
            for match in EMAIL.finditer(data):
                self.add(match.group().rstrip("."))


def extract_addresses(html):
    parser = EmailHTML()
    parser.feed(html)
    parser.close()
    return sorted(parser.addresses.values(), key=str.casefold)


def fetch_page(url):
    """Worker-only HTTP read; parent enforces the total deadline including DNS."""
    import requests

    validate_url(url)
    with requests.Session() as session:
        session.max_redirects = 5
        with session.get(
            url,
            timeout=(5, 10),
            stream=True,
            headers={"User-Agent": "contacts-cli/0.1", "Accept": "text/html,application/xhtml+xml"},
        ) as response:
            response.raise_for_status()
            validate_url(response.url)
            media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if media not in {"text/html", "application/xhtml+xml"}:
                raise SyncError("The URL did not return an HTML page.")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise SyncError("The webpage exceeds the 2 MiB size limit.")
                chunks.append(chunk)
            # requests defaults text/html to Latin-1 without an explicit charset.
            encoding = (
                response.encoding
                if "charset=" in response.headers.get("Content-Type", "").lower()
                else "utf-8"
            )
            return {
                "url": response.url,
                "addresses": extract_addresses(
                    b"".join(chunks).decode(encoding or "utf-8", errors="replace")
                ),
            }


def fetch_addresses(url):
    validate_url(url)
    process = subprocess.Popen(
        [sys.executable, "-m", "contacts_cli.web_emails"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        try:
            output, _ = process.communicate(
                json.dumps({"url": url}).encode(), timeout=FETCH_SECONDS
            )
        except subprocess.TimeoutExpired:
            raise SyncError(
                f"Reading webpage timed out after {FETCH_SECONDS:g} seconds. Retry later."
            ) from None
        if process.returncode:
            raise SyncError("Could not read the webpage.")
        result = json.loads(output)
        if "error" in result:
            raise SyncError(result["error"])
        return result
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                process.kill()
        process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()


def main():
    import requests

    try:
        result = fetch_page(json.load(sys.stdin)["url"])
    except SyncError as exc:
        result = {"error": str(exc)}
    except requests.HTTPError as exc:
        result = {"error": f"Webpage returned HTTP {exc.response.status_code}."}
    except (requests.RequestException, ValueError, LookupError):
        result = {"error": "Could not read the webpage; check its URL and your connection."}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
