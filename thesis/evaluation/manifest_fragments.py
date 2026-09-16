"""Per-writer run-manifest fragments (pilot_002 pre-run wave, block G).

The run manifest used to be ONE shared JSON that every stage read, modified
and rewrote (read-modify-write). With parallel per-model terminals and
containers on one mounted output tree that is a lost-update hazard: two
registrations that interleave keep only the last writer's view.

Architecture here: every registration writes ITS OWN fragment file, once,
atomically, into

    <intermediate_dir>/<run_id>/run_manifest.fragments/<kind>[.<owner>].json

    global.json                 frozen run configuration (first contact)
    enrichment.<field>.json     prompt_selection / enhanced_policy / enhanced_specs
    drift.<stage>.<sha12>.json  one recorded config drift (content-keyed)
    enhanced_execution.json     the run-global enhanced execution fingerprint
    enhanced.<model_id>.json    per-model enhanced execution fingerprint
    static.condition.json       static_analysis_condition
    repair.condition.json       repair_condition
    assembly.<model_id>.json    per-model assembly set fingerprint
    runtime.evidence.json       T0 runtime evidence (image/tool identities)
    contract.json               frozen pilot run contract sha

Rules:
  * one owner per fragment; a fragment is never read-modified-written
  * a registration with the SAME key and the SAME fingerprint is idempotent
  * the SAME key with a DIFFERENT fingerprint is a HARD FAIL (FragmentConflict)
  * the merged manifest is a deterministic, read-only function of the
    fragment set; run_manifest.json is written as that merged snapshot
    after every registration (a convenience copy - `merge` is the truth)
  * an expected-but-missing fragment makes the merge INCOMPLETE; an
    unexpected fragment is reported, never silently absorbed
  * an optional append-only history (history/<fragment>.<utc>.<pid>.json)
    records every registration attempt; it is not part of any condition

Python 3.8 compatible.
"""
from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from thesis.evaluation import atomic_io
from thesis.evaluation.condition_hashing import canonical_sha256

FRAGMENTS_DIR_NAME = "run_manifest.fragments"
HISTORY_DIR_NAME = "history"
FRAGMENT_SCHEMA_VERSION = "run_manifest_fragment.v1"
MERGED_SCHEMA_VERSION = "run_manifest_merged.v1"
MANIFEST_NAME = "run_manifest.json"

_SAFE = re.compile(r"[^A-Za-z0-9_.@+-]")


class FragmentConflict(RuntimeError):
    """Same fragment key, different fingerprint under one run_id."""


class FragmentIncomplete(RuntimeError):
    """An expected fragment is missing from the run."""


def _safe(name: str) -> str:
    return _SAFE.sub("_", str(name))


def fragments_dir(intermediate_dir: Path, run_id: str) -> Path:
    return Path(intermediate_dir) / run_id / FRAGMENTS_DIR_NAME


def fragment_name(kind: str, owner: "Optional[str]" = None) -> str:
    if owner is None:
        return "%s.json" % _safe(kind)
    return "%s.%s.json" % (_safe(kind), _safe(owner))


def fragment_path(intermediate_dir: Path, run_id: str, kind: str,
                  owner: "Optional[str]" = None) -> Path:
    return fragments_dir(intermediate_dir, run_id) / fragment_name(kind, owner)


def uses_fragments(intermediate_dir: Path, run_id: str) -> bool:
    """A run is fragment-based when its fragments dir exists, or when it has
    no manifest at all yet (every NEW run is fragment-based). A run with a
    legacy run_manifest.json and no fragments dir (pilot_001) stays a legacy
    shared-manifest run: it is never migrated in place."""
    if fragments_dir(intermediate_dir, run_id).is_dir():
        return True
    return not (Path(intermediate_dir) / run_id / MANIFEST_NAME).is_file()


def _utc_now() -> str:
    from thesis.generation.common import utc_now_iso

    return utc_now_iso()


