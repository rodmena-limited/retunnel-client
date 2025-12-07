"""ReTunnel command-line interface."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

import click
import yaml

from .. import __version__
from ..core.config import AuthConfig, ClientConfig
from .high_performance_model import HighPerformanceClient, TunnelConfig


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Set up logging with simple format."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


@click.group()
@click.version_option(version=__version__, prog_name="retunnel")
def cli() -> None:
    """ReTunnel - Securely expose local servers to the internet."""
    pass


@cli.command()
@click.argument("port", type=int)
@click.option(
    "-s", "--subdomain", default=None, help="Request specific subdomain"
)
@click.option("-h", "--hostname", default=None, help="Request specific hostname")
@click.option("-a", "--auth", default=None, help="HTTP basic auth (user:pass)")
@click.option("--server", default=None, help="ReTunnel server address")
@click.option("--token", default=None, help="Authentication token")
@click.option(
    "--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)"
)
def http(
    port: int,
    subdomain: Optional[str],
    hostname: Optional[str],
    auth: Optional[str],
    server: Optional[str],
    token: Optional[str],
    log_level: str,
) -> None:
    """Create an HTTP tunnel to expose a local port."""
    setup_logging(log_level)

    config = TunnelConfig(
        protocol="http",
        local_port=port,
        subdomain=subdomain,
        hostname=hostname,
        auth=auth,
        inspect=True,
    )

    asyncio.run(_run_tunnel(config, server, token))


@cli.command()
@click.argument("port", type=int)
@click.option(
    "-r", "--remote-port", default=None, type=int,
    help="Request specific remote port"
)
@click.option("--server", default=None, help="ReTunnel server address")
@click.option("--token", default=None, help="Authentication token")
@click.option(
    "--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)"
)
def tcp(
    port: int,
    remote_port: Optional[int],
    server: Optional[str],
    token: Optional[str],
    log_level: str,
) -> None:
    """Create a TCP tunnel to expose a local port."""
    setup_logging(log_level)

    config = TunnelConfig(
        protocol="tcp",
        local_port=port,
    )

    asyncio.run(_run_tunnel(config, server, token))


@cli.command()
@click.argument(
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default="retunnel.yml",
)
@click.option(
    "--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)"
)
def start(config_path: Path, log_level: str) -> None:
    """Start tunnels from configuration file."""
    setup_logging(log_level)

    try:
        config = ClientConfig.from_yaml(config_path)
        asyncio.run(_run_from_config(config))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("token", required=False)
def authtoken(token: Optional[str]) -> None:
    """Save authentication token for future use."""
    if not token:
        token = click.prompt("Enter authentication token", hide_input=True)

    if not token:
        click.echo("Error: Token cannot be empty", err=True)
        sys.exit(1)

    auth_config = AuthConfig()
    auth_config.auth_token = token

    click.echo(f"Auth token saved to {auth_config.CONFIG_PATH}")


@cli.command()
@click.option("--show", is_flag=True, help="Show current configuration")
@click.option("--example", is_flag=True, help="Show example configuration")
def config(show: bool, example: bool) -> None:
    """Manage ReTunnel configuration."""
    if show:
        auth_config = AuthConfig()
        click.echo("ReTunnel Configuration:")
        click.echo("-" * 40)
        if auth_config.auth_token:
            click.echo(f"  Token: {auth_config.auth_token[:8]}...")
        else:
            click.echo("  Token: Not configured")
        click.echo("  Server: retunnel.net (default)")

    elif example:
        example_config = {
            "server_addr": "${RETUNNEL_SERVER_ENDPOINT:localhost:6400}",
            "auth_token": "${RETUNNEL_AUTH_TOKEN}",
            "region": "us",
            "log_level": "INFO",
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

        click.echo("# Example retunnel.yml")
        click.echo(yaml.dump(example_config, default_flow_style=False))

    else:
        click.echo("Use --show to display config or --example for sample")


@cli.command(name="help")
def help_cmd() -> None:
    """Show detailed help information."""
    help_text = """
ReTunnel CLI Help
=================

ReTunnel is a secure tunnel service for exposing local servers to the internet.

Quick Start
-----------
  # Expose HTTP server on port 8080
  retunnel http 8080

  # Expose with custom subdomain
  retunnel http 8080 --subdomain myapp

  # Expose TCP service
  retunnel tcp 22

