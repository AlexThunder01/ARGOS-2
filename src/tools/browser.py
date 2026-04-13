"""
ARGOS-2 Tool — Stateful Playwright Browser.

Enables multi-step web navigation with JavaScript support.
Maintains a single headless browser session across tool calls within a task.

Dependencies:
  - playwright (pip install playwright && playwright install chromium)
  - html2text (already in requirements)
"""

import atexit
import threading

from .helpers import _get_arg

_lock = threading.Lock()
_state: dict = {"pw": None, "browser": None, "page": None}


def _ensure_page():
    """Lazily initialize Playwright and return (page, error_string)."""
    with _lock:
        if _state["page"] is not None:
            return _state["page"], None
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None, (
                "Error: playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            )
            _state["pw"] = pw
            _state["browser"] = browser
            _state["page"] = page
            return page, None
        except Exception as e:
            return None, f"Error starting browser: {e}"


def _cleanup():
    with _lock:
        if _state["browser"]:
            try:
                _state["browser"].close()
            except Exception:
                pass
        if _state["pw"]:
            try:
                _state["pw"].stop()
            except Exception:
                pass
        _state["browser"] = None
        _state["pw"] = None
        _state["page"] = None


atexit.register(_cleanup)


def _page_to_text(page, max_chars: int = 12000) -> str:
    """Convert current page HTML to readable markdown-ish text."""
    try:
        from html2text import html2text

        # If URL has an anchor, try to surface that section first
        current_url = page.url
        anchor = None
        if "#" in current_url:
            anchor = current_url.split("#", 1)[1]

        if anchor:
            try:
                element = page.query_selector(f"#{anchor}, [name='{anchor}']")
                if element:
                    # Walk siblings after the anchor, collecting text until next header
                    section_text = page.evaluate(
                        """(el) => {
                            var result = '';
                            // The anchor might be inside an <h> tag — start from parent's siblings
                            var node = el.parentElement || el;
                            node = node.nextElementSibling;
                            var steps = 0;
                            while (node && steps < 20) {
                                var tag = node.tagName || '';
                                if (tag === 'H1' || tag === 'H2' || tag === 'H3') break;
                                result += (node.innerText || '') + '\\n';
                                node = node.nextElementSibling;
                                steps++;
                            }
                            return result;
                        }""",
                        element,
                    )
                    if section_text and len(section_text.strip()) > 100:
                        full_html = page.content()
                        full_text = html2text(full_html)
                        combined = (
                            f"[Section '{anchor}' content]:\n{section_text.strip()}\n\n"
                            f"[Full page excerpt]:\n{full_text}"
                        )
                        if len(combined) > max_chars:
                            combined = combined[:max_chars] + "\n... [truncated]"
                        return combined
            except Exception:
                pass

        html = page.content()
        text = html2text(html)
    except Exception:
        try:
            text = page.inner_text("body")
        except Exception:
            return "[Could not extract page content]"

    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated]"
    return text


# ─── Tools ────────────────────────────────────────────────────────────────────


def browser_navigate_tool(inp):
    """
    Navigates to a URL and returns the rendered page content (handles JS-heavy pages).

    Input:
        {"url": "https://example.com"}
    """
    url = _get_arg(inp, ["url"])
    if not url:
        return "Error: No URL specified."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    page, err = _ensure_page()
    if err:
        return err

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        title = page.title()
        text = _page_to_text(page)
        return f"Title: {title}\nURL: {page.url}\n\n{text}"
    except Exception as e:
        return f"Error navigating to '{url}': {e}"


def browser_click_tool(inp):
    """
    Clicks an element on the current browser page by visible text or CSS selector.
    Returns the new page content after the click.

    Input:
        {"text": "Next page"}
        {"selector": "button.submit"}
    """
    target = _get_arg(inp, ["text", "selector", "target"])
    if not target:
        return "Error: Specify 'text' (visible label) or 'selector' (CSS) to click."

    page, err = _ensure_page()
    if err:
        return err

    try:
        # Try exact/partial text match first, then CSS selector
        try:
            page.click(f"text={target}", timeout=5000)
        except Exception:
            page.click(target, timeout=5000)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        title = page.title()
        text = _page_to_text(page)
        return f"Clicked '{target}'.\nTitle: {title}\nURL: {page.url}\n\n{text}"
    except Exception as e:
        return f"Error clicking '{target}': {e}"


def browser_type_tool(inp):
    """
    Types text into a form field on the current browser page.

    Input:
        {"selector": "input[name='q']", "text": "search query"}
        {"selector": "Search", "text": "search query", "press_enter": true}
    """
    selector = _get_arg(inp, ["selector", "target", "field"])
    text = _get_arg(inp, ["text", "value", "query"])
    if not selector or not text:
        return "Error: Specify 'selector' (field) and 'text' (value to type)."

    press_enter = bool(inp.get("press_enter")) if isinstance(inp, dict) else False

    page, err = _ensure_page()
    if err:
        return err

    try:
        # Try CSS selector first, then individual fallback strategies
        filled = False
        try:
            page.fill(selector, text, timeout=5000)
            filled = True
        except Exception:
            pass

        if not filled:
            # Try each strategy separately to avoid CSS injection issues when selector
            # itself contains quotes or special characters (e.g. "input[name='q']")
            for strategy in [
                lambda: page.get_by_placeholder(selector).first.fill(text, timeout=3000),
                lambda: page.get_by_label(selector).first.fill(text, timeout=3000),
                lambda: page.locator(f"[name='{selector}']").first.fill(text, timeout=3000),
                lambda: page.locator("input, textarea").first.fill(text, timeout=3000),
            ]:
                try:
                    strategy()
                    filled = True
                    break
                except Exception:
                    continue

        if not filled:
            return f"Error typing into '{selector}': could not find field with any strategy."

        if press_enter:
            page.keyboard.press("Enter")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            title = page.title()
            text_content = _page_to_text(page)
            return f"Typed and pressed Enter.\nTitle: {title}\nURL: {page.url}\n\n{text_content}"

        return f"Typed '{text}' into '{selector}'."
    except Exception as e:
        return f"Error typing into '{selector}': {e}"


def browser_get_content_tool(inp):
    """
    Returns the text content of the current browser page.
    Use after browser_click or browser_navigate to re-read the page.

    Input: {} (no arguments needed)
    """
    page, err = _ensure_page()
    if err:
        return err

    try:
        title = page.title()
        text = _page_to_text(page)
        return f"Title: {title}\nURL: {page.url}\n\n{text}"
    except Exception as e:
        return f"Error getting page content: {e}"
