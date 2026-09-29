"""schema-lint: validate structured data (JSON-LD, microdata, RDFa Lite) against schema.org."""
from __future__ import annotations

__version__ = "1.0.0"

from .model import Finding, Item, Page, Ref  # noqa: E402
from .lint import crawl, lint_file, lint_html, lint_url  # noqa: E402

__all__ = ["lint_html", "lint_file", "lint_url", "crawl", "Finding", "Item", "Page", "Ref", "__version__"]
