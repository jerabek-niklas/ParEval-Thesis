"""Single-writer lock and durable append helpers for successor runs.

The repair state machine itself has no process lock (orchestrator.py). A
successor run therefore holds ONE exclusive writer lock for its whole
productive invocation. The lock is never taken over automatically: a lock
left behind by a crashed process refuses the next start until an operator
has verified that no writer is alive and removed it explicitly.

Tool containers started by the lock holder receive the lock token on their
command line; they refuse to write unless the lock file carries exactly that
token (so a container launched by hand cannot write into the successor run).

Python 3.8 compatible (imported inside the LLOV container).
"""
from __future__ import annotations

import json
import os
import platform
import secrets
import time
from pathlib import Path

from thesis.evaluation.recovery_lineage import RecoveryRefused

LOCK_SCHEMA = "successor_writer_lock.v1"
LOCK_DIR = "thesis/results/intermediate/.successor_locks"
# the lock holder's token travels to its own process environment and to its
# tool containers in this variable (never on a command line)
TOKEN_ENV = "PAREVAL_SUCCESSOR_TOKEN"


def lock_path(root, run_id):
    if not run_id or "/" in run_id or "\\" in run_id or run_id.startswith("."):
        raise RecoveryRefused("invalid run id for a writer lock")
    return Path(root) / LOCK_DIR / ("%s.writer.lock" % run_id)


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class WriterLock:
    """O_EXCL lock file; acquire() refuses if any lock exists (no stale takeover)."""

    def __init__(self, root, run_id, purpose):
        self.path = lock_path(root, run_id)
        self.run_id = run_id
        self.purpose = purpose
        self.token = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(16)
        payload = {
            "schema_version": LOCK_SCHEMA, "run_id": self.run_id, "purpose": self.purpose,
            "token": token, "pid": os.getpid(), "hostname": platform.node(),
            "acquired_at_utc": _utc_now(),
        }
        try:
            descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise RecoveryRefused(
                "another successor writer holds %s (%s). Verify that no successor process or "
                "tool container is still running, then remove the lock file explicitly."
                % (self.path, describe(self.path)))
        try:
            os.write(descriptor, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.token = token
        return token

    def release(self):
        if self.token is None:
            return
        current = read_lock(self.path)
        if current is not None and current.get("token") == self.token:
            self.path.unlink()
        self.token = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def read_lock(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"unreadable": True}


def describe(path):
    lock = read_lock(path)
    if not lock:
        return "no lock"
    if lock.get("unreadable"):
        return "unreadable lock file"
    return "pid %s on %s since %s (%s)" % (lock.get("pid"), lock.get("hostname"),
                                          lock.get("acquired_at_utc"), lock.get("purpose"))


def require_token(root, run_id, token):
    """A child process may only write while its parent's lock is held."""
    lock = read_lock(lock_path(root, run_id))
    if not lock or lock.get("unreadable") or not token or lock.get("token") != token:
        raise RecoveryRefused("no matching successor writer lock is held for %s; this process "
                              "may not write successor evidence" % run_id)
    return True


def tail_is_torn(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with path.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) != b"\n"


def archive_torn_tail(path):
    """Move a partially written last line (crash during append) into a sibling
    audit file and truncate the ledger to its last complete line. Returns the
    archived byte count (0 when the tail is complete)."""
    path = Path(path)
    if not tail_is_torn(path):
        return 0
    data = path.read_bytes()
    cut = data.rfind(b"\n") + 1
    torn = data[cut:]
    audit = path.with_name(path.name + ".torn")
    with audit.open("ab") as handle:
        handle.write(json.dumps({"archived_at_utc": _utc_now(), "bytes": len(torn),
                                 "text": torn.decode("utf-8", "replace")}).encode("utf-8") + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    with path.open("r+b") as handle:
        handle.truncate(cut)
        handle.flush()
        os.fsync(handle.fileno())
    return len(torn)


def durable_append_jsonl(path, record):
    """Append ONE JSON line and fsync it before returning (crash-durable).

    A torn tail refuses: it must be archived explicitly first, so a partial
    record can never be glued to the next one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if tail_is_torn(path):
        raise RecoveryRefused("torn last line in %s; archive it before appending" % path)
    # same byte format as the native ledgers (common.append_jsonl)
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    with path.open("ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def fsync_file(path):
    """Flush a file appended by a native writer to stable storage."""
    path = Path(path)
    if path.is_file():
        with path.open("ab") as handle:
            handle.flush()
            os.fsync(handle.fileno())


def read_jsonl(path):
    """Rows of a successor-owned JSONL; a torn tail or bad line refuses."""
    path = Path(path)
    if not path.is_file():
        return []
    if tail_is_torn(path):
        raise RecoveryRefused("torn last line in %s" % path)
    rows = []
    for number, line in enumerate(path.read_bytes().decode("utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            raise RecoveryRefused("undecodable line %d in %s" % (number, path))
        rows.append(row)
    return rows
