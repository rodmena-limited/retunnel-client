"""Run one or more tunnels to completion (Ctrl+C or a permanent refusal)."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from typing import Any

import click

from ..core.exceptions import TerminalError
from .client import ReTunnelClient, TunnelConfig
from .config_manager import config_manager

# Exit codes following Unix conventions
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 69  # EX_UNAVAILABLE - service unavailable / refused


def echo_stderr(message: str) -> None:
    """Echo to stderr (for status messages)."""
    click.echo(message, err=True)


def echo_stdout(message: str, flush: bool = True) -> None:
    """Echo to stdout (for primary output like URLs)."""
    click.echo(message, err=False)
    if flush:
        sys.stdout.flush()


def _print_tunnels(
    client: ReTunnelClient, json_output: bool, quiet: bool
) -> None:
    tunnels = client.tunnels
    if json_output:
        if len(tunnels) == 1:
            t = tunnels[0]
            echo_stdout(
                json.dumps(
                    {
                        "url": t.url,
                        "protocol": t.config.protocol,
                        "local_port": t.config.local_port,
                        "subdomain": t.subdomain,
                        "path": t.path,
                        "protocol_version": client.protocol_version,
                    }
                )
            )
        else:
            echo_stdout(
                json.dumps(
                    {
                        "tunnels": [
                            {
                                "name": t.config.name,
                                "url": t.url,
                                "local_port": t.config.local_port,
                                "protocol": t.config.protocol,
                            }
                            for t in tunnels
                        ]
                    }
                )
            )
        return
    for t in tunnels:
        echo_stdout(f"{t.config.name}={t.url}" if t.config.name else t.url)
    if not quiet:
        echo_stderr("")
        for t in tunnels:
            echo_stderr(
                f"Forwarding {t.url} -> localhost:{t.config.local_port}"
            )
        echo_stderr("")
        echo_stderr("Press Ctrl+C to stop")
        echo_stderr("-" * 40)


async def run_tunnels(
    configs: list[TunnelConfig],
    server: str | None = None,
    token: str | None = None,
    ssl_verify: bool = True,
    quiet: bool = False,
    json_output: bool = False,
    logger: logging.Logger | None = None,
) -> int:
    """Create every tunnel on one control connection and serve until
    interrupted. Returns the process exit code."""
    if logger is None:
        logger = logging.getLogger("retunnel")

    if not token:
        token = await config_manager.get_auth_token()

    client = ReTunnelClient(
        server_addr=server or "wss://retunnel.net",
        auth_token=token or "",
        ssl_verify=ssl_verify,
    )

    shutdown_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            logger.debug("signal handlers unavailable on this platform")

    waiters: list[asyncio.Future[Any]] = []
    try:
        if not quiet:
            echo_stderr("Connecting to ReTunnel server...")

        await client.connect()
        for cfg in configs:
            client.add_tunnel(cfg)

        # Race the first connection against Ctrl-C. The signal handler only
        # sets an event and start() waits on its own, so while the server was
        # unreachable the client ignored SIGINT/SIGTERM entirely and had to be
        # SIGKILLed -- exactly when a user is most likely to interrupt it
        # (issuedb #58).
        stop = asyncio.ensure_future(shutdown_event.wait())
        started = asyncio.ensure_future(client.start())
        waiters = [stop, started]
        done, _ = await asyncio.wait(
            waiters, return_when=asyncio.FIRST_COMPLETED
        )
        if started not in done:
            return EXIT_SUCCESS  # interrupted before any tunnel came up
        started.result()  # re-raise a terminal refusal
        _print_tunnels(client, json_output, quiet)

        ended = asyncio.ensure_future(client.wait_closed())
        waiters = [stop, ended]
        done, _ = await asyncio.wait(
            waiters, return_when=asyncio.FIRST_COMPLETED
        )
        if ended in done:
            code = ended.result()
            echo_stderr(
                "Error: the tunnel could not be kept up; see the log above"
            )
            return int(code) if code else EXIT_ERROR
        return EXIT_SUCCESS
    except TerminalError as e:
        echo_stderr(f"Error: {e}")
        return e.exit_code
    except Exception as e:
        echo_stderr(f"Error: {e}")
        return EXIT_ERROR
    finally:
        for w in waiters:
            if not w.done():
                w.cancel()
        if not quiet:
            echo_stderr("\nShutting down...")
        await client.close()
        if not quiet:
            echo_stderr("Tunnel closed.")