def _read(path: Path) -> "Dict[str, Any]":
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# registration (one writer, one file)
# ---------------------------------------------------------------------------

def register_fragment(intermediate_dir: Path, run_id: str, kind: str,
                      owner: "Optional[str]", content: "Dict[str, Any]",
                      fingerprint: "Optional[str]" = None,
                      writer: "Optional[str]" = None,
                      history: bool = True) -> "Dict[str, Any]":
    """Write one fragment atomically.

    fingerprint defaults to the canonical sha256 of `content`. An existing
    fragment with the same fingerprint makes this a no-op (idempotent); a
    different fingerprint raises FragmentConflict BEFORE anything is
    written. Returns the fragment as stored.
    """
    if fingerprint is None:
        fingerprint = canonical_sha256(content)
    path = fragment_path(intermediate_dir, run_id, kind, owner)
    fragment = OrderedDict([
        ("schema_version", FRAGMENT_SCHEMA_VERSION),
        ("run_id", run_id),
        ("kind", kind),
        ("owner", owner),
        ("fingerprint_sha256", fingerprint),
        # the FULL content, volatile fields included: a hand edit of a field
        # the methodical fingerprint leaves out (e.g. authorized_at_utc) is
        # still detected by verify_fragment_integrity
        ("content_sha256", canonical_sha256(content)),
        ("registered_at_utc", _utc_now()),
        ("writer", writer),
        ("content", content),
    ])

    outcome = "created"
    # Exclusive section per fragment key: two processes that register the
    # same key at the same instant must not both believe they created it
    # (the loser's os.replace would silently overwrite the winner's file).
    # mkdir is atomic and exclusive on every filesystem the pipeline runs on
    # (NTFS, ext4, the WSL2/DrvFS bind mount); the section holds for
    # milliseconds, so a lock older than LOCK_STALE_SECONDS belongs to a
    # crashed writer and is taken over.
    with _exclusive(path):
        if path.is_file():
            existing = _read(path)
            if existing.get("run_id") != run_id:
                raise FragmentConflict(
                    "fragment %s belongs to run %r, not %r" % (path, existing.get("run_id"), run_id))
            if existing.get("fingerprint_sha256") == fingerprint:
                outcome = "idempotent"
                fragment = existing
            else:
                _append_history(intermediate_dir, run_id, kind, owner, fragment, "REFUSED",
                                history)
                raise FragmentConflict(
                    "run %s already registers %s = %s... but this invocation computes "
                    "%s.... The same run must not carry two conditions for one key; "
                    "use a fresh run_id." % (run_id, fragment_name(kind, owner),
                                             str(existing.get("fingerprint_sha256"))[:12],
                                             fingerprint[:12]))

        if outcome == "created":
            atomic_io.atomic_write_json(path, fragment)
            # verify what landed, never assume
            stored = _read(path)
            if stored.get("fingerprint_sha256") != fingerprint:
                _append_history(intermediate_dir, run_id, kind, owner, fragment, "REFUSED",
                                history)
                raise FragmentConflict(
                    "run %s: registration of %s did not land (%s... on disk vs %s...)"
                    % (run_id, fragment_name(kind, owner),
                       str(stored.get("fingerprint_sha256"))[:12], fingerprint[:12]))
    _append_history(intermediate_dir, run_id, kind, owner, fragment, outcome, history)
    return fragment


LOCK_STALE_SECONDS = 10.0
LOCK_WAIT_SECONDS = 30.0


