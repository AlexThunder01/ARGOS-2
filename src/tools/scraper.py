"""
ARGOS-2 Tool — Web Page Scraper.

Fetches and extracts readable text content from web pages.
Uses requests + html2text for lightweight, JavaScript-free page reading.
Critical for tasks that require navigating URLs and
extracting specific information from web pages.

Dependencies:
  - requests (already in requirements.txt)
  - html2text (new dependency — pure Python, zero system deps)
"""

import requests as http_client

from src.config import SCRAPER_TIMEOUT

from .helpers import _get_arg

# Maximum page size to download (5MB)
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024

# Maximum output text length
MAX_OUTPUT_CHARS = 8000

# Request timeout (configurable via SCRAPER_TIMEOUT env var)
TIMEOUT = SCRAPER_TIMEOUT

# User-Agent header to avoid bot-blocking
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def web_scrape_tool(inp):
    """
    Fetches a URL and extracts readable text content.

    Input:
        {"url": "https://example.com/page"}
        or a raw URL string.

    Returns:
        Extracted text content from the page.
    """
    url = _get_arg(inp, ["url", "link", "page", "website", "href"])
    if not url:
        return "Error: No URL specified. Use {'url': 'https://example.com'}."

    # Ensure protocol
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        response = http_client.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
        response.raise_for_status()

        # Check content type
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return (
                f"⚠️ URL returned non-text content: {content_type}. Cannot extract text."
            )

        # Read with size limit
        content = response.text[:MAX_DOWNLOAD_BYTES]

        # Convert HTML to readable markdown-like text
        try:
            import html2text

            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = True
            h.ignore_emphasis = False
            h.body_width = 0  # No line wrapping
            text = h.handle(content)
        except ImportError:
            # Fallback: basic tag stripping
            import re

            text = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

        if not text.strip():
            return f"🌐 Page '{url}': No extractable text content."

        # Truncate
        if len(text) > MAX_OUTPUT_CHARS:
            text = (
                text[:MAX_OUTPUT_CHARS]
                + f"\n\n... [truncated, {len(text)} total chars]"
            )

        return f"🌐 Content from '{url}':\n\n{text}"

    except http_client.exceptions.Timeout:
        return f"Error: Request to '{url}' timed out ({TIMEOUT}s)."
    except http_client.exceptions.ConnectionError:
        return f"Error: Could not connect to '{url}'. Check the URL or your network."
    except http_client.exceptions.HTTPError as e:
        return f"Error: HTTP {e.response.status_code} for '{url}'."
    except Exception as e:
        return f"Error scraping '{url}': {e}"
