"""ReTunnel command-line interface."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.logging import RichHandler
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.traceback import install
from rich.tree import Tree

from .. import __version__
from ..core.config import AuthConfig, ClientConfig
from .high_performance_model import HighPerformanceClient, TunnelConfig

# Install rich traceback handler for better error display
install(show_locals=False)

app = typer.Typer(
    name="retunnel",
    help="ReTunnel - Enterprise-grade secure tunnel service for exposing local servers to the internet",
    add_completion=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
console = Console()

# Define ReTunnel brand colors and styles
RETUNNEL_THEME = {
    "primary": "cyan",
    "success": "green",
    "warning": "yellow",
    "error": "red",
    "info": "blue",
    "dim": "dim",
}


def display_error(error: Exception, title: str = "Error") -> None:
    """Display error in a consistent, styled format."""
    console.print(
        Panel(
            f"[{RETUNNEL_THEME['error']}]{error}[/{RETUNNEL_THEME['error']}]",
            title=f"[bold {RETUNNEL_THEME['error']}]{title}[/bold {RETUNNEL_THEME['error']}]",
            border_style=RETUNNEL_THEME["error"],
            padding=(1, 2),
        )
    )


def _format_bytes(num: int) -> str:
    """Format bytes to human readable format"""
    size = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024.0:
            if unit == "B":
                return f"{size:.0f}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"


def setup_logging(level: str = "INFO") -> None:
    """Set up logging with rich handler."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_time=False,
                show_path=False,
            )
        ],
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
        display_error(e, "Configuration Error")
        raise typer.Exit(1)


