"""Command line: schema-lint <url|file|dir> ... [--crawl] [--format md|json|sarif] [--fail-on error]."""
from __future__ import annotations

import argparse
import pathlib
import sys

from . import __version__
from .lint import MAX_PAGES, USER_AGENT, Fetcher, FetchError, crawl, lint_file, lint_url
from .model import RANK
from .report import FORMATS, counts

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse exits with 2 already; keep the message short
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"schema-lint: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="schema-lint",
                description="Validate JSON-LD, microdata and RDFa Lite against the schema.org vocabulary "
                            "and a summary of Google's rich-result requirements.")
    p.add_argument("targets", nargs="+", help="http(s) URLs, HTML/JSON-LD files, or directories of .html files")
    p.add_argument("--crawl", action="store_true",
                   help=f"follow same-origin links from each URL (robots.txt honoured, at most {MAX_PAGES} pages)")
    p.add_argument("--max-pages", type=int, default=MAX_PAGES, help=f"pages per crawl (1-{MAX_PAGES}, default {MAX_PAGES})")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests (minimum 1, default 1)")
    p.add_argument("--format", choices=["md", "json", "sarif"], default="md", help="output format (default md)")
    p.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    p.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default="error",
                   help="exit 1 when a finding at or above this severity exists (default error)")
    p.add_argument("--no-google", action="store_true", help="skip the Google rich-result table")
    p.add_argument("--render", action="store_true", help="render pages with Playwright/Chromium before extracting")
    p.add_argument("--user-agent", default=USER_AGENT)
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--version", action="version", version=f"schema-lint {__version__}")
    return p


def _files(target: str) -> list[str]:
    path = pathlib.Path(target)
    if path.is_dir():
        return sorted(str(f) for f in path.rglob("*") if f.suffix.lower() in (".html", ".htm", ".jsonld"))
    if path.is_file():
        return [target]
    raise FileNotFoundError(target)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_pages < 1 or args.max_pages > MAX_PAGES:
        print(f"schema-lint: --max-pages must be between 1 and {MAX_PAGES}", file=sys.stderr)
        return EXIT_USAGE
    if args.delay < 1:
        print("schema-lint: --delay must be at least 1 second", file=sys.stderr)
        return EXIT_USAGE
    google = not args.no_google
    fetcher = Fetcher(args.user_agent, args.delay, args.timeout, args.render)
    pages = []
    try:
        for target in args.targets:
            if target.startswith(("http://", "https://")):
                if args.crawl:
                    pages += crawl(target, fetcher, args.max_pages, google,
                                   log=lambda u: print(f"fetching {u}", file=sys.stderr))
                else:
                    pages.append(lint_url(target, fetcher, google)[0])
            else:
                for f in _files(target):
                    pages.append(lint_file(f, google))
    except FetchError as e:
        print(f"schema-lint: {e}", file=sys.stderr)
        return EXIT_USAGE
    except (FileNotFoundError, IsADirectoryError, PermissionError) as e:
        print(f"schema-lint: cannot read {e.filename if hasattr(e, 'filename') and e.filename else e}",
              file=sys.stderr)
        return EXIT_USAGE
    finally:
        fetcher.close()
    text = FORMATS[args.format](pages)
    if args.output:
        pathlib.Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.format != "md" or args.output:
        c = counts(pages)
        print(f"{c['error']} error(s), {c['warning']} warning(s), {c['info']} info", file=sys.stderr)
    if args.fail_on == "never":
        return EXIT_OK
    threshold = RANK[args.fail_on]
    worst = max((RANK[f.severity] for p in pages for f in p.findings), default=0)
    return EXIT_FINDINGS if worst >= threshold else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
