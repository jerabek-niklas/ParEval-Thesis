"""Crash-safe file writes (pilot_002 pre-run wave).

Every artifact a later stage or a verifier trusts - generated-code.hpp,
assembly.jsonl, run-manifest fragments, verification reports - is written
as: temp file in the SAME directory -> flush -> fsync -> os.replace. A reader
therefore sees either the complete previous file or the complete new one,
never a torn one, and a crash leaves at most a ``*.tmp-<pid>`` file that no
consumer reads.

Text writes deliberately keep ``newline=None`` (the interpreter's universal
newline translation, LF -> os.linesep), i.e. EXACTLY the behaviour of
Path.write_text that the legacy assembly writer used: this wave measures and
documents that host dependence, it does not silently change it.

Python 3.8 compatible.
"""
from __future__ import annotations

import binascii
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

TEMP_MARKER = ".tmp-"


def _tmp_path(target: Path) -> Path:
    """Temp name of ONE write attempt.

    It must be unique across every writer that can see this directory - and a
    PID is NOT: the pipeline runs stages in separate containers on one mounted
    output tree, where each `docker run python3 ...` is PID 1, so two writers
    would pick the same temp path for the same target and one of them would
    fsync/replace a file the other had already renamed away (FileNotFoundError
    mid-registration). PID + thread id + 6 random bytes is unique per attempt
    while keeping the `.tmp-` marker that readers and the stale-temp cleanup
    recognise."""
    token = binascii.hexlify(os.urandom(6)).decode("ascii")
    return target.with_name("%s%s%d-%d-%s" % (target.name, TEMP_MARKER, os.getpid(),
                                              threading.get_ident() & 0xFFFF, token))


REPLACE_ATTEMPTS = 40
REPLACE_BACKOFF_SECONDS = 0.02


def _replace(tmp: Path, target: Path) -> None:
    """os.replace with a bounded retry.

    On Windows the rename fails with a sharing violation (WinError 5 / 32)
    while ANOTHER writer or reader holds the target open - which happens
    routinely when several stages rewrite the same derived file. POSIX
    replaces are atomic and never hit this path; the retry is bounded so a
    genuinely locked file still raises."""
    last = None
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, target)
            return
        except PermissionError as exc:  # Windows sharing violation
            last = exc
            time.sleep(REPLACE_BACKOFF_SECONDS)
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (5, 32):
                raise
            last = exc
            time.sleep(REPLACE_BACKOFF_SECONDS)
    try:
        tmp.unlink()
    except OSError:
        pass
    raise last


def atomic_write_bytes(target: Path, data: bytes) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(target)
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    _replace(tmp, target)


def atomic_write_text(target: Path, text: str, encoding: str = "utf-8",
                      newline: "Any" = None) -> None:
    """Text-mode atomic write. ``newline=None`` reproduces Path.write_text
    (host-dependent line terminator); pass an explicit LF only where a
    caller owns an LF policy."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(target)
    with open(tmp, "w", encoding=encoding, newline=newline) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    _replace(tmp, target)


def atomic_write_json(target: Path, payload: Any, indent: int = 2) -> None:
    """JSON artifacts are written with explicit LF so their raw bytes (and
    hence any raw artifact hash over them) are host-independent."""
    text = json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"
    atomic_write_bytes(target, text.encode("utf-8"))


def atomic_write_jsonl(target: Path, records: Iterable[Any]) -> None:
    """One JSON object per line, LF-terminated, same serialization as
    thesis.generation.common.append_jsonl (ensure_ascii=False)."""
    lines = [json.dumps(record, ensure_ascii=False) + "\n" for record in records]
    atomic_write_bytes(target, "".join(lines).encode("utf-8"))


def remove_stale_temp_files(directory: Path) -> int:
    """Remove ``*.tmp-<pid>-<tid>-<token>`` leftovers of crashed writers.

    A concurrent writer's temp file may vanish (renamed into place) between
    listing and unlinking - that is not an error."""
    directory = Path(directory)
    removed = 0
    if not directory.is_dir():
        return 0
    for candidate in sorted(directory.iterdir()):
        if candidate.is_file() and TEMP_MARKER in candidate.name:
            try:
                candidate.unlink()
            except OSError:
                continue
            removed += 1
    return removed
