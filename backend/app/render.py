"""Render generated text to .docx and .pdf.

The assistant writes lightly-marked-up text (headings, bullets, **bold**). That
is parsed once into a block model, then handed to either renderer, so the Word
and PDF versions of a document are structurally identical rather than two
independent best-efforts.
"""

import io
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE = "application/pdf"

BlockKind = Literal["heading", "paragraph", "bullet", "numbered"]

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
# **bold** or *italic*; the bold alternative is first so it wins on `**x**`.
_INLINE = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")
# A short line that is entirely bold reads as a heading, which is how the
# assistant tends to write section titles.
_BOLD_ONLY_LINE = re.compile(r"^\*\*(.+?)\*\*:?$")


@dataclass(slots=True)
class Block:
    kind: BlockKind
    text: str
    level: int = 1


def parse_blocks(text: str) -> list[Block]:
    """Turn lightly-marked-up text into an ordered list of blocks."""
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block("paragraph", " ".join(paragraph).strip()))
            paragraph.clear()

    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            flush()
            continue

        heading = _HEADING.match(line)
        if heading:
            flush()
            blocks.append(Block("heading", heading.group(2).strip(), len(heading.group(1))))
            continue

        bold_only = _BOLD_ONLY_LINE.match(line.strip())
        if bold_only:
            flush()
            blocks.append(Block("heading", bold_only.group(1).strip(), 2))
            continue

        bullet = _BULLET.match(line)
        if bullet:
            flush()
            blocks.append(Block("bullet", bullet.group(1).strip()))
            continue

        numbered = _NUMBERED.match(line)
        if numbered:
            flush()
            blocks.append(Block("numbered", numbered.group(1).strip()))
            continue

        paragraph.append(line.strip())

    flush()
    return blocks


@dataclass(slots=True)
class Segment:
    text: str
    bold: bool = False
    italic: bool = False


def _segments(text: str) -> list[Segment]:
    """Split inline markup into styled segments, so no asterisks reach the page."""
    parts: list[Segment] = []
    cursor = 0
    for match in _INLINE.finditer(text):
        if match.start() > cursor:
            parts.append(Segment(text[cursor : match.start()]))
        if match.group(1) is not None:
            parts.append(Segment(match.group(1), bold=True))
        else:
            parts.append(Segment(match.group(2), italic=True))
        cursor = match.end()
    if cursor < len(text):
        parts.append(Segment(text[cursor:]))
    return parts or [Segment(text)]


# ------------------------------------------------------------------------------- docx


def to_docx(title: str, blocks: list[Block], subtitle: str | None = None) -> bytes:
    document = DocxDocument()

    # Letter explicitly: the default varies by template and this is a US-format
    # document people will print or attach.
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    for margin in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, margin, Inches(1))

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.15

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = heading.add_run(title)
    run.bold = True
    run.font.size = Pt(18)

    if subtitle:
        meta = document.add_paragraph()
        meta_run = meta.add_run(subtitle)
        meta_run.font.size = Pt(9)
        meta_run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    for block in blocks:
        if block.kind == "heading":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(12)
            head_run = paragraph.add_run(block.text)
            head_run.bold = True
            head_run.font.size = Pt(13 if block.level <= 2 else 11)
            continue

        # Real list styles, so Word shows proper bullets and indentation
        # rather than a literal character typed into the text.
        style = {
            "bullet": "List Bullet",
            "numbered": "List Number",
        }.get(block.kind)
        paragraph = document.add_paragraph(style=style)

        for part in _segments(block.text):
            run = paragraph.add_run(part.text)
            run.bold = part.bold
            run.italic = part.italic

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# -------------------------------------------------------------------------------- pdf


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _markup(text: str) -> str:
    """Reportlab's inline markup, with the source text escaped first."""
    out = []
    for part in _segments(text):
        body = _escape(part.text)
        if part.bold:
            body = f"<b>{body}</b>"
        if part.italic:
            body = f"<i>{body}</i>"
        out.append(body)
    return "".join(out)


