"""The single reader/writer of ~/.retunnel.conf (issuedb #72).

Every change to the file goes through `update`, which holds an exclusive lock,
re-reads the current contents, applies the change, and replaces the file
atomically (temporary file created 0o600 in the same directory, fsync,
os.replace, directory fsync). A file that exists but cannot be read or parsed
raises ConfigUnreadable and is never overwritten: in client 3.2.1 a failed read
rewrote the file with defaults, and the next start registered a new account,
orphaning every custom hostname the old account owned.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

if sys.platform != "win32":
    import fcntl


class ConfigUnreadable(Exception):
    """The config file exists but could not be read or parsed."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def read(path: Path) -> dict[str, Any] | None:
    """The file's contents, None if it does not exist.

    Raises ConfigUnreadable for any other failure, including a file that is
    empty, truncated, not JSON, or JSON that is not an object.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigUnreadable(
            path, f"cannot read: {exc.strerror or exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigUnreadable(path, f"not valid JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise ConfigUnreadable(path, "not a JSON object")
    return data


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        yield
        return
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, indent=2).encode("utf-8")
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        if sys.platform != "win32":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def update(
    path: Path,
    change: Callable[[dict[str, Any]], None],
    *,
    replace_unreadable: bool = False,
) -> dict[str, Any]:
    """Apply `change` to the file's contents and write the result atomically.

    Keys the caller does not touch are preserved. If the current file cannot
    be read, ConfigUnreadable is raised and nothing is written -- unless
    `replace_unreadable` is set (the explicit `retunnel authtoken` recovery
    path), in which case the unreadable file is kept beside it as
    .retunnel.conf.corrupt-<unix time> before a fresh one is written.
    """
    with _locked(path):
        try:
            current = read(path) or {}
        except ConfigUnreadable:
            if not replace_unreadable:
                raise
            aside = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
            os.replace(path, aside)
            current = {}
        change(current)
        _atomic_write(path, current)
        return current


__all__ = ["ConfigUnreadable", "read", "update"]