@app.command()
def authtoken(
    token: Optional[str] = typer.Argument(
        None, help="Authentication token to save"
    ),
) -> None:
    """Save authentication token for future use."""
    # Interactive prompt if token not provided
    if not token:
        token = Prompt.ask(
            f"[{RETUNNEL_THEME['primary']}]Enter authentication token[/{RETUNNEL_THEME['primary']}]",
            password=True,
        )

    if not token:
        display_error(ValueError("Token cannot be empty"), "Invalid Token")
        raise typer.Exit(1)

    auth_config = AuthConfig()
    auth_config.auth_token = token

    console.print(
        Panel(
            f"[{RETUNNEL_THEME['success']}]✓[/{RETUNNEL_THEME['success']}] Auth token saved successfully\n\n"
            f"[{RETUNNEL_THEME['dim']}]Location: {auth_config.CONFIG_PATH}[/{RETUNNEL_THEME['dim']}]",
            title="[bold]Token Saved[/bold]",
            border_style=RETUNNEL_THEME["success"],
        )
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
        tree = Tree("[bold]ReTunnel Configuration[/bold]")

        # Auth section
        auth_branch = tree.add("[cyan]Authentication[/cyan]")
        if auth_config.auth_token:
            auth_branch.add(
                f"Token: [green]{auth_config.auth_token[:8]}...[/green]"
            )
        else:
            auth_branch.add("[red]No auth token configured[/red]")

        # Server section
        server_branch = tree.add("[cyan]Server[/cyan]")
        server_branch.add("Default: [blue]retunnel.net[/blue]")

        console.print(
            Panel(tree, title="Current Configuration", border_style="cyan")
        )

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

        yaml_content = yaml.dump(example_config, default_flow_style=False)
        syntax = Syntax(
            yaml_content, "yaml", theme="monokai", line_numbers=True
        )
        console.print(
            Panel(
                syntax,
                title="[bold]Example retunnel.yml[/bold]",
                border_style=RETUNNEL_THEME["success"],
                padding=(1, 2),
            )
        )

    else:
        console.print("Use --show to display config or --example for sample")


@app.command()
def help() -> None:
    """Show detailed help information."""
    help_text = """
# ReTunnel CLI Help

**ReTunnel** is a secure tunnel service for exposing local servers to the internet.

## Quick Start

```bash
# Expose HTTP server on port 8080
retunnel http 8080

# Expose with custom subdomain
retunnel http 8080 --subdomain myapp

# Expose TCP service
retunnel tcp 22
```

## Features

- 🚀 **Fast** - High-performance WebSocket connections
- 🔒 **Secure** - TLS encryption and authentication
- 🌍 **Global** - Multiple regions available
- 📊 **Real-time Stats** - Live traffic monitoring
- 🎨 **Beautiful CLI** - Rich terminal interface

## Commands

### `retunnel http <port>`
Create an HTTP tunnel to expose a local web server.

**Options:**
- `--subdomain` / `-s`: Request specific subdomain
- `--hostname` / `-h`: Request specific hostname
- `--auth` / `-a`: HTTP basic auth (user:pass)
- `--server`: Custom server address
- `--token`: Authentication token

### `retunnel tcp <port>`
Create a TCP tunnel to expose any TCP service.

**Options:**
- `--remote-port` / `-r`: Request specific remote port
- `--server`: Custom server address
- `--token`: Authentication token

### `retunnel start [config.yml]`
Start tunnels from a configuration file.

### `retunnel authtoken <token>`
Save authentication token for future use.

### `retunnel config`
Manage configuration settings.

**Options:**
- `--show`: Display current configuration
- `--example`: Show example config file

### `retunnel version`
Display version information.

### `retunnel credits`
Show open source credits.

## Configuration File

Create a `retunnel.yml` file:

```yaml
server_addr: retunnel.net
auth_token: your-token-here
tunnels:
  - name: web
    protocol: http
    local_port: 8080
    subdomain: myapp
  - name: api
    protocol: http
    local_port: 3000
    auth: user:pass
```

Then run: `retunnel start`

## Environment Variables

- `RETUNNEL_SERVER_ENDPOINT`: Override default server
- `RETUNNEL_AUTH_TOKEN`: Set authentication token

## Support

- GitHub: https://github.com/retunnel/retunnel
- Documentation: https://docs.retunnel.com
- Email: support@retunnel.com
"""

    console.print(Markdown(help_text))


@app.command()
def version() -> None:
    """Show ReTunnel version."""
    version_panel = Panel(
        Align.center(
            Group(
                f"[bold {RETUNNEL_THEME['primary']}]ReTunnel[/bold {RETUNNEL_THEME['primary']}]",
                f"[{RETUNNEL_THEME['dim']}]Version {__version__}[/{RETUNNEL_THEME['dim']}]",
                "",
                f"[{RETUNNEL_THEME['dim']}]© 2024 ReTunnel Team[/{RETUNNEL_THEME['dim']}]",
            ),
            vertical="middle",
        ),
        border_style=RETUNNEL_THEME["primary"],
        padding=(1, 20),
    )
    console.print(version_panel)


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
        box=None,
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

        # Display welcome banner
        welcome_panel = Panel(
            Align.center(
                Group(
                    f"[bold {RETUNNEL_THEME['primary']}]ReTunnel[/bold {RETUNNEL_THEME['primary']}]",
                    f"[{RETUNNEL_THEME['dim']}]Secure Tunnel Service v{__version__}[/{RETUNNEL_THEME['dim']}]",
                ),
                vertical="middle",
            ),
            border_style=RETUNNEL_THEME["primary"],
            padding=(1, 10),
        )
        console.print(welcome_panel)
        console.print()

        # Connection with status
        with console.status(
            f"[{RETUNNEL_THEME['primary']}]Establishing secure connection...[/{RETUNNEL_THEME['primary']}]",
            spinner="dots2",
        ) as status:
            await client.connect()
            status.update(
                f"[{RETUNNEL_THEME['success']}]✓ Connected to tunnel service[/{RETUNNEL_THEME['success']}]"
            )
            await asyncio.sleep(0.5)

        # Request tunnel with status
        with console.status(
            f"[{RETUNNEL_THEME['primary']}]Creating {config.protocol.upper()} tunnel...[/{RETUNNEL_THEME['primary']}]",
            spinner="dots2",
        ) as status:
            tunnel = await client.request_tunnel(config)
            status.update(
                f"[{RETUNNEL_THEME['success']}]✓ Tunnel created successfully[/{RETUNNEL_THEME['success']}]"
            )
            await asyncio.sleep(0.5)

        # Create tunnel info table
        tunnel_table = Table(show_header=False, box=None, padding=(0, 2))
        tunnel_table.add_column(style=f"{RETUNNEL_THEME['dim']}")
        tunnel_table.add_column(style="bold")

        tunnel_table.add_row(
            "URL",
            f"[bold {RETUNNEL_THEME['success']}]{tunnel.url}[/bold {RETUNNEL_THEME['success']}]",
        )
        tunnel_table.add_row("Protocol", tunnel.protocol.upper())
        tunnel_table.add_row("Local Port", str(tunnel.config.local_port))
        # Initial status
        status_text = f"[{RETUNNEL_THEME['success']}]● Active[/{RETUNNEL_THEME['success']}]"
        tunnel_table.add_row("Status", status_text)

        # Add auth token display (last 4 characters)
        if client.auth_token:
            token_display = f"****{client.auth_token[-4:]}"
        else:
            token_display = "None"
        tunnel_table.add_row(
            "Token",
            f"[{RETUNNEL_THEME['dim']}]{token_display}[/{RETUNNEL_THEME['dim']}]",
        )

        tunnel_panel = Panel(
            tunnel_table,
            title="[bold]Tunnel Details[/bold]",
            border_style=RETUNNEL_THEME["success"],
            padding=(1, 2),
        )

        # Create layout for tunnel info and traffic stats
        layout = Layout()
        layout.split_column(
            Layout(tunnel_panel, name="info", size=8),
            Layout(name="stats", size=3),
        )

        # Initial stats panel
        initial_stats = Panel(
            Align.center(
                Columns(
                    [
                        f"[{RETUNNEL_THEME['primary']}]↑ Upload[/{RETUNNEL_THEME['primary']}] 0B",
                        f"[{RETUNNEL_THEME['primary']}]↓ Download[/{RETUNNEL_THEME['primary']}] 0B",
                        f"[{RETUNNEL_THEME['dim']}]Uptime 0m 0s[/{RETUNNEL_THEME['dim']}]",
                    ],
                    expand=True,
                    align="center",
                ),
                vertical="middle",
            ),
            title="[bold]Traffic[/bold]",
            border_style=RETUNNEL_THEME["info"],
        )
        layout["stats"].update(initial_stats)

        # Initial display
        console.print(layout)
        console.print(
            f"\n[{RETUNNEL_THEME['dim']}]Press Ctrl+C to stop[/{RETUNNEL_THEME['dim']}]\n"
        )

        # Keep running and show stats using Live
        try:
            with Live(
                layout, console=console, refresh_per_second=2, transient=False
            ) as live:
                while True:
                    # Update connection status
                    if client.is_connected:
                        status_text = f"[{RETUNNEL_THEME['success']}]● Active[/{RETUNNEL_THEME['success']}]"
                    elif client._reconnecting:
                        status_text = f"[{RETUNNEL_THEME['warning']}]⟳ {client.connection_status}[/{RETUNNEL_THEME['warning']}]"
                    else:
                        status_text = f"[{RETUNNEL_THEME['error']}]● {client.connection_status}[/{RETUNNEL_THEME['error']}]"

                    # Rebuild tunnel table with updated status
                    tunnel_table = Table(
                        show_header=False, box=None, padding=(0, 2)
                    )
                    tunnel_table.add_column(style=f"{RETUNNEL_THEME['dim']}")
                    tunnel_table.add_column(style="bold")

                    tunnel_table.add_row(
                        "URL",
                        f"[bold {RETUNNEL_THEME['success']}]{tunnel.url}[/bold {RETUNNEL_THEME['success']}]",
                    )
                    tunnel_table.add_row("Protocol", tunnel.protocol.upper())
                    tunnel_table.add_row(
                        "Local Port", str(tunnel.config.local_port)
                    )
                    tunnel_table.add_row("Status", status_text)

                    # Add auth token display (last 4 characters)
                    if client.auth_token:
                        token_display = f"****{client.auth_token[-4:]}"
                    else:
                        token_display = "None"
                    tunnel_table.add_row(
                        "Token",
                        f"[{RETUNNEL_THEME['dim']}]{token_display}[/{RETUNNEL_THEME['dim']}]",
                    )

                    tunnel_panel = Panel(
                        tunnel_table,
                        title="[bold]Tunnel Details[/bold]",
                        border_style=(
                            RETUNNEL_THEME["success"]
                            if client.is_connected
                            else RETUNNEL_THEME["warning"]
                        ),
                        padding=(1, 2),
                    )

                    layout["info"].update(tunnel_panel)

                    # Update traffic stats
                    stats = tunnel.get_stats()
                    in_bytes = _format_bytes(stats["bytes_in"])
                    out_bytes = _format_bytes(stats["bytes_out"])
                    uptime = int(stats.get("uptime", 0))
                    uptime_str = f"{uptime // 60}m {uptime % 60}s"

                    # Create traffic stats panel
                    stats_content = Columns(
                        [
                            f"[{RETUNNEL_THEME['primary']}]↑ Upload[/{RETUNNEL_THEME['primary']}] {in_bytes}",
                            f"[{RETUNNEL_THEME['primary']}]↓ Download[/{RETUNNEL_THEME['primary']}] {out_bytes}",
                            f"[{RETUNNEL_THEME['dim']}]Uptime {uptime_str}[/{RETUNNEL_THEME['dim']}]",
                        ],
                        expand=True,
                        align="center",
                    )

                    stats_panel = Panel(
                        Align.center(stats_content, vertical="middle"),
                        title="[bold]Traffic[/bold]",
                        border_style=RETUNNEL_THEME["info"],
                    )

                    layout["stats"].update(stats_panel)
                    await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass

    except KeyboardInterrupt:
        # Move to a clean line and show shutdown message
        console.print()
        with console.status(
            f"[{RETUNNEL_THEME['warning']}]Shutting down tunnel...[/{RETUNNEL_THEME['warning']}]",
            spinner="dots2",
        ):
            await client.close()
            await asyncio.sleep(0.5)

        console.print(
            Panel(
                f"[{RETUNNEL_THEME['success']}]✓ Tunnel closed successfully[/{RETUNNEL_THEME['success']}]",
                border_style=RETUNNEL_THEME["success"],
                padding=(0, 2),
            )
        )
    except Exception as e:
        console.print()
        display_error(e, "Connection Error")
        raise typer.Exit(1)
    finally:
        # Ensure client is closed
        if "client" in locals():
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
        # Connect with status
        with console.status(
            f"[{RETUNNEL_THEME['primary']}]Connecting to {config.server_addr}...[/{RETUNNEL_THEME['primary']}]",
            spinner="dots2",
        ) as status:
            await client.connect()
            status.update(
                f"[{RETUNNEL_THEME['success']}]✓ Connected successfully[/{RETUNNEL_THEME['success']}]"
            )
            await asyncio.sleep(0.5)

        # Start all tunnels with progress
        tunnels = []
        with Progress(
            SpinnerColumn(
                spinner_name="dots2", style=RETUNNEL_THEME["primary"]
            ),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:

            task_id = progress.add_task(
                f"[{RETUNNEL_THEME['primary']}]Starting tunnels...[/{RETUNNEL_THEME['primary']}]",
                total=len(config.tunnels),
            )

            for tunnel_def in config.tunnels:
                progress.update(
                    task_id,
                    description=f"[{RETUNNEL_THEME['primary']}]Starting '{tunnel_def.name}'...[/{RETUNNEL_THEME['primary']}]",
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
                progress.advance(task_id)

            progress.update(
                task_id,
                description=f"[{RETUNNEL_THEME['success']}]✓ All tunnels started[/{RETUNNEL_THEME['success']}]",
            )

        # Display summary using Tree
        console.print()
        tree = Tree(
            f"[bold]Active Tunnels[/bold] ({len(tunnels)} total)",
            guide_style=RETUNNEL_THEME["dim"],
        )

        for name, tunnel in tunnels:
            branch = tree.add(
                f"[{RETUNNEL_THEME['primary']}]{name}[/{RETUNNEL_THEME['primary']}]"
            )
            branch.add(
                f"[{RETUNNEL_THEME['success']}]{tunnel.url}[/{RETUNNEL_THEME['success']}]"
            )
            branch.add(
                f"[{RETUNNEL_THEME['dim']}]Local port: {tunnel.config.local_port}[/{RETUNNEL_THEME['dim']}]"
            )
            if tunnel.protocol == "http":
                branch.add(
                    f"[{RETUNNEL_THEME['dim']}]Protocol: HTTP/HTTPS[/{RETUNNEL_THEME['dim']}]"
                )
            else:
                branch.add(
                    f"[{RETUNNEL_THEME['dim']}]Protocol: {tunnel.protocol.upper()}[/{RETUNNEL_THEME['dim']}]"
                )

        console.print(
            Panel(
                tree,
                border_style=RETUNNEL_THEME["success"],
                padding=(1, 2),
            )
        )

        console.print(
            f"\n[{RETUNNEL_THEME['dim']}]Press Ctrl+C to stop all tunnels...[/{RETUNNEL_THEME['dim']}]"
        )

        # Keep running
        await asyncio.Event().wait()

    except KeyboardInterrupt:
        console.print()
        with console.status(
            f"[{RETUNNEL_THEME['warning']}]Shutting down all tunnels...[/{RETUNNEL_THEME['warning']}]",
            spinner="dots2",
        ):
            await client.close()
            await asyncio.sleep(0.5)

        console.print(
            Panel(
                f"[{RETUNNEL_THEME['success']}]✓ All tunnels closed successfully[/{RETUNNEL_THEME['success']}]",
                border_style=RETUNNEL_THEME["success"],
                padding=(0, 2),
            )
        )
    except Exception as e:
        console.print()
        display_error(e, "Configuration Error")
        raise typer.Exit(1)
    finally:
        if "client" in locals():
            await client.close()


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