class _exclusive:
    """mkdir-based exclusive section for one fragment path."""

    def __init__(self, path: Path) -> None:
        self.lock = path.with_name(path.name + ".lock")

    def __enter__(self) -> "_exclusive":
        import time

        self.lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                self.lock.mkdir()
                return self
            except PermissionError as error:
                # Windows: a concurrent rmdir/mkdir of the SAME lock directory
                # fails with a sharing violation (WinError 5 / 32) instead of
                # FileExistsError. Measured at ~1.4% with six processes
                # registering one key. Retrying is the same bounded policy
                # atomic_io._replace already uses for renames; without it a
                # concurrent per-model start would die with an UNCLASSIFIED
                # PermissionError that the orchestrator reads as a model
                # failure. POSIX never takes this path.
                if getattr(error, "winerror", None) not in (None, 5, 32):
                    raise
                if time.monotonic() > deadline:
                    raise FragmentConflict(
                        "could not acquire the registration lock %s within %.0fs (%s)"
                        % (self.lock, LOCK_WAIT_SECONDS, error))
                time.sleep(0.005)
            except FileExistsError:
                try:
                    age = time.time() - self.lock.stat().st_mtime
                except OSError:
                    continue  # vanished between the failed mkdir and stat
                if age > LOCK_STALE_SECONDS:
                    try:
                        self.lock.rmdir()  # crashed writer; take over
                    except OSError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise FragmentConflict(
                        "could not acquire the registration lock %s within %.0fs"
                        % (self.lock, LOCK_WAIT_SECONDS))
                time.sleep(0.005)

    def __exit__(self, *exc: Any) -> None:
        try:
            self.lock.rmdir()
        except OSError:
            pass


def _append_history(intermediate_dir: Path, run_id: str, kind: str,
                    owner: "Optional[str]", fragment: "Dict[str, Any]",
                    outcome: str, enabled: bool) -> None:
    if not enabled:
        return
    directory = fragments_dir(intermediate_dir, run_id) / HISTORY_DIR_NAME
    stamp = _utc_now().replace(":", "").replace("-", "").replace("+", "")
    name = "%s.%s.%d.json" % (fragment_name(kind, owner)[:-5], stamp, os.getpid())
    record = OrderedDict(list(fragment.items()) + [("outcome", outcome)])
    try:
        atomic_io.atomic_write_json(directory / name, record)
    except OSError:
        pass  # history is best-effort evidence, never a gate


# ---------------------------------------------------------------------------
# reading / merging (deterministic, read-only)
# ---------------------------------------------------------------------------

def load_fragments(intermediate_dir: Path, run_id: str) -> "List[Tuple[str, Dict[str, Any]]]":
    directory = fragments_dir(intermediate_dir, run_id)
    if not directory.is_dir():
        return []
    result = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".json" or ".tmp-" in path.name:
            continue
        result.append((path.name, _read(path)))
    return result


def _split(name: str) -> "Tuple[str, Optional[str]]":
    stem = name[:-5] if name.endswith(".json") else name
    kind, _, owner = stem.partition(".")
    return kind, (owner or None)


