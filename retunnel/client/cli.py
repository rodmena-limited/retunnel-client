"""ReTunnel command-line interface."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.live import Live

from .. import __version__
from ..core.config import AuthConfig, ClientConfig
from .high_performance_model import HighPerformanceClient, TunnelConfig

app = typer.Typer(
    name="retunnel",
    help="ReTunnel - Enterprise-grade secure tunnel service for exposing local servers to the internet",
    add_completion=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
console = Console()


def _format_bytes(num: int) -> str:
    """Format bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(num) < 1024.0:
            if unit == 'B':
                return f"{num:.0f}{unit}"
            return f"{num:.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}PB"


def setup_logging(level: str = "INFO") -> None:
    """Set up logging with rich handler."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_time=False, show_path=False)],
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
    console.print(f"\n[bold cyan]ReTunnel[/bold cyan] v{__version__}")
    console.print("[dim]© 2024 ReTunnel Team[/dim]\n")


@app.command()
def credits() -> None:
    """Show open source credits."""
    console.print("\n[bold cyan]Open Source Credits[/bold cyan]\n")
    
    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        show_edge=False,
        pad_edge=False,
        box=None
    )
    table.add_column("Package", style="cyan")
    table.add_column("License", style="green")
    table.add_column("Description")

    credits_data = [
        ("aiohttp", "Apache-2.0", "Async HTTP client/server"),
        ("msgpack", "Apache-2.0", "Binary serialization"),
        ("typer", "MIT", "CLI framework"),
        ("rich", "MIT", "Terminal formatting"),
        ("pydantic", "MIT", "Data validation"),
        ("pyyaml", "MIT", "YAML parser"),
    ]

    for package, license, desc in credits_data:
        table.add_row(package, license, desc)

    console.print(table)
    console.print("\n[dim italic]Thank you to all contributors[/dim italic]\n")


async def _run_tunnel(
    config: TunnelConfig,
    server: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """Run a single tunnel."""
    # Suppress client logging to preserve Rich output
    import logging as _logging
    _logging.getLogger("client").setLevel(_logging.ERROR)
    _logging.getLogger("retunnel").setLevel(_logging.ERROR)
    _logging.getLogger("aiohttp").setLevel(_logging.ERROR)
    _logging.getLogger("asyncio").setLevel(_logging.ERROR)
    
    # Disable the default KeyboardInterrupt traceback
    import sys
    sys.tracebacklimit = 0
    
    # Create client (server defaults to RETUNNEL_SERVER_ENDPOINT or localhost:6400)
    client = HighPerformanceClient(server, auth_token=token)

    try:
        # Clean header
        console.clear()
        console.print()
        console.print(f"[bold cyan]ReTunnel[/bold cyan] [dim]v{__version__}[/dim]")
        console.print("[dim]Secure tunnel service[/dim]")
        console.print()
        
        # Connection progress
        with Progress(
            SpinnerColumn(spinner_name="dots", style="cyan"),
            TextColumn("[cyan]Establishing secure connection...[/cyan]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Connecting", total=None)
            await client.connect()
            progress.update(task, description="[green]✓[/green] Connected successfully")
            await asyncio.sleep(0.3)
        
        console.print(f"[green]✓[/green] Connected to tunnel service")
        console.print(f"[dim]Client ID: {client.client_id}[/dim]")
        console.print()

        # Request tunnel
        with Progress(
            SpinnerColumn(spinner_name="dots", style="cyan"),
            TextColumn(f"[cyan]Creating {config.protocol.upper()} tunnel...[/cyan]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Creating", total=None)
            tunnel = await client.request_tunnel(config)
            progress.update(task, description="[green]✓[/green] Tunnel created")
            await asyncio.sleep(0.3)

        # Display tunnel info cleanly
        console.print()
        console.print(Rule(style="dim"))
        console.print()
        console.print(f"[bold green]{tunnel.url}[/bold green]")
        console.print()
        console.print(f"  [cyan]Protocol[/cyan]    {tunnel.protocol.upper()}")
        console.print(f"  [cyan]Local port[/cyan]  {tunnel.config.local_port}")
        console.print(f"  [cyan]Status[/cyan]      [green]● Active[/green]")
        console.print()
        console.print(Rule(style="dim"))
        console.print()
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        console.print()
        
        # Keep running and show stats using Live
        try:
            with Live(
                "[dim]↑ 0B  ↓ 0B[/dim]",
                console=console,
                refresh_per_second=0.5,
                transient=False
            ) as live:
                while True:
                    stats = tunnel.get_stats()
                    in_bytes = _format_bytes(stats['bytes_in'])
                    out_bytes = _format_bytes(stats['bytes_out'])
                    
                    # Update the live display
                    live.update(f"[dim]↑ {in_bytes}  ↓ {out_bytes}[/dim]")
                    
                    await asyncio.sleep(2)
        except KeyboardInterrupt:
            pass

    except KeyboardInterrupt:
        # Move to a clean line and show shutdown message
        console.print()  # New line
        console.print("[yellow]Shutting down tunnel...[/yellow]")
        await client.close()
        console.print("[green]✓[/green] Tunnel closed successfully\n")
    except Exception as e:
        console.print()
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        # Ensure client is closed
        if 'client' in locals():
            await client.close()
        # Give asyncio time to clean up
        await asyncio.sleep(0.1)


async def _run_from_config(config: ClientConfig) -> None:
    """Run tunnels from configuration."""
    # Create client
    client = HighPerformanceClient(
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
            table.add_row(name, tunnel.url, str(tunnel.config.local_port))

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
