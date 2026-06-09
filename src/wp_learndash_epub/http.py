from __future__ import annotations

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import Credentials


USER_AGENT = "wp-learndash-epub/0.2 (+personal ebook export)"


def auth_header(credentials: Credentials | None) -> dict[str, str]:
    if not credentials:
        return {}
    token = base64.b64encode(
        f"{credentials.username}:{credentials.application_password}".encode("utf-8")
    ).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def fetch_text(url: str, credentials: Credentials | None = None, timeout: int = 45) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, **auth_header(credentials)})
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc.reason}") from exc


def fetch_binary(url: str, timeout: int = 45) -> tuple[bytes, str | None]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get_content_type()
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc.reason}") from exc


def fetch_json(url: str, credentials: Credentials | None = None, timeout: int = 45) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **auth_header(credentials),
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
            message = data.get("message") if isinstance(data, dict) else None
        except json.JSONDecodeError:
            message = body[:300]
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Expected JSON from {url}, got non-JSON response.") from exc
