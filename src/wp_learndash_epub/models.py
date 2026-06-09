from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Credentials:
    username: str
    application_password: str

    @property
    def is_complete(self) -> bool:
        return bool(self.username and self.application_password)


@dataclass(frozen=True)
class LessonLink:
    title: str
    url: str


@dataclass(frozen=True)
class Heading:
    title: str
    target: str
    level: int


@dataclass(frozen=True)
class Chapter:
    title: str
    url: str
    file_name: str
    body_html: str
    headings: list[Heading] = field(default_factory=list)


@dataclass(frozen=True)
class Book:
    title: str
    authors: list[str]
    source_url: str
    course_id: int
    intro_html: str
    lessons: list[LessonLink]
    cover_url: str | None
    language: str = "bn"
    publisher: str | None = None


@dataclass(frozen=True)
class CoverAsset:
    item_id: str
    path: str
    media_type: str
    data: bytes


@dataclass(frozen=True)
class BuildResult:
    output_path: str
    file_count: int
    chapter_count: int
    has_cover: bool
    xml_documents_checked: int
