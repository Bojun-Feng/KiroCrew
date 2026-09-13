"""Routes behind the member inbox-model tools: ``outbox_send``, ``peer_send``.

Strict-internal like the session-control routes (loopback + ``X-Internal-Secret``):
the caller's identity is the ``X-Session-Key`` of the member WAKE slot (or the
member DM slot during migration), and that key is what authorizes the write —
a wake may only write ITS member's outbox and send AS its member; acking is the
runner's, never a tool. Parsing and status mapping only; admission lives in
``kiro_crew.member_peer`` and the stores in ``kiro_crew.member_inbox``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web

from kiro_crew.dashboard.handlers._shared import _read_session_key
from kiro_crew.dashboard.handlers.session_control import _require_internal
from kiro_crew.dashboard.state import DashboardState
from kiro_crew.member_inbox import (
    OUTBOX_REPLY_KIND,
    VIEW_BORN_PENDING,
    InboxError,
    OutboxStore,
    inbox_model_enabled,
    member_slug_from_key,
    strip_reserved_refs,
)
from kiro_crew.member_peer import PeerSendError, peer_send

logger = logging.getLogger(__name__)


def _refuse(
    message: str, code: str, status: int = 403, *, retry_after: float | None = None
) -> web.Response:
    # Two literal bodies rather than one with a `**spread`: the error-code
    # contract (test_error_code_contract) can only see a `code` it can read off
    # the dict literal, and a spread makes the body opaque to it.
    if retry_after is not None:
        return web.json_response(
            {"error": message, "code": code, "retry_after": retry_after}, status=status
        )
    return web.json_response({"error": message, "code": code}, status=status)


async def _body(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 - malformed JSON is a 400, not a 500
        return {}
    return data if isinstance(data, dict) else {}


async def _caller(state: DashboardState, request: web.Request) -> tuple[str, str] | web.Response:
    """``(caller_key, slug)`` for a member-wake / member caller, or the refusal."""
    from kiro_crew.dashboard.session_control import caller_slot_key

    session_key = _read_session_key(request)
    caller_key = caller_slot_key(state, session_key)
    slug = member_slug_from_key(caller_key)
    if not caller_key or slug is None:
        return _refuse("only a crew member's wake may call this", "member_caller_required")
    # The flag is a config read (disk): off the loop like every other one here.
    if not await asyncio.to_thread(inbox_model_enabled, slug):
        return _refuse(f"member {slug!r} is not on the inbox model", "member_not_flagged", 409)
    return caller_key, slug


async def api_member_inbox_outbox(request: web.Request) -> web.Response:
    """POST /api/member-inbox/outbox {body, refs?} — write a reply into the projection."""
    refused = await _require_internal(request)
    if refused is not None:
        return refused
    state: DashboardState = request.app["state"]
    who = await _caller(state, request)
    if isinstance(who, web.Response):
        return who
    caller_key, slug = who
    body = await _body(request)
    text = body.get("body")
    if not isinstance(text, str) or not text.strip():
        return _refuse("body is required", "message_empty", 400)
    # Reserved keys are the runner's: `completed` in particular is the
    # redelivery idempotency stamp, and a model must not be able to set it.
    refs: dict[str, Any] = strip_reserved_refs(body.get("refs"))
    from kiro_crew.dashboard.chat_delivery import sanitize_outbound

    slot = state.get_slot(caller_key)
    is_wake = slot is not None and getattr(slot, "_wake_slug", "") == slug
    # `in_reply_to` is the runner's, never the model's: it is what makes the
    # reply the idempotency record for this batch on redelivery.
    batch_ids = list(getattr(slot, "_wake_batch_ids", []) or []) if is_wake else []
    try:
        row = await asyncio.to_thread(
            OutboxStore(slug).append,
            kind=OUTBOX_REPLY_KIND,
            body=sanitize_outbound(text),
            # Born `view=pending` in the same durable write (see member_inbox.VIEW_REF).
            refs={**refs, "wake_key": caller_key, "in_reply_to": batch_ids, **VIEW_BORN_PENDING},
        )
    except InboxError as exc:
        return _refuse(str(exc), "message_too_long", 400)
    if is_wake:
        slot._wake_outbox_sent = True  # type: ignore[union-attr]
    from kiro_crew.dashboard.member_wake import _mirror_record
    from kiro_crew.member_inbox import member_owner_key

    # The caller IS the wake: folding its key gives the thread key of the same
    # memory generation (a bare slug would miss a private V2 thread).
    await _mirror_record(
        state,
        member_owner_key(caller_key),
        OutboxStore(slug),
        row,
        "assistant",
        {"peer_dm": {"outbox_id": row.id, "wake": caller_key}},
    )
    return web.json_response({"ok": True, "outbox_id": row.id})


async def api_member_inbox_peer_send(request: web.Request) -> web.Response:
    """POST /api/member-inbox/peer-send {to, body, refs?} — message another member."""
    refused = await _require_internal(request)
    if refused is not None:
        return refused
    state: DashboardState = request.app["state"]
    who = await _caller(state, request)
    if isinstance(who, web.Response):
        return who
    caller_key, slug = who
    body = await _body(request)
    to = body.get("to")
    text = body.get("body")
    if not isinstance(to, str) or not to.strip():
        return _refuse("to is required", "target_required", 400)
    if not isinstance(text, str) or not text.strip():
        return _refuse("body is required", "message_empty", 400)
    refs: dict[str, Any] = strip_reserved_refs(body.get("refs"))
    slot = state.get_slot(caller_key)
    inbound_hop = int(getattr(slot, "_wake_inbound_hop", 0) or 0)
    try:
        receipt = await asyncio.to_thread(
            peer_send,
            caller_key=caller_key,
            sender_slug=slug,
            target=to.strip(),
            body=text,
            inbound_hop=inbound_hop,
            refs=refs,
        )
    except PeerSendError as exc:
        retry_after = round(exc.retry_after, 1) if exc.retry_after is not None else None
        return _refuse(str(exc), exc.code, exc.status, retry_after=retry_after)
    return web.json_response(receipt)
