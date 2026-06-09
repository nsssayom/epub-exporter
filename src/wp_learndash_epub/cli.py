from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from rich.prompt import Confirm

from .config import load_env_file, settings_from_environment
from .epub import fetch_cover_asset, write_epub
from .models import Book, Chapter, Credentials
from .source import default_output_path, parse_book, parse_lesson_page, parse_lessons_via_rest
from .ui import build_summary, console, header, lesson_table, progress, source_table


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wp-learndash-epub",
        description="Export a WordPress + LearnDash course/book page to EPUB.",
    )
    parser.add_argument("url", nargs="?", help="Course/book landing page URL.")
    parser.add_argument("-o", "--output", type=Path, help="Output .epub path.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Path to .env file.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect metadata and lesson structure only.")
    parser.add_argument("--no-rest", action="store_true", help="Disable authenticated LearnDash REST.")
    parser.add_argument("--language", help="EPUB language code, default from .env or bn.")
    parser.add_argument("--publisher", help="Optional EPUB publisher metadata.")
    parser.add_argument("--sleep", type=float, default=0.75, help="Delay between HTML fallback lesson requests.")
    parser.add_argument("--confirm-rights", action="store_true", help="Confirm you may export this content.")
    return parser.parse_args(argv)


def resolve_credentials(no_rest: bool, credentials: Credentials | None) -> Credentials | None:
    if no_rest:
        return None
    if credentials and credentials.is_complete:
        return credentials
    return None


def fetch_html_chapters(book: Book, delay: float) -> list[Chapter]:
    chapters: list[Chapter] = []
    with progress() as bar:
        task = bar.add_task("Fetching rendered lesson pages", total=len(book.lessons))
        for index, lesson in enumerate(book.lessons, 1):
            chapters.append(parse_lesson_page(lesson, index))
            bar.advance(task)
            if delay and index < len(book.lessons):
                time.sleep(delay)
    return chapters


def fetch_chapters(book: Book, credentials: Credentials | None, delay: float) -> list[Chapter]:
    if credentials:
        with progress() as bar:
            task = bar.add_task("Fetching lessons through LearnDash REST", total=1)
            chapters = parse_lessons_via_rest(book, credentials)
            bar.update(task, completed=1)
        return chapters
    return fetch_html_chapters(book, delay)


def run_epubcheck(output: Path) -> str:
    if not shutil.which("epubcheck"):
        return "not installed"
    completed = subprocess.run(
        ["epubcheck", str(output)],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        details = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        raise RuntimeError(f"EPUBCheck failed:\n{details}")
    return "passed"


def run(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    settings = settings_from_environment()
    source_url = args.url or settings.book_url
    if not source_url:
        raise RuntimeError("No source URL supplied. Pass a URL or set WP_LMS_BOOK_URL in .env.")

    language = args.language or settings.language
    publisher = args.publisher or settings.publisher
    output = args.output or settings.output
    credentials = resolve_credentials(args.no_rest, settings.credentials)

    header()
    with console.status("[bold cyan]Reading source page...[/bold cyan]", spinner="dots"):
        book = parse_book(source_url, language=language, publisher=publisher)
    if output is None:
        output = default_output_path(book)

    console.print(source_table(book, rest_enabled=bool(credentials), output=output))

    if args.dry_run:
        if credentials:
            chapters = fetch_chapters(book, credentials, args.sleep)
            console.print(lesson_table(chapters))
        else:
            console.print("[yellow]REST credentials not available; dry-run used the rendered index only.[/yellow]")
        return 0

    if not args.confirm_rights:
        if not Confirm.ask("Confirm you may export this content into a local EPUB", default=False):
            console.print("[red]Export cancelled.[/red]")
            return 2

    chapters = fetch_chapters(book, credentials, args.sleep)
    console.print(lesson_table(chapters))

    cover = None
    if book.cover_url:
        with console.status("[bold cyan]Fetching cover image...[/bold cyan]", spinner="dots"):
            try:
                cover = fetch_cover_asset(book)
            except RuntimeError as exc:
                console.print(f"[yellow]Cover skipped:[/yellow] {exc}")

    with console.status("[bold cyan]Packaging and validating EPUB...[/bold cyan]", spinner="dots"):
        result = write_epub(book, chapters, output, cover)
    with console.status("[bold cyan]Running EPUBCheck...[/bold cyan]", spinner="dots"):
        epubcheck_status = run_epubcheck(output)
    console.print(build_summary(result, epubcheck_status))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv or sys.argv[1:]))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