def merge_fragments(intermediate_dir: Path, run_id: str,
                    expected: "Optional[Iterable[str]]" = None) -> "OrderedDict[str, Any]":
    """Deterministic merged view of one run's fragments.

    Top level keeps the LEGACY manifest shape (the global fragment's content
    is spread at top level, model_execution_fingerprints / condition fields
    are rebuilt from their fragments) so every existing consumer keeps
    working, plus a `fragments` section with the full per-fragment truth.

    `expected` (fragment file names) turns missing ones into
    `missing_expected_fragments`; fragments outside the known kinds are
    listed in `unexpected_fragments`. Nothing is written.
    """
    known_kinds = {"global", "enrichment", "drift", "enhanced_execution", "enhanced",
                   "static", "repair", "assembly", "runtime", "contract",
                   "authorization", "invocation"}
    fragments = load_fragments(intermediate_dir, run_id)
    names = [name for name, _ in fragments]

    merged: "OrderedDict[str, Any]" = OrderedDict()
    merged["schema_version"] = MERGED_SCHEMA_VERSION
    merged["run_id"] = run_id

    by_kind: "Dict[str, List[Tuple[Optional[str], Dict[str, Any]]]]" = {}
    unexpected = []
    for name, fragment in fragments:
        kind, owner = _split(name)
        if fragment.get("run_id") != run_id:
            raise FragmentConflict("fragment %s belongs to run %r" % (name, fragment.get("run_id")))
        if kind not in known_kinds:
            unexpected.append(name)
            continue
        by_kind.setdefault(kind, []).append((owner, fragment))

    global_fragments = by_kind.get("global", [])
    if global_fragments:
        merged.update(global_fragments[0][1]["content"])
    for owner, fragment in by_kind.get("enrichment", []):
        merged[owner] = fragment["content"].get(owner)
    drift = []
    for owner, fragment in by_kind.get("drift", []):
        drift.append(fragment["content"])
    drift.sort(key=lambda d: (str(d.get("detected_at_utc")), str(d.get("stage"))))
    merged["config_drift"] = drift
    for owner, fragment in by_kind.get("enhanced_execution", []):
        merged["enhanced_execution"] = fragment["content"]
    model_fps = OrderedDict()
    for owner, fragment in sorted(by_kind.get("enhanced", []), key=lambda x: str(x[0])):
        model_fps[owner] = fragment["fingerprint_sha256"]
    if model_fps:
        merged["model_execution_fingerprints"] = model_fps
    for kind, field in (("static", "static_analysis_condition"), ("repair", "repair_condition")):
        for owner, fragment in by_kind.get(kind, []):
            merged[field + "_sha256"] = fragment["fingerprint_sha256"]
            merged[field] = fragment["content"].get(field)
    sets = OrderedDict()
    for owner, fragment in sorted(by_kind.get("assembly", []), key=lambda x: str(x[0])):
        sets[owner] = fragment["content"]
    if sets:
        merged["assembly_model_sets"] = sets
        shas = {s.get("assembly_condition_sha256") for s in sets.values()}
        merged["assembly_condition_sha256"] = sorted(shas)[0] if len(shas) == 1 else None
        if len(shas) > 1:
            merged["assembly_condition_conflict"] = sorted(str(s) for s in shas)
    # runtime fragments: the T0 evidence (owner "evidence") and the per-stage
    # stamps (owner "stage.<name>") are different evidence and never merge
    stage_runtime = OrderedDict()
    for owner, fragment in sorted(by_kind.get("runtime", []), key=lambda x: str(x[0])):
        if owner == "evidence":
            merged["runtime_evidence"] = fragment["content"]
            merged["runtime_evidence_sha256"] = fragment["fingerprint_sha256"]
        else:
            stage_runtime[owner] = fragment["content"]
    if stage_runtime:
        merged["stage_runtime_evidence"] = stage_runtime
    for owner, fragment in by_kind.get("contract", []):
        # the fragment wraps {contract_sha256, contract}: consumers want the
        # CONTRACT itself under "contract", exactly as the frozen file has it
        content = fragment["content"] or {}
        merged["contract"] = content.get("contract", content)
        merged["contract_sha256"] = fragment["fingerprint_sha256"]
    for owner, fragment in by_kind.get("authorization", []):
        merged["authorization"] = fragment["content"]
        merged["authorization_sha256"] = fragment["fingerprint_sha256"]
    invocations = OrderedDict()
    for owner, fragment in sorted(by_kind.get("invocation", []), key=lambda x: str(x[0])):
        invocations[owner] = fragment["content"]
    if invocations:
        merged["stage_invocations"] = invocations

    missing = []
    if expected is not None:
        present = set(names)
        missing = sorted(set(expected) - present)

    merged["fragments"] = OrderedDict(
        (name, OrderedDict([("kind", fragment.get("kind")), ("owner", fragment.get("owner")),
                            ("fingerprint_sha256", fragment.get("fingerprint_sha256")),
                            ("registered_at_utc", fragment.get("registered_at_utc"))]))
        for name, fragment in fragments)
    merged["unexpected_fragments"] = unexpected
    merged["missing_expected_fragments"] = missing
    merged["complete"] = not missing
    merged["fragment_set_sha256"] = canonical_sha256(
        [(name, fragment.get("fingerprint_sha256")) for name, fragment in fragments])
    return merged


