"""Tests for kiro_crew.doc_blocks — structured block extraction for docx/pptx.

What is pinned here is the block CONTRACT the dashboard renders against
(heading level, list orderedness, table grid, image member) and the two places
this module can be wrong in a way plaintext extraction never could:

* pptx slide ORDER. Reordering a deck does not rename its parts, so the
  presentation manifest and the filenames disagree — and a filename sort quietly
  reorders the deck. Every ordering assertion below uses a deck whose
  ``sldIdLst`` contradicts its filenames, so a regression to filename order
  fails rather than passing by coincidence.
* the BUDGETS. A structured payload becomes DOM nodes, so an unbounded block
  count is a render-time denial of service, not just a large response.
"""

from __future__ import annotations

import zipfile

import pytest
from ooxml_fixtures import (
    PNG_1X1,
    docx_image_para,
    docx_para,
    docx_styles_xml,
    docx_table,
    pptx_pic,
    pptx_shape,
    pptx_slide_xml,
    write_docx,
    write_pptx,
)

from kiro_crew import doc_blocks
from kiro_crew.doc_blocks import extract_blocks, read_media_member


def _kinds(blocks: list[dict]) -> list[str]:
    return [block["type"] for block in blocks]


# ── docx ──


def test_heading_levels_and_title_come_back_as_headings(tmp_path):
    f = tmp_path / "report.docx"
    write_docx(
        str(f),
        docx_para("Quarterly report", style="Title")
        + docx_para("Overview", style="Heading1")
        + docx_para("Detail", style="heading 3")
        + docx_para("Body text"),
    )
    blocks, truncated = extract_blocks(str(f))
    assert truncated is False
    assert _kinds(blocks) == ["heading", "heading", "heading", "paragraph"]
    # Title is level 1; "heading 3" is the same style as "Heading3" — a document
    # from a non-Word writer spells it with the space.
    assert [b["level"] for b in blocks[:3]] == [1, 1, 3]
    assert blocks[1]["text"] == "Overview"


def test_paragraph_runs_keep_bold_and_italic(tmp_path):
    f = tmp_path / "runs.docx"
    write_docx(str(f), docx_para("plain") + docx_para("strong", bold=True))
    blocks, _ = extract_blocks(str(f))
    assert blocks[0]["runs"] == [{"text": "plain", "bold": False, "italic": False}]
    assert blocks[1]["runs"] == [{"text": "strong", "bold": True, "italic": False}]


def test_bold_toggle_explicitly_off_is_not_bold(tmp_path):
    """``<w:b w:val="0"/>`` cancels bold inherited from the paragraph style."""
    f = tmp_path / "toggle.docx"
    write_docx(
        str(f),
        '<w:p><w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t>not strong</w:t></w:r></w:p>',
    )
    blocks, _ = extract_blocks(str(f))
    assert blocks[0]["runs"][0]["bold"] is False


def test_consecutive_numbered_paragraphs_become_one_ordered_list(tmp_path):
    f = tmp_path / "list.docx"
    write_docx(
        str(f),
        docx_para("first", num_id="1") + docx_para("second", num_id="1") + docx_para("after"),
        numbering={"1": "decimal"},
    )
    blocks, _ = extract_blocks(str(f))
    assert _kinds(blocks) == ["list", "paragraph"]
    assert blocks[0] == {"type": "list", "ordered": True, "items": ["first", "second"]}


def test_bullet_numbering_is_unordered_and_splits_from_a_numbered_run(tmp_path):
    f = tmp_path / "mixed.docx"
    write_docx(
        str(f),
        docx_para("one", num_id="1") + docx_para("dot", num_id="2"),
        numbering={"1": "decimal", "2": "bullet"},
    )
    blocks, _ = extract_blocks(str(f))
    assert [(b["ordered"], b["items"]) for b in blocks] == [(True, ["one"]), (False, ["dot"])]


def test_list_without_a_numbering_part_renders_unordered(tmp_path):
    """No numbering.xml: a bullet in front of numbered text still reads as a
    bullet, where an invented "1." asserts an order the document never had."""
    f = tmp_path / "nonum.docx"
    write_docx(str(f), docx_para("item", num_id="7"))
    blocks, _ = extract_blocks(str(f))
    assert blocks[0]["ordered"] is False


