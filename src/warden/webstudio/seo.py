"""Deterministic SEO/AEO/site-readiness checks for SMB websites.

Heuristic and dependency-light: uses the stdlib HTML parser only, so it works
without a browser or network access when given raw HTML/text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional


@dataclass
class SeoCheckResult:
    title: Optional[str] = None
    meta_description: Optional[str] = None
    canonical: Optional[str] = None
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    has_json_ld: bool = False
    json_ld_types: list[str] = field(default_factory=list)
    has_local_business_schema: bool = False
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "meta_description": self.meta_description,
            "canonical": self.canonical,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image": self.og_image,
            "has_json_ld": self.has_json_ld,
            "json_ld_types": self.json_ld_types,
            "has_local_business_schema": self.has_local_business_schema,
            "issues": self.issues,
        }


class _HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self._in_title = False
        self.meta_tags: list[dict[str, str]] = []
        self.link_tags: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.meta_tags.append(attr_dict)
        elif tag == "link":
            self.link_tags.append(attr_dict)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)


def check_html(html: str) -> SeoCheckResult:
    parser = _HeadParser()
    parser.feed(html)
    result = SeoCheckResult()

    result.title = ("".join(parser.title_parts).strip() or None)
    if not result.title:
        result.issues.append("missing <title>")
    elif len(result.title) > 65:
        result.issues.append("title longer than 65 characters")

    for meta in parser.meta_tags:
        name = meta.get("name", "").lower()
        prop = meta.get("property", "").lower()
        content = meta.get("content", "")
        if name == "description":
            result.meta_description = content or None
        elif prop == "og:title":
            result.og_title = content or None
        elif prop == "og:description":
            result.og_description = content or None
        elif prop == "og:image":
            result.og_image = content or None

    if not result.meta_description:
        result.issues.append("missing meta description")
    elif len(result.meta_description) > 160:
        result.issues.append("meta description longer than 160 characters")

    for link in parser.link_tags:
        if link.get("rel", "").lower() == "canonical":
            result.canonical = link.get("href") or None
    if not result.canonical:
        result.issues.append("missing canonical link")

    if not result.og_title:
        result.issues.append("missing og:title")
    if not result.og_description:
        result.issues.append("missing og:description")
    if not result.og_image:
        result.issues.append("missing og:image")

    json_ld_blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if json_ld_blocks:
        result.has_json_ld = True
        for block in json_ld_blocks:
            types = re.findall(r'"@type"\s*:\s*"([^"]+)"', block)
            result.json_ld_types.extend(types)
            if any("localbusiness" in t.lower() for t in types):
                result.has_local_business_schema = True
    else:
        result.issues.append("missing JSON-LD structured data")

    return result


def check_site_files(repo_path: Path, *, public_dir_candidates: tuple[str, ...] = ("public", "static", ".")) -> dict:
    """Check for robots.txt, sitemap.xml, and llms.txt presence in common public dirs."""
    found: dict[str, Optional[str]] = {"robots_txt": None, "sitemap_xml": None, "llms_txt": None}
    for candidate in public_dir_candidates:
        base = repo_path / candidate
        if not base.exists():
            continue
        for filename, key in (
            ("robots.txt", "robots_txt"),
            ("sitemap.xml", "sitemap_xml"),
            ("llms.txt", "llms_txt"),
        ):
            target = base / filename
            if target.exists() and found[key] is None:
                found[key] = str(target.relative_to(repo_path))
    issues = [f"missing {key.replace('_', '.')}" for key, value in found.items() if value is None]
    return {**found, "issues": issues}


def check_homepage_file(repo_path: Path, homepage_relpath: str) -> dict:
    """Run HTML checks against a homepage file (e.g. a built index.html)."""
    target = repo_path / homepage_relpath
    if not target.exists():
        return {"path": homepage_relpath, "exists": False, "issues": ["homepage file not found"]}
    html = target.read_text(encoding="utf-8", errors="replace")
    checks = check_html(html)
    payload = checks.to_dict()
    payload["path"] = homepage_relpath
    payload["exists"] = True
    return payload
