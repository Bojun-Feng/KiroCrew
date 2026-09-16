"""The Slack gateway's cron turn loops consume the post-compaction flag.

``session_compaction`` marks ``needs_reinjection`` on a live session after an
in-place compaction dropped its session-start context. The two cron turn loops in
``slack/gateway.py`` (single-agent and ``agent_sequence``) are their own copies of
the turn loop, so each must read-and-clear the flag itself, forward it to
``build_message``, and put it back when the turn that consumed it never lands --
the contract the dashboard runner keeps in its ``finally``.

The harness mirrors ``test_cron_acp_retry.py``: a ``GatewayOrchestrator`` built
with ``__new__`` and mocked sessions, with the cron callback captured off
``CronService.create``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kiro_crew.cron import CronJob, CronSchedule


@pytest.fixture
def gw_and_cb() -> tuple[Any, Callable[[], Any], Callable[..., Any]]:
    from kiro_crew.slack.gateway import GatewayOrchestrator

    gw = GatewayOrchestrator.__new__(GatewayOrchestrator)
    gw.sessions = MagicMock()
    gw.sessions.get_pid = MagicMock(return_value=None)
    gw.sessions.get_or_create = AsyncMock(return_value=(MagicMock(), False, False))
    gw.sessions.release = MagicMock()
    gw.sessions.reset = AsyncMock()
    # The flag surface under test: armed once, like a session that just compacted.
    gw.sessions.consume_needs_reinjection = MagicMock(side_effect=[True, False, False, False])
    gw.sessions.mark_needs_reinjection = MagicMock()
    gw.ctx_builder = MagicMock()
    gw.ctx_builder.build_message = MagicMock(return_value=("msg", None))
    gw.ctx_builder.hooks = MagicMock()
    gw.slack = None
    gw.conv_log = None
    gw.dashboard_state = None
    gw._owner_id = "U000"
    gw.subagent_mgr = None
    gw._cron_injecting = {}
    gw._no_crons = False
    gw._interactive_approval = MagicMock(return_value="interactive_cb")

    captured_cb: list[Any] = [None]

    def capture_cron(on_job: Any = None, **kw: Any) -> MagicMock:
        captured_cb[0] = on_job
        svc = MagicMock()
        svc.start = AsyncMock()
        return svc

    return gw, lambda: captured_cb[0], capture_cron


def _job(**kw: Any) -> CronJob:
    return CronJob(
        id=kw.pop("id", "j1"),
        name="test",
        message="msg",
        schedule=CronSchedule(kind="every", every_secs=60),
        **kw,
    )


def _run(gw: Any, get_cb: Callable[[], Any], capture_cron: Any, job: CronJob, stream: Any) -> Any:
    with (
        patch("kiro_crew.slack.gateway.stream_and_collect", side_effect=stream),
        patch("kiro_crew.slack.gateway.redact_exfiltration_urls", return_value=("", False)),
        patch("kiro_crew.slack.gateway.redact_credentials", return_value=("", False)),
        patch(
            "kiro_crew.slack.gateway.CronService.create", new=AsyncMock(side_effect=capture_cron)
        ),
    ):

        async def _init_and_run() -> Any:
            await gw._init_cron()
            cb = get_cb()
            assert cb is not None
            return await cb(job)

        return asyncio.run(_init_and_run())


def _reinjection_kwargs(gw: Any) -> list[bool]:
    return [
        call.kwargs["needs_reinjection"] for call in gw.ctx_builder.build_message.call_args_list
    ]


class TestSingleAgentCronTurn:
    def test_a_compacted_session_forwards_the_flag_to_build_message(self, gw_and_cb) -> None:
        gw, get_cb, capture_cron = gw_and_cb

        async def ok(*a: Any, **k: Any) -> str:
            return "done"

        _run(gw, get_cb, capture_cron, _job(), ok)

        gw.sessions.consume_needs_reinjection.assert_called_once_with("cron:j1")
        assert _reinjection_kwargs(gw) == [True]
        # Landed: consumed exactly once, and NOT put back.
        gw.sessions.mark_needs_reinjection.assert_not_called()

    def test_a_session_stand_in_without_the_flag_gets_the_false_default(self, gw_and_cb) -> None:
        gw, get_cb, capture_cron = gw_and_cb
        del gw.sessions.consume_needs_reinjection
        del gw.sessions.mark_needs_reinjection

        async def ok(*a: Any, **k: Any) -> str:
            return "done"

        _run(gw, get_cb, capture_cron, _job(), ok)

        assert _reinjection_kwargs(gw) == [False]

    def test_a_failed_consuming_turn_puts_the_flag_back(self, gw_and_cb) -> None:
        # The flag is cleared BEFORE build_message; a stream error on that very
        # turn discards the prompt carrying the re-injected context. The re-arm
        # runs in the finally, ahead of the session release/reset.
        gw, get_cb, capture_cron = gw_and_cb
        gw.dashboard_state = MagicMock()

        async def boom(*a: Any, **k: Any) -> str:
            raise RuntimeError("provider fell over")

        with pytest.raises(RuntimeError):
            _run(gw, get_cb, capture_cron, _job(), boom)

        assert _reinjection_kwargs(gw) == [True]
        gw.sessions.mark_needs_reinjection.assert_called_once_with("cron:j1")


class TestAgentSequenceCronTurn:
    def test_each_agent_turn_reads_its_own_key(self, gw_and_cb) -> None:
        gw, get_cb, capture_cron = gw_and_cb

        async def ok(*a: Any, **k: Any) -> str:
            return "done"

        _run(gw, get_cb, capture_cron, _job(agent_sequence=["alpha", "beta"]), ok)

        consumed = [c.args[0] for c in gw.sessions.consume_needs_reinjection.call_args_list]
        assert consumed == ["cron:j1:alpha", "cron:j1:beta"]
        # Only alpha's session had compacted (the fixture arms the flag once).
        assert _reinjection_kwargs(gw) == [True, False]
        gw.sessions.mark_needs_reinjection.assert_not_called()

    def test_a_failed_consuming_agent_turn_puts_the_flag_back(self, gw_and_cb) -> None:
        gw, get_cb, capture_cron = gw_and_cb
        gw.dashboard_state = MagicMock()

        async def boom(*a: Any, **k: Any) -> str:
            raise RuntimeError("provider fell over")

        with pytest.raises(RuntimeError):
            _run(gw, get_cb, capture_cron, _job(agent_sequence=["alpha", "beta"]), boom)

        assert _reinjection_kwargs(gw) == [True]
        gw.sessions.mark_needs_reinjection.assert_called_once_with("cron:j1:alpha")