def test_a_list_numbered_only_by_its_style_is_still_a_list(tmp_path):
    """Word's own "List Bullet" / "List Number" put the numbering in styles.xml, so
    the paragraph carries nothing but ``w:pStyle``. Reading ``w:numPr`` off the
    paragraph alone renders every such list as ordinary body paragraphs -- which is
    exactly what a real Word / python-docx document produces."""
    f = tmp_path / "styled.docx"
    write_docx(
        str(f),
        docx_para("bullet one", style="ListBullet")
        + docx_para("bullet two", style="ListBullet")
        + docx_para("step one", style="ListNumber"),
        numbering={"1": "bullet", "5": "decimal"},
        styles_xml=docx_styles_xml({"ListBullet": "1", "ListNumber": "5"}),
    )
    blocks, _ = extract_blocks(str(f))
    assert [(b["type"], b["ordered"], b["items"]) for b in blocks] == [
        ("list", False, ["bullet one", "bullet two"]),
        ("list", True, ["step one"]),
    ]


def test_a_paragraph_cancelling_its_style_numbering_is_not_a_list(tmp_path):
    """``w:numId w:val="0"`` is Word cancelling numbering the style would supply;
    honouring the style anyway puts a bullet in front of a plain paragraph."""
    f = tmp_path / "cancelled.docx"
    write_docx(
        str(f),
        '<w:p><w:pPr><w:pStyle w:val="ListBullet"/>'
        '<w:numPr><w:numId w:val="0"/></w:numPr></w:pPr>'
        "<w:r><w:t>not a bullet</w:t></w:r></w:p>",
        numbering={"1": "bullet"},
        styles_xml=docx_styles_xml({"ListBullet": "1"}),
    )
    blocks, _ = extract_blocks(str(f))
    assert _kinds(blocks) == ["paragraph"]


def test_a_style_that_names_no_numbering_leaves_its_paragraphs_alone(tmp_path):
    """The complement: the styles.xml lookup must not turn every styled paragraph
    into a list item."""
    f = tmp_path / "quote.docx"
    write_docx(
        str(f),
        docx_para("just a quotation", style="IntenseQuote"),
        styles_xml=docx_styles_xml({"ListBullet": "1"}),
    )
    blocks, _ = extract_blocks(str(f))
    assert _kinds(blocks) == ["paragraph"]


def test_table_comes_back_as_a_row_major_grid(tmp_path):
    f = tmp_path / "table.docx"
    write_docx(str(f), docx_table([["Region", "Total"], ["EU", "12"]]))
    blocks, _ = extract_blocks(str(f))
    assert blocks == [
        {"type": "table", "rows": [["Region", "Total"], ["EU", "12"]], "truncated_cols": False}
    ]


def test_embedded_raster_becomes_an_image_block_naming_its_member(tmp_path):
    f = tmp_path / "pic.docx"
    write_docx(
        str(f),
        docx_image_para("rId4") + docx_para("caption"),
        images={"rId4": "media/image1.png"},
        media={"word/media/image1.png": PNG_1X1},
    )
    blocks, _ = extract_blocks(str(f))
    assert blocks[0] == {"type": "image", "member": "word/media/image1.png"}
    assert blocks[1]["type"] == "paragraph"


def test_vector_and_missing_members_become_placeholders_and_mark_truncation(tmp_path):
    """An .emf is never served (the media endpoint is sniffed-raster only) and a
    member the archive lacks cannot render -- but silently DROPPING either lets a
    report whose only chart is a metafile render complete-looking with the figure
    gone. The block stays, with no member, and the result is marked truncated so
    the pinned notice fires."""
    f = tmp_path / "vector.docx"
    write_docx(
        str(f),
        docx_image_para("rId1") + docx_image_para("rId2") + docx_para("text"),
        images={"rId1": "media/drawing.emf", "rId2": "media/gone.png"},
        media={"word/media/drawing.emf": b"\x01\x00\x00\x00"},
    )
    blocks, truncated = extract_blocks(str(f))
    assert blocks[:2] == [
        {"type": "image", "member": None},
        {"type": "image", "member": None},
    ]
    assert blocks[2]["type"] == "paragraph"
    assert truncated is True


