"""URL content fetcher — httpx GET + BeautifulSoup main-content extraction."""
from __future__ import annotations

import ipaddress
import urllib.parse

import httpx
from bs4 import BeautifulSoup

_TIMEOUT = httpx.Timeout(30.0)
_HEADERS = {"User-Agent": "MindVault/1.0 (knowledge-preservation-tool)"}

# Tags that typically contain noise rather than main content
_NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]

# Only allow safe, routable URL schemes
_ALLOWED_SCHEMES = {"http", "https"}


def _validate_url(url: str) -> None:
    """
    Reject URLs that could be used for Server-Side Request Forgery (SSRF).

    Blocks:
    - Non-HTTP/S schemes (file://, ftp://, gopher://, etc.)
    - Bare IP literals that resolve to private, loopback, link-local, or reserved
      address spaces (RFC 1918 / RFC 4193 / RFC 3927).

    Note: hostname-based SSRF via DNS rebinding is not mitigated here because it
    requires an async DNS pre-check with atomic connection binding. For a local
    single-user tool this risk is acceptable; add a DNS-resolution guard if the
    service is ever exposed to untrusted networks.
    """
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"URL scheme '{parsed.scheme}' is not allowed. Only http and https are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no valid hostname.")

    # Attempt to parse the hostname as a raw IP address. If it succeeds, block
    # any address that is not a publicly routable unicast address.
    try:
        addr = ipaddress.ip_address(hostname)
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise ValueError(
                "URLs targeting private, loopback, link-local, or reserved IP addresses are not permitted."
            )
    except ValueError as exc:
        # Re-raise SSRF rejections; ignore the error when hostname is a DNS name
        # (ip_address() raises ValueError for non-numeric strings).
        if "not permitted" in str(exc) or "not allowed" in str(exc):
            raise


def fetch_url(url: str) -> tuple[str, str]:
    """
    Fetch a URL and return (title, extracted_text).

    Raises ValueError for disallowed URLs (SSRF guard).
    Raises httpx.HTTPError on network/HTTP errors.
    """
    _validate_url(url)

    with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove noise elements
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url

    # Prefer <main> or <article> if available
    main = soup.find("main") or soup.find("article")
    container = main if main else soup.find("body") or soup

    text = container.get_text(separator="\n", strip=True)
    # Collapse excessive blank lines
    lines = [line for line in text.splitlines() if line.strip()]
    return title, "\n".join(lines)
