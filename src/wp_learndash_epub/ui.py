from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .models import Book, BuildResult, Chapter


console = Console()


def progress() -> Progress:
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def header() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]WordPress + LearnDash EPUB Exporter[/bold cyan]\n"
            "[dim]Clean source extraction, REST-aware lesson loading, EPUB3 packaging[/dim]",
            border_style="cyan",
        )
    )


def source_table(book: Book, rest_enabled: bool, output: Path | None) -> Table:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Title", book.title)
    table.add_row("Authors", ", ".join(book.authors))
    table.add_row("Course ID", str(book.course_id))
    table.add_row("Lessons", str(len(book.lessons)))
    table.add_row("Language", book.language)
    table.add_row("Cover", "detected" if book.cover_url else "not found")
    table.add_row("Content path", "LearnDash REST" if rest_enabled else "rendered HTML fallback")
    if output:
        table.add_row("Output", str(output))
    return table


def lesson_table(chapters: list[Chapter]) -> Table:
    table = Table(title="Detected Lessons", show_lines=False)
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("Sections", justify="right")
    for index, chapter in enumerate(chapters, 1):
        table.add_row(str(index), chapter.title, str(len(chapter.headings)))
    return table


def build_summary(result: BuildResult, epubcheck_status: str) -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Output", result.output_path)
    table.add_row("Chapters", str(result.chapter_count))
    table.add_row("Files", str(result.file_count))
    table.add_row("Cover", "included" if result.has_cover else "not included")
    table.add_row("XML checked", str(result.xml_documents_checked))
    table.add_row("EPUBCheck", epubcheck_status)
    return Panel(table, title="[bold green]EPUB ready[/bold green]", border_style="green")


def batch_summary(run_dir: Path, total: int, succeeded: int, failed: int) -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Run directory", str(run_dir))
    table.add_row("Total", str(total))
    table.add_row("Succeeded", str(succeeded))
    table.add_row("Failed", str(failed))
    table.add_row("Logs", str(run_dir / "logs"))
    style = "green" if failed == 0 else "yellow"
    return Panel(table, title=f"[bold {style}]Batch complete[/bold {style}]", border_style=style)