def test_external_image_relationship_is_not_resolved(tmp_path):
    """An External target is a URL or a path outside the container; following one
    would turn a document preview into an outbound fetch."""
    f = tmp_path / "external.docx"
    with zipfile.ZipFile(f, "w") as zf:
        pass
    write_docx(str(f), docx_image_para("rId1") + docx_para("body"))
    with zipfile.ZipFile(f, "a") as zf:
        zf.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" TargetMode="External" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="https://example.invalid/logo.png"/></Relationships>',
        )
    blocks, truncated = extract_blocks(str(f))
    # An External relationship is not a picture the document holds, so nothing
    # was dropped and nothing is marked truncated.
    assert _kinds(blocks) == ["paragraph"]
    assert truncated is False


def test_content_control_contents_are_not_dropped(tmp_path):
    """Template-produced documents wrap sections in ``w:sdt``; walking only the
    body's direct children would silently lose everything inside one."""
    f = tmp_path / "sdt.docx"
    write_docx(
        str(f),
        f"<w:sdt><w:sdtContent>{docx_para('Inside', style='Heading1')}</w:sdtContent></w:sdt>",
    )
    blocks, _ = extract_blocks(str(f))
    assert blocks == [{"type": "heading", "level": 1, "text": "Inside"}]


def test_empty_paragraphs_do_not_become_blocks(tmp_path):
    f = tmp_path / "spacing.docx"
    write_docx(str(f), "<w:p/><w:p/>" + docx_para("only real line") + "<w:p/>")
    blocks, _ = extract_blocks(str(f))
    assert _kinds(blocks) == ["paragraph"]


# ── pptx ──


def _reordered_deck(path) -> None:
    """A two-slide deck whose manifest order contradicts its filenames.

    ``slide1.xml`` holds the appendix and ``slide2.xml`` the summary, and
    ``sldIdLst`` puts slide2 first — which is exactly what happens when an author
    drags a slide to the front, since reordering renames nothing.
    """
    write_pptx(
        str(path),
        {
            "ppt/slides/slide1.xml": pptx_slide_xml(pptx_shape(["Appendix"], ph_type="title")),
            "ppt/slides/slide2.xml": pptx_slide_xml(pptx_shape(["Summary"], ph_type="title")),
        },
        order=["ppt/slides/slide2.xml", "ppt/slides/slide1.xml"],
    )


def test_slides_follow_the_presentation_manifest_not_the_filenames(tmp_path):
    f = tmp_path / "deck.pptx"
    _reordered_deck(f)
    blocks, _ = extract_blocks(str(f))
    assert [b["type"] for b in blocks] == ["slide", "slide"]
    assert [(b["index"], b["title"]) for b in blocks] == [(1, "Summary"), (2, "Appendix")]


def test_slide_index_is_the_presentation_position(tmp_path):
    """The index the UI labels a card with must be the reader's position, not the
    part number — those differ for every reordered deck."""
    f = tmp_path / "deck.pptx"
    _reordered_deck(f)
    blocks, _ = extract_blocks(str(f))
    assert blocks[0]["index"] == 1 and blocks[0]["title"] == "Summary"


def test_deck_without_a_presentation_part_yields_no_slides(tmp_path):
    """Guessing an order from the filenames is the mistake this resolver exists to
    avoid. No slides means the frontend falls back to the text preview, which
    carries its own best-effort scan."""
    f = tmp_path / "partial.pptx"
    write_pptx(
        str(f),
        {
            "ppt/slides/slide2.xml": pptx_slide_xml(pptx_shape(["Two"], ph_type="title")),
            "ppt/slides/slide10.xml": pptx_slide_xml(pptx_shape(["Ten"], ph_type="title")),
        },
        presentation=False,
    )
    assert extract_blocks(str(f)) == ([], False)


def test_unreadable_manifest_yields_no_slides_rather_than_an_invented_order(tmp_path):
    f = tmp_path / "broken.pptx"
    write_pptx(
        str(f),
        {"ppt/slides/slide1.xml": pptx_slide_xml(pptx_shape(["One"], ph_type="title"))},
        presentation_xml="<not-xml",
    )
    blocks, _ = extract_blocks(str(f))
    assert blocks == []


