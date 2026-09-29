"""Lint pages: HTML in, findings out. Fetching and crawling live here too."""
from __future__ import annotations

import collections
import pathlib
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urldefrag, urlsplit

from . import __version__, rfc9309
from .checks import Checker
from .extract import extract, links
from .google import GoogleCheck
from .model import Finding, Page
from .vocab import load

USER_AGENT = f"schema-lint/{__version__.split('.')[0]}.0 (+https://github.com/dreadmoreeee/schema-lint)"
MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 30
SKIP_EXT = re.compile(r"\.(?:jpe?g|png|gif|webp|avif|svg|ico|pdf|zip|gz|mp3|mp4|webm|woff2?|ttf|css|js|json|xml|txt)$",
                      re.I)


class FetchError(Exception):
    pass


def lint_html(html: str, url: str = "", google: bool = True, base: str | None = None) -> Page:
    """Lint one HTML document. url labels the findings; base resolves relative links (defaults to url)."""
    vocab = load()
    items, findings = extract(html, base if base is not None else url)
    for f in findings:
        f.url = url
    checker = Checker(vocab, url)
    findings += checker.run(items)
    if google:
        findings += GoogleCheck(vocab, checker.index, url).run(items)
    return Page(url, items, findings)


def lint_file(path: str, google: bool = True) -> Page:
    """Lint a local .html file, or a .json/.jsonld file holding one JSON-LD document."""
    p = pathlib.Path(path)
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    if p.suffix.lower() in (".json", ".jsonld"):
        text = f'<script type="application/ld+json">{text}</script>'
    return lint_html(text, p.as_posix(), google, base=p.resolve().as_uri())


class Fetcher:
    """GET with a User-Agent and a minimum gap between requests to the same run."""

    def __init__(self, user_agent: str = USER_AGENT, delay: float = 1.0, timeout: float = 20.0,
                 render: bool = False) -> None:
        self.user_agent, self.delay, self.timeout, self.render = user_agent, delay, timeout, render
        self._last = 0.0
        self.count = 0
        self._browser = None
        self._pw = None

    def wait(self) -> None:
        gap = time.monotonic() - self._last
        if self._last and gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()
        self.count += 1

    def get(self, url: str) -> tuple[str, str, str]:
        """Return (final_url, content_type, text)."""
        self.wait()
        if self.render:
            return self._render(url)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent,
                                                   "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                ctype = resp.headers.get("Content-Type", "")
                raw = resp.read(MAX_BYTES)
                final = resp.geturl()
        except urllib.error.HTTPError as e:
            raise FetchError(f"{url}: HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise FetchError(f"{url}: {getattr(e, 'reason', e)}") from None
        m = re.search(r"charset=([\w-]+)", ctype, re.I)
        charset = m.group(1) if m else "utf-8"
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        return final, ctype, text

    def _render(self, url: str) -> tuple[str, str, str]:
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise FetchError("--render needs Playwright: pip install playwright && playwright install chromium") \
                    from None
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
        page = self._browser.new_page(user_agent=self.user_agent)
        try:
            resp = page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
            if resp is None or resp.status >= 400:
                raise FetchError(f"{url}: HTTP {resp.status if resp else '?'}")
            return page.url, resp.headers.get("content-type", "text/html"), page.content()
        except FetchError:
            raise
        except Exception as e:  # Playwright timeout and friends
            raise FetchError(f"{url}: {e.__class__.__name__}: {str(e).splitlines()[0]}") from None
        finally:
            page.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._pw.stop()
            self._browser = None


def lint_url(url: str, fetcher: Fetcher, google: bool = True) -> tuple[Page, str]:
    final, ctype, text = fetcher.get(url)
    if "html" not in ctype.lower() and "json" in ctype.lower():
        text = f'<script type="application/ld+json">{text}</script>'
    page = lint_html(text, final, google)
    return page, text


def _origin(url: str) -> tuple[str, str]:
    p = urlsplit(url)
    return p.scheme.lower(), p.netloc.lower()


def crawl(start: str, fetcher: Fetcher, max_pages: int = MAX_PAGES, google: bool = True,
          log=None) -> list[Page]:
    """Same-origin breadth-first crawl that honours robots.txt (RFC 9309)."""
    max_pages = max(1, min(max_pages, MAX_PAGES))
    origin = _origin(start)
    fetcher.wait()
    robots = rfc9309.fetch(f"{origin[0]}://{origin[1]}", fetcher.user_agent, fetcher.timeout)
    delay = robots.crawl_delay(fetcher.user_agent)
    if delay:
        fetcher.delay = max(fetcher.delay, min(delay, 30.0))
    queue = collections.deque([urldefrag(start)[0]])
    seen = {queue[0]}
    pages: list[Page] = []
    loaded = 0
    while queue and loaded < max_pages:
        url = queue.popleft()
        if not robots.can_fetch(fetcher.user_agent, url):
            pages.append(Page(url, findings=[Finding("info", "robots-disallowed",
                                                     "skipped: disallowed by robots.txt", url=url)]))
            continue
        if log:
            log(url)
        loaded += 1
        try:
            page, text = lint_url(url, fetcher, google)
        except FetchError as e:
            if loaded == 1:
                raise
            pages.append(Page(url, error=str(e), findings=[Finding("warning", "fetch-error", str(e), url=url)]))
            continue
        pages.append(page)
        if _origin(page.url) != origin:
            continue
        for link in links(text, page.url):
            link = urldefrag(link)[0]
            p = urlsplit(link)
            if (_origin(link) != origin or link in seen or "/cdn-cgi/" in p.path or SKIP_EXT.search(p.path)):
                continue
            seen.add(link)
            queue.append(link)
    return pages
