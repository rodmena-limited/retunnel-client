"""ReTunnel command-line interface.

Enterprise-grade CLI with proper stdout/stderr separation,
exit codes, and Unix compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

import click
import yaml

from .. import __version__
from ..core.config import AuthConfig, ClientConfig
from .client import TunnelConfig
from .hostname import InvalidHostname, normalize_hostname
from .hostname_cli import hostname as hostname_group
from .runner import (
    EXIT_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE,
    echo_stderr,
    echo_stdout,
    run_tunnels,
)

if TYPE_CHECKING:
    # logging.StreamHandler is generic to type checkers but is NOT subscriptable
    # at runtime on Python 3.9, which this package still supports. Aliasing it
    # under TYPE_CHECKING keeps the annotation precise without a suppression.
    _StreamHandlerBase = logging.StreamHandler[TextIO]
else:
    _StreamHandlerBase = logging.StreamHandler


class FlushingStreamHandler(_StreamHandlerBase):
    """StreamHandler that flushes after every emit for real-time output."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    quiet: bool = False,
) -> logging.Logger:
    """Set up logging with proper flushing and stderr output."""
    logger = logging.getLogger("retunnel")
    logger.setLevel(level.upper())

    # Clear existing handlers
    logger.handlers.clear()

    # --quiet/--json suppress chatter, never errors: a scripted user must
    # still see a reconnect failure or a refused subdomain on stderr.
    console = FlushingStreamHandler(sys.stderr)
    console.setLevel(logging.WARNING if quiet else level.upper())
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)

    return logger


class Context:
    """CLI context for sharing state."""

    def __init__(self) -> None:
        self.quiet: bool = False
        self.json_output: bool = False
        self.log_level: str = "INFO"
        self.log_file: str | None = None
        self.insecure: bool = False


pass_context = click.make_pass_decorator(Context, ensure=True)


@click.group(invoke_without_command=True)
@click.option("--version", "-V", is_flag=True, help="Show version and exit")
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    envvar="RETUNNEL_QUIET",
    help="Suppress all output except errors and the tunnel URL",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Output tunnel information as JSON (implies --quiet)",
)
@click.option(
    "--log-level",
    "-l",
    type=click.Choice(
        ["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False
    ),
    default="INFO",
    envvar="RETUNNEL_LOG_LEVEL",
    help="Set logging verbosity [default: INFO]",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, writable=True),
    envvar="RETUNNEL_LOG_FILE",
    help="Write logs to file in addition to stderr",
)
@click.pass_context
def cli(
    ctx: click.Context,
    version: bool,
    quiet: bool,
    json_output: bool,
    log_level: str,
    log_file: str | None,
) -> None:
    """ReTunnel - Securely expose local servers to the internet."""
    ctx.ensure_object(Context)
    ctx.obj.quiet = quiet or json_output
    ctx.obj.json_output = json_output
    ctx.obj.log_level = log_level
    ctx.obj.log_file = log_file

    if version:
        if json_output:
            echo_stdout(json.dumps({"version": __version__}))
        else:
            echo_stdout(f"retunnel {__version__}")
        ctx.exit(EXIT_SUCCESS)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("port", type=click.IntRange(1, 65535))
@click.option(
    "--subdomain",
    metavar="NAME",
    help="Request specific subdomain",
)
@click.option(
    "-s",
    "--spa",
    is_flag=True,
    help="Single-page-app mode: serve at retunnel.net/<ulid> (no subdomain needed)",
)
@click.option(
    "-H",
    "--hostname",
    metavar="HOST",
    help=(
        "Serve on a custom hostname you own, e.g. app.example.com "
        "(must be registered and verified first)"
    ),
)
@click.option(
    "-a",
    "--auth",
    metavar="USER:PASS",
    help="Require HTTP basic authentication",
)
@click.option(
    "--server",
    metavar="URL",
    envvar="RETUNNEL_SERVER",
    help="ReTunnel server address [default: wss://retunnel.net]",
)
@click.option(
    "--token",
    metavar="TOKEN",
    envvar="RETUNNEL_AUTH_TOKEN",
    help="Authentication token (or set RETUNNEL_AUTH_TOKEN)",
)
@click.option(
    "--insecure",
    "-k",
    is_flag=True,
    envvar="RETUNNEL_INSECURE",
    help="Disable SSL certificate verification (NOT recommended)",
)
@pass_context
def http(
    ctx: Context,
    port: int,
    subdomain: str | None,
    spa: bool,
    hostname: str | None,
    auth: str | None,
    server: str | None,
    token: str | None,
    insecure: bool,
) -> None:
    """Create an HTTP tunnel to expose a local port."""
    logger = setup_logging(ctx.log_level, ctx.log_file, ctx.quiet)

    if hostname:
        if subdomain:
            echo_stderr(
                "Error: --hostname and --subdomain are mutually exclusive"
            )
            sys.exit(EXIT_USAGE)
        if spa:
            echo_stderr("Error: --hostname and --spa are mutually exclusive")
            sys.exit(EXIT_USAGE)
        try:
            # Checked locally so an obvious typo costs no round trip, and so
            # the value sent on the wire is already canonical.
            hostname = normalize_hostname(hostname)
        except InvalidHostname as exc:
            echo_stderr(f"Error: --hostname {hostname!r}: {exc}")
            sys.exit(EXIT_USAGE)
    if auth and ":" not in auth:
        echo_stderr("Error: --auth must be USER:PASS")
        sys.exit(EXIT_USAGE)

    config = TunnelConfig(
        protocol="http",
        local_port=port,
        subdomain=subdomain,
        spa=spa,
        hostname=hostname,
        auth=auth,
        inspect=True,
    )

    exit_code = asyncio.run(
        run_tunnels(
            [config],
            server,
            token,
            ssl_verify=not insecure,
            quiet=ctx.quiet,
            json_output=ctx.json_output,
            logger=logger,
        )
    )
    sys.exit(exit_code)


