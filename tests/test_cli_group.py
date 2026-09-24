"""issuedb #65: group-level options must work on either side of the subcommand.

The assertions compare the PARSED VALUES in both positions rather than only
checking that parsing did not raise. A test that asserts "exit code 0" passes
on a build that accepts the flag and discards it, which is the same defect with
a quieter symptom.
"""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from retunnel.client.cli_group import RelocatingGroup


@click.group(cls=RelocatingGroup, invoke_without_command=True)
@click.option("--json", "json_output", is_flag=True)
@click.option("--quiet", "-q", is_flag=True)
@click.option("--log-level", default="INFO")
@click.option("--log-file", default=None)
@click.pass_context
def probe(
    ctx: click.Context,
    json_output: bool,
    quiet: bool,
    log_level: str,
    log_file: str | None,
) -> None:
    ctx.obj = {
        "json": json_output,
        "quiet": quiet,
        "log_level": log_level,
        "log_file": log_file,
    }


@probe.command("http")
@click.argument("port", type=int)
@click.option("--token", default=None)
@click.pass_context
def probe_http(ctx: click.Context, port: int, token: str | None) -> None:
    click.echo(f"{port}|{token}|{ctx.obj}")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.mark.parametrize(
    "before,after",
    [
        (["--json", "http", "8412"], ["http", "8412", "--json"]),
        (["-q", "http", "8412"], ["http", "8412", "-q"]),
        (
            ["--log-level", "DEBUG", "http", "8412"],
            ["http", "8412", "--log-level", "DEBUG"],
        ),
        (
            ["--log-level=DEBUG", "http", "8412"],
            ["http", "8412", "--log-level=DEBUG"],
        ),
        (
            ["--log-file", "/tmp/a.log", "http", "8412"],
            ["http", "8412", "--log-file", "/tmp/a.log"],
        ),
    ],
)
def test_either_position_parses_identically(
    runner: CliRunner, before: list[str], after: list[str]
) -> None:
    lead = runner.invoke(probe, before)
    trail = runner.invoke(probe, after)
    assert lead.exit_code == 0, lead.output
    assert trail.exit_code == 0, trail.output
    assert trail.output == lead.output


def test_subcommand_option_is_not_disturbed(runner: CliRunner) -> None:
    res = runner.invoke(probe, ["http", "8412", "--token", "abc", "--json"])
    assert res.exit_code == 0, res.output
    port, token, ctx = res.output.strip().split("|", 2)
    assert port == "8412"
    assert token == "abc"
    assert "'json': True" in ctx


def test_unknown_option_after_subcommand_still_fails(
    runner: CliRunner,
) -> None:
    """The fix must not become permissive about real typos."""
    res = runner.invoke(probe, ["http", "8412", "--nonesuch"])
    assert res.exit_code != 0
    assert "No such option" in res.output


def test_unknown_option_before_subcommand_still_fails(
    runner: CliRunner,
) -> None:
    res = runner.invoke(probe, ["--nonesuch", "http", "8412"])
    assert res.exit_code != 0
    assert "No such option" in res.output


def test_tokens_after_terminator_are_left_alone(runner: CliRunner) -> None:
    """`--` ends option parsing; a later --json is data, not a flag."""
    res = runner.invoke(probe, ["http", "8412", "--", "--json"])
    assert res.exit_code != 0


def test_value_that_looks_like_a_group_option_is_not_stolen(
    runner: CliRunner,
) -> None:
    """`--token --json` means the literal token "--json", not the flag."""
    res = runner.invoke(probe, ["http", "8412", "--token", "--json"])
    assert res.exit_code == 0, res.output
    _, token, ctx = res.output.strip().split("|", 2)
    assert token == "--json"
    assert "'json': False" in ctx


def test_real_cli_accepts_json_after_subcommand() -> None:
    """The exact invocation from the vellum-build-d8bbd2 report."""
    from retunnel.client.cli import cli

    res = CliRunner().invoke(cli, ["http", "8412", "--json", "--help"])
    assert res.exit_code == 0, res.output
    assert "No such option" not in res.output


def test_real_cli_accepts_log_level_after_subcommand() -> None:
    """The invocation this project's own documentation instructed."""
    from retunnel.client.cli import cli

    res = CliRunner().invoke(
        cli, ["http", "8080", "--log-level", "DEBUG", "--help"]
    )
    assert res.exit_code == 0, res.output
    assert "No such option" not in res.output


@click.group(cls=RelocatingGroup, invoke_without_command=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def nested_root(ctx: click.Context, json_output: bool) -> None:
    ctx.obj = {"root_json": json_output}


@nested_root.group("hostname")
def nested_hostname() -> None:
    pass


@nested_hostname.command("list")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def nested_list(ctx: click.Context, as_json: bool) -> None:
    click.echo(f"sub_json={as_json} root={ctx.find_root().obj}")


def test_nested_subcommand_keeps_its_own_option(runner: CliRunner) -> None:
    """`hostname list --json`: the option belongs to `list`, two levels down.

    3.2.1/3.2.2 checked only the first subcommand (`hostname`, a group with no
    --json), moved the flag to the root, and `list` never saw it.
    """
    res = runner.invoke(nested_root, ["hostname", "list", "--json"])
    assert res.exit_code == 0, res.output
    assert "sub_json=True" in res.output
    assert "'root_json': False" in res.output


def test_real_cli_hostname_list_json_reaches_the_subcommand() -> None:
    from retunnel.client.cli import cli

    res = CliRunner().invoke(cli, ["hostname", "list", "--json", "--help"])
    assert res.exit_code == 0, res.output
    assert "Machine-readable output" in res.output
