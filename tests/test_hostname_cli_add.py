"""issuedb #66 D4: `hostname add` must not issue setup steps for a live name.

Registration is idempotent server-side, but the client announced it as a fresh
registration and printed DNS records to publish -- instructing an operator to
churn the DNS of a hostname already carrying production traffic.

Both directions are asserted here. Suppressing the records whenever a name is
already registered would satisfy the first test and silently destroy first
registration, which is the only case the instructions exist for.
"""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner

from retunnel.client import hostname_cli

ROUTABLE = {
    "hostname": "live.example.com",
    "verified": True,
    "certificate": True,
    "routable": True,
    "verification_error": None,
    "certificate_error": None,
    "dns": {
        "cname": {"name": "live.example.com", "value": "retunnel.net"},
        "txt": {
            "name": "_retunnel-challenge.live.example.com",
            "value": "tok",
        },
    },
}

FRESH = {
    "hostname": "new.example.com",
    "verified": False,
    "certificate": False,
    "routable": False,
    "verification_error": None,
    "certificate_error": None,
    "dns": {
        "cname": {"name": "new.example.com", "value": "retunnel.net"},
        "txt": {"name": "_retunnel-challenge.new.example.com", "value": "tok"},
    },
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _stub(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> None:
    monkeypatch.setattr(hostname_cli, "_call", lambda *a, **k: (200, body))
    monkeypatch.setattr(hostname_cli, "_run", lambda coro: coro)


def test_routable_hostname_prints_no_dns_instructions(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub(monkeypatch, ROUTABLE)
    res = runner.invoke(hostname_cli.hostname, ["add", "live.example.com"])
    assert res.exit_code == 0, res.output
    assert "already registered and live" in res.output
    assert "Publish these two DNS records" not in res.output
    assert "CNAME" not in res.output
    assert "_retunnel-challenge" not in res.output
    assert "Registered live.example.com" not in res.output


def test_fresh_hostname_still_prints_dns_instructions(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The known-positive. Without it the fix can pass by printing nothing."""
    _stub(monkeypatch, FRESH)
    res = runner.invoke(hostname_cli.hostname, ["add", "new.example.com"])
    assert res.exit_code == 0, res.output
    assert "Registered new.example.com" in res.output
    assert "Publish these two DNS records" in res.output
    assert "CNAME" in res.output
    assert "_retunnel-challenge.new.example.com" in res.output


def test_json_output_is_unchanged_for_a_routable_hostname(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json is the scripting contract; the human-form fix must not alter it."""
    import json

    _stub(monkeypatch, ROUTABLE)
    res = runner.invoke(
        hostname_cli.hostname, ["add", "live.example.com", "--json"]
    )
    assert res.exit_code == 0, res.output
    assert json.loads(res.output) == ROUTABLE
