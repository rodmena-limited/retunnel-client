"""ReTunnel command-line interface.

Enterprise-grade CLI with proper stdout/stderr separation,
exit codes, and Unix compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import click
import yaml

from .. import __version__
from ..core.config import AuthConfig, ClientConfig
from .high_performance_model import HighPerformanceClient, TunnelConfig

# Exit codes following Unix conventions
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 69  # EX_UNAVAILABLE - service unavailable


class FlushingStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after every emit for real-time output."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    quiet: bool = False,
) -> logging.Logger:
    """Set up logging with proper flushing and stderr output.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for persistent logging
        quiet: If True, suppress all log output to stderr

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("retunnel")
    logger.setLevel(level.upper())

    # Clear existing handlers
    logger.handlers.clear()

    if not quiet:
        # Console handler - always stderr, with flushing
        console = FlushingStreamHandler(sys.stderr)
        console.setLevel(level.upper())
        console.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(console)

    if log_file:
        # File handler for persistent logging
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # Always capture everything to file
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(file_handler)

    return logger


def echo_stderr(message: str) -> None:
    """Echo to stderr (for status messages)."""
    click.echo(message, err=True)


def echo_stdout(message: str, flush: bool = True) -> None:
    """Echo to stdout (for primary output like URLs)."""
    click.echo(message, err=False)
    if flush:
        sys.stdout.flush()


class Context:
    """CLI context for sharing state."""

    def __init__(self) -> None:
        self.quiet: bool = False
        self.json_output: bool = False
        self.log_level: str = "INFO"
        self.log_file: Optional[str] = None
        self.insecure: bool = False


pass_context = click.make_pass_decorator(Context, ensure=True)


@click.group(invoke_without_command=True)
@click.option("--version", "-V", is_flag=True, help="Show version and exit")
@click.option(
    "--quiet", "-q", is_flag=True, envvar="RETUNNEL_QUIET",
    help="Suppress all output except errors and the tunnel URL"
)
@click.option(
    "--json", "json_output", is_flag=True,
    help="Output tunnel information as JSON (implies --quiet)"
)
@click.option(
    "--log-level", "-l",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO", envvar="RETUNNEL_LOG_LEVEL",
    help="Set logging verbosity [default: INFO]"
)
@click.option(
    "--log-file", type=click.Path(dir_okay=False, writable=True),
    envvar="RETUNNEL_LOG_FILE",
    help="Write logs to file in addition to stderr"
)
@click.pass_context
def cli(
    ctx: click.Context,
    version: bool,
    quiet: bool,
    json_output: bool,
    log_level: str,
    log_file: Optional[str],
) -> None:
    """ReTunnel - Securely expose local servers to the internet.

    \b
    Quick start:
      retunnel http 8080              # Expose local port 8080
      retunnel http 8080 -s myapp     # With custom subdomain
      retunnel tcp 22                 # Expose TCP service

    \b
    Environment variables:
      RETUNNEL_AUTH_TOKEN     Authentication token
      RETUNNEL_SERVER         Server address (wss://...)
      RETUNNEL_LOG_LEVEL      Logging level
      RETUNNEL_QUIET          Suppress output (set to 1)

    Run 'retunnel COMMAND --help' for command-specific help.
    """
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
    "-s", "--subdomain", metavar="NAME",
    help="Request specific subdomain (e.g., myapp -> myapp.retunnel.net)"
)
@click.option(
    "-H", "--hostname", metavar="HOST",
    help="Request specific hostname (requires DNS setup)"
)
@click.option(
    "-a", "--auth", metavar="USER:PASS",
    help="Require HTTP basic authentication"
)
@click.option(
    "--server", metavar="URL", envvar="RETUNNEL_SERVER",
    help="ReTunnel server address [default: wss://retunnel.net]"
)
@click.option(
    "--token", metavar="TOKEN", envvar="RETUNNEL_AUTH_TOKEN",
    help="Authentication token (or set RETUNNEL_AUTH_TOKEN)"
)
@click.option(
    "--insecure", "-k", is_flag=True, envvar="RETUNNEL_INSECURE",
    help="Disable SSL certificate verification (NOT recommended)"
)
@pass_context
def http(
    ctx: Context,
    port: int,
    subdomain: Optional[str],
    hostname: Optional[str],
    auth: Optional[str],
    server: Optional[str],
    token: Optional[str],
    insecure: bool,
) -> None:
    """Create an HTTP tunnel to expose a local port.

    \b
    Examples:
      retunnel http 8080                    # Basic usage
      retunnel http 8080 -s myapp           # Custom subdomain
      retunnel http 3000 -a user:secret     # With basic auth
      retunnel http 8080 --json             # JSON output for scripts

    \b
    The tunnel URL will be printed to stdout for easy scripting:
      URL=$(retunnel http 8080 -q)
    """
    logger = setup_logging(ctx.log_level, ctx.log_file, ctx.quiet)

    config = TunnelConfig(
        protocol="http",
        local_port=port,
        subdomain=subdomain,
        hostname=hostname,
        auth=auth,
        inspect=True,
    )

    exit_code = asyncio.run(_run_tunnel(
        config, server, token,
        ssl_verify=not insecure,
        quiet=ctx.quiet,
        json_output=ctx.json_output,
        logger=logger,
    ))
    sys.exit(exit_code)


