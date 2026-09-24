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

    @staticmethod
    def _own_flags(command: click.Command) -> dict[str, int]:
        return {
            opt: _option_arity(param)
            for param in command.params
            for opt in (*param.opts, *param.secondary_opts)
            if opt.startswith("-")
        }

    def _chain_flags(
        self, ctx: click.Context, name: str, rest: list[str]
    ) -> dict[str, int]:
        """Options declared anywhere along the resolved subcommand chain.

        `hostname list --json`: `--json` belongs to `list`, two levels down.
        Looking only at the first subcommand (a group without --json) moved
        the flag to the root, so `list` never received it (#65 regression in
        3.2.1 and 3.2.2).
        """
        owned: dict[str, int] = {}
        command = self.get_command(ctx, name)
        i = 0
        while command is not None:
            own = self._own_flags(command)
            owned.update(own)
            if not isinstance(command, click.Group):
                break
            nxt = None
            while i < len(rest):
                token = rest[i]
                if token == _TERMINATOR:
                    return owned
                if token.startswith("-"):
                    flag = token.split("=", 1)[0]
                    if "=" not in token and flag in own:
                        i += own[flag]
                    i += 1
                    continue
                nxt = token
                i += 1
                break
            if nxt is None:
                break
            command = command.get_command(ctx, nxt)
        return owned

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

        owned = self._chain_flags(ctx, args[split], args[split + 1 :])
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
