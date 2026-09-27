"""issuedb #93 (audit R3): an unattended client never gives up on a server that
told it to wait, and budget exhaustion is restartable (75), not a refusal (69).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from retunnel.client import client as client_mod
from retunnel.client import refusals
from retunnel.client.client import ReTunnelClient, TunnelConfig
from retunnel.core.exceptions import TerminalError, TunnelError
from retunnel.msg.messages import Error

from .fake_server import Conn, FakeServer, hold_open


def _cfg() -> TunnelConfig:
    return TunnelConfig(protocol="http", local_port=1)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_mod, "jittered", lambda delay, r: 0.01)


class TestClassification:
    @pytest.mark.parametrize("code", sorted(refusals.TRANSIENT_CODES))
    def test_server_declared_transient_codes(self, code: str) -> None:
        err = refusals.refusal(Error(code=code, message="later"))
        assert isinstance(err, refusals.TransientRefusal)

    @pytest.mark.parametrize("code", sorted(refusals.TERMINAL_CODES))
    def test_terminal_codes_keep_their_exit_code(self, code: str) -> None:
        err = refusals.refusal(Error(code=code, message="no"))
        assert isinstance(err, TerminalError)
        assert err.exit_code == refusals.TERMINAL_CODES[code]

    def test_unknown_code_is_budgeted(self) -> None:
        err = refusals.refusal(Error(code="SOMETHING_NEW", message="?"))
        assert type(err) is TunnelError

    def test_no_code_is_both_terminal_and_transient(self) -> None:
        assert not refusals.TRANSIENT_CODES & set(refusals.TERMINAL_CODES)

    def test_certificate_being_issued_is_transient(self) -> None:
        assert "HOSTNAME_NO_CERTIFICATE" in refusals.TRANSIENT_CODES

    @pytest.mark.parametrize("r", [0.0, 0.5, 0.999])
    def test_jitter_never_exceeds_the_cap(self, r: float) -> None:
        assert (
            refusals.jittered(refusals.MAX_BACKOFF, r) <= refusals.MAX_BACKOFF
        )


def _refuse(code: str) -> Callable[[Conn], Awaitable[None]]:
    async def script(conn: Conn) -> None:
        await conn.expect_auth()
        await conn.refuse_create(code, "try later")
        await hold_open(conn)

    return script


async def _accept(conn: Conn) -> None:
    await conn.expect_auth()
    await conn.expect_create()
    await hold_open(conn)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["SERVICE_UNAVAILABLE", "HOSTNAME_NO_CERTIFICATE"]
)
async def test_transient_refusals_outlast_the_budget(code: str) -> None:
    refusing = [_refuse(code)] * (refusals.RETRY_BUDGET + 4)
    async with FakeServer() as srv:
        srv.on_connection(*refusing, _accept)
        client = ReTunnelClient(srv.url, "tok")
        try:
            tunnel = await asyncio.wait_for(client.request_tunnel(_cfg()), 20)
            assert tunnel.url.startswith("https://")
            assert len(srv.connections) == refusals.RETRY_BUDGET + 5
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_unknown_refusal_exhausts_the_budget_with_exit_75() -> None:
    async with FakeServer() as srv:
        srv.on_connection(_refuse("SOMETHING_NEW"))
        client = ReTunnelClient(srv.url, "tok")
        try:
            with pytest.raises(TerminalError) as ei:
                await asyncio.wait_for(client.request_tunnel(_cfg()), 20)
            assert ei.value.code == "RETRY_BUDGET_EXHAUSTED"
            assert ei.value.exit_code == refusals.EXIT_TEMPFAIL
            assert len(srv.connections) == refusals.RETRY_BUDGET + 1
        finally:
            await client.close()