def test_title_is_the_card_header_and_is_not_repeated_in_the_body(tmp_path):
    f = tmp_path / "one.pptx"
    write_pptx(
        str(f),
        {
            "ppt/slides/slide1.xml": pptx_slide_xml(
                pptx_shape(["Agenda"], ph_type="title")
                + pptx_shape(["alpha", "beta"], bullet=True),
            ),
        },
    )
    blocks, _ = extract_blocks(str(f))
    slide = blocks[0]
    assert slide["title"] == "Agenda"
    assert slide["blocks"] == [
        {"type": "list", "ordered": False, "items": ["alpha", "beta"]},
    ]


def test_speaker_notes_are_attached_only_when_present(tmp_path):
    f = tmp_path / "notes.pptx"
    write_pptx(
        str(f),
        {
            "ppt/slides/slide1.xml": pptx_slide_xml(pptx_shape(["Intro"], ph_type="title")),
            "ppt/slides/slide2.xml": pptx_slide_xml(pptx_shape(["Next"], ph_type="title")),
        },
        notes={"ppt/slides/slide1.xml": "Remember to mention the deadline"},
    )
    blocks, _ = extract_blocks(str(f))
    assert blocks[0]["notes"] == "Remember to mention the deadline"
    assert "notes" not in blocks[1]


def test_slide_table_is_extracted_from_its_graphic_frame(tmp_path):
    f = tmp_path / "tbl.pptx"
    shapes = (
        "<p:graphicFrame><a:graphic><a:graphicData><a:tbl>"
        "<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Cell</a:t></a:r></a:p></a:txBody></a:tc></a:tr>"
        "</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"
    )
    write_pptx(str(f), {"ppt/slides/slide1.xml": pptx_slide_xml(shapes)})
    blocks, _ = extract_blocks(str(f))
    assert blocks[0]["blocks"] == [{"type": "table", "rows": [["Cell"]], "truncated_cols": False}]


def test_slide_pictures_become_image_blocks(tmp_path):
    """A deck whose content is pictures would otherwise render as empty cards."""
    f = tmp_path / "pics.pptx"
    write_pptx(
        str(f),
        {
            "ppt/slides/slide1.xml": pptx_slide_xml(
                pptx_shape(["Architecture"], ph_type="title") + pptx_pic("rId2"),
            ),
        },
        images={"ppt/slides/slide1.xml": {"rId2": "../media/image1.png"}},
        media={"ppt/media/image1.png": PNG_1X1},
    )
    blocks, _ = extract_blocks(str(f))
    assert blocks[0]["title"] == "Architecture"
    assert blocks[0]["blocks"] == [{"type": "image", "member": "ppt/media/image1.png"}]


def test_slide_picture_pointing_at_a_missing_member_is_a_placeholder(tmp_path):
    f = tmp_path / "brokenpic.pptx"
    write_pptx(
        str(f),
        {
            "ppt/slides/slide1.xml": pptx_slide_xml(
                pptx_shape(["Title"], ph_type="title") + pptx_pic("rId2"),
            ),
        },
        images={"ppt/slides/slide1.xml": {"rId2": "../media/gone.png"}},
    )
    blocks, truncated = extract_blocks(str(f))
    assert blocks[0]["blocks"] == [{"type": "image", "member": None}]
    assert truncated is True


# ── budgets and refusals ──


def test_block_budget_stops_extraction_and_reports_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_blocks, "MAX_BLOCKS", 3)
    f = tmp_path / "long.docx"
    write_docx(str(f), "".join(docx_para(f"line {i}") for i in range(50)))
    blocks, truncated = extract_blocks(str(f))
    assert len(blocks) == 3
    assert truncated is True


def test_character_budget_stops_extraction_and_reports_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_blocks, "MAX_CHARS", 20)
    f = tmp_path / "wide.docx"
    write_docx(str(f), "".join(docx_para("x" * 30) for _ in range(10)))
    blocks, truncated = extract_blocks(str(f))
    assert truncated is True
    assert len(blocks) < 10


def test_an_oversized_run_is_dropped_whole_and_never_overruns_the_allowance(tmp_path, monkeypatch):
    """A single ``w:t`` can be megabytes on its own. Charging it AFTER appending
    left the payload past MAX_CHARS by that whole run while every counter still
    read as though it had not -- so it is charged first, and refused whole.

    Refused rather than cut to fit: redaction runs on these strings later and
    downstream and matches patterns, so a string cut to length can carry a partial
    secret those patterns miss. Dropping the string covers every secret shape at
    once, and costs only the LAST string, since extraction stops immediately
    after."""
    monkeypatch.setattr(doc_blocks, "MAX_CHARS", 50)
    f = tmp_path / "onebigrun.docx"
    write_docx(str(f), docx_para("x" * 5000))
    blocks, truncated = extract_blocks(str(f))
    assert truncated is True
    body = "".join(run["text"] for b in blocks for run in b.get("runs", []))
    assert body == ""


