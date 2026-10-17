"""Read-only ingestion tools for the deep dive. Fetched content is untrusted (prompt injection).

`fetch_text` is the only network door: http(s) only, public addresses only (every redirect hop is
re-checked), size and time caps, and an allow-list of content types. It never writes anywhere.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_S = 20.0
MAX_REDIRECTS = 4
MAX_PAGES = 60
USER_AGENT = "ResearchRadar-DeepDive/0.1 (personal research digest)"

_ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf|html)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?/?$")


class FetchError(Exception):
    """Raised for anything the user should see as 'could not read that page'."""


@dataclass
class Doc:
    url: str
    title: str
    kind: str  # html | pdf | text
    pages: list[str] = field(default_factory=list)  # one entry per PDF page, or a single entry

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)


def check_url(url: str) -> str:
    """Raise FetchError unless `url` is http(s) and every address it resolves to is public."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("Only http(s) links can be read.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise FetchError(f"Could not resolve {parsed.hostname}.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:  # private, loopback, link-local, multicast, reserved, ...
            raise FetchError("That address is not a public website, so it was not fetched.")
    return url


def _get(url: str, client: httpx.Client) -> tuple[str, str, bytes]:
    """GET with manual redirects (each hop re-checked), streamed with a byte cap."""
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        with client.stream("GET", url, follow_redirects=False) as resp:
            if resp.is_redirect:
                url = urljoin(url, resp.headers.get("location", ""))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"The site answered with an error ({resp.status_code}).")
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if not (ctype.startswith("text/") or ctype in ("application/pdf", "application/xhtml+xml")):
                raise FetchError(f"Unsupported content type: {ctype or 'unknown'}.")
            body = bytearray()
            for chunk in resp.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise FetchError("That document is too large to read.")
            return url, ctype, bytes(body)
    raise FetchError("Too many redirects.")


def _pdf_pages(data: bytes) -> list[str]:
    import pymupdf

    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            return [p.get_text() for _, p in zip(range(MAX_PAGES), pdf, strict=False)]
    except Exception as e:  # corrupt or encrypted file
        raise FetchError("Could not open that PDF.") from e


def _html_text(html: str, url: str) -> tuple[str, str]:
    import trafilatura

    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True)
    meta = trafilatura.extract_metadata(html)
    return (text or ""), ((meta.title if meta and meta.title else "") or url)


def candidate_urls(url: str) -> list[str]:
    """arXiv pages: the full-text HTML first, then the PDF, then the abstract page itself."""
    m = _ARXIV_ID.search(url)
    if not m:
        return [url]
    pid = m.group(1)
    return [f"https://arxiv.org/html/{pid}", f"https://arxiv.org/pdf/{pid}", url]


def fetch_text(url: str, *, client: httpx.Client | None = None) -> Doc:
    """Fetch a paper or web page as plain text. Raises FetchError with a reader-safe message."""
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    last: FetchError | None = None
    try:
        for target in candidate_urls(url):
            try:
                final, ctype, body = _get(target, client)
                if ctype == "application/pdf":
                    pages = _pdf_pages(body)
                    if sum(len(p) for p in pages) > 200:
                        return Doc(final, url, "pdf", pages)
                    raise FetchError("That PDF has no readable text.")
                text, title = _html_text(body.decode("utf-8", errors="replace"), final)
                if len(text) > 500:
                    return Doc(final, title, "html" if ctype != "text/plain" else "text", [text])
                raise FetchError("No readable article text was found on that page.")
            except (FetchError, httpx.HTTPError) as e:
                last = e if isinstance(e, FetchError) else FetchError("The site could not be reached.")
        raise last or FetchError("Could not read that page.")
    finally:
        if own:
            client.close()
