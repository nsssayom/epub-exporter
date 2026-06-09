from __future__ import annotations

import datetime as dt
import html
import mimetypes
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

from .http import fetch_binary
from .models import Book, BuildResult, Chapter, CoverAsset


EPUB_NS = "http://www.idpf.org/2007/ops"
OPF_NS = "http://www.idpf.org/2007/opf"


def media_type_for(path: str, fallback: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(path)[0] or fallback


def cover_extension(url: str, content_type: str | None) -> str:
    if content_type:
        extension = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if extension:
            return ".jpg" if extension == ".jpe" else extension
    suffix = Path(urlparse(url).path).suffix
    return suffix if suffix else ".jpg"


def xhtml_document(title: str, body: str, language: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{language}" lang="{language}">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="styles.css" />
</head>
<body>
  <h1>{html.escape(title)}</h1>
{body}
</body>
</html>
"""


def cover_document(title: str, cover_path: str, language: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="{EPUB_NS}" xml:lang="{language}" lang="{language}">
<head>
  <meta charset="utf-8" />
  <title>Cover</title>
  <link rel="stylesheet" type="text/css" href="styles.css" />
</head>
<body epub:type="cover" class="cover">
  <div class="cover-image"><img src="{html.escape(cover_path)}" alt="{html.escape(title)}" /></div>
</body>
</html>
"""


def stylesheet() -> str:
    return """body {
  font-family: serif;
  line-height: 1.58;
  margin: 0 5%;
  text-align: left;
}
h1, h2, h3, h4 {
  line-height: 1.25;
  margin: 1.2em 0 0.55em;
}
h1 {
  font-size: 1.45em;
  text-align: center;
}
p {
  margin: 0 0 0.85em;
}
blockquote {
  margin: 1em 1.5em;
}
table {
  border-collapse: collapse;
  width: 100%;
}
td, th {
  border: 1px solid #999;
  padding: 0.35em;
}
.cover-image {
  margin: 0;
  padding: 0;
  text-align: center;
}
.cover-image img {
  max-height: 95vh;
  max-width: 100%;
}
"""


def opf_document(book: Book, uid: str, chapters: list[Chapter], cover: CoverAsset | None) -> str:
    modified = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="styles.css" media-type="text/css"/>',
        '<item id="intro" href="intro.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine = ['<itemref idref="intro"/>']
    if cover:
        manifest.append(
            f'<item id="{cover.item_id}" href="{html.escape(cover.path)}" '
            f'media-type="{cover.media_type}" properties="cover-image"/>'
        )
        manifest.append('<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
        spine.insert(0, '<itemref idref="cover"/>')

    for index, chapter in enumerate(chapters, 1):
        item_id = f"chapter-{index:03d}"
        manifest.append(f'<item id="{item_id}" href="{chapter.file_name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{item_id}"/>')

    creators = "\n".join(
        f'    <dc:creator id="creator-{index}">{html.escape(author)}</dc:creator>'
        for index, author in enumerate(book.authors, 1)
    )
    publisher = f"    <dc:publisher>{html.escape(book.publisher)}</dc:publisher>\n" if book.publisher else ""
    meta_cover = '    <meta name="cover" content="cover-image"/>\n' if cover else ""
    manifest_text = "\n    ".join(manifest)
    spine_text = "\n    ".join(spine)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="{OPF_NS}" xmlns:dc="http://purl.org/dc/elements/1.1/" unique-identifier="book-id" version="3.0" prefix="schema: http://schema.org/">
  <metadata>
    <dc:identifier id="book-id">urn:uuid:{uid}</dc:identifier>
    <dc:title>{html.escape(book.title)}</dc:title>
{creators}
    <dc:language>{html.escape(book.language)}</dc:language>
{publisher}    <dc:source>{html.escape(book.source_url)}</dc:source>
    <dc:date>{modified[:10]}</dc:date>
    <meta property="dcterms:modified">{modified}</meta>
    <meta property="schema:accessibilityFeature">tableOfContents</meta>
{meta_cover}  </metadata>
  <manifest>
    {manifest_text}
  </manifest>
  <spine toc="ncx">
    {spine_text}
  </spine>
</package>
"""


def nav_document(book: Book, chapters: list[Chapter], has_cover: bool) -> str:
    items: list[str] = []
    if has_cover:
        items.append('<li><a href="cover.xhtml">Cover</a></li>')
    items.append('<li><a href="intro.xhtml">Introduction</a></li>')
    for chapter in chapters:
        nested = ""
        if chapter.headings:
            nested_items = "\n".join(
                f'<li><a href="{html.escape(heading.target)}">{html.escape(heading.title)}</a></li>'
                for heading in chapter.headings
            )
            nested = f"\n<ol>\n{nested_items}\n</ol>"
        items.append(f'<li><a href="{chapter.file_name}">{html.escape(chapter.title)}</a>{nested}</li>')
    toc = "\n".join(items)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="{EPUB_NS}" xml:lang="{book.language}" lang="{book.language}">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(book.title)} - Contents</title>
  <link rel="stylesheet" type="text/css" href="styles.css" />
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Contents</h1>
    <ol>
{toc}
    </ol>
  </nav>
</body>
</html>
"""


def ncx_document(book: Book, uid: str, chapters: list[Chapter], has_cover: bool) -> str:
    nav_points: list[str] = []
    play_order = 1

    def point(label: str, src: str, children: str = "") -> str:
        nonlocal play_order
        current = play_order
        play_order += 1
        return f"""<navPoint id="navPoint-{current}" playOrder="{current}">
  <navLabel><text>{html.escape(label)}</text></navLabel>
  <content src="{html.escape(src)}"/>
{children}</navPoint>"""

    if has_cover:
        nav_points.append(point("Cover", "cover.xhtml"))
    nav_points.append(point("Introduction", "intro.xhtml"))
    for chapter in chapters:
        child_points = "".join(point(heading.title, heading.target) for heading in chapter.headings)
        nav_points.append(point(chapter.title, chapter.file_name, child_points))

    return f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{book.language}">
  <head>
    <meta name="dtb:uid" content="urn:uuid:{uid}"/>
    <meta name="dtb:depth" content="2"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{html.escape(book.title)}</text></docTitle>
  <navMap>
{''.join(nav_points)}
  </navMap>
</ncx>
"""


def container_document() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def fetch_cover_asset(book: Book) -> CoverAsset | None:
    if not book.cover_url:
        return None
    cover_bytes, content_type = fetch_binary(book.cover_url)
    extension = cover_extension(book.cover_url, content_type)
    path = f"images/cover{extension}"
    return CoverAsset(
        item_id="cover-image",
        path=path,
        media_type=content_type or media_type_for(path),
        data=cover_bytes,
    )


def validate_epub_xml(output: Path) -> int:
    checked = 0
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                ElementTree.fromstring(archive.read(name))
                checked += 1
    return checked


def write_epub(book: Book, chapters: list[Chapter], output: Path, cover: CoverAsset | None) -> BuildResult:
    uid = str(uuid.uuid5(uuid.NAMESPACE_URL, book.source_url))
    files: dict[str, bytes] = {
        "META-INF/container.xml": container_document().encode("utf-8"),
        "EPUB/styles.css": stylesheet().encode("utf-8"),
        "EPUB/intro.xhtml": xhtml_document("Introduction", book.intro_html or "<p></p>", book.language).encode("utf-8"),
    }

    if cover:
        files[f"EPUB/{cover.path}"] = cover.data
        files["EPUB/cover.xhtml"] = cover_document(book.title, cover.path, book.language).encode("utf-8")

    for chapter in chapters:
        files[f"EPUB/{chapter.file_name}"] = xhtml_document(
            chapter.title,
            chapter.body_html,
            book.language,
        ).encode("utf-8")

    has_cover = cover is not None
    files["EPUB/nav.xhtml"] = nav_document(book, chapters, has_cover).encode("utf-8")
    files["EPUB/toc.ncx"] = ncx_document(book, uid, chapters, has_cover).encode("utf-8")
    files["EPUB/package.opf"] = opf_document(book, uid, chapters, cover).encode("utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for path, data in files.items():
            archive.writestr(path, data, compress_type=zipfile.ZIP_DEFLATED)

    with zipfile.ZipFile(output) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise RuntimeError(f"EPUB archive integrity check failed at {bad_file}.")
        names = archive.namelist()
        if not names or names[0] != "mimetype":
            raise RuntimeError("EPUB archive is invalid: mimetype must be the first entry.")

    checked = validate_epub_xml(output)
    return BuildResult(
        output_path=str(output),
        file_count=len(files) + 1,
        chapter_count=len(chapters),
        has_cover=has_cover,
        xml_documents_checked=checked,
    )
