"""Hand-built .docx / .pptx fixtures for the structured-block tests.

The archives are written with the standard library only. A real writer
(python-docx / python-pptx) would produce a document whose exact XML this suite
does not control, and the whole point of these fixtures is to pin behaviour on
specific markup: a numbering definition that says "decimal", a ``sldIdLst`` that
disagrees with the slide filenames, a picture relationship pointing at a member
that is or is not in the archive.

Only the parts the extractor actually reads are written, which is also what makes
the "incomplete container" cases expressible.
"""

from __future__ import annotations

import base64
import zipfile

#: A real 1×1 PNG. The media endpoint sniffs CONTENT, so a fixture picture has
#: to carry a genuine signature — a placeholder byte string is refused, which
#: would make a success-path test unwritable.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
_P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_PKG = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
_REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def docx_para(text: str, style: str = "", num_id: str = "", bold: bool = False) -> str:
    """One ``w:p``: optionally styled (heading), numbered (list) or bold."""
    props = ""
    if style or num_id:
        inner = f'<w:pStyle w:val="{style}"/>' if style else ""
        if num_id:
            inner += f'<w:numPr><w:numId w:val="{num_id}"/></w:numPr>'
        props = f"<w:pPr>{inner}</w:pPr>"
    run_props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f"<w:p>{props}<w:r>{run_props}<w:t>{text}</w:t></w:r></w:p>"


def docx_styles_xml(style_nums: dict[str, str]) -> str:
    """A ``word/styles.xml`` whose named styles carry a ``w:numPr``.

    This is how Word writes its own "List Bullet" / "List Number": a paragraph
    using one carries nothing but ``w:pStyle``, and the numbering lives here.
    """
    styles = "".join(
        f'<w:style w:type="paragraph" w:styleId="{sid}">'
        f'<w:name w:val="{sid}"/><w:basedOn w:val="Normal"/>'
        f'<w:pPr><w:numPr><w:numId w:val="{num_id}"/></w:numPr></w:pPr></w:style>'
        for sid, num_id in style_nums.items()
    )
    return f"<w:styles {_W}>{styles}</w:styles>"


def docx_table(rows: list[list[str]]) -> str:
    """One ``w:tbl`` from a row-major grid of cell strings."""
    body = "".join(
        "<w:tr>"
        + "".join(f"<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>" for cell in row)
        + "</w:tr>"
        for row in rows
    )
    return f"<w:tbl>{body}</w:tbl>"


def docx_image_para(rel_id: str) -> str:
    """A picture-bearing paragraph: a ``w:drawing`` whose blip names *rel_id*."""
    return (
        f"<w:p><w:r><w:drawing><a:graphic {_A}><a:graphicData>"
        f'<a:blip r:embed="{rel_id}"/>'
        "</a:graphicData></a:graphic></w:drawing></w:r></w:p>"
    )


def write_docx(
    path: str,
    body: str,
    *,
    numbering: dict[str, str] | None = None,
    images: dict[str, str] | None = None,
    media: dict[str, bytes] | None = None,
    styles_xml: str | None = None,
) -> None:
    """Write a .docx.

    *numbering* maps ``w:numId`` → ``w:numFmt`` ("decimal", "bullet", …); the
    two-level abstractNum indirection real documents use is written out so the
    extractor's resolution is exercised rather than bypassed.
    *images* maps relationship id → target relative to ``word/``.
    *media* maps full member name → bytes.
    *styles_xml* is written as ``word/styles.xml`` -- see :func:`docx_styles_xml`.
    """
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:document {_W} {_R}><w:body>{body}</w:body></w:document>",
        )
        if numbering:
            abstracts = "".join(
                f'<w:abstractNum w:abstractNumId="{i}">'
                f'<w:lvl w:ilvl="0"><w:numFmt w:val="{fmt}"/></w:lvl>'
                f"</w:abstractNum>"
                for i, fmt in enumerate(numbering.values())
            )
            nums = "".join(
                f'<w:num w:numId="{nid}"><w:abstractNumId w:val="{i}"/></w:num>'
                for i, nid in enumerate(numbering)
            )
            zf.writestr("word/numbering.xml", f"<w:numbering {_W}>{abstracts}{nums}</w:numbering>")
        if styles_xml is not None:
            zf.writestr("word/styles.xml", styles_xml)
        if images:
            rels = "".join(
                f'<Relationship Id="{rid}" Type="{_REL_BASE}/image" Target="{target}"/>'
                for rid, target in images.items()
            )
            zf.writestr(
                "word/_rels/document.xml.rels",
                f"<Relationships {_PKG}>{rels}</Relationships>",
            )
        for member, data in (media or {}).items():
            zf.writestr(member, data)