@cli.command()
@click.argument("port", type=click.IntRange(1, 65535))
@click.option(
    "-r",
    "--remote-port",
    type=click.IntRange(1, 65535),
    metavar="PORT",
    help="Request specific remote port",
)
@click.option(
    "--server",
    metavar="URL",
    envvar="RETUNNEL_SERVER",
    help="ReTunnel server address [default: wss://retunnel.net]",
)
@click.option(
    "--token",
    metavar="TOKEN",
    envvar="RETUNNEL_AUTH_TOKEN",
    help="Authentication token (or set RETUNNEL_AUTH_TOKEN)",
)
@click.option(
    "--insecure",
    "-k",
    is_flag=True,
    envvar="RETUNNEL_INSECURE",
    help="Disable SSL certificate verification (NOT recommended)",
)
@pass_context
def tcp(
    ctx: Context,
    port: int,
    remote_port: int | None,
    server: str | None,
    token: str | None,
    insecure: bool,
) -> None:
    """Create a TCP tunnel to expose a local port."""
    logger = setup_logging(ctx.log_level, ctx.log_file, ctx.quiet)

    config = TunnelConfig(
        protocol="tcp",
        local_port=port,
        remote_port=remote_port,
    )

    exit_code = asyncio.run(
        run_tunnels(
            [config],
            server,
            token,
            ssl_verify=not insecure,
            quiet=ctx.quiet,
            json_output=ctx.json_output,
            logger=logger,
        )
    )
    sys.exit(exit_code)


@cli.command()
@click.argument(
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default="retunnel.yml",
    required=False,
)
@pass_context
def start(ctx: Context, config_path: Path) -> None:
    """Start tunnels from a YAML configuration file."""
    logger = setup_logging(ctx.log_level, ctx.log_file, ctx.quiet)

    try:
        config = ClientConfig.from_yaml(config_path)
        for t in config.tunnels:
            if not t.hostname:
                continue
            if t.subdomain:
                echo_stderr(
                    f"Error: tunnel {t.name or t.local_port}: 'hostname' and "
                    "'subdomain' are mutually exclusive"
                )
                sys.exit(EXIT_USAGE)
            try:
                t.hostname = normalize_hostname(t.hostname)
            except InvalidHostname as exc:
                echo_stderr(
                    f"Error: tunnel {t.name or t.local_port}: "
                    f"hostname {t.hostname!r}: {exc}"
                )
                sys.exit(EXIT_USAGE)
        configs = [
            TunnelConfig(
                protocol=t.protocol,
                local_port=t.local_port,
                name=t.name,
                subdomain=t.subdomain,
                hostname=t.hostname,
                auth=t.auth,
                inspect=t.inspect,
            )
            for t in config.tunnels
        ]
        if not configs:
            echo_stderr(f"Error: no tunnels defined in {config_path}")
            sys.exit(EXIT_USAGE)
        # All tunnels ride ONE control connection and are re-created together
        # on reconnect (audit #47 G3).
        exit_code = asyncio.run(
            run_tunnels(
                configs,
                server=config.server_addr,
                token=config.auth_token,
                quiet=ctx.quiet,
                json_output=ctx.json_output,
                logger=logger,
            )
        )
        sys.exit(exit_code)
    except FileNotFoundError:
        echo_stderr(f"Error: Config file not found: {config_path}")
        sys.exit(EXIT_USAGE)
    except yaml.YAMLError as e:
        echo_stderr(f"Error: Invalid YAML in {config_path}: {e}")
        sys.exit(EXIT_USAGE)
    except Exception as e:
        echo_stderr(f"Error: {e}")
        sys.exit(EXIT_ERROR)


