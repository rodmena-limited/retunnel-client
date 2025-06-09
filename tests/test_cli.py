"""Fast CLI tests."""

from unittest.mock import patch

from typer.testing import CliRunner

from retunnel.client.cli import app


def test_version():
    """Test version command."""
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "ReTunnel" in result.stdout


def test_help():
    """Test help command."""
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ReTunnel" in result.stdout


def test_credits():
    """Test credits command."""
    runner = CliRunner()
    result = runner.invoke(app, ["credits"])
    assert result.exit_code == 0


@patch("retunnel.client.cli.asyncio.run")
def test_http_command(mock_run):
    """Test HTTP command."""
    runner = CliRunner()
    result = runner.invoke(app, ["http", "8080"])
    mock_run.assert_called_once()


@patch("retunnel.client.cli.asyncio.run")
def test_tcp_command(mock_run):
    """Test TCP command."""
    runner = CliRunner()
    result = runner.invoke(app, ["tcp", "22"])
    mock_run.assert_called_once()


@patch("retunnel.client.cli.asyncio.run")
def test_ssh_command(mock_run):
    """Test SSH command."""
    runner = CliRunner()
    result = runner.invoke(app, ["ssh", "22"])
    mock_run.assert_called_once()


@patch("retunnel.client.cli.asyncio.run")
def test_list_command(mock_run):
    """Test list command."""
    runner = CliRunner()
    result = runner.invoke(app, ["list"])
    mock_run.assert_called_once()


@patch("retunnel.client.cli.asyncio.run")
def test_status_command(mock_run):
    """Test status command."""
    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    mock_run.assert_called_once()


def test_http_with_hostname():
    """Test HTTP command with hostname."""
    runner = CliRunner()
    with patch("retunnel.client.cli.asyncio.run") as mock_run:
        result = runner.invoke(app, ["http", "8080", "--hostname", "custom.ngrok.io"])
        mock_run.assert_called_once()


def test_tcp_with_auth():
    """Test TCP command with auth."""
    runner = CliRunner()
    with patch("retunnel.client.cli.asyncio.run") as mock_run:
        result = runner.invoke(app, ["tcp", "22", "--auth", "user:pass"])
        mock_run.assert_called_once()


def test_global_options():
    """Test global options."""
    runner = CliRunner()
    with patch("retunnel.client.cli.asyncio.run") as mock_run:
        result = runner.invoke(app, ["--server", "wss://custom.com", "http", "8080"])
        mock_run.assert_called_once()