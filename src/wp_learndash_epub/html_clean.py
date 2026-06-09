from __future__ import annotations

import html
import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .models import Heading


DROP_SELECTORS = [
    "script",
    "style",
    "noscript",
    "iframe",
    "form",
    "button",
    ".screen-reader-text",
    ".ld-breadcrumbs",
    ".ld-content-actions",
    ".ld-lesson-status",
    ".learndash-shortcode-wrap-ld_navigation",
    "#ftwp-container-outer",
    "#ftwp-container",
    ".ftwp-wrap",
    ".comment-respond",
    ".ld-focus-comments",
    "[class*='before-content']",
    "[class*='random-paragraph']",
]

ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}


def soup_from_html(markup: str) -> BeautifulSoup:
    return BeautifulSoup(markup, "html.parser")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def text_from(node: Tag | None) -> str:
    return clean_text(node.get_text(" ", strip=True)) if node else ""


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = clean_text(value)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def sanitize_fragment(fragment: BeautifulSoup | Tag) -> str:
    for comment in list(fragment.find_all(string=lambda text: isinstance(text, Comment))):
        comment.extract()

    for selector in DROP_SELECTORS:
        for node in list(fragment.select(selector)):
            node.decompose()

    for tag in list(fragment.find_all(True)):
        if tag.name in {"div", "span"}:
            tag.attrs = {k: v for k, v in tag.attrs.items() if k == "id"}
            continue
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue

        attrs: dict[str, str] = {}
        if tag.get("id"):
            attrs["id"] = clean_text(str(tag["id"]))
        if tag.name == "a" and tag.get("href"):
            href = clean_text(str(tag["href"]))
            if href.startswith("#") or href.startswith(("http://", "https://")):
                attrs["href"] = href
        if tag.name in {"td", "th"}:
            for attr in ("colspan", "rowspan"):
                if tag.get(attr):
                    attrs[attr] = clean_text(str(tag[attr]))
        tag.attrs = attrs

    for image in list(fragment.find_all("img")):
        image.decompose()

    for tag in list(fragment.find_all(["span", "div"])):
        if not tag.attrs:
            tag.unwrap()

    for tag in list(fragment.find_all(["p", "strong", "b", "em", "i", "li"])):
        if not text_from(tag) and not tag.find("br"):
            tag.decompose()

    html_parts: list[str] = []
    root = fragment.body if isinstance(fragment, BeautifulSoup) and fragment.body else fragment
    for child in root.children:
        if isinstance(child, NavigableString):
            text = clean_text(str(child))
            if text:
                html_parts.append(f"<p>{html.escape(text)}</p>")
        else:
            html_parts.append(str(child))
    return "\n".join(
        part
        for part in html_parts
        if clean_text(BeautifulSoup(part, "html.parser").get_text(" ", strip=True)) or "<hr" in part
    )


def assign_heading_ids(body_html: str, file_name: str) -> tuple[str, list[Heading]]:
    soup = BeautifulSoup(body_html, "html.parser")
    headings: list[Heading] = []
    used: set[str] = set()
    counter = 1
    for tag in soup.find_all(re.compile("^h[2-4]$")):
        title = text_from(tag)
        if not title:
            continue
        existing = clean_text(str(tag.get("id", "")))
        heading_id = re.sub(r"[^A-Za-z0-9_.:-]+", "-", existing).strip("-")
        if not heading_id:
            heading_id = f"section-{counter}"
        while heading_id in used:
            counter += 1
            heading_id = f"section-{counter}"
        used.add(heading_id)
        tag["id"] = heading_id
        headings.append(Heading(title=title, target=f"{file_name}#{heading_id}", level=int(tag.name[1])))
        counter += 1
    return str(soup), headings