def test_a_run_that_fits_is_still_returned_whole(tmp_path, monkeypatch):
    """The complement, so "refuse what does not fit" cannot be satisfied by
    refusing everything."""
    monkeypatch.setattr(doc_blocks, "MAX_CHARS", 50)
    f = tmp_path / "smallrun.docx"
    write_docx(str(f), docx_para("z" * 40))
    blocks, truncated = extract_blocks(str(f))
    assert truncated is False
    body = "".join(run["text"] for b in blocks for run in b.get("runs", []))
    assert body == "z" * 40


def test_an_oversized_table_cell_is_dropped_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_blocks, "MAX_CHARS", 30)
    f = tmp_path / "bigcell.docx"
    write_docx(str(f), docx_table([["y" * 4000]]))
    blocks, truncated = extract_blocks(str(f))
    assert truncated is True
    assert blocks[0]["rows"][0][0] == ""


def _total_blocks(blocks: list[dict]) -> int:
    """Blocks anywhere in a payload, counting those nested inside a slide card."""
    return sum(1 + _total_blocks(b.get("blocks", [])) for b in blocks)


def test_one_dense_slide_cannot_emit_past_the_block_allowance(tmp_path, monkeypatch):
    """One slide holds arbitrarily many shapes, so the block allowance has to bind
    WITHIN a slide and not only between slides.

    An EMPTY payload is a correct outcome here rather than a bug: this slide's body
    spends the whole allowance, which leaves nothing to record the slide card with,
    and the frontend falls back to text. What must never happen is a payload larger
    than the allowance.
    """
    monkeypatch.setattr(doc_blocks, "MAX_BLOCKS", 5)
    f = tmp_path / "dense.pptx"
    shapes = "".join(pptx_shape([f"line {i}"]) for i in range(60))
    write_pptx(str(f), {"ppt/slides/slide1.xml": pptx_slide_xml(shapes)})
    blocks, truncated = extract_blocks(str(f))
    assert truncated is True
    assert _total_blocks(blocks) <= 5


def test_a_slide_whose_body_fits_the_allowance_is_emitted_whole(tmp_path, monkeypatch):
    """The complement, so the refusal above cannot be satisfied by dropping
    everything: a deck within the allowance still comes back complete."""
    monkeypatch.setattr(doc_blocks, "MAX_BLOCKS", 20)
    f = tmp_path / "sparse.pptx"
    shapes = pptx_shape(["Agenda"], ph_type="title") + "".join(
        pptx_shape([f"line {i}"]) for i in range(3)
    )
    write_pptx(str(f), {"ppt/slides/slide1.xml": pptx_slide_xml(shapes)})
    blocks, truncated = extract_blocks(str(f))
    assert truncated is False
    assert blocks[0]["title"] == "Agenda"
    assert len(blocks[0]["blocks"]) == 3


def test_one_paragraph_cannot_emit_past_the_block_allowance_through_its_pictures(
    tmp_path, monkeypatch
):
    """ONE paragraph can reference as many distinct pictures as the archive holds.
    The loop checked the allowance only at each paragraph's top and `emit` merely
    decremented, so a single crafted paragraph emitted an image block per picture
    — each firing its own media request — well past MAX_BLOCKS."""
    monkeypatch.setattr(doc_blocks, "MAX_BLOCKS", 4)
    rels = {f"rId{i}": f"media/image{i}.png" for i in range(40)}
    media = {f"word/media/image{i}.png": PNG_1X1 for i in range(40)}
    body = "".join(docx_image_para(f"rId{i}") for i in range(40))
    f = tmp_path / "manypics.docx"
    write_docx(str(f), body, images=rels, media=media)
    blocks, truncated = extract_blocks(str(f))
    assert truncated is True
    assert len(blocks) <= 4


