# WordPress + LearnDash EPUB Exporter

Personal-use EPUB builder for WordPress sites that publish books or courses
through LearnDash. It reads the LearnDash course index, fetches lesson bodies,
cleans page chrome, and writes a Kindle-friendly EPUB3 package.

## Format Choice

Use EPUB as the default output. It is the standard reflowable ebook format,
works across most readers, and is the right source format for modern Kindle
workflows. MOBI is legacy; convert the generated EPUB with Calibre or Kindle
Previewer only if an older device specifically requires it.

## Setup

Use a virtual environment:

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .
```

Install `epubcheck` as well. The CLI runs it automatically after packaging
when it is available, and fails the build if EPUBCheck reports errors:

```bash
brew install epubcheck
```

Create `.env` from `.env.example` and set:

```dotenv
WP_LMS_USERNAME=
WP_LMS_PASSWORD=
WP_LMS_APPLICATION_PASSWORD=
WP_LMS_LANGUAGE=bn
WP_LMS_OUTPUT_DIR=epubs
```

`WP_LMS_APPLICATION_PASSWORD` is used for WordPress REST Basic Auth. The normal
password is kept only for completeness and is not sent by the exporter.

## Usage

Inspect a source:

```bash
./.venv/bin/python -m wp_learndash_epub --dry-run 'https://example.com/books/book-slug/'
```

Build an EPUB with authenticated LearnDash REST:

```bash
./.venv/bin/python -m wp_learndash_epub --confirm-rights -o book.epub 'https://example.com/books/book-slug/'
```

Build with an automatic English/ASCII filename inside an output directory:

```bash
./.venv/bin/python -m wp_learndash_epub --confirm-rights --output-dir epubs 'https://example.com/books/book-slug/'
```

When `-o/--output` is not supplied, the CLI reads source metadata first and
creates a romanized English filename from the book title. EPUB metadata keeps
the original title and authors; only filesystem names are transliterated.

After packaging, the CLI always performs built-in ZIP/XML validation. If
`epubcheck` is installed on `PATH`, it also runs EPUBCheck automatically and
shows the result in the final summary.

Use HTML lesson-page fallback instead of REST:

```bash
./.venv/bin/python -m wp_learndash_epub --confirm-rights --no-rest -o book.epub 'https://example.com/books/book-slug/'
```

The exporter refuses to build unless `--confirm-rights` is supplied. It does
not bypass login, paywalls, DRM, capability checks, or restricted content.

## Batch Mode

Create a text file with one source URL per line. Blank lines and lines starting
with `#` are ignored:

```text
https://example.com/books/book-one/
https://example.com/books/book-two/
```

Run the batch:

```bash
./.venv/bin/python -m wp_learndash_epub --confirm-rights \
  --batch-file books.txt \
  --output-dir epub-runs
```

Batch mode creates a fresh run directory under the output root:

```text
epub-runs/
  batch-20260609-011530-a1b2c3/
    books/
      001-english-book-title.epub
      002-another-book-title.epub
    logs/
      batch.log
      batch.jsonl
      books/
        001-english-book-title.log
        002-another-book-title.log
```

The numbered EPUB filenames are English/ASCII slugs generated from metadata.
The JSONL log is intended for scripting; the text logs are for quick inspection.
By default the batch continues after individual failures. Add `--fail-fast` to
stop after the first failed book.

## How It Works

- Source metadata: title, authors, cover, front matter, and LearnDash course ID
  are discovered from the public course/book page.
- Ordered lessons: `.ld-lesson-list a.ld-item-name` is used as a reliable
  index from the rendered page.
- Preferred content path: LearnDash REST
  `/wp-json/ldlms/v2/sfwd-lessons?course=<id>`.
- Fallback path: rendered lesson pages, using the LearnDash content block and
  stripping navigation, comments, forms, scripts, and floating table-of-contents
  widgets.
- EPUB output: EPUB3 package document, XHTML navigation, NCX navigation for
  older Kindle tooling, cover image metadata, stable identifier, source URL,
  language, authors, and generation timestamp.
- Naming: output paths use romanized English/ASCII slugs from metadata, with
  stable hash fallback when a title cannot be transliterated.
- Validation: the builder checks ZIP integrity, parses all generated XML, and
  automatically runs `epubcheck` when it is installed. EPUBCheck failures are
  treated as build failures.
