"""issuedb #72: the credential file, basic auth, and loopback detection."""

from __future__ import annotations

import base64
import json
import multiprocessing
import os
import sys
from pathlib import Path

import pytest

from retunnel.client.api_client import (
    APIError,
    is_loopback_url,
    registration_refusal,
)
from retunnel.client.streams import basic_auth_ok
from retunnel.core import conf_store
from retunnel.core.conf_store import ConfigUnreadable


def test_missing_file_reads_as_none(tmp_path: Path) -> None:
    assert conf_store.read(tmp_path / "absent.conf") is None


@pytest.mark.parametrize(
    "content", ["", '{"auth_token": "abc', "not json", "[1, 2]", "null"]
)
def test_unreadable_file_raises_and_is_not_overwritten(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "c.conf"
    path.write_text(content)
    with pytest.raises(ConfigUnreadable):
        conf_store.read(path)
    with pytest.raises(ConfigUnreadable):
        conf_store.update(path, lambda d: d.update({"auth_token": "new"}))
    assert path.read_text() == content


def test_update_preserves_keys_it_does_not_touch(tmp_path: Path) -> None:
    path = tmp_path / "c.conf"
    path.write_text(json.dumps({"auth_token": "t", "api_key": "legacy"}))
    conf_store.update(path, lambda d: d.update({"server_url": "wss://x"}))
    data = json.loads(path.read_text())
    assert data == {
        "auth_token": "t",
        "api_key": "legacy",
        "server_url": "wss://x",
    }


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_written_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "c.conf"
    conf_store.update(path, lambda d: d.update({"auth_token": "t"}))
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_explicit_recovery_keeps_the_corrupt_copy(tmp_path: Path) -> None:
    path = tmp_path / "c.conf"
    path.write_text('{"auth_token": "tor')
    conf_store.update(
        path,
        lambda d: d.update({"auth_token": "fresh"}),
        replace_unreadable=True,
    )
    assert json.loads(path.read_text()) == {"auth_token": "fresh"}
    aside = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert len(aside) == 1
    assert aside[0].read_text() == '{"auth_token": "tor'


def _writer(path_str: str, key: str) -> None:
    for i in range(50):

        def change(d: dict[str, object], n: int = i) -> None:
            d[key] = n

        conf_store.update(Path(path_str), change)


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl lock is POSIX-only")
def test_concurrent_processes_lose_no_update(tmp_path: Path) -> None:
    """Two processes doing read-modify-write must not drop each other's key."""
    path = tmp_path / "c.conf"
    conf_store.update(path, lambda d: d.update({"auth_token": "keep"}))
    ctx = multiprocessing.get_context("fork")
    procs = [
        ctx.Process(target=_writer, args=(str(path), k)) for k in ("a", "b")
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
        assert p.exitcode == 0
    data = json.loads(path.read_text())
    assert data == {"auth_token": "keep", "a": 49, "b": 49}


def _hdr(value: str) -> list[tuple[str, str]]:
    return [("Authorization", value)]


GOOD = base64.b64encode(b"probe:s3cret").decode()


@pytest.mark.parametrize("scheme", ["Basic", "basic", "BASIC", "bAsIc"])
def test_basic_auth_scheme_is_case_insensitive(scheme: str) -> None:
    assert basic_auth_ok(_hdr(f"{scheme} {GOOD}"), "probe:s3cret")


@pytest.mark.parametrize(
    "value",
    [
        "Basic " + base64.b64encode(b"probe:wrong").decode(),
        "Bearer " + GOOD,
        "Basic !!!not-base64!!!",
        "Basic",
        "",
    ],
)
def test_basic_auth_refuses_wrong_or_malformed(value: str) -> None:
    assert not basic_auth_ok(_hdr(value), "probe:s3cret")


def test_basic_auth_without_header_is_refused() -> None:
    assert not basic_auth_ok([("Host", "x")], "probe:s3cret")


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:6400",
        "http://127.0.0.1:6400/api",
        "https://LOCALHOST",
        "http://[::1]:8080",
    ],
)
def test_loopback_urls(url: str) -> None:
    assert is_loopback_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost.example.com",
        "https://example.com/?next=localhost",
        "https://127.0.0.1.nip.io",
        "https://retunnel.net",
        "not a url",
    ],
)
def test_substring_lookalikes_are_not_loopback(url: str) -> None:
    assert not is_loopback_url(url)


@pytest.mark.parametrize("status", [429, 503])
def test_temporary_registration_refusal_is_terminal(status: int) -> None:
    refusal = registration_refusal(APIError(status, "slow down", 120))
    assert refusal is not None
    assert refusal.exit_code == 75
    assert "retry in 120s" in str(refusal)


@pytest.mark.parametrize(
    "exc", [APIError(400, "bad"), APIError(500, "x"), ValueError()]
)
def test_other_failures_are_not_a_registration_refusal(exc: Exception) -> None:
    assert registration_refusal(exc) is None