def test_a_table_wider_than_the_column_cap_reports_truncation_on_the_table(tmp_path, monkeypatch):
    """Dropping columns silently produced a complete-LOOKING grid with nothing in
    the UI to say the right-hand columns were missing.

    Reported ON THE TABLE, not on the document: the document-level flag renders as
    "only the beginning of this document", which describes running out of budget
    part-way through and sends the reader looking for missing pages instead of
    missing columns."""
    monkeypatch.setattr(doc_blocks, "MAX_TABLE_COLS", 3)
    f = tmp_path / "wide.docx"
    write_docx(str(f), docx_table([[f"c{i}" for i in range(9)]]))
    blocks, truncated = extract_blocks(str(f))
    assert blocks[0]["rows"] == [["c0", "c1", "c2"]]
    assert blocks[0]["truncated_cols"] is True
    assert truncated is False, "a width trim is not the document running out"


def test_many_empty_tables_cannot_build_cells_for_free(tmp_path, monkeypatch):
    """A cell is charged a minimum of one character, so the aggregate ceiling that
    bounds text bounds cells too.

    Without that floor an EMPTY cell costs nothing, and no counter bounds the
    grid: tables of empty cells sit under both per-table ceilings and under the
    block and character budgets at once, while the frontend renders a ``<td>``
    per entry for a tiny upload."""
    monkeypatch.setattr(doc_blocks, "MAX_CHARS", 60)
    f = tmp_path / "empty-grids.docx"
    write_docx(str(f), docx_table([["" for _ in range(40)] for _ in range(20)]) * 3)
    blocks, truncated = extract_blocks(str(f))
    assert truncated is True
    cells = sum(len(row) for b in blocks if b["type"] == "table" for row in b["rows"])
    # The row that spends the last of the allowance may overrun by its own width.
    assert cells <= 60 + doc_blocks.MAX_TABLE_COLS


def test_the_cell_charge_is_aggregate_across_tables_not_per_table(tmp_path, monkeypatch):
    """A per-table ceiling is what MAX_TABLE_ROWS/COLS already are; the point of
    this one is that the second table inherits what the first spent."""
    monkeypatch.setattr(doc_blocks, "MAX_CHARS", 3)
    f = tmp_path / "two.docx"
    write_docx(str(f), docx_table([["a", "b"]]) + docx_table([["c", "d"]]))
    blocks, truncated = extract_blocks(str(f))
    assert truncated is True
    grids = [b["rows"] for b in blocks if b["type"] == "table"]
    # First table spends 2 of 3; the second gets the remaining 1 and stops.
    assert grids[0] == [["a", "b"]]
    assert grids[1][0][0] == "c"


def test_a_row_whose_cells_are_content_control_wrapped_is_read_not_skipped(tmp_path):
    """A template wraps cells in ``w:sdt``, so a direct-children lookup found none.
    Reading that as "budget spent" ended the whole row loop on the first such row,
    dropping every row after it with nothing marking the gap."""
    wrapped = (
        "<w:tr><w:sdt><w:sdtContent>"
        "<w:tc><w:p><w:r><w:t>wrapped-a</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>wrapped-b</w:t></w:r></w:p></w:tc>"
        "</w:sdtContent></w:sdt></w:tr>"
    )
    f = tmp_path / "sdt-row.docx"
    write_docx(str(f), f"<w:tbl>{wrapped}</w:tbl>")
    blocks, truncated = extract_blocks(str(f))
    assert truncated is False
    assert [b["rows"] for b in blocks if b["type"] == "table"] == [[["wrapped-a", "wrapped-b"]]]


def test_a_cell_less_row_does_not_end_the_table(tmp_path):
    """The row-loop regression in its own right: a genuinely empty ``w:tr`` is
    skipped, and the rows AFTER it still arrive."""
    empty_row = "<w:tr></w:tr>"
    f = tmp_path / "gap-row.docx"
    write_docx(
        str(f),
        "<w:tbl>"
        + "<w:tr><w:tc><w:p><w:r><w:t>first</w:t></w:r></w:p></w:tc></w:tr>"
        + empty_row
        + "<w:tr><w:tc><w:p><w:r><w:t>last</w:t></w:r></w:p></w:tc></w:tr>"
        + "</w:tbl>",
    )
    blocks, truncated = extract_blocks(str(f))
    assert truncated is False
    assert [b["rows"] for b in blocks if b["type"] == "table"] == [[["first"], ["last"]]]


