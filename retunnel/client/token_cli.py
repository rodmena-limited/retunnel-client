"""`retunnel token ...` -- see and rotate this machine's auth token (issuedb #74).

The token IS the account: custom hostnames and reserved names belong to it.
`show` identifies the account without printing the secret; `rotate` replaces
the token with a new one for the SAME account (the server's authenticated
rotation), so nothing it owns is lost.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
from typing import Any
from urllib.parse import urljoin

import click

from ..core.config import AuthConfig
from .runner import config_unreadable_message

EXIT_ERROR = 1
DEFAULT_API = "https://retunnel.net"


def _load() -> tuple[AuthConfig, str]:
    cfg = AuthConfig()
    if cfg.unreadable is not None:
        click.echo(config_unreadable_message(cfg.unreadable), err=True)
        sys.exit(EXIT_ERROR)
    token = cfg.auth_token
    if not token:
        click.echo(
            "No auth token saved. Run `retunnel http <port>` once, or "
            "`retunnel authtoken <TOKEN>`.",
            err=True,
        )
        sys.exit(EXIT_ERROR)
    return cfg, str(token)


def _api_base(cfg: AuthConfig) -> str:
    raw: Any = getattr(cfg, "_data", {})
    return str(raw.get("api_url") or DEFAULT_API).rstrip("/") + "/"


async def _post(
    base: str, path: str, *, body: Any = None, bearer: str | None = None
) -> tuple[int, dict[str, Any]]:
    import aiohttp

    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    connector = aiohttp.TCPConnector(ssl=ssl.create_default_context())
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), connector=connector
    ) as session:
        async with session.post(
            urljoin(base, path.lstrip("/")), json=body, headers=headers
        ) as resp:
            try:
                data = await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                data = {"detail": await resp.text()}
            return resp.status, data


def _run(coro: Any) -> tuple[int, dict[str, Any]]:
    import aiohttp

    try:
        result: tuple[int, dict[str, Any]] = asyncio.run(coro)
        return result
    except (
        aiohttp.ClientError,
        ssl.SSLError,
        OSError,
        asyncio.TimeoutError,
    ) as exc:
        click.echo(f"Error: {type(exc).__name__}: {exc}", err=True)
        sys.exit(EXIT_ERROR)


@click.group()
def token() -> None:
    """See or rotate the auth token this machine uses."""


@token.command("show")
@click.option(
    "--json", "as_json", is_flag=True, help="Machine-readable output"
)
def token_show(as_json: bool) -> None:
    """Identify the account behind the saved token (the secret is masked)."""
    cfg, tok = _load()
    status, body = _run(
        _post(
            _api_base(cfg),
            "/api/v1/auth/verify-token",
            body={"old_token": tok},
        )
    )
    info = {
        "config": str(cfg.CONFIG_PATH),
        "token": f"{tok[:4]}…{tok[-4:]}",
        "valid": status == 200,
        "account_id": body.get("user_id") if status == 200 else None,
        "email": body.get("email") if status == 200 else None,
    }
    if as_json:
        click.echo(json.dumps(info, indent=2))
    else:
        for key, value in info.items():
            click.echo(f"{key:10} {value}")
    sys.exit(0 if status == 200 else EXIT_ERROR)


@token.command("rotate")
@click.confirmation_option(
    prompt="Replace this machine's token? Other machines using it will stop working."
)
def token_rotate() -> None:
    """Replace the token with a new one for the SAME account."""
    cfg, tok = _load()
    status, body = _run(
        _post(_api_base(cfg), "/api/v1/auth/login", bearer=tok)
    )
    new = body.get("auth_token") if status == 200 else None
    if not new:
        click.echo(
            f"Error: rotation refused ({status}): {body.get('detail', body)}",
            err=True,
        )
        sys.exit(EXIT_ERROR)
    try:
        cfg.auth_token = str(new)
    except OSError as exc:
        click.echo(
            f"Error: the server rotated the token but saving it failed ({exc}).\n"
            f"Your NEW token is:\n    {new}\n"
            "Save it now with `retunnel authtoken <TOKEN>` once the disk is "
            "writable; the old token no longer works.",
            err=True,
        )
        sys.exit(EXIT_ERROR)
    click.echo(
        f"Token rotated and saved to {cfg.CONFIG_PATH}. The old token no longer "
        "works; restart any tunnel that was using it."
    )
