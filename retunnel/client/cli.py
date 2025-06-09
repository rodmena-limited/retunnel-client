"""ReTunnel command-line interface."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from .. import __version__
from ..core.config import AuthConfig, ClientConfig
from .client import ReTunnelClient, TunnelConfig

app = typer.Typer(
    name="retunnel",
    help="ReTunnel - Securely expose local servers to the internet",
    add_completion=True,
)
console = Console()


def setup_logging(level: str = "INFO") -> None:
    """Set up logging with rich handler."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@app.command()
def http(
    port: int = typer.Argument(..., help="Local port to expose"),
    subdomain: Optional[str] = typer.Option(
        None, "--subdomain", "-s", help="Request specific subdomain"
    ),
    hostname: Optional[str] = typer.Option(
        None, "--hostname", "-h", help="Request specific hostname"
    ),
    auth: Optional[str] = typer.Option(
        None, "--auth", "-a", help="HTTP basic auth (user:pass)"
    ),
    server: Optional[str] = typer.Option(
        None, "--server", help="ReTunnel server address"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="Authentication token"
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Create an HTTP tunnel to expose a local port."""
    setup_logging(log_level)

    config = TunnelConfig(
        protocol="http",
        local_port=port,
        subdomain=subdomain,
        hostname=hostname,
        auth=auth,
    )

    asyncio.run(_run_tunnel(config, server, token))


@app.command()
def tcp(
    port: int = typer.Argument(..., help="Local port to expose"),
    remote_port: Optional[int] = typer.Option(
        None, "--remote-port", "-r", help="Request specific remote port"
    ),
    server: Optional[str] = typer.Option(
        None, "--server", help="ReTunnel server address"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="Authentication token"
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Create a TCP tunnel to expose a local port."""
    setup_logging(log_level)

    config = TunnelConfig(
        protocol="tcp",
        local_port=port,
    )

    asyncio.run(_run_tunnel(config, server, token))


@app.command()
def start(
    config_path: Path = typer.Argument(
        Path("retunnel.yml"),
        help="Path to configuration file",
        exists=True,
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Start tunnels from configuration file."""
    setup_logging(log_level)

    try:
        config = ClientConfig.from_yaml(config_path)
        asyncio.run(_run_from_config(config))
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def authtoken(
    token: str = typer.Argument(..., help="Authentication token to save"),
) -> None:
    """Save authentication token for future use."""
    auth_config = AuthConfig()
    auth_config.auth_token = token

    console.print(
        f"[green]✓[/green] Auth token saved to {auth_config.CONFIG_PATH}"
    )


@app.command()
def config(
    show: bool = typer.Option(
        False, "--show", help="Show current configuration"
    ),
    example: bool = typer.Option(
        False, "--example", help="Show example configuration"
    ),
) -> None:
    """Manage ReTunnel configuration."""
    if show:
        auth_config = AuthConfig()
        if auth_config.auth_token:
            console.print(f"Auth token: {auth_config.auth_token[:8]}...")
        else:
            console.print("No auth token configured")

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

        console.print(
            Panel(
                yaml.dump(example_config, default_flow_style=False),
                title="Example retunnel.yml",
                border_style="green",
            )
        )

    else:
        console.print("Use --show to display config or --example for sample")


@app.command()
def version() -> None:
    """Show ReTunnel version."""
    console.print(f"ReTunnel v{__version__}")


@app.command()
def credits() -> None:
    """Show open source credits."""
    table = Table(title="Open Source Credits", show_header=True)
    table.add_column("Package", style="cyan")
    table.add_column("License", style="green")
    table.add_column("Description", style="white")

    credits_data = [
        ("aiohttp", "Apache-2.0", "Async HTTP client/server"),
        ("websockets", "BSD-3", "WebSocket client/server"),
        ("msgpack", "Apache-2.0", "MessagePack serialization"),
        ("typer", "MIT", "CLI framework"),
        ("rich", "MIT", "Terminal formatting"),
        ("pydantic", "MIT", "Data validation"),
        ("pyyaml", "MIT", "YAML parser"),
    ]

    for package, license, desc in credits_data:
        table.add_row(package, license, desc)

    console.print(table)
    console.print("\n[dim]Thank you to all open source contributors![/dim]")


async def _run_tunnel(
    config: TunnelConfig,
    server: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """Run a single tunnel."""
    # Create client (server defaults to RETUNNEL_SERVER_ENDPOINT or 127.0.0.1:6400)
    client = ReTunnelClient(server, auth_token=token)

    try:
        # Connect
        console.print(f"[cyan]Connecting to {server}...[/cyan]")
        await client.connect()

        console.print(
            f"[green]✓[/green] Connected with client ID: {client.client_id}"
        )

        # Request tunnel
        msg = (
            f"[cyan]Requesting {config.protocol} tunnel on port "
            f"{config.local_port}...[/cyan]"
        )
        console.print(msg)
        tunnel = await client.request_tunnel(config)

        # Display tunnel info
        panel = Panel(
            f"[bold green]{tunnel.url}[/bold green]\n\n"
            f"[dim]Tunnel ID: {tunnel.id}[/dim]\n"
            f"[dim]Protocol: {tunnel.protocol}[/dim]\n"
            f"[dim]Local Port: {tunnel.local_port}[/dim]",
            title="🚀 Tunnel Active",
            border_style="green",
        )
        console.print(panel)

        console.print("\n[dim]Press Ctrl+C to stop the tunnel...[/dim]")

        # Keep running
        await asyncio.Event().wait()

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        await client.close()
        console.print("[green]✓[/green] Tunnel closed")


async def _run_from_config(config: ClientConfig) -> None:
    """Run tunnels from configuration."""
    # Create client
    client = ReTunnelClient(
        config.server_addr,
        auth_token=config.auth_token,
    )

    try:
        # Connect
        console.print(f"[cyan]Connecting to {config.server_addr}...[/cyan]")
        await client.connect()

        console.print(
            f"[green]✓[/green] Connected with client ID: {client.client_id}"
        )

        # Start all tunnels
        tunnels = []
        for tunnel_def in config.tunnels:
            console.print(
                f"[cyan]Starting tunnel '{tunnel_def.name}'...[/cyan]"
            )

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

            console.print(f"[green]✓[/green] {tunnel_def.name}: {tunnel.url}")

        # Display summary
        table = Table(title="Active Tunnels", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("URL", style="green")
        table.add_column("Local Port", style="yellow")

        for name, tunnel in tunnels:
            table.add_row(name, tunnel.url, str(tunnel.local_port))

        console.print("\n")
        console.print(table)
        console.print("\n[dim]Press Ctrl+C to stop all tunnels...[/dim]")

        # Keep running
        await asyncio.Event().wait()

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        await client.close()
        console.print("[green]✓[/green] All tunnels closed")


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
