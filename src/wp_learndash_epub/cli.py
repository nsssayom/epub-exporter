from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rich.prompt import Confirm

from .batch import BatchLogger, BatchRecord, exception_details, read_batch_urls, utc_now
from .config import load_env_file, settings_from_environment
from .epub import fetch_cover_asset, write_epub
from .models import Book, BuildResult, Chapter, Credentials
from .naming import batch_run_dir, book_file_name, unique_path
from .source import parse_book, parse_lesson_page, parse_lessons_via_rest
from .ui import batch_summary, build_summary, console, header, lesson_table, progress, source_table


DEFAULT_SINGLE_OUTPUT_DIR = Path("epubs")
DEFAULT_BATCH_OUTPUT_ROOT = Path("epub-runs")


@dataclass(frozen=True)
class ExportOutcome:
    book: Book
    output: Path
    result: BuildResult | None
    epubcheck_status: str | None
    chapters: list[Chapter]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wp-learndash-epub",
        description="Export a WordPress + LearnDash course/book page to EPUB.",
    )
    parser.add_argument("url", nargs="?", help="Course/book landing page URL.")
    parser.add_argument("-o", "--output", type=Path, help="Output .epub path.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for metadata-derived English filenames when -o is not used.",
    )
    parser.add_argument("--batch-file", type=Path, help="Newline-separated source URL file.")
    parser.add_argument("--batch-name", help="Optional English-friendly batch directory label.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop a batch after the first failure.")
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


def resolve_output_path(book: Book, output: Path | None, output_dir: Path, index: int | None = None) -> Path:
    if output is not None:
        return output
    return unique_path(output_dir / book_file_name(book.title, book.source_url, index=index))


def export_one(
    source_url: str,
    language: str,
    publisher: str | None,
    credentials: Credentials | None,
    delay: float,
    output: Path | None,
    output_dir: Path,
    dry_run: bool,
    index: int | None = None,
    show_lessons: bool = True,
) -> ExportOutcome:
    with console.status("[bold cyan]Reading source page...[/bold cyan]", spinner="dots"):
        book = parse_book(source_url, language=language, publisher=publisher)
    final_output = resolve_output_path(book, output, output_dir, index=index)

    console.print(source_table(book, rest_enabled=bool(credentials), output=final_output))

    if dry_run:
        chapters: list[Chapter] = []
        if credentials:
            chapters = fetch_chapters(book, credentials, delay)
            if show_lessons:
                console.print(lesson_table(chapters))
        elif show_lessons:
            console.print("[yellow]REST credentials not available; dry-run used the rendered index only.[/yellow]")
        return ExportOutcome(book, final_output, None, None, chapters)

    chapters = fetch_chapters(book, credentials, delay)
    if show_lessons:
        console.print(lesson_table(chapters))

    cover = None
    if book.cover_url:
        with console.status("[bold cyan]Fetching cover image...[/bold cyan]", spinner="dots"):
            try:
                cover = fetch_cover_asset(book)
            except RuntimeError as exc:
                console.print(f"[yellow]Cover skipped:[/yellow] {exc}")

    with console.status("[bold cyan]Packaging and validating EPUB...[/bold cyan]", spinner="dots"):
        result = write_epub(book, chapters, final_output, cover)
    with console.status("[bold cyan]Running EPUBCheck...[/bold cyan]", spinner="dots"):
        epubcheck_status = run_epubcheck(final_output)
    return ExportOutcome(book, final_output, result, epubcheck_status, chapters)


def run_single(args: argparse.Namespace, settings, credentials: Credentials | None) -> int:
    source_url = args.url or settings.book_url
    if not source_url:
        raise RuntimeError("No source URL supplied. Pass a URL or set WP_LMS_BOOK_URL in .env.")

    language = args.language or settings.language
    publisher = args.publisher or settings.publisher
    output_dir = args.output_dir or settings.output_dir or DEFAULT_SINGLE_OUTPUT_DIR
    output = args.output or settings.output

    outcome = export_one(
        source_url=source_url,
        language=language,
        publisher=publisher,
        credentials=credentials,
        delay=args.sleep,
        output=output,
        output_dir=output_dir,
        dry_run=args.dry_run,
        show_lessons=True,
    )
    if outcome.result and outcome.epubcheck_status:
        console.print(build_summary(outcome.result, outcome.epubcheck_status))
    return 0


def run_batch(args: argparse.Namespace, settings, credentials: Credentials | None) -> int:
    if args.output:
        raise RuntimeError("Batch mode uses --output-dir, not -o/--output.")

    urls = read_batch_urls(args.batch_file)
    language = args.language or settings.language
    publisher = args.publisher or settings.publisher
    output_root = args.output_dir or settings.output_dir or DEFAULT_BATCH_OUTPUT_ROOT
    run_dir = batch_run_dir(output_root, args.batch_name)
    books_dir = run_dir / "books"
    books_dir.mkdir(parents=True, exist_ok=True)
    logger = BatchLogger(run_dir)
    logger.write_header(urls)

    console.print(f"[bold cyan]Batch run:[/bold cyan] {run_dir}")
    succeeded = 0
    failed = 0

    for index, url in enumerate(urls, 1):
        started_monotonic = time.monotonic()
        started_at = utc_now()
        console.rule(f"[bold]Book {index}/{len(urls)}[/bold]")
        try:
            outcome = export_one(
                source_url=url,
                language=language,
                publisher=publisher,
                credentials=credentials,
                delay=args.sleep,
                output=None,
                output_dir=books_dir,
                dry_run=args.dry_run,
                index=index,
                show_lessons=False,
            )
            finished_at = utc_now()
            duration = time.monotonic() - started_monotonic
            if args.dry_run:
                status = "dry-run"
                epubcheck = None
                output = None
                succeeded += 1
            else:
                status = "success"
                epubcheck = outcome.epubcheck_status
                output = str(outcome.output)
                succeeded += 1
            record = BatchRecord(
                index=index,
                url=url,
                title=outcome.book.title,
                output=output,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                epubcheck=epubcheck,
            )
            logger.record(
                record,
                {
                    "authors": outcome.book.authors,
                    "course_id": outcome.book.course_id,
                    "chapters": len(outcome.chapters),
                    "sections": sum(len(chapter.headings) for chapter in outcome.chapters),
                },
            )
            console.print(f"[green]Done:[/green] {outcome.book.title}")
        except Exception as exc:
            finished_at = utc_now()
            duration = time.monotonic() - started_monotonic
            failed += 1
            record = BatchRecord(
                index=index,
                url=url,
                status="failed",
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                error=str(exc),
            )
            logger.record(record, exception_details(exc))
            console.print(f"[red]Failed:[/red] {url}\n[dim]{exc}[/dim]")
            if args.fail_fast:
                break

    console.print(batch_summary(run_dir, len(urls), succeeded, failed))
    return 1 if failed else 0


def run(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    settings = settings_from_environment()
    credentials = resolve_credentials(args.no_rest, settings.credentials)

    header()
    if args.batch_file and args.url:
        raise RuntimeError("Use either a positional URL or --batch-file, not both.")

    if not args.dry_run and not args.confirm_rights:
        if not Confirm.ask("Confirm you may export this content into a local EPUB", default=False):
            console.print("[red]Export cancelled.[/red]")
            return 2

    if args.batch_file:
        return run_batch(args, settings, credentials)
    return run_single(args, settings, credentials)


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv or sys.argv[1:]))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