def to_pdf(title: str, blocks: list[Block], subtitle: str | None = None) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        topMargin=inch,
        bottomMargin=inch,
        leftMargin=inch,
        rightMargin=inch,
        title=title,
    )

    sheet = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=sheet["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        spaceAfter=8,
        alignment=TA_LEFT,
    )
    title_style = ParagraphStyle(
        "DocTitle", parent=body, fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle", parent=body, fontSize=8.5, textColor="#666666", spaceAfter=14
    )
    heading_style = ParagraphStyle(
        "Head",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=12.5,
        leading=16,
        spaceBefore=12,
        spaceAfter=4,
    )
    # Deeper headings (a role under Experience) must not compete with the
    # section title above them. docx already sizes by level; match it here.
    subheading_style = ParagraphStyle(
        "SubHead", parent=heading_style, fontSize=10.8, leading=14, spaceBefore=9, spaceAfter=2
    )

    story: list = [Paragraph(_escape(title), title_style)]
    if subtitle:
        story.append(Paragraph(_escape(subtitle), subtitle_style))
    else:
        story.append(Spacer(1, 10))

    # Consecutive list items are grouped so they render as one list.
    pending: list[Paragraph] = []
    pending_kind: BlockKind | None = None

    def flush_list() -> None:
        nonlocal pending, pending_kind
        if pending:
            is_bullet = pending_kind == "bullet"
            story.append(
                ListFlowable(
                    [ListItem(p, leftIndent=18) for p in pending],
                    bulletType="bullet" if is_bullet else "1",
                    start="circle" if is_bullet else 1,
                    # Numbers read at body size; only the bullet glyph is shrunk.
                    bulletFontSize=8 if is_bullet else body.fontSize,
                    bulletFontName="Helvetica",
                    leftIndent=18,
                )
            )
            pending = []
            pending_kind = None

    for block in blocks:
        if block.kind in ("bullet", "numbered"):
            if pending_kind and block.kind != pending_kind:
                flush_list()
            pending_kind = block.kind
            pending.append(Paragraph(_markup(block.text), body))
            continue

        flush_list()
        if block.kind == "heading":
            style = heading_style if block.level <= 2 else subheading_style
        else:
            style = body
        story.append(Paragraph(_markup(block.text), style))

    flush_list()
    document.build(story)
    return buffer.getvalue()


# Long enough to stay descriptive, short enough for any filesystem.
_MAX_NAME_CHARS = 90


def resume_blocks(
    *,
    summary: str | None,
    skills: list[str],
    roles: list[dict],
    education: list[dict],
    sections: list[str],
) -> list[Block]:
    """Lay a resume out as blocks, so it renders through the same two renderers.

    Company, title and dates arrive already resolved from the record -- nothing
    here invents them.
    """
    blocks: list[Block] = []

    for section in sections:
        if section == "summary" and summary:
            blocks.append(Block("heading", "Summary", 2))
            blocks.append(Block("paragraph", summary))

        elif section == "skills" and skills:
            blocks.append(Block("heading", "Skills", 2))
            blocks.append(Block("paragraph", " · ".join(skills)))

        elif section == "experience" and roles:
            blocks.append(Block("heading", "Experience", 2))
            for role in roles:
                header = f"{role['title']} — {role['company']}"
                if role.get("location"):
                    header += f" ({role['location']})"
                if role.get("period"):
                    header += f" | {role['period']}"
                blocks.append(Block("heading", header, 3))
                if role.get("summary"):
                    blocks.append(Block("paragraph", role["summary"]))
                blocks.extend(Block("bullet", text) for text in role.get("highlights", []))

        elif section == "education" and education:
            blocks.append(Block("heading", "Education", 2))
            for item in education:
                line = item["institution"]
                if item.get("credential"):
                    line = f"{item['credential']}, {line}"
                if item.get("period"):
                    line += f" | {item['period']}"
                blocks.append(Block("bullet", line))

    return blocks


def default_filename(title: str, extension: str, subject: str | None = None) -> str:
    """A readable, filesystem-safe, distinguishable name.

    The subject (the role this was written for) is part of the name so that
    exporting for several applications on one day does not produce a folder of
    identically-named files.
    """
    parts = [title, subject] if subject else [title]
    safe = re.sub(r"[^\w\s-]", "", " - ".join(parts)).strip() or "document"
    safe = re.sub(r"\s+", " ", safe)[:_MAX_NAME_CHARS].rstrip(" -")
    return f"{safe} - {date.today().isoformat()}.{extension}"