@cli.command()
@click.argument("port", type=click.IntRange(1, 65535))
@click.option(
    "-r", "--remote-port", type=click.IntRange(1, 65535), metavar="PORT",
    help="Request specific remote port"
)
@click.option(
    "--server", metavar="URL", envvar="RETUNNEL_SERVER",
    help="ReTunnel server address [default: wss://retunnel.net]"
)
@click.option(
    "--token", metavar="TOKEN", envvar="RETUNNEL_AUTH_TOKEN",
    help="Authentication token (or set RETUNNEL_AUTH_TOKEN)"
)
@click.option(
    "--insecure", "-k", is_flag=True, envvar="RETUNNEL_INSECURE",
    help="Disable SSL certificate verification (NOT recommended)"
)
@pass_context
def tcp(
    ctx: Context,
    port: int,
    remote_port: Optional[int],
    server: Optional[str],
    token: Optional[str],
    insecure: bool,
) -> None:
    """Create a TCP tunnel to expose a local port.

    \b
    Examples:
      retunnel tcp 22                # Expose SSH
      retunnel tcp 5432 -r 15432     # PostgreSQL with specific remote port
    """
    logger = setup_logging(ctx.log_level, ctx.log_file, ctx.quiet)

    config = TunnelConfig(
        protocol="tcp",
        local_port=port,
        remote_port=remote_port,
    )

    exit_code = asyncio.run(_run_tunnel(
        config, server, token,
        ssl_verify=not insecure,
        quiet=ctx.quiet,
        json_output=ctx.json_output,
        logger=logger,
    ))
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
    """Start tunnels from a YAML configuration file.

    \b
    Default config file: retunnel.yml

    \b
    Example config:
      tunnels:
        - name: web
          protocol: http
          local_port: 8080
          subdomain: myapp
    """
    logger = setup_logging(ctx.log_level, ctx.log_file, ctx.quiet)

    try:
        config = ClientConfig.from_yaml(config_path)
        exit_code = asyncio.run(_run_from_config(
            config,
            quiet=ctx.quiet,
            json_output=ctx.json_output,
            logger=logger,
        ))
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
    "--stdin", is_flag=True,
    help="Read token from stdin (for piping)"
)
def authtoken(token: Optional[str], stdin: bool) -> None:
    """Save authentication token for future use.

    \b
    Examples:
      retunnel authtoken abc123              # Direct input
      retunnel authtoken                     # Interactive prompt
      echo "abc123" | retunnel authtoken --stdin  # From pipe
    """
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
@click.option("--example", is_flag=True, help="Print example YAML configuration")
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
            echo_stderr(f"  Token: {auth_config.auth_token[:8]}...{auth_config.auth_token[-4:]}")
        else:
            echo_stderr("  Token: (not configured)")
        echo_stderr(f"  Config: {auth_config.CONFIG_PATH}")
        echo_stderr("")
        echo_stderr("Environment:")
        echo_stderr(f"  RETUNNEL_SERVER: {os.environ.get('RETUNNEL_SERVER', '(not set)')}")
        echo_stderr(f"  RETUNNEL_AUTH_TOKEN: {'(set)' if os.environ.get('RETUNNEL_AUTH_TOKEN') else '(not set)'}")

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
                    "name": "api",
                    "protocol": "http",
                    "local_port": 3000,
                    "hostname": "api.example.com",
                    "auth": "user:pass",
                },
                {
                    "name": "ssh",
                    "protocol": "tcp",
                    "local_port": 22,
                },
            ],
        }
        # Output YAML to stdout for easy redirection
        echo_stdout("# ReTunnel configuration file")
        echo_stdout("# Save as retunnel.yml and run: retunnel start")
        echo_stdout(yaml.dump(example_config, default_flow_style=False, sort_keys=False))

    else:
        echo_stderr("Usage: retunnel config [--show|--example|--path]")
        echo_stderr("")
        echo_stderr("  --show     Display current configuration")
        echo_stderr("  --example  Print example YAML configuration")
        echo_stderr("  --path     Print config file path")


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
        ("msgpack", "Apache-2.0", "Binary serialization"),
        ("click", "BSD-3-Clause", "CLI framework"),
        ("pydantic", "MIT", "Data validation"),
        ("pyyaml", "MIT", "YAML parser"),
    ]
    for package, license_name, desc in credits_data:
        echo_stderr(f"  {package:<15} {license_name:<12} {desc}")
    echo_stderr("")
    echo_stderr("Source: https://github.com/anthropics/retunnel")