@cli.command()
@click.argument("token", required=False)
@click.option(
    "--stdin", is_flag=True, help="Read token from stdin (for piping)"
)
def authtoken(token: str | None, stdin: bool) -> None:
    """Save authentication token for future use."""
    if stdin:
        token = sys.stdin.read().strip()
    elif not token:
        token = click.prompt("Enter authentication token", hide_input=True)

    if not token:
        echo_stderr("Error: Token cannot be empty")
        sys.exit(EXIT_USAGE)

    try:
        auth_config = AuthConfig()
        auth_config.auth_token = token
        echo_stderr(f"Auth token saved to {auth_config.CONFIG_PATH}")
        sys.exit(EXIT_SUCCESS)
    except Exception as e:
        echo_stderr(f"Error saving token: {e}")
        sys.exit(EXIT_ERROR)


@cli.command()
@click.option("--show", is_flag=True, help="Show current configuration")
@click.option(
    "--example", is_flag=True, help="Print example YAML configuration"
)
@click.option("--path", is_flag=True, help="Print config file path")
def config(show: bool, example: bool, path: bool) -> None:
    """View or manage ReTunnel configuration."""
    auth_config = AuthConfig()

    if path:
        echo_stdout(str(auth_config.CONFIG_PATH))
        return

    if show:
        echo_stderr("ReTunnel Configuration")
        echo_stderr("=" * 40)
        if auth_config.auth_token:
            echo_stderr(
                f"  Token: {auth_config.auth_token[:8]}...{auth_config.auth_token[-4:]}"
            )
        else:
            echo_stderr("  Token: (not configured)")
        echo_stderr(f"  Config: {auth_config.CONFIG_PATH}")
        echo_stderr("")
        echo_stderr("Environment:")
        echo_stderr(
            f"  RETUNNEL_SERVER: {os.environ.get('RETUNNEL_SERVER', '(not set)')}"
        )
        echo_stderr(
            f"  RETUNNEL_AUTH_TOKEN: {'(set)' if os.environ.get('RETUNNEL_AUTH_TOKEN') else '(not set)'}"
        )

    elif example:
        example_config = {
            "server_addr": "wss://retunnel.net",
            "auth_token": "${RETUNNEL_AUTH_TOKEN}",
            "tunnels": [
                {
                    "name": "web",
                    "protocol": "http",
                    "local_port": 8080,
                    "subdomain": "myapp",
                },
                {
                    "name": "ssh",
                    "protocol": "tcp",
                    "local_port": 22,
                },
            ],
        }
        echo_stdout("# ReTunnel configuration file")
        echo_stdout("# Save as retunnel.yml and run: retunnel start")
        echo_stdout(
            yaml.dump(
                example_config, default_flow_style=False, sort_keys=False
            )
        )

    else:
        echo_stderr("Usage: retunnel config [--show|--example|--path]")


@cli.command()
def version() -> None:
    """Show version and build information."""
    echo_stdout(f"retunnel {__version__}")
    echo_stderr(f"Python {sys.version.split()[0]}")
    echo_stderr(f"Platform: {sys.platform}")


@cli.command()
def credits() -> None:
    """Show open source library credits."""
    echo_stderr("ReTunnel Open Source Credits")
    echo_stderr("=" * 40)
    credits_data = [
        ("aiohttp", "Apache-2.0", "Async HTTP client/server"),
        ("websockets", "BSD", "WebSocket client/server"),
        ("msgpack", "Apache-2.0", "Binary serialization"),
        ("click", "BSD-3-Clause", "CLI framework"),
        ("pydantic", "MIT", "Data validation"),
        ("pyyaml", "MIT", "YAML parser"),
    ]
    for package, license_name, desc in credits_data:
        echo_stderr(f"  {package:<15} {license_name:<12} {desc}")
    echo_stderr("")
    echo_stderr("Source: https://github.com/anthropics/retunnel")


def main() -> None:
    """Entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        echo_stderr("\nInterrupted")
        sys.exit(130)


# Registered here, BEFORE the __main__ block: placing it after would mean
# main() had already run by the time the group was attached, so
# `retunnel hostname ...` would not exist when invoked as a module.
cli.add_command(hostname_group)


if __name__ == "__main__":
    main()
