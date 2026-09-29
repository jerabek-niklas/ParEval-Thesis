"""Explicit, read-only recovery references. No discovery fallback or file writes.

The manifest is a definition, not authorization. A valid definition alone must
never enable a productive runner. Paths are repo-relative and content-addressed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from thesis.evaluation.condition_hashing import canonical_sha256

PARENT = "full_ext_001"
RECOVERY = "full_ext_recovery_001"
PILOT = "pilot_002"
VARIANTS = ("static_feedback", "test_feedback", "combined_feedback")
REUSED = ("generation", "assembly", "static", "correctness", "dynamic")
OWNERSHIP = {**{s: PARENT for s in REUSED},
             **{s: RECOVERY for s in ("repair", "enhanced", "backfill")}}
SCHEMA = "recovery_lineage.v1"


class RecoveryRefused(ValueError):
    pass


def fingerprint(document, field="lineage_sha256"):
    return canonical_sha256({k: v for k, v in document.items() if k != field})


def checked_path(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise RecoveryRefused("expected canonical repo-relative path")
    path = Path(relative)
    if path.is_absolute() or ":" in relative or any(p in ("..", ".") for p in relative.split("/")):
        raise RecoveryRefused("path escapes declared repository")
    candidate = root / path
    for parent in (candidate, *candidate.parents):
        if parent == root:
            break
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            raise RecoveryRefused("symlink/junction evidence is forbidden")
    if root not in candidate.resolve().parents:
        raise RecoveryRefused("path outside repository")
    return candidate


@dataclass(frozen=True)
class ParentEvidenceRef:
    path: str
    raw_sha256: str
    size: int
    stage: str
    source_run: str
    model_id: Optional[str] = None
    record_count: Optional[int] = None
    record_identities_sha256: Optional[str] = None

    def verify(self, root):
        path = checked_path(root, self.path)
        allowed = ("thesis/results/raw/" + PARENT + "/",
                   "thesis/results/intermediate/" + PARENT + "/")
        if self.source_run != PARENT or not self.path.startswith(allowed):
            raise RecoveryRefused("foreign or historical repair evidence reference")
        if not path.is_file():
            raise RecoveryRefused("missing parent artifact: " + self.path)
        data = path.read_bytes()
        if len(data) != self.size or hashlib.sha256(data).hexdigest() != self.raw_sha256:
            raise RecoveryRefused("parent artifact drift: " + self.path)
        return path


@dataclass(frozen=True)
class StageOwnership:
    candidate_run: str
    writer_run: str
    authority_run: str
    stage: str


class RecoveryLineage:
    def __init__(self, root, document, expected_sha):
        self.root = Path(root).resolve()
        self._document = copy.deepcopy(document)
        d = self._document
        if (not expected_sha or d.get("lineage_sha256") != expected_sha
                or fingerprint(d) != expected_sha or d.get("schema_version") != SCHEMA):
            raise RecoveryRefused("unbound/tampered lineage manifest")
        if (d.get("run_id") != RECOVERY or d.get("parent_run_id") != PARENT
                or d.get("pilot_run_id") != PILOT or d.get("stage_ownership") != OWNERSHIP
                or d.get("recovery_base_cells") != 0
                or d.get("historical_repair_policy") != "EXCLUDE_ALL_PARENT_REPAIR"):
            raise RecoveryRefused("invalid recovery ownership/policy")
        rows = d.get("artifacts")
        if not isinstance(rows, list) or not rows:
            raise RecoveryRefused("empty parent inventory")
        self.refs = {}
        try:
            for row in rows:
                ref = ParentEvidenceRef(**row)
                if ref.path in self.refs:
                    raise RecoveryRefused("duplicate artifact reference")
                self.refs[ref.path] = ref
        except TypeError as error:
            raise RecoveryRefused("invalid inventory entry") from error
        if list(self.refs) != sorted(self.refs):
            raise RecoveryRefused("inventory must have deterministic path ordering")

    @classmethod
    def load(cls, root, relative, expected_sha):
        return cls(root, json.loads(checked_path(root, relative).read_text(encoding="utf-8")), expected_sha)

    @property
    def document(self):
        return copy.deepcopy(self._document)

    def verify_artifacts(self):
        for ref in self.refs.values():
            ref.verify(self.root)

    def read_path(self, relative):
        ref = self.refs.get(relative)
        if ref is None or ref.stage == "historical_only":
            raise RecoveryRefused("unregistered source; implicit fallback forbidden: " + relative)
        return ref.verify(self.root)

    def iteration_run(self, variant, iteration):
        if variant not in VARIANTS or type(iteration) is not int or iteration < 0:
            raise RecoveryRefused("invalid recovery iteration")
        maximum = self._document.get("max_iterations")
        if type(maximum) is not int or iteration > maximum:
            raise RecoveryRefused("iteration outside bound contract")
        return RECOVERY if iteration == 0 else "%s__%s__iter%d" % (RECOVERY, variant, iteration)

    def resolve(self, stage, variant, iteration):
        target = self.iteration_run(variant, iteration)
        if stage not in OWNERSHIP:
            raise RecoveryRefused("unknown stage")
        if iteration == 0 and stage in REUSED:
            # None of these stages is writable through a recovery reference.
            return StageOwnership(PARENT, "", RECOVERY, stage)
        return StageOwnership(PARENT if iteration == 0 else target, target, RECOVERY, stage)

    def assert_writer(self, run_id, stage, variant, iteration):
        owner = self.resolve(stage, variant, iteration)
        if not owner.writer_run or run_id != owner.writer_run:
            raise RecoveryRefused("write outside recovery stage ownership")
        return owner

    def envelope(self, stage, record, source_run, variant, iteration):
        owner = self.resolve(stage, variant, iteration)
        expected = PARENT if iteration == 0 and stage in REUSED else owner.writer_run
        if not expected or source_run != expected or record.get("run_id") != source_run:
            raise RecoveryRefused("native source identity mismatch")
        return {"source_run": source_run, "stage": stage, "record": copy.deepcopy(record)}


def reject_historical_response(record):
    run = record.get("run_id", "")
    if not isinstance(run, str) or not re.fullmatch(
            re.escape(RECOVERY) + r"__(static_feedback|test_feedback|combined_feedback)__iter[1-9][0-9]*", run):
        raise RecoveryRefused("historical/foreign repair response adoption forbidden")


def compare_requests(derived, historical):
    """Compare methodical request content only; never adopt historical responses."""
    fields = ("model_id", "sample_id", "variant", "iteration", "built_from_iteration", "strategy", "request")
    def projection(rows):
        result = {}
        for row in rows:
            if any(k not in row for k in fields) or row["sample_id"] in result:
                raise RecoveryRefused("missing/duplicate request identity")
            result[row["sample_id"]] = tuple(row[k] for k in fields)
        return result
    if projection(derived) != projection(historical):
        raise RecoveryRefused("freshly derived request set/content differs from historical requests")


def require_complete_loop(states, expected_ids, terminal_statuses):
    ids = [s.get("sample_id") for s in states]
    if len(ids) != len(set(ids)) or set(ids) != set(expected_ids):
        raise RecoveryRefused("incomplete/duplicate loop sample set")
    if any(s.get("run_id") != RECOVERY or s.get("status") not in terminal_statuses for s in states):
        raise RecoveryRefused("foreign/active recovery loop; enhanced forbidden")
