"""Tests for /api/file-office-media — one embedded picture out of a docx/pptx.

This endpoint reads a caller-named member out of a caller-named archive, so its
whole value is in what it REFUSES. Pinned here:

* the member allowlist is checked before any I/O, and no traversal, separator or
  extension trick gets past it;
* the response body is served only when the CONTENT sniffs as raster — an SVG
  member wearing a .png name is refused, because vector markup is script-capable;
* the path goes through the shared file-serving prefix, so sensitive paths,
  symlinks and oversize files are refused here exactly as elsewhere;
* every "no" other than the sensitive-path policy answer looks identical from
  outside, so a request loop cannot enumerate a document's members.
"""

from __future__ import annotations

import json
import os
from typing import NamedTuple
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from ooxml_fixtures import PNG_1X1, docx_para, write_docx

from kiro_crew.dashboard.handlers import api_file_office_media
from kiro_crew.dashboard.handlers.files import _MAX_UPLOAD_BYTES, _OFFICE_MEDIA_MEMBER_RE

_MEMBER = "word/media/image1.png"


def _make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/file-office-media", api_file_office_media)
    return app


@pytest.fixture
def mock_sel():
    with (
        patch("kiro_crew.sel.sel") as m,
        patch("kiro_crew.dashboard.handlers.files.is_sensitive_path", return_value=False),
    ):
        instance = MagicMock()
        m.return_value = instance
        yield instance


class _Answer(NamedTuple):
    """A completed response: status, headers and body read before teardown.

    The body has to be read inside the client's context manager, so the tests
    below take this snapshot rather than a live response object.
    """

    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def code(self) -> str:
        return str(json.loads(self.body)["code"])


def _docx_with(tmp_path, media: dict[str, bytes], name: str = "pic.docx"):
    f = tmp_path / name
    write_docx(str(f), docx_para("caption"), media=media)
    return f


async def _get(path, member: str) -> _Answer:
    async with TestClient(TestServer(_make_app())) as client:
        resp = await client.get(f"/api/file-office-media?path={path}&member={member}")
        return _Answer(resp.status, dict(resp.headers), await resp.read())


# ── success ──


@pytest.mark.asyncio
async def test_raster_member_is_served_with_its_sniffed_type_and_nosniff(tmp_path, mock_sel):
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1})
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)):
        answer = await _get(f, _MEMBER)
    assert answer.status == 200
    assert answer.headers["Content-Type"] == "image/png"
    # Without nosniff a member whose bytes sniff as PNG here could still be
    # re-interpreted by the browser from its own heuristics.
    assert answer.headers["X-Content-Type-Options"] == "nosniff"
    assert answer.body == PNG_1X1


@pytest.mark.asyncio
async def test_success_is_sel_audited(tmp_path, mock_sel):
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1})
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)):
        assert (await _get(f, _MEMBER)).status == 200
    kwargs = mock_sel.log_tool_invocation.call_args.kwargs
    assert kwargs["tool_name"] == "file_office_media"
    assert kwargs["outcome"] == "success"


# ── content refusals ──


