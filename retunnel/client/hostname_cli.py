"""`retunnel hostname ...` -- self-service custom hostnames (issuedb #60).

Kept out of cli.py deliberately: that file is already at the project's 500-line
soft cap, and these commands are a self-contained group.

Every call authenticates with the auth token already in ~/.retunnel.conf. That
is the whole point of this group existing: registering a custom hostname must
never require sending your credential to an operator.
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
from .hostname import InvalidHostname, normalize_hostname

EXIT_USAGE = 2
EXIT_ERROR = 1
DEFAULT_API = "https://retunnel.net"
# Must match app/core/hostname_manager.CHALLENGE_LABEL on the server.
CHALLENGE_PREFIX = "_retunnel-challenge"
TIMEOUT_SECONDS = 30


def _api_base() -> str:
    cfg = AuthConfig()
    raw: Any = getattr(cfg, "_data", {})
    base = raw.get("api_url") or DEFAULT_API
    return str(base).rstrip("/") + "/"


def _token() -> str:
    token = AuthConfig().auth_token
    if not token:
        click.echo(
            "Error: no auth token. Run `retunnel authtoken <TOKEN>` first.",
            err=True,
        )
        sys.exit(EXIT_USAGE)
    return str(token)


async def _call(
    method: str, path: str, payload: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]]:
    import aiohttp

    url = urljoin(_api_base(), path.lstrip("/"))
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    headers = {"Authorization": f"Bearer {_token()}"}
    connector = aiohttp.TCPConnector(ssl=ssl.create_default_context())
    async with aiohttp.ClientSession(
        timeout=timeout, connector=connector
    ) as session:
        async with session.request(
            method, url, json=payload, headers=headers
        ) as resp:
            try:
                body = await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                # A non-JSON body (an nginx error page, a plain-text 502)
                # is surfaced verbatim rather than swallowed.
                body = {"detail": await resp.text()}
            return resp.status, body


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
        # Narrow on purpose: these are the reachable transport failures and
        # they are reported to the user. Anything else is a bug and must keep
        # its traceback rather than be reduced to one line.
        click.echo(f"Error: {type(exc).__name__}: {exc}", err=True)
        sys.exit(EXIT_ERROR)


def _print_dns(state: dict[str, Any]) -> None:
    dns = state.get("dns") or {}
    cname, txt = dns.get("cname") or {}, dns.get("txt") or {}
    click.echo("")
    click.echo(
        "Publish these two DNS records, then run `retunnel hostname verify`:"
    )
    click.echo("")
    click.echo(f"  CNAME  {cname.get('name')}")
    click.echo(f"         -> {cname.get('value')}")
    click.echo("         (an APEX domain cannot hold a CNAME; use an A record")
    click.echo(
        f"          pointing at the same address as {cname.get('value')})"
    )
    click.echo("")
    click.echo(f"  TXT    {txt.get('name')}")
    click.echo(f"         -> \"{txt.get('value')}\"")
    click.echo("")


_CERT_STATE_NOTE = {
    "not_requested": "certificate not requested yet",
    "in_progress": "certificate is being issued now",
    "issued": "certificate issued",
    "failed": "certificate issuance FAILED",
}


def _print_state(state: dict[str, Any]) -> None:
    flags = []
    flags.append("verified" if state.get("verified") else "UNVERIFIED")
    flags.append("cert" if state.get("certificate") else "NO CERT")
    mark = "ready" if state.get("routable") else "not ready"
    click.echo(f"{state.get('hostname')}  [{', '.join(flags)}]  {mark}")
    cert_state = state.get("certificate_state")
    if cert_state and not state.get("certificate"):
        # issuedb #66: absence used to be the only symptom, and it read the
        # same whether issuance had started, was running, or had given up.
        note = _CERT_STATE_NOTE.get(str(cert_state), str(cert_state))
        attempts = state.get("certificate_attempts")
        suffix = f" (attempt {attempts})" if attempts else ""
        click.echo(f"    {note}{suffix}")
    for key in ("verification_error", "certificate_error"):
        if state.get(key):
            click.echo(f"    {key}: {state[key]}")


def _validate(hostname: str) -> str:
    try:
        return normalize_hostname(hostname)
    except InvalidHostname as exc:
        click.echo(f"Error: {hostname!r}: {exc}", err=True)
        sys.exit(EXIT_USAGE)


@click.group()
def hostname() -> None:
    """Manage custom hostnames you own (e.g. app.example.com)."""


@hostname.command("add")
@click.argument("name")
@click.option(
    "--json", "as_json", is_flag=True, help="Machine-readable output"
)
def hostname_add(name: str, as_json: bool) -> None:
    """Register NAME for your account and print the DNS records to publish."""
    host = _validate(name)
    status, body = _run(_call("POST", "/api/v1/hostnames", {"hostname": host}))
    if as_json:
        click.echo(json.dumps(body, indent=2))
        sys.exit(0 if status < 400 else EXIT_ERROR)
    if status >= 400:
        click.echo(f"Error: {body.get('detail', body)}", err=True)
        sys.exit(EXIT_ERROR)
    if body.get("routable"):
        # issuedb #66 D4. Registration is idempotent server-side, but announcing
        # it as fresh and printing setup records told an operator to republish
        # the DNS of a hostname already carrying production traffic -- the same
        # churn that caused a resolver negative-cache incident on a name that
        # was merely idle.
        click.echo(f"{host} is already registered and live; nothing to do.")
        _print_state(body)
        return
    click.echo(f"Registered {host}")
    _print_dns(body)


@hostname.command("list")
@click.option(
    "--json", "as_json", is_flag=True, help="Machine-readable output"
)
def hostname_list(as_json: bool) -> None:
    """List the custom hostnames registered to your account."""
    status, body = _run(_call("GET", "/api/v1/hostnames"))
    if as_json:
        click.echo(json.dumps(body, indent=2))
        sys.exit(0 if status < 400 else EXIT_ERROR)
    if status >= 400:
        click.echo(f"Error: {body.get('detail', body)}", err=True)
        sys.exit(EXIT_ERROR)
    rows = body.get("hostnames") or []
    if not rows:
        click.echo("No custom hostnames registered.")
        return
    for row in rows:
        _print_state(row)


@hostname.command("verify")
@click.argument("name")
@click.option(
    "--json", "as_json", is_flag=True, help="Machine-readable output"
)
def hostname_verify(name: str, as_json: bool) -> None:
    """Check the DNS proof for NAME and mark it verified when it passes."""
    host = _validate(name)
    status, body = _run(_call("POST", f"/api/v1/hostnames/{host}/verify"))
    if as_json:
        click.echo(json.dumps(body, indent=2))
        sys.exit(0 if body.get("verified") else EXIT_ERROR)
    if status >= 400:
        click.echo(f"Error: {body.get('detail', body)}", err=True)
        sys.exit(EXIT_ERROR)
    if not body.get("verified"):
        click.echo(f"NOT VERIFIED: {body.get('detail')}", err=True)
        _print_dns(body)
        sys.exit(EXIT_ERROR)
    click.echo(f"Verified {host}")
    if body.get("dns_points_at_retunnel") is False:
        click.echo(f"WARNING: {body.get('dns_hint')}", err=True)
    if not body.get("certificate"):
        # The wording follows the SERVER's reported state rather than an
        # assumption about it. #62 removed a claim that issuance was under way
        # when nothing issued certificates at all; #66 made issuance automatic,
        # so the same sentence is now true -- but only when the server says so.
        # Reading it off certificate_state keeps the two in step, and a server
        # with automatic issuance disabled still tells the user to ask an
        # operator.
        state = str(body.get("certificate_state") or "")
        if state == "failed":
            click.echo(
                f"\nTLS certificate issuance FAILED for {host}."
                f"\n  {body.get('certificate_error') or 'no reason recorded'}"
                "\nIt will be retried automatically; `retunnel hostname list`"
                "\nshows the current state."
            )
        elif state in ("not_requested", ""):
            click.echo(
                "\nNo TLS certificate yet, and issuance has NOT started on"
                "\nthis server: it is an operator step here, not an automatic"
                f"\none. Ask the ReTunnel operator to provision {host}."
                "\nUntil then the hostname cannot be used with --hostname."
            )
        else:
            click.echo(
                f"\nA TLS certificate is being issued for {host} now."
                "\nRun `retunnel hostname list` until it shows 'ready';"
                "\nif issuance fails the reason will appear there."
            )


@hostname.command("remove")
@click.argument("name")
def hostname_remove(name: str) -> None:
    """Remove NAME from your account."""
    host = _validate(name)
    status, body = _run(_call("DELETE", f"/api/v1/hostnames/{host}"))
    if status >= 400:
        click.echo(f"Error: {body.get('detail', body)}", err=True)
        sys.exit(EXIT_ERROR)
    click.echo(f"Removed {host}")
    # The server forgets the challenge; DNS does not. A stale TXT left behind
    # here silently blocks the NEXT registration of this name, because
    # re-registering mints a fresh token while the old record keeps answering
    # -- and the resulting failure looks like a propagation delay unless you
    # read the message carefully (issuedb #60, hit in practice).
    click.echo(
        f"\nAlso delete the DNS record  TXT {CHALLENGE_PREFIX}.{host}\n"
        "Leaving it published will block a future re-registration of this "
        "name with a stale challenge."
    )


__all__ = ["hostname"]