def pptx_shape(text_lines: list[str], ph_type: str = "", bullet: bool = False) -> str:
    """One ``p:sp``: a placeholder of *ph_type* holding *text_lines*."""
    ph = f'<p:nvPr><p:ph type="{ph_type}"/></p:nvPr>' if ph_type else "<p:nvPr/>"
    props = "<a:pPr><a:buChar/></a:pPr>" if bullet else ""
    paras = "".join(f"<a:p>{props}<a:r><a:t>{line}</a:t></a:r></a:p>" for line in text_lines)
    return f"<p:sp><p:nvSpPr>{ph}</p:nvSpPr><p:txBody>{paras}</p:txBody></p:sp>"


def pptx_pic(rel_id: str) -> str:
    """A ``p:pic`` shape whose blip names *rel_id* -- how a deck holds a picture."""
    return f'<p:pic><p:blipFill><a:blip r:embed="{rel_id}"/></p:blipFill></p:pic>'


def pptx_slide_xml(shapes: str) -> str:
    """A ``p:sld`` wrapping *shapes* in the shape tree the extractor walks."""
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<p:sld {_P} {_A} {_R}><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sld>"
    )


def write_pptx(
    path: str,
    slides: dict[str, str],
    *,
    order: list[str] | None = None,
    notes: dict[str, str] | None = None,
    presentation: bool = True,
    presentation_xml: str | None = None,
    images: dict[str, dict[str, str]] | None = None,
    media: dict[str, bytes] | None = None,
) -> None:
    """Write a .pptx.

    *slides* maps member name → slide XML. *order* lists member names in
    presentation order (defaults to *slides*' own order); the ``sldIdLst`` and
    the relationship part are written to agree with it, so a caller can make the
    manifest disagree with the filenames on purpose. *notes* maps a slide member
    to its speaker-notes text. With *presentation* False the presentation part is
    omitted entirely, which is the incomplete-container case, and
    *presentation_xml* replaces it with markup the generator cannot produce.
    *images* maps a slide member to its {relationship id: target relative to
    ``ppt/slides/``} picture relationships, and *media* maps full member name to
    bytes.
    """
    order = order if order is not None else list(slides)
    with zipfile.ZipFile(path, "w") as zf:
        for member, xml in slides.items():
            zf.writestr(member, xml)
        if presentation_xml is not None:
            zf.writestr("ppt/presentation.xml", presentation_xml)
        elif presentation:
            ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(len(order)))
            zf.writestr(
                "ppt/presentation.xml",
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f"<p:presentation {_P} {_R}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>",
            )
            rels = "".join(
                f'<Relationship Id="rId{i + 1}" Type="{_REL_BASE}/slide" '
                f'Target="{member.removeprefix("ppt/")}"/>'
                for i, member in enumerate(order)
            )
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                f"<Relationships {_PKG}>{rels}</Relationships>",
            )
        for member, rels_map in (images or {}).items():
            rels = "".join(
                f'<Relationship Id="{rid}" Type="{_REL_BASE}/image" Target="{target}"/>'
                for rid, target in rels_map.items()
            )
            zf.writestr(
                f"ppt/slides/_rels/{member.removeprefix('ppt/slides/')}.rels",
                f"<Relationships {_PKG}>{rels}</Relationships>",
            )
        for name, data in (media or {}).items():
            zf.writestr(name, data)
        for i, (member, text) in enumerate((notes or {}).items(), 1):
            notes_member = f"ppt/notesSlides/notesSlide{i}.xml"
            zf.writestr(notes_member, pptx_slide_xml(pptx_shape([text], ph_type="body")))
            zf.writestr(
                f"ppt/slides/_rels/{member.removeprefix('ppt/slides/')}.rels",
                f'<Relationships {_PKG}><Relationship Id="rId9" '
                f'Type="{_REL_BASE}/notesSlide" '
                f'Target="../notesSlides/notesSlide{i}.xml"/></Relationships>',
            )