@pytest.mark.asyncio
async def test_svg_member_named_png_is_refused_by_the_content_sniff(tmp_path, mock_sel):
    """The extension allowlist alone cannot decide this: the member's NAME is on
    the allowlist and its CONTENT is script-capable vector markup."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    f = _docx_with(tmp_path, {_MEMBER: svg})
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)):
        answer = await _get(f, _MEMBER)
    assert answer.status == 404
    assert answer.code == "not_found"


@pytest.mark.asyncio
async def test_non_raster_bytes_are_refused(tmp_path, mock_sel):
    f = _docx_with(tmp_path, {_MEMBER: b"%PDF-1.7 not an image at all"})
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)):
        assert (await _get(f, _MEMBER)).status == 404


@pytest.mark.asyncio
async def test_oversize_member_is_refused(tmp_path, mock_sel):
    """The cap is enforced on the DECOMPRESSED bytes, so a member that inflates
    past it is refused however small its ZIP header claims it is."""
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1 + b"\0" * 2048})
    with (
        patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)),
        patch("kiro_crew.doc_blocks.MAX_MEDIA_BYTES", 64),
    ):
        assert (await _get(f, _MEMBER)).status == 404
    # Same member, default ceiling: the refusal above is the cap, not the bytes.
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)):
        assert (await _get(f, _MEMBER)).status == 200


@pytest.mark.asyncio
async def test_member_absent_from_the_archive_is_refused(tmp_path, mock_sel):
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1})
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)):
        answer = await _get(f, "word/media/absent.png")
    assert answer.status == 404
    assert answer.code == "not_found"


# ── member allowlist ──


@pytest.mark.parametrize(
    "member",
    [
        "",
        "word/document.xml",
        "ppt/presentation.xml",
        "..%2F..%2Fetc%2Fpasswd",
        "word/media/..%2F..%2F..%2Fetc%2Fpasswd",
        "word/media/logo.svg",
        "word/media/logo.emf",
        "word/media/sub/dir/logo.png",
        "WORD/media/logo.png",
        "/word/media/logo.png",
        "word%5Cmedia%5Clogo.png",
        "word/media/" + "a" * 200 + ".png",
        "word/media/image1.png%00.svg",
    ],
)
@pytest.mark.asyncio
async def test_members_outside_the_allowlist_are_refused_before_any_io(
    tmp_path,
    mock_sel,
    member,
):
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1})
    # No _validate_dashboard_path patch and no read patch: the allowlist rejects
    # before the path is validated or the archive opened, so this passes without
    # either — which is the property being asserted.
    answer = await _get(f, member)
    assert answer.status == 400
    assert answer.code == "invalid_member"


def test_the_allowlist_pattern_admits_exactly_the_media_shapes():
    """Pinned directly as well as through the endpoint: this pattern is the only
    thing between a caller-supplied string and a ZIP member name."""
    for good in (
        "word/media/image1.png",
        "word/media/image10.JPG",
        "ppt/media/image2.jpeg",
        "ppt/media/photo-1_final.webp",
        "word/media/frame.gif",
    ):
        assert _OFFICE_MEDIA_MEMBER_RE.match(good), good
    for bad in (
        "word/media/image1.png\n",
        "word/media/image1.png.svg",
        "xl/media/image1.png",
        "word/media/.png",
        "word/media/a/b.png",
        "WORD/media/image1.png",
    ):
        assert not _OFFICE_MEDIA_MEMBER_RE.match(bad), bad


# ── path boundary (shared prefix) ──


@pytest.mark.asyncio
async def test_sensitive_path_is_refused_with_its_own_status(tmp_path, mock_sel):
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1})
    with (
        patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)),
        patch("kiro_crew.dashboard.handlers.files.is_sensitive_path", return_value=True),
    ):
        answer = await _get(f, _MEMBER)
    assert answer.status == 403
    assert answer.code == "sensitive_path"


@pytest.mark.asyncio
async def test_path_the_validator_rejects_is_refused(tmp_path, mock_sel):
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1})
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=None):
        answer = await _get(f, _MEMBER)
    assert answer.status == 404
    assert answer.code == "not_found"


@pytest.mark.asyncio
async def test_symlink_to_a_readable_document_is_refused(tmp_path, mock_sel):
    real = _docx_with(tmp_path, {_MEMBER: PNG_1X1}, name="real.docx")
    link = tmp_path / "link.docx"
    os.symlink(real, link)
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(link)):
        assert (await _get(link, _MEMBER)).status == 404


@pytest.mark.asyncio
async def test_oversize_document_is_refused_before_the_archive_is_opened(tmp_path, mock_sel):
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1})
    with (
        patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)),
        patch("kiro_crew.dashboard.handlers.files._MAX_UPLOAD_BYTES", 8),
        patch("kiro_crew.dashboard.handlers.files.read_media_member") as never,
    ):
        assert (await _get(f, _MEMBER)).status == 404
        never.assert_not_called()
    assert _MAX_UPLOAD_BYTES > 8  # the patch above narrows the cap, it is not the default


@pytest.mark.asyncio
async def test_non_office_extension_is_refused(tmp_path, mock_sel):
    f = _docx_with(tmp_path, {_MEMBER: PNG_1X1}, name="archive.zip")
    with patch("kiro_crew.dashboard.handlers._validate_dashboard_path", return_value=str(f)):
        assert (await _get(f, _MEMBER)).status == 404
