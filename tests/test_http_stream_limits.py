"""issuedb #93 (audit R6): a slow or hostile public cannot freeze or exhaust a
small client through the HTTP handler.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from retunnel.client import http_stream
from retunnel.client.http_stream import BodyBudget, handle_http_stream
from retunnel.client.streams import Sender, StreamState
from retunnel.local_proxy import (
    LOCAL_CONNECT_TIMEOUT,
    LOCAL_POOL_LIMIT,
    LocalProxy,
)
from retunnel.msg.messages import StreamClose, StreamData, StreamOpen


class FakeSender:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    async def message(self, data: bytes) -> None:
        self.events.append(("message", data))

    async def chunk(self, data: bytes) -> None:
        self.events.append(("chunk", data))

    async def close(self) -> None:
        self.events.append(("close", None))

    async def reset(self, reason: str) -> None:
        self.events.append(("reset", reason))


class HangingLocal:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def open_http(self, *args: Any) -> Any:
        self.started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _open(stream_id: int = 1, has_body: bool = False) -> StreamOpen:
    return StreamOpen(
        stream_id=stream_id,
        tunnel_id="t",
        mode="http",
        path="/",
        method="POST",
        headers=[["host", "x.example"]],
        has_body=has_body,
    )


@pytest.mark.asyncio
async def test_server_close_cancels_a_hanging_local_request() -> None:
    state = StreamState(1)
    local = HangingLocal()
    sender = FakeSender()
    task = asyncio.ensure_future(
        handle_http_stream(
            _open(), state, cast(Sender, sender), cast(LocalProxy, local), None
        )
    )
    await asyncio.wait_for(local.started.wait(), 5)
    state.queue.put_nowait(StreamClose(stream_id=1))
    await asyncio.wait_for(task, 5)
    assert local.cancelled
    assert sender.events == []


@pytest.mark.asyncio
async def test_body_budget_refuses_past_the_cap_and_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_stream, "MAX_BUFFERED_BODIES", 10)
    monkeypatch.setattr(BodyBudget, "in_use", 0)
    state = StreamState(1)
    sender = FakeSender()
    state.queue.put_nowait(StreamData(stream_id=1, data=b"x" * 11, fin=True))
    await asyncio.wait_for(
        handle_http_stream(
            _open(has_body=True),
            state,
            cast(Sender, sender),
            cast(LocalProxy, HangingLocal()),
            None,
        ),
        5,
    )
    assert sender.events and sender.events[0][0] == "reset"
    assert "memory cap" in sender.events[0][1]
    assert BodyBudget.in_use == 0


def test_budget_take_release_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_stream, "MAX_BUFFERED_BODIES", 10)
    monkeypatch.setattr(BodyBudget, "in_use", 0)
    a, b = BodyBudget(), BodyBudget()
    a.take(6)
    with pytest.raises(ValueError):
        b.take(6)
    a.release()
    b.take(6)
    b.release()
    assert BodyBudget.in_use == 0


@pytest.mark.asyncio
async def test_http_and_websocket_use_separate_bounded_pools() -> None:
    local = LocalProxy(1)
    try:
        http = local._get_session()
        ws = local._get_ws_session()
        assert http is not ws
        for session in (http, ws):
            assert session.connector is not None
            assert session.connector.limit == LOCAL_POOL_LIMIT == 256
            assert session.timeout.connect == LOCAL_CONNECT_TIMEOUT
    finally:
        await local.close()
