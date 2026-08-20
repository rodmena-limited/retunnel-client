"""Stream plumbing: v2 reassembly, framing, basic auth, verb/header helpers."""

from __future__ import annotations

import base64

import pytest

from retunnel.client.streams import (
    Sender,
    StreamState,
    basic_auth_ok,
    open_headers,
    open_method,
)
from retunnel.msg.messages import (
    MAX_CHUNK_SIZE,
    StreamClose,
    StreamData,
    StreamOpen,
    StreamReset,
    deserialize,
)


class TestNextMessage:
    @pytest.mark.asyncio
    async def test_v1_frames_are_whole_messages(self) -> None:
        s = StreamState(1)
        s.queue.put_nowait(StreamData(1, b"one", "text"))
        s.queue.put_nowait(StreamData(1, b"", "text"))
        s.queue.put_nowait(StreamClose(1, code=1000, reason="bye"))
        assert await s.next_message() == ("data", b"one", "text")
        assert await s.next_message() == ("data", b"", "text")
        assert await s.next_message() == ("close", 1000, "bye")

    @pytest.mark.asyncio
    async def test_v2_frames_reassemble_across_a_split_code_point(
        self,
    ) -> None:
        s = StreamState(1)
        payload = ("€" * 30000).encode()  # 3-byte chars, 65536 % 3 != 0
        a, b = payload[:MAX_CHUNK_SIZE], payload[MAX_CHUNK_SIZE:]
        s.queue.put_nowait(StreamData(1, a, "text", fin=False))
        s.queue.put_nowait(StreamData(1, b, "text", fin=True))
        s.queue.put_nowait(StreamData(1, b"", "binary", fin=True))
        s.queue.put_nowait(StreamReset(1, reason="gone"))
        kind, data, ws_type = await s.next_message()
        assert (kind, ws_type) == ("data", "text")
        assert data == payload and isinstance(data, bytes)
        assert data.decode() == "€" * 30000
        assert await s.next_message() == ("data", b"", "binary")
        assert await s.next_message() == ("close", 1011, "gone")


class TestSender:
    @pytest.mark.asyncio
    async def test_v2_message_is_fin_framed(self) -> None:
        sent: list[bytes] = []

        async def raw(b: bytes) -> None:
            sent.append(b)

        await Sender(raw, 7, v2=True).message(
            b"x" * (MAX_CHUNK_SIZE + 1), "text"
        )
        frames = [deserialize(b) for b in sent]
        assert [getattr(f, "fin", None) for f in frames] == [False, True]
        assert all(getattr(f, "ws_type", None) == "text" for f in frames)

        sent.clear()
        await Sender(raw, 7, v2=True).message(b"", "text")
        f = deserialize(sent[0])
        assert isinstance(f, StreamData) and f.data == b"" and f.fin is True

    @pytest.mark.asyncio
    async def test_v1_message_is_one_unframed_frame(self) -> None:
        sent: list[bytes] = []

        async def raw(b: bytes) -> None:
            sent.append(b)

        await Sender(raw, 7, v2=False).message(
            b"x" * (2 * MAX_CHUNK_SIZE), "binary"
        )
        assert len(sent) == 1
        f = deserialize(sent[0])
        assert isinstance(f, StreamData) and f.fin is None


class TestHelpers:
    def test_method_from_field_or_header(self) -> None:
        assert (
            open_method(StreamOpen(1, "t", "http", method="PATCH", headers=[]))
            == "PATCH"
        )
        assert (
            open_method(
                StreamOpen(1, "t", "http", headers={"Method": "DELETE"})
            )
            == "DELETE"
        )
        assert open_method(StreamOpen(1, "t", "http", headers={})) == "GET"

    def test_headers_keep_order_and_dups_and_drop_verb(self) -> None:
        msg = StreamOpen(
            1,
            "t",
            "http",
            headers=[["Method", "GET"], ["Cookie", "a"], ["Cookie", "b"]],
        )
        assert open_headers(msg) == [("Cookie", "a"), ("Cookie", "b")]

    def test_basic_auth(self) -> None:
        good = "Basic " + base64.b64encode(b"user:pass").decode()
        assert basic_auth_ok([("authorization", good)], "user:pass")
        assert not basic_auth_ok([("Authorization", "Bearer x")], "user:pass")
        assert not basic_auth_ok([], "user:pass")
