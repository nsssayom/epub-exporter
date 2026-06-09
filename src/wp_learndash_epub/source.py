from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .html_clean import (
    assign_heading_ids,
    clean_text,
    sanitize_fragment,
    soup_from_html,
    text_from,
    unique_preserving_order,
)
from .http import fetch_json, fetch_text
from .models import Book, Chapter, Credentials, LessonLink


def rest_api_base(source_url: str) -> str:
    parsed = urlparse(source_url)
    return f"{parsed.scheme}://{parsed.netloc}/wp-json"


def safe_file_stem(title: str, source_url: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "", title)
    text = re.sub(r"\s+", "-", text).strip("-")
    if text:
        return text[:80]
    digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:10]
    return f"book-{digest}"


def book_title(soup: BeautifulSoup) -> str:
    for selector in ("h1.page-header-title", "h1", "meta[property='og:title']"):
        node = soup.select_one(selector)
        if not node:
            continue
        title = node.get("content", "") if node.name == "meta" else text_from(node)
        if title:
            return title
    raise RuntimeError("Could not find a title on the source page.")


def book_authors(soup: BeautifulSoup) -> list[str]:
    authors = [text_from(a) for a in soup.select(".entry-terms-authors a")]
    authors = unique_preserving_order(authors)
    return authors or ["Unknown"]


def course_id(soup: BeautifulSoup) -> int:
    for selector in ("[id^='learndash_post_']", "body"):
        node = soup.select_one(selector)
        if not node:
            continue
        node_id = str(node.get("id", ""))
        match = re.search(r"learndash_post_(\d+)", node_id)
        if match:
            return int(match.group(1))
        classes = " ".join(str(value) for value in node.get("class", []))
        match = re.search(r"\bpostid-(\d+)\b", classes)
        if match:
            return int(match.group(1))
    raise RuntimeError("Could not find the LearnDash course ID on the source page.")


def cover_url(soup: BeautifulSoup, base_url: str) -> str | None:
    for selector, attr in (
        ("meta[property='og:image']", "content"),
        ("figure.entry-image-link img", "data-src"),
        ("figure.entry-image-link img", "src"),
        ("img.entry-image", "data-src"),
        ("img.entry-image", "src"),
    ):
        node = soup.select_one(selector)
        if node and node.get(attr):
            return urljoin(base_url, str(node[attr]))
    return None


def lesson_links(soup: BeautifulSoup, base_url: str) -> list[LessonLink]:
    candidates = soup.select(".ld-lesson-list a.ld-item-name[href], .ld-item-list a.ld-item-name[href]")
    if not candidates:
        candidates = soup.select("main a[href*='/lessons/'], article a[href*='/lessons/']")

    seen: set[str] = set()
    lessons: list[LessonLink] = []
    for link in candidates:
        href = str(link.get("href", ""))
        if "/lessons/" not in href:
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        title_node = link.select_one(".ld-item-title")
        title = text_from(title_node) or text_from(link)
        if title:
            lessons.append(LessonLink(title=title, url=absolute))
    return lessons


def extract_intro_html(soup: BeautifulSoup) -> str:
    intro = soup.select_one(".ld-tabs-content .ld-tab-content.entry-content")
    if not intro:
        intro = soup.select_one("article .entry-content")
    if not intro:
        return ""
    fragment = BeautifulSoup(str(intro), "html.parser")
    for node in fragment.select(".learndash-shortcode-wrap-course_content, .ld-item-list"):
        node.decompose()
    return sanitize_fragment(fragment)


def parse_book(source_url: str, language: str, publisher: str | None = None) -> Book:
    soup = soup_from_html(fetch_text(source_url))
    lessons = lesson_links(soup, source_url)
    if not lessons:
        raise RuntimeError("No lesson links found. The source page may not be a LearnDash course page.")
    return Book(
        title=book_title(soup),
        authors=book_authors(soup),
        source_url=source_url,
        course_id=course_id(soup),
        intro_html=extract_intro_html(soup),
        lessons=lessons,
        cover_url=cover_url(soup, source_url),
        language=language,
        publisher=publisher,
    )


def extract_lesson_content(soup: BeautifulSoup) -> Tag:
    for selector in (
        ".ld-tab-content.entry-content #ftwp-postcontent",
        ".ld-tab-content.entry-content",
        ".ld-focus-content",
    ):
        content = soup.select_one(selector)
        if content:
            return content
    raise RuntimeError("Could not find lesson content in the rendered page.")


def lesson_title(soup: BeautifulSoup, fallback: str) -> str:
    for selector in (".ld-focus-content > h1", "h1", "meta[property='og:title']"):
        node = soup.select_one(selector)
        if not node:
            continue
        title = node.get("content", "") if node.name == "meta" else text_from(node)
        if title:
            return title
    return fallback


def parse_lesson_page(link: LessonLink, index: int) -> Chapter:
    soup = soup_from_html(fetch_text(link.url))
    title = lesson_title(soup, link.title)
    content = extract_lesson_content(soup)
    body_html = sanitize_fragment(BeautifulSoup(str(content), "html.parser"))
    file_name = f"chapter-{index:03d}.xhtml"
    body_html, headings = assign_heading_ids(body_html, file_name)
    return Chapter(title=title, url=link.url, file_name=file_name, body_html=body_html, headings=headings)


def parse_rest_lesson(item: dict[str, object], index: int, fallback_url: str = "") -> Chapter:
    title_value = item.get("title")
    if isinstance(title_value, dict):
        title = clean_text(str(title_value.get("rendered") or title_value.get("raw") or ""))
    else:
        title = clean_text(str(title_value or ""))
    if not title:
        title = f"Chapter {index}"

    content_value = item.get("content")
    rendered = ""
    if isinstance(content_value, dict):
        rendered = str(content_value.get("rendered") or "")
    if not rendered:
        raise RuntimeError(f"REST lesson {item.get('id') or index} did not include rendered content.")

    soup = soup_from_html(rendered)
    content = soup.select_one("#ftwp-postcontent") or soup
    body_html = sanitize_fragment(BeautifulSoup(str(content), "html.parser"))
    file_name = f"chapter-{index:03d}.xhtml"
    body_html, headings = assign_heading_ids(body_html, file_name)
    link = item.get("link")
    url = str(link) if link else fallback_url
    return Chapter(title=title, url=url, file_name=file_name, body_html=body_html, headings=headings)


def parse_lessons_via_rest(book: Book, credentials: Credentials) -> list[Chapter]:
    query = urlencode(
        {
            "course": book.course_id,
            "per_page": 100,
            "orderby": "menu_order",
            "order": "asc",
        }
    )
    url = f"{rest_api_base(book.source_url)}/ldlms/v2/sfwd-lessons?{query}"
    data = fetch_json(url, credentials=credentials)
    if not isinstance(data, list):
        raise RuntimeError("LearnDash REST lesson list did not return a list.")
    if not data:
        raise RuntimeError("LearnDash REST returned no lessons for this course.")

    chapters: list[Chapter] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            continue
        fallback_url = book.lessons[index - 1].url if index - 1 < len(book.lessons) else ""
        chapters.append(parse_rest_lesson(item, index, fallback_url=fallback_url))
    if not chapters:
        raise RuntimeError("LearnDash REST returned no parseable lessons.")
    return chapters


def default_output_path(book: Book) -> Path:
    return Path.cwd() / f"{safe_file_stem(book.title, book.source_url)}.epub"