async def _run_tunnel(
    config: TunnelConfig,
    server: Optional[str] = None,
    token: Optional[str] = None,
    ssl_verify: bool = True,
    quiet: bool = False,
    json_output: bool = False,
    logger: Optional[logging.Logger] = None,
) -> int:
    """Run a single tunnel with infinite retry on connection failure.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    if logger is None:
        logger = logging.getLogger("retunnel")

    # Create client with SSL verification setting
    client = HighPerformanceClient(server, auth_token=token, ssl_verify=ssl_verify)

    # Handle shutdown gracefully
    shutdown_event = asyncio.Event()
    exit_code = EXIT_SUCCESS

    def signal_handler() -> None:
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # Exponential backoff settings
    retry_delay = 1.0
    max_retry_delay = 60.0

    try:
        # Infinite retry loop for connection
        while not shutdown_event.is_set():
            try:
                # Connect
                if not quiet:
                    echo_stderr("Connecting to ReTunnel server...")
                await client.connect()

                # Request tunnel
                if not quiet:
                    echo_stderr(f"Creating {config.protocol.upper()} tunnel...")
                tunnel = await client.request_tunnel(config)

                # Output the URL - PRIMARY OUTPUT to stdout
                if json_output:
                    output = {
                        "url": tunnel.url,
                        "protocol": config.protocol,
                        "local_port": config.local_port,
                        "subdomain": getattr(tunnel, "subdomain", None),
                    }
                    echo_stdout(json.dumps(output))
                else:
                    # For scripting: just the URL to stdout
                    echo_stdout(tunnel.url)

                    # Status info to stderr
                    if not quiet:
                        echo_stderr("")
                        echo_stderr(f"Forwarding {tunnel.url} -> localhost:{config.local_port}")
                        echo_stderr("")
                        echo_stderr("Press Ctrl+C to stop")
                        echo_stderr("-" * 40)

                # Reset retry delay on successful connection
                retry_delay = 1.0

                # Wait for requests and log them
                while not shutdown_event.is_set():
                    try:
                        # Check for incoming requests
                        requests = client.get_requests()
                        for req in requests:
                            logger.info(f"{req.method} {req.path} -> {req.status}")

                        # Check connection status using public property
                        if not client.is_connected:
                            # Check if client is attempting reconnection
                            if hasattr(client, 'is_reconnecting') and client.is_reconnecting:
                                pass  # Let internal reconnection handle it
                            else:
                                logger.warning("Connection lost, will retry...")
                                break

                        await asyncio.sleep(0.5)
                    except asyncio.CancelledError:
                        shutdown_event.set()
                        break

            except ConnectionRefusedError:
                if shutdown_event.is_set():
                    break
                echo_stderr(f"Connection refused. Retrying in {retry_delay:.0f}s...")
                exit_code = EXIT_UNAVAILABLE

            except ConnectionResetError:
                if shutdown_event.is_set():
                    break
                echo_stderr(f"Connection reset. Retrying in {retry_delay:.0f}s...")
                exit_code = EXIT_UNAVAILABLE

            except TimeoutError:
                if shutdown_event.is_set():
                    break
                echo_stderr(f"Connection timed out. Retrying in {retry_delay:.0f}s...")
                exit_code = EXIT_UNAVAILABLE

            except OSError as e:
                if shutdown_event.is_set():
                    break
                echo_stderr(f"Network error: {e}. Retrying in {retry_delay:.0f}s...")
                logger.debug(f"OSError details: {e}", exc_info=True)
                exit_code = EXIT_UNAVAILABLE

            except Exception as e:
                if shutdown_event.is_set():
                    break
                echo_stderr(f"Error: {e}. Retrying in {retry_delay:.0f}s...")
                logger.debug(f"Exception details: {e}", exc_info=True)
                exit_code = EXIT_ERROR

            # Close client before retry (if we got here due to error)
            if not shutdown_event.is_set():
                try:
                    await client.close()
                except Exception:
                    pass

                # Wait with exponential backoff
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(), timeout=retry_delay
                    )
                    break  # Shutdown requested
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue retry

                # Increase delay with exponential backoff
                retry_delay = min(retry_delay * 2, max_retry_delay)

                # Create new client for retry
                client = HighPerformanceClient(
                    server, auth_token=token, ssl_verify=ssl_verify
                )

    except KeyboardInterrupt:
        pass
    finally:
        if not quiet:
            echo_stderr("\nShutting down...")
        await client.close()
        if not quiet:
            echo_stderr("Tunnel closed.")

    return EXIT_SUCCESS if exit_code == EXIT_SUCCESS else exit_code


async def _run_from_config(
    config: ClientConfig,
    quiet: bool = False,
    json_output: bool = False,
    logger: Optional[logging.Logger] = None,
) -> int:
    """Run tunnels from configuration file.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    if logger is None:
        logger = logging.getLogger("retunnel")

    # Create client
    client = HighPerformanceClient(
        config.server_addr,
        auth_token=config.auth_token,
    )

    # Handle shutdown gracefully
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass

    try:
        # Connect
        if not quiet:
            echo_stderr(f"Connecting to {config.server_addr}...")
        await client.connect()

        # Start all tunnels
        tunnels = []
        for tunnel_def in config.tunnels:
            if not quiet:
                echo_stderr(f"Starting tunnel '{tunnel_def.name}'...")

            tunnel_config = TunnelConfig(
                protocol=tunnel_def.protocol,
                local_port=tunnel_def.local_port,
                subdomain=tunnel_def.subdomain,
                hostname=tunnel_def.hostname,
                auth=tunnel_def.auth,
                inspect=tunnel_def.inspect,
            )

            tunnel = await client.request_tunnel(tunnel_config)
            tunnels.append((tunnel_def.name, tunnel, tunnel_config))

        # Output
        if json_output:
            output = {
                "tunnels": [
                    {
                        "name": name,
                        "url": t.url,
                        "local_port": tc.local_port,
                        "protocol": tc.protocol,
                    }
                    for name, t, tc in tunnels
                ]
            }
            echo_stdout(json.dumps(output))
        else:
            # URLs to stdout (one per line for scripting)
            for name, tunnel, _ in tunnels:
                echo_stdout(f"{name}={tunnel.url}")

            if not quiet:
                echo_stderr("")
                echo_stderr(f"Active Tunnels ({len(tunnels)}):")
                echo_stderr("-" * 40)
                for name, tunnel, tc in tunnels:
                    echo_stderr(f"  {name}: {tunnel.url} -> localhost:{tc.local_port}")
                echo_stderr("")
                echo_stderr("Press Ctrl+C to stop all tunnels")

        # Wait for shutdown
        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

        return EXIT_SUCCESS

    except KeyboardInterrupt:
        return EXIT_SUCCESS
    except ConnectionRefusedError:
        echo_stderr("Error: Could not connect to server")
        return EXIT_UNAVAILABLE
    except Exception as e:
        echo_stderr(f"Error: {e}")
        logger.debug(f"Exception details: {e}", exc_info=True)
        return EXIT_ERROR
    finally:
        if not quiet:
            echo_stderr("\nShutting down all tunnels...")
        await client.close()
        if not quiet:
            echo_stderr("All tunnels closed.")


def main() -> None:
    """Entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        echo_stderr("\nInterrupted")
        sys.exit(130)  # 128 + SIGINT(2)


if __name__ == "__main__":
    main()
