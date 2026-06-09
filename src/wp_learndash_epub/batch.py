from __future__ import annotations

import json
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .naming import slugify


@dataclass(frozen=True)
class BatchRecord:
    index: int
    url: str
    status: str
    started_at: str
    finished_at: str
    duration_seconds: float
    title: str | None = None
    output: str | None = None
    error: str | None = None
    epubcheck: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_batch_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(("http://", "https://")):
            raise RuntimeError(f"Invalid URL at {path}:{line_number}: {line}")
        urls.append(line)
    if not urls:
        raise RuntimeError(f"No URLs found in batch file: {path}")
    return urls


class BatchLogger:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.logs_dir = run_dir / "logs"
        self.books_dir = self.logs_dir / "books"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self.text_log = self.logs_dir / "batch.log"
        self.jsonl_log = self.logs_dir / "batch.jsonl"

    def write_header(self, urls: list[str]) -> None:
        started = utc_now()
        with self.text_log.open("a", encoding="utf-8") as stream:
            stream.write(f"Batch started: {started}\n")
            stream.write(f"Run directory: {self.run_dir}\n")
            stream.write(f"Items: {len(urls)}\n\n")

    def record(self, record: BatchRecord, details: dict[str, Any] | None = None) -> None:
        payload = asdict(record)
        if details:
            payload["details"] = details
        with self.jsonl_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

        with self.text_log.open("a", encoding="utf-8") as stream:
            stream.write(
                f"[{record.status.upper()}] #{record.index:03d} "
                f"{record.title or record.url}\n"
            )
            stream.write(f"  URL: {record.url}\n")
            if record.output:
                stream.write(f"  Output: {record.output}\n")
            if record.epubcheck:
                stream.write(f"  EPUBCheck: {record.epubcheck}\n")
            if record.error:
                stream.write(f"  Error: {record.error}\n")
            stream.write(f"  Duration: {record.duration_seconds:.2f}s\n\n")

        self.write_book_log(record, details or {})

    def write_book_log(self, record: BatchRecord, details: dict[str, Any]) -> None:
        title_key = record.title or record.url
        name = f"{record.index:03d}-{slugify(title_key, record.url, max_length=64)}.log"
        path = self.books_dir / name
        with path.open("w", encoding="utf-8") as stream:
            stream.write(f"Status: {record.status}\n")
            stream.write(f"URL: {record.url}\n")
            if record.title:
                stream.write(f"Title: {record.title}\n")
            if record.output:
                stream.write(f"Output: {record.output}\n")
            if record.epubcheck:
                stream.write(f"EPUBCheck: {record.epubcheck}\n")
            stream.write(f"Started: {record.started_at}\n")
            stream.write(f"Finished: {record.finished_at}\n")
            stream.write(f"Duration: {record.duration_seconds:.2f}s\n")
            if record.error:
                stream.write(f"Error: {record.error}\n")
            if details:
                stream.write("\nDetails:\n")
                stream.write(json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True))
                stream.write("\n")


def exception_details(exc: BaseException) -> dict[str, str]:
    return {
        "exception_type": exc.__class__.__name__,
        "traceback": "".join(traceback.format_exception(exc)),
    }