def write_snapshot(intermediate_dir: Path, run_id: str) -> Path:
    """run_manifest.json = merged snapshot. Regenerated after each
    registration; a concurrent registration that lands between listing and
    writing is caught by re-listing and regenerating (bounded)."""
    target = Path(intermediate_dir) / run_id / MANIFEST_NAME
    for _ in range(4):
        before = merge_fragments(intermediate_dir, run_id)
        try:
            atomic_io.atomic_write_json(target, before)
        except OSError as exc:
            # The snapshot is DERIVED: the fragments are the truth and a
            # reader can always re-merge them. A writer must never fail its
            # registration because a concurrent writer held the snapshot.
            print("[run_manifest] snapshot not refreshed (%s); the fragments under %s "
                  "remain authoritative" % (exc, FRAGMENTS_DIR_NAME))
            return target
        after = merge_fragments(intermediate_dir, run_id)
        if after["fragment_set_sha256"] == before["fragment_set_sha256"]:
            break
    return target


def verify_fragment_integrity(intermediate_dir: Path, run_id: str) -> "List[Dict[str, Any]]":
    """Fragments whose stored fingerprint no longer matches their content.

    Registration fingerprints are either the canonical hash of the whole
    content or a caller-supplied METHODICAL subset hash (authorization, stage
    runtime, invocation). A hand edit of a methodical field therefore always
    shows up here; a hand edit of a purely volatile field never does, by
    design."""
    problems = []
    for name, fragment in load_fragments(intermediate_dir, run_id):
        content = fragment.get("content")
        stored = fragment.get("fingerprint_sha256")
        kind, owner = _split(name)
        if content is None or stored is None:
            problems.append({"fragment": name, "problem": "fragment without content or fingerprint"})
            continue
        content_stored = fragment.get("content_sha256")
        if content_stored is not None and content_stored != canonical_sha256(content):
            problems.append({"fragment": name,
                             "problem": "content does not match its registered content hash "
                                        "(a field was edited after registration)",
                             "stored": content_stored, "recomputed": canonical_sha256(content)})
        recomputed = _recompute_fingerprint(kind, owner, content)
        if recomputed is None:
            continue  # caller-supplied condition fingerprint: not recomputable here
        if recomputed != stored:
            problems.append({"fragment": name,
                             "problem": "content does not match the registered fingerprint",
                             "stored": stored, "recomputed": recomputed})
    return problems


def _recompute_fingerprint(kind: str, owner: "Optional[str]",
                           content: "Dict[str, Any]") -> "Optional[str]":
    """The fingerprint rule of the fragment kinds whose rule lives in this
    repository. Kinds whose fingerprint is a caller-supplied condition sha
    (static/repair/enhanced/assembly/global) are not independently
    recomputable and are skipped rather than falsely reported."""
    try:
        if kind == "authorization":
            from thesis.evaluation.run_authorization import authorization_fingerprint

            return authorization_fingerprint(content)
        if kind == "invocation":
            from thesis.evaluation.effective_invocation import invocation_fingerprint

            return invocation_fingerprint(content)
        if kind == "runtime" and owner and owner.startswith("stage."):
            from thesis.evaluation.stage_runtime import _evidence_fingerprint

            return _evidence_fingerprint(content)
        if kind == "runtime" and owner == "evidence":
            from thesis.evaluation.run_authorization import t0_evidence_fingerprint

            if content.get("evidence_version", "").startswith("t0_runtime_evidence.v2"):
                return t0_evidence_fingerprint(content)
            return canonical_sha256(content)
        if kind == "contract":
            return content.get("contract_sha256")
    except Exception:  # noqa: BLE001 - an unverifiable fragment is not a false FAIL
        return None
    return None


def merge_is_deterministic(intermediate_dir: Path, run_id: str) -> bool:
    a = json.dumps(merge_fragments(intermediate_dir, run_id), sort_keys=True)
    b = json.dumps(merge_fragments(intermediate_dir, run_id), sort_keys=True)
    return a == b