def test_a_nested_table_does_not_add_columns_to_the_outer_row(tmp_path):
    """``_row_cells`` descends content controls but NOT arbitrary depth: an inner
    table's cells belong to the inner table, and its text rides along on the outer
    cell's own descendant walk rather than inventing outer columns."""
    inner = "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>inner</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    f = tmp_path / "nested.docx"
    write_docx(
        str(f),
        f"<w:tbl><w:tr><w:tc><w:p><w:r><w:t>outer</w:t></w:r></w:p>{inner}</w:tc></w:tr></w:tbl>",
    )
    blocks, _ = extract_blocks(str(f))
    grids = [b["rows"] for b in blocks if b["type"] == "table"]
    assert len(grids[0][0]) == 1, "outer row must have exactly its own one cell"
    assert "inner" in grids[0][0][0]


def test_a_table_within_the_column_cap_is_not_reported_truncated(tmp_path):
    f = tmp_path / "narrow.docx"
    write_docx(str(f), docx_table([["a", "b"], ["c", "d"]]))
    blocks, truncated = extract_blocks(str(f))
    assert truncated is False
    assert blocks[0]["truncated_cols"] is False


def test_a_short_document_is_not_reported_truncated(tmp_path):
    f = tmp_path / "short.docx"
    write_docx(str(f), docx_para("done"))
    assert extract_blocks(str(f))[1] is False


@pytest.mark.parametrize("name", ["notes.txt", "book.epub", "sheet.xlsx", "old.doc"])
def test_unsupported_extensions_yield_no_blocks(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"whatever")
    assert extract_blocks(str(f)) == ([], False)


def test_a_non_zip_file_named_docx_degrades_instead_of_raising(tmp_path):
    f = tmp_path / "fake.docx"
    f.write_bytes(b"not a zip at all")
    assert extract_blocks(str(f)) == ([], False)


def test_sensitive_paths_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_blocks, "is_sensitive_path", lambda path: True)
    f = tmp_path / "secret.docx"
    write_docx(str(f), docx_para("body"))
    assert extract_blocks(str(f)) == ([], False)
    assert read_media_member(str(f), "word/media/image1.png") is None


def test_extraction_reads_through_a_supplied_handle(tmp_path):
    """The endpoint stat-gates the file then parses the SAME handle, so the bytes
    parsed are the bytes measured."""
    f = tmp_path / "handle.docx"
    write_docx(str(f), docx_para("Heading", style="Heading1"))
    with open(f, "rb") as fobj:
        blocks, _ = extract_blocks(str(f), fileobj=fobj)
    assert blocks == [{"type": "heading", "level": 1, "text": "Heading"}]


# ── read_media_member ──


def test_media_member_returns_the_stored_bytes(tmp_path):
    f = tmp_path / "pic.docx"
    write_docx(str(f), docx_para("x"), media={"word/media/image1.png": PNG_1X1})
    assert read_media_member(str(f), "word/media/image1.png") == PNG_1X1


def test_media_member_absent_from_the_archive_is_none(tmp_path):
    f = tmp_path / "pic.docx"
    write_docx(str(f), docx_para("x"), media={"word/media/image1.png": PNG_1X1})
    assert read_media_member(str(f), "word/media/nope.png") is None


def test_media_member_over_the_cap_is_none(tmp_path, monkeypatch):
    """The cap is enforced on the DECOMPRESSED bytes, so a highly compressible
    member cannot slip past by declaring a small size. The ceiling is module
    policy rather than a parameter, so this patches the constant."""
    f = tmp_path / "big.docx"
    write_docx(str(f), docx_para("x"), media={"word/media/image1.png": b"\0" * 5000})
    monkeypatch.setattr(doc_blocks, "MAX_MEDIA_BYTES", 100)
    assert read_media_member(str(f), "word/media/image1.png") is None
    monkeypatch.setattr(doc_blocks, "MAX_MEDIA_BYTES", 9000)
    assert read_media_member(str(f), "word/media/image1.png") is not None


def test_media_member_refused_for_a_non_office_extension(tmp_path):
    f = tmp_path / "archive.zip"
    write_docx(str(f), docx_para("x"), media={"word/media/image1.png": PNG_1X1})
    assert read_media_member(str(f), "word/media/image1.png") is None
