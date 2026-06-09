from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    from unidecode import unidecode
except ImportError:  # pragma: no cover - dependency fallback.
    unidecode = None


BN_FALLBACK = {
        "০": "0",
        "১": "1",
        "২": "2",
        "৩": "3",
        "৪": "4",
        "৫": "5",
        "৬": "6",
        "৭": "7",
        "৮": "8",
        "৯": "9",
        "অ": "a",
        "আ": "a",
        "ই": "i",
        "ঈ": "i",
        "উ": "u",
        "ঊ": "u",
        "ঋ": "ri",
        "এ": "e",
        "ঐ": "oi",
        "ও": "o",
        "ঔ": "ou",
        "া": "a",
        "ি": "i",
        "ী": "i",
        "ু": "u",
        "ূ": "u",
        "ৃ": "ri",
        "ে": "e",
        "ৈ": "oi",
        "ো": "o",
        "ৌ": "ou",
        "ক": "k",
        "খ": "kh",
        "গ": "g",
        "ঘ": "gh",
        "ঙ": "ng",
        "চ": "ch",
        "ছ": "chh",
        "জ": "j",
        "ঝ": "jh",
        "ঞ": "n",
        "ট": "t",
        "ঠ": "th",
        "ড": "d",
        "ঢ": "dh",
        "ণ": "n",
        "ত": "t",
        "থ": "th",
        "দ": "d",
        "ধ": "dh",
        "ন": "n",
        "প": "p",
        "ফ": "ph",
        "ব": "b",
        "ভ": "bh",
        "ম": "m",
        "য": "y",
        "য়": "y",
        "র": "r",
        "ল": "l",
        "শ": "sh",
        "ষ": "sh",
        "স": "s",
        "হ": "h",
        "ড়": "r",
        "ঢ়": "rh",
        "ৎ": "t",
        "ং": "ng",
        "ঃ": "h",
        "ঁ": "n",
        "্": "",
}


def romanize(value: str) -> str:
    if unidecode:
        return unidecode(value)
    normalized = unicodedata.normalize("NFKD", value)
    for source, target in sorted(BN_FALLBACK.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(source, target)
    return normalized.encode("ascii", "ignore").decode("ascii")


def stable_hash(value: str, length: int = 8) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def slugify(value: str, fallback_key: str, max_length: int = 84) -> str:
    romanized = romanize(value).lower()
    romanized = romanized.replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", romanized)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        slug = f"book-{stable_hash(fallback_key)}"
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or f"book-{stable_hash(fallback_key)}"


def book_file_name(title: str, source_url: str, index: int | None = None) -> str:
    stem = slugify(title, source_url)
    if index is not None:
        stem = f"{index:03d}-{stem}"
    return f"{stem}.epub"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def batch_run_dir(output_root: Path, batch_name: str | None = None) -> Path:
    if batch_name:
        name = slugify(batch_name, batch_name, max_length=60)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"batch-{stamp}-{secrets.token_hex(3)}"
    return unique_path(output_root / name)
