#!/usr/bin/env python3
"""Fail on exception handlers that swallow the error silently.

A handler whose body cannot report anything is indistinguishable from success.
This is not a style rule -- it is the failure mode that cost real time during
the #41 audit, where a bare `except Exception: return` hid a NameError and made
a probe report "0 resets" while the server was in fact rejecting every frame.
CLAUDE.md already forbids empty catch blocks; this enforces it.

A handler is ACCEPTABLE when it does any of:
  * re-raises (bare `raise`, or `raise X from e`)
  * logs with a traceback: `log.exception(...)`, or `exc_info=` on any log call
  * returns/continues/breaks AFTER doing one of the above
  * is explicitly annotated `# noqa: silent-except  <reason>`

A handler is REJECTED when it catches BROADLY -- bare `except:`,
`except Exception`, or `except BaseException` -- and its whole body is `pass`,
`...`, `return`, `continue` or `break` with nothing recorded.

Narrow handlers are deliberately NOT flagged: `except CancelledError: break`,
`except ValueError: pass  # skip malformed row` and friends are ordinary control
flow, and the author has already named exactly what they expect. The danger is
the handler that catches *everything* and says nothing, because it swallows the
failures nobody predicted -- which is precisely the NameError case above. A hook
that shouts about legitimate narrow handlers is a hook that gets disabled.

Usage: check_no_silent_except.py FILE [FILE ...]
"""

from __future__ import annotations

import ast
import sys

INERT = (ast.Pass, ast.Continue, ast.Break)
ALLOW_MARKER = "noqa: silent-except"


def _records_something(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            # any *.exception(...) call, e.g. logger.exception / log.exception
            if isinstance(node.func, ast.Attribute) and node.func.attr == "exception":
                return True
            # any log call carrying a traceback
            if any(kw.arg == "exc_info" for kw in node.keywords):
                return True
    return False


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """True for `except:`, `except Exception`, `except BaseException` (or a
    tuple containing one of those)."""
    node = handler.type
    if node is None:
        return True  # bare except
    candidates = node.elts if isinstance(node, ast.Tuple) else [node]
    for c in candidates:
        if isinstance(c, ast.Name) and c.id in ("Exception", "BaseException"):
            return True
        if isinstance(c, ast.Attribute) and c.attr in ("Exception", "BaseException"):
            return True
    return False


def _is_inert(handler: ast.ExceptHandler) -> bool:
    for stmt in handler.body:
        if isinstance(stmt, INERT):
            continue
        if isinstance(stmt, ast.Return) and stmt.value is None:
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # bare `...` or a docstring-ish constant
        return False
    return True


def check(path: str) -> list[str]:
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []  # other tools report syntax errors
    lines = src.splitlines()
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_broad(node):
            continue
        if _records_something(node) or not _is_inert(node):
            continue
        window = "\n".join(lines[node.lineno - 1 : node.end_lineno or node.lineno])
        if ALLOW_MARKER in window:
            continue
        problems.append(
            f"{path}:{node.lineno}: exception is swallowed silently -- log it "
            f"with exc_info=True / logger.exception(), re-raise, or annotate "
            f"with `# {ALLOW_MARKER} <reason>`"
        )
    return problems


def main(argv: list[str]) -> int:
    problems: list[str] = []
    for path in argv[1:]:
        if path.endswith(".py"):
            problems.extend(check(path))
    for p in problems:
        print(p)
    if problems:
        print(f"\n{len(problems)} silently swallowed exception(s).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
