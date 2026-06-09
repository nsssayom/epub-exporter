from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .models import Credentials


ENV_PREFIX = "WP_LMS_"


@dataclass(frozen=True)
class Settings:
    book_url: str | None
    output: Path | None
    language: str
    publisher: str | None
    credentials: Credentials | None


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_env_file(path: Path, override: bool = False) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        values[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return values


def compact_application_password(value: str | None) -> str:
    return "".join((value or "").split())


def settings_from_environment() -> Settings:
    username = os.environ.get(f"{ENV_PREFIX}USERNAME", "").strip()
    app_password = compact_application_password(os.environ.get(f"{ENV_PREFIX}APPLICATION_PASSWORD"))
    credentials = Credentials(username, app_password) if username and app_password else None
    output = os.environ.get(f"{ENV_PREFIX}OUTPUT", "").strip()
    return Settings(
        book_url=os.environ.get(f"{ENV_PREFIX}BOOK_URL", "").strip() or None,
        output=Path(output) if output else None,
        language=os.environ.get(f"{ENV_PREFIX}LANGUAGE", "bn").strip() or "bn",
        publisher=os.environ.get(f"{ENV_PREFIX}PUBLISHER", "").strip() or None,
        credentials=credentials,
    )
