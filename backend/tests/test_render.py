"""Tests for parsing generated text and rendering it to .docx / .pdf."""

import io

import pytest
from docx import Document as DocxDocument

from app.render import DOCX_MEDIA_TYPE, default_filename, parse_blocks, to_docx, to_pdf
from app.textextract import extract_document_text

SAMPLE = """**Likely questions**

- Walk me through a service you owned. *What they check:* scope.
- How do you plan capacity?

## Your stories

1. Cut p99 from 900ms to 120ms.
2. Owned the Terraform estate.

You have **no production Go**; be direct about it.
"""


# --------------------------------------------------------------------------- parsing


def test_parses_each_block_kind():
    kinds = [b.kind for b in parse_blocks(SAMPLE)]
    assert kinds == [
        "heading",
        "bullet",
        "bullet",
        "heading",
        "numbered",
        "numbered",
        "paragraph",
    ]


def test_a_fully_bold_line_becomes_a_heading():
    """The assistant writes section titles as **Title**, not as # Title."""
    blocks = parse_blocks("**Where you are thin**\n\nSome prose.")
    assert blocks[0].kind == "heading"
    assert blocks[0].text == "Where you are thin"


def test_heading_level_follows_hash_count():
    blocks = parse_blocks("# One\n\n### Three")
    assert [(b.text, b.level) for b in blocks] == [("One", 1), ("Three", 3)]


def test_wrapped_lines_join_into_one_paragraph():
    blocks = parse_blocks("This sentence\nwraps across lines.\n\nSecond one.")
    assert [b.text for b in blocks] == ["This sentence wraps across lines.", "Second one."]


def test_blank_input_produces_no_blocks():
    assert parse_blocks("") == []


# ------------------------------------------------------------------------------ docx


def test_docx_uses_real_list_styles():
    """Bullets must be list-styled, not a literal character typed into the text."""
    document = DocxDocument(io.BytesIO(to_docx("Prep", parse_blocks(SAMPLE))))
    styles = {p.style.name for p in document.paragraphs}
    assert "List Bullet" in styles
    assert "List Number" in styles
    assert not any("•" in p.text for p in document.paragraphs)


def test_docx_carries_no_leftover_markup():
    document = DocxDocument(io.BytesIO(to_docx("Prep", parse_blocks(SAMPLE))))
    assert sum(p.text.count("*") for p in document.paragraphs) == 0


def test_docx_applies_bold_and_italic_runs():
    document = DocxDocument(io.BytesIO(to_docx("Prep", parse_blocks(SAMPLE))))
    runs = [r for p in document.paragraphs for r in p.runs]
    assert any(r.bold and r.text == "no production Go" for r in runs)
    assert any(r.italic and r.text == "What they check:" for r in runs)


def test_docx_is_us_letter():
    document = DocxDocument(io.BytesIO(to_docx("Prep", parse_blocks(SAMPLE))))
    section = document.sections[0]
    assert round(section.page_width.inches, 1) == 8.5
    assert round(section.page_height.inches, 1) == 11.0


def test_docx_includes_title_and_subtitle():
    document = DocxDocument(io.BytesIO(to_docx("Cover letter", parse_blocks("Hi."), "Role at Co")))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "Cover letter" in text
    assert "Role at Co" in text


async def test_generated_docx_reads_back_through_ingest():
    """What we write must be readable by the same pipeline that reads uploads."""
    data = to_docx("Interview prep", parse_blocks(SAMPLE), "Staff Engineer at Helios")
    text = await extract_document_text(data, DOCX_MEDIA_TYPE, "prep.docx")
    assert text is not None
    assert "Terraform" in text
    assert "*" not in text


# ------------------------------------------------------------------------------- pdf


def test_pdf_is_a_valid_single_page_document():
    data = to_pdf("Prep", parse_blocks(SAMPLE), "Staff Engineer")
    assert data.startswith(b"%PDF")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 1000


def test_pdf_escapes_markup_characters():
    """Angle brackets are reportlab markup; unescaped they break the build."""
    data = to_pdf("Prep", parse_blocks("Compare <script> & R&D <b>bold</b> literally."))
    assert data.startswith(b"%PDF")


def test_both_formats_render_the_same_blocks():
    blocks = parse_blocks(SAMPLE)
    assert to_docx("T", blocks).startswith(b"PK")  # docx is a zip
    assert to_pdf("T", blocks).startswith(b"%PDF")


# -------------------------------------------------------------------------- filenames


@pytest.mark.parametrize("bad", ["a/b", "a:b", "a\\b", "a*b?"])
def test_filename_strips_path_and_wildcard_characters(bad):
    name = default_filename(bad, "pdf")
    assert not set(name) & set('/:\\*?"<>|')
    assert name.endswith(".pdf")


def test_filename_includes_the_subject_so_exports_are_distinguishable():
    a = default_filename("Cover letter", "docx", "Staff Engineer at Helios")
    b = default_filename("Cover letter", "docx", "Backend Engineer at Northwind")
    assert a != b
    assert "Helios" in a


def test_filename_is_capped():
    name = default_filename("Cover letter", "docx", "A" * 400)
    assert len(name) < 120


def test_filename_survives_an_empty_title():
    assert default_filename("", "pdf").endswith(".pdf")
