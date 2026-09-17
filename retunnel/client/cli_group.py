"""Group that accepts its own options before or after the subcommand.

issuedb #65. Click binds group-level options strictly ahead of the subcommand
name, so `retunnel http 8080 --json` failed with "No such option: --json Did
you mean --token?" -- a suggestion drawn from the subcommand's namespace, which
points away from the cause. Every group option was affected, including
`--log-level DEBUG`, which the project's own documentation instructed users to
pass in the failing position.
"""

from __future__ import annotations

import click

_TERMINATOR = "--"


def _option_arity(param: click.Parameter) -> int:
    """How many following tokens this option consumes as its value."""
    if isinstance(param, click.Option) and param.is_flag:
        return 0
    nargs = getattr(param, "nargs", 1)
    return int(nargs)


class RelocatingGroup(click.Group):
    """A `click.Group` whose options may follow the subcommand.

    Only options this group actually declares are moved, and only when the
    resolved subcommand does not declare the same name itself. An unknown
    option is left where it is so click still rejects it: the point is to stop
    misreporting a misplaced known option, not to become permissive about
    typos.
    """

    def _group_options(self) -> dict[str, click.Parameter]:
        flags: dict[str, click.Parameter] = {}
        for param in self.params:
            for opt in (*param.opts, *param.secondary_opts):
                if opt.startswith("-"):
                    flags[opt] = param
        return flags

    def _subcommand_flags(
        self, ctx: click.Context, name: str
    ) -> dict[str, int]:
        """The subcommand's own options, mapped to the values they consume."""
        command = self.get_command(ctx, name)
        if command is None:
            return {}
        return {
            opt: _option_arity(param)
            for param in command.params
            for opt in (*param.opts, *param.secondary_opts)
            if opt.startswith("-")
        }

    def _split_at_subcommand(
        self, args: list[str], flags: dict[str, click.Parameter]
    ) -> int:
        """Index of the subcommand name, or len(args) when there is none."""
        i = 0
        while i < len(args):
            token = args[i]
            if token == _TERMINATOR:
                return len(args)
            if not token.startswith("-"):
                return i
            if "=" not in token and token in flags:
                i += _option_arity(flags[token])
            i += 1
        return len(args)

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        return super().parse_args(ctx, self._relocate(ctx, args))

    def _relocate(self, ctx: click.Context, args: list[str]) -> list[str]:
        flags = self._group_options()
        split = self._split_at_subcommand(args, flags)
        if split >= len(args):
            return args

        owned = self._subcommand_flags(ctx, args[split])
        leading = args[:split]
        trailing = [args[split]]
        moved: list[str] = []

        rest = args[split + 1 :]
        i = 0
        while i < len(rest):
            token = rest[i]
            if token == _TERMINATOR:
                trailing.extend(rest[i:])
                break
            name = token.split("=", 1)[0] if token.startswith("-") else token
            if name in owned:
                # The subcommand owns this option. Carry its value tokens with
                # it untouched: `--token --json` means the literal string
                # "--json", and stealing it leaves --token without an argument.
                trailing.append(token)
                if "=" not in token:
                    take = owned[name]
                    trailing.extend(rest[i + 1 : i + 1 + take])
                    i += take
            elif name in flags:
                moved.append(token)
                if "=" not in token:
                    take = _option_arity(flags[name])
                    moved.extend(rest[i + 1 : i + 1 + take])
                    i += take
            else:
                trailing.append(token)
            i += 1

        if not moved:
            return args
        return [*leading, *moved, *trailing]


__all__ = ["RelocatingGroup"]