Commands
--------
  retunnel http <port>       Create an HTTP tunnel
    --subdomain, -s          Request specific subdomain
    --hostname, -h           Request specific hostname
    --auth, -a               HTTP basic auth (user:pass)
    --server                 Custom server address
    --token                  Authentication token

  retunnel tcp <port>        Create a TCP tunnel
    --remote-port, -r        Request specific remote port
    --server                 Custom server address
    --token                  Authentication token

  retunnel start [config]    Start tunnels from config file
  retunnel authtoken [token] Save authentication token
  retunnel config            Manage configuration
    --show                   Display current configuration
    --example                Show example config file

  retunnel version           Display version information

Environment Variables
---------------------
  RETUNNEL_SERVER_ENDPOINT   Override default server
  RETUNNEL_AUTH_TOKEN        Set authentication token

Support
-------
  GitHub: https://github.com/retunnel/retunnel
  Documentation: https://docs.retunnel.com
"""
    click.echo(help_text)


@cli.command()
def version() -> None:
    """Show ReTunnel version."""
    click.echo(f"ReTunnel v{__version__}")


@cli.command()
def credits() -> None:
    """Show open source credits."""
    click.echo("Open Source Credits")
    click.echo("=" * 40)
    credits_data = [
        ("aiohttp", "Apache-2.0", "Async HTTP client/server"),
        ("msgpack", "Apache-2.0", "Binary serialization"),
        ("click", "BSD-3-Clause", "CLI framework"),
        ("pydantic", "MIT", "Data validation"),
        ("pyyaml", "MIT", "YAML parser"),
    ]
    for package, license_name, desc in credits_data:
        click.echo(f"  {package:<15} {license_name:<12} {desc}")
    click.echo()
    click.echo("Thank you to all contributors!")


async def _run_tunnel(
    config: TunnelConfig,
    server: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """Run a single tunnel."""
    logger = logging.getLogger("retunnel")

    # Create client
    client = HighPerformanceClient(server, auth_token=token)

    # Handle shutdown gracefully
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        # Connect
        click.echo("Connecting to ReTunnel server...")
        await client.connect()

        # Request tunnel
        click.echo(f"Creating {config.protocol.upper()} tunnel...")
        tunnel = await client.request_tunnel(config)

        # Output the URL - this is the main output
        click.echo("")
        click.echo(f"Tunnel URL: {tunnel.url}")
        click.echo(f"Forwarding to localhost:{config.local_port}")
        click.echo("")
        click.echo("Press Ctrl+C to stop")
        click.echo("-" * 40)

        # Wait for requests and log them
        while not shutdown_event.is_set():
            try:
                # Check for incoming requests
                requests = client.get_requests()
                for req in requests:
                    logger.info(f"{req.method} {req.path} -> {req.status}")

                # Check connection status
                if not client.is_connected and not client._reconnecting:
                    logger.warning("Connection lost")

                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break

    except KeyboardInterrupt:
        pass
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        click.echo("\nShutting down...")
        await client.close()
        click.echo("Tunnel closed.")


async def _run_from_config(config: ClientConfig) -> None:
    """Run tunnels from configuration."""
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
        click.echo(f"Connecting to {config.server_addr}...")
        await client.connect()

        # Start all tunnels
        tunnels = []
        for tunnel_def in config.tunnels:
            click.echo(f"Starting tunnel '{tunnel_def.name}'...")

            tunnel_config = TunnelConfig(
                protocol=tunnel_def.protocol,
                local_port=tunnel_def.local_port,
                subdomain=tunnel_def.subdomain,
                hostname=tunnel_def.hostname,
                auth=tunnel_def.auth,
                inspect=tunnel_def.inspect,
            )

            tunnel = await client.request_tunnel(tunnel_config)
            tunnels.append((tunnel_def.name, tunnel))

        # Display summary
        click.echo("")
        click.echo(f"Active Tunnels ({len(tunnels)} total):")
        click.echo("-" * 40)
        for name, tunnel in tunnels:
            click.echo(f"  {name}: {tunnel.url}")
            click.echo(f"    -> localhost:{tunnel.config.local_port}")
        click.echo("")
        click.echo("Press Ctrl+C to stop all tunnels")

        # Wait for shutdown
        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

    except KeyboardInterrupt:
        pass
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        click.echo("\nShutting down all tunnels...")
        await client.close()
        click.echo("All tunnels closed.")


if __name__ == "__main__":
    cli()
