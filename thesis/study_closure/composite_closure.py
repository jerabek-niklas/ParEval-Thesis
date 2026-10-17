"""Guarded persistence of the final composite (study closure, --write only).

The composite document (pc.composite_document, 'phase2_composite.v1') is
the one artifact the closure writes into a results tree: into the phase-2
tree, through the phase-2 writer (pc.write_document -> atomic_io), under
the phase-2 successor writer lock. Everything here is a precondition of
that single write:

  * the target is exactly core.COMPOSITE_REL and pl.require_writable accepts
    it (inside the phase-2 tree, never inside a protected tree);
  * no successor writer lock of ANY run exists (except the one this module
    holds itself while writing);
  * the phase-2 manifest is complete and the last invocation of every
    phase-2 stage is 'completed' with no open item (the composite is a view
    of a finished run);
  * an existing composite must be byte-identical to what would be written:
    a different composite is never overwritten (the caller reports it);
  * (in study.persisted_check, which calls the hook) every closure check
    that precedes the persistence passed: the composite of a failed closure
    is never materialised, whatever the state of the tree.

persist_composite writes, reads the bytes back and verifies the self-hash;
the raw bytes of two writes of the same document are identical because
atomic_write_json serialises deterministically (indent 2, ensure_ascii
False, LF).

Python 3.8 compatible syntax.
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import successor_writer as sw
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import lineage as pl
from thesis.study_closure import core
from thesis.study_closure.core import ClosureRefused

LOCK_PURPOSE = "study_closure_composite"
MANIFEST_REL = core.PHASE2_RESULTS_REL + "/run_manifest.json"
STAGE_INVOCATIONS_REL = core.PHASE2_RESULTS_REL + "/phase2_stage_invocations.jsonl"
STATUS_INVOKED = "invoked"
STATUS_COMPLETED = "completed"


def document_bytes(document):
    """Exactly the bytes pc.write_document persists (atomic_io.atomic_write_json:
    indent 2, ensure_ascii False, one trailing LF, UTF-8) - the idempotence
    comparison and the read-back check rely on this rule."""
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def writer_locks(root):
    """Names of every successor writer lock file (any run)."""
    directory = Path(root) / sw.LOCK_DIR
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.glob("*.lock") if p.is_file())


def manifest_state(root):
    """run_id / complete / fragment findings of the phase-2 run manifest
    (missing -> refused)."""
    manifest = core.read_json(root, MANIFEST_REL)
    return OrderedDict([("run_id", manifest.get("run_id")), ("complete", manifest.get("complete")),
                        ("contract_sha256", manifest.get("contract_sha256")),
                        ("missing_expected_fragments", manifest.get("missing_expected_fragments")),
                        ("unexpected_fragments", manifest.get("unexpected_fragments"))])


def stage_invocation_rows(root):
    """Rows of the phase-2 stage invocation log (missing -> refused, torn -> refused)."""
    path = checked_path(Path(root).resolve(), STAGE_INVOCATIONS_REL)
    if not path.is_file():
        raise ClosureRefused("missing artifact: " + STAGE_INVOCATIONS_REL)
    return core.read_jsonl(root, STAGE_INVOCATIONS_REL)


def last_stage_status(rows, stages=pl.STAGES):
    """stage -> {status, open_items} of the LAST log row of each stage (None
    when a stage was never logged). A foreign row or an unknown stage
    refuses (same fail-closed rule as study.stage_history)."""
    last = OrderedDict((stage, None) for stage in stages)
    for row in rows:
        if row.get("run_id") != core.PHASE2:
            raise ClosureRefused("foreign stage invocation row (run_id %r)" % row.get("run_id"))
        stage = row.get("stage")
        if stage not in last:
            raise ClosureRefused("unknown stage %r in the invocation log" % stage)
        last[stage] = OrderedDict([("status", row.get("status")), ("open_items", row.get("open_items"))])
    return last


def open_stages(last):
    """Stages whose last invocation is not 'completed' with no open item."""
    return [stage for stage, entry in last.items()
            if entry is None or entry.get("status") != STATUS_COMPLETED or entry.get("open_items") != []]


def composite_write_allowed(root, document=None, relative=core.COMPOSITE_REL, own_lock=None):
    """Ownership / state facts of the composite target; raises ClosureRefused
    on any reason not to write. own_lock: the WriterLock this process holds
    (its file is the only lock tolerated, and it must carry our token)."""
    root = Path(root).resolve()
    if relative != core.COMPOSITE_REL:
        raise ClosureRefused("the closure persists only %s (refused: %s)" % (core.COMPOSITE_REL, relative))
    path = pl.require_writable(root, relative)
    locks = writer_locks(root)
    own = own_lock.path.name if (own_lock is not None and own_lock.token) else None
    foreign = [name for name in locks if name != own]
    if foreign:
        raise ClosureRefused("successor writer lock(s) present: %s" % foreign)
    if own is not None:
        current = sw.read_lock(own_lock.path)
        if not current or current.get("unreadable") or current.get("token") != own_lock.token:
            raise ClosureRefused("the closure's own writer lock is not held")
    manifest = manifest_state(root)
    missing, unexpected = manifest["missing_expected_fragments"], manifest["unexpected_fragments"]
    # a manifest that says complete but lists missing or unexpected
    # fragments is contradictory (merge_fragments derives complete from
    # missing == []): refused, never trusted
    if (manifest["run_id"] != core.PHASE2 or manifest["complete"] is not True or missing != []
            or unexpected not in (None, [])):
        raise ClosureRefused("the phase-2 run manifest is not complete (run_id %r, complete %r, missing fragments "
                             "%r, unexpected fragments %r)" % (manifest["run_id"], manifest["complete"],
                                                               missing, unexpected))
    last = last_stage_status(stage_invocation_rows(root))
    pending = open_stages(last)
    if pending:
        raise ClosureRefused("phase-2 stages without a completed last invocation: %s" % pending)
    exists = path.is_file()
    existing_sha = None
    identical = None
    if exists:
        data = path.read_bytes()
        existing_sha = hashlib.sha256(data).hexdigest()
        if document is not None:
            identical = data == document_bytes(document)
            if not identical:
                raise ClosureRefused("a different composite is already persisted at %s (raw sha256 %s); "
                                     "the closure never overwrites it" % (relative, existing_sha))
    return OrderedDict([
        ("relative", relative), ("exists", exists), ("raw_sha256", existing_sha), ("identical", identical),
        ("manifest_complete", True), ("missing_expected_fragments", missing), ("unexpected_fragments", unexpected),
        ("stages_completed", list(last)), ("writer_locks", locks),
    ])


def persist_composite(root, document, log=None):
    """Write the composite under the phase-2 writer lock (idempotent: an
    identical persisted composite is left alone, written=False) and verify
    the read-back bytes and self-hash."""
    root = Path(root).resolve()
    log = log or (lambda message: None)
    pc.verify_document(document)
    expected = document_bytes(document)
    # every guard runs before the lock is taken, and a lock that appears in
    # between refuses with the lock NAME only (successor_writer's message
    # carries the absolute path, pid, host and time - not for a report)
    composite_write_allowed(root, document)
    lock = sw.WriterLock(root, core.PHASE2, LOCK_PURPOSE)
    try:
        lock.acquire()
    except RecoveryRefused:
        raise ClosureRefused("successor writer lock present: %s" % lock.path.name)
    try:
        state = composite_write_allowed(root, document, own_lock=lock)
        written = False
        if not state["identical"]:
            log("persisting the composite at %s" % core.COMPOSITE_REL)
            pc.write_document(root, document)
            written = True
        data = checked_path(root, core.COMPOSITE_REL).read_bytes()
    finally:
        lock.release()
    loaded = json.loads(data.decode("utf-8"), object_pairs_hook=OrderedDict)
    pc.verify_document(loaded)
    if data != expected or loaded.get("composite_sha256") != document.get("composite_sha256"):
        raise ClosureRefused("the persisted composite read back differs from the document")
    return OrderedDict([
        ("relative", core.COMPOSITE_REL), ("raw_sha256", hashlib.sha256(data).hexdigest()),
        ("composite_sha256", loaded["composite_sha256"]), ("bytes", len(data)), ("written", written),
    ])
