"""Read-only, hash-bound predecessor references for recovery successor 004.

This module grants NO execution authority. Native records are never rewritten.
A byte snapshot is necessary, but is not a substitute for trajectory validation.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

PREDECESSOR = "full_ext_recovery_001"
SUCCESSOR = "full_ext_recovery_004"
SCHEMA = "successor_handoff.v1"
VARIANTS = ("static_feedback", "test_feedback", "combined_feedback")
# file-system latency (not CPU) dominates on bind mounts: per-file checks run
# in a bounded thread pool; results are identical to the sequential order
IO_WORKERS = 16


def parallel_map(function, items):
    """list(map(function, items)) on IO_WORKERS threads (order preserved;
    the first exception propagates)."""
    from concurrent.futures import ThreadPoolExecutor

    items = list(items)
    if len(items) < 2:
        return [function(item) for item in items]
    with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
        return list(pool.map(function, items))


def iteration_run(base, variant, iteration, maximum):
    if base not in (PREDECESSOR, SUCCESSOR) or variant not in VARIANTS:
        raise RecoveryRefused("unregistered successor trajectory")
    if type(iteration) is not int or type(maximum) is not int or not 1 <= iteration <= maximum:
        raise RecoveryRefused("iteration outside inherited budget")
    return "%s__%s__iter%d" % (base, variant, iteration)


def predecessor_paths(root):
    """Enumerate only predecessor run trees; never .git, dependencies or secrets."""
    root = Path(root).resolve()
    result = []
    for area in ("raw", "intermediate"):
        directory = root / "thesis/results" / area
        if not directory.is_dir():
            continue
        for run in sorted(directory.iterdir()):
            if run.name != PREDECESSOR and not run.name.startswith(PREDECESSOR + "__"):
                continue
            checked_path(root, run.relative_to(root).as_posix())
            if not run.is_dir():
                raise RecoveryRefused("predecessor run is not a directory")
            relatives = [path.relative_to(root).as_posix() for path in run.rglob("*")]

            def classify(relative):
                return relative if checked_path(root, relative).is_file() else None

            result.extend(r for r in parallel_map(classify, relatives) if r is not None)
    return sorted(result)


def _allowed(relative):
    parts = relative.split("/")
    return (len(parts) >= 5 and parts[:2] == ["thesis", "results"]
            and parts[2] in ("raw", "intermediate")
            and (parts[3] == PREDECESSOR or parts[3].startswith(PREDECESSOR + "__")))


def build_snapshot(root):
    """Two-pass raw-byte snapshot. Caller must separately establish writer quiescence."""
    paths = predecessor_paths(root)
    if not paths:
        raise RecoveryRefused("missing predecessor evidence")
    files = {}
    for relative in paths:
        data = checked_path(root, relative).read_bytes()
        files[relative] = {"raw_sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    document = dict(schema_version=SCHEMA, source_run=PREDECESSOR, successor_run=SUCCESSOR,
                    status="BYTE_SNAPSHOT_NOT_EXECUTION_AUTHORITY", files=files)
    document["snapshot_sha256"] = canonical_sha256(document)
    Snapshot(root, document, document["snapshot_sha256"]).verify_all()
    return document


class Snapshot:
    def __init__(self, root, document, expected_sha):
        self.root = Path(root).resolve()
        self.document = copy.deepcopy(document)
        body = {k: v for k, v in document.items() if k != "snapshot_sha256"}
        if (not expected_sha or canonical_sha256(body) != expected_sha
                or document.get("snapshot_sha256") != expected_sha
                or document.get("schema_version") != SCHEMA
                or document.get("source_run") != PREDECESSOR
                or document.get("successor_run") != SUCCESSOR
                or document.get("status") != "BYTE_SNAPSHOT_NOT_EXECUTION_AUTHORITY"):
            raise RecoveryRefused("invalid successor snapshot binding")
        self.files = self.document.get("files")
        if not isinstance(self.files, dict) or not self.files:
            raise RecoveryRefused("empty successor snapshot")
        for relative, facts in self.files.items():
            if not _allowed(relative):
                raise RecoveryRefused("historical parent/foreign evidence cannot be adopted")
            checked_path(self.root, relative)
            if (set(facts) != {"raw_sha256", "size"} or type(facts["size"]) is not int
                    or facts["size"] < 0 or not isinstance(facts["raw_sha256"], str)
                    or len(facts["raw_sha256"]) != 64):
                raise RecoveryRefused("invalid artifact facts")

    def read_bytes(self, relative):
        if relative not in self.files:
            raise RecoveryRefused("unregistered predecessor artifact")
        data = checked_path(self.root, relative).read_bytes()
        expected = self.files[relative]
        if len(data) != expected["size"] or hashlib.sha256(data).hexdigest() != expected["raw_sha256"]:
            raise RecoveryRefused("predecessor artifact drift: " + relative)
        return data

    def verify_all(self):
        if predecessor_paths(self.root) != sorted(self.files):
            raise RecoveryRefused("predecessor inventory membership drift")
        parallel_map(lambda relative: self.read_bytes(relative) and None, sorted(self.files))
        return True

    def rows(self, relative, native_run, model):
        """Return lossless envelopes; duplicates require an explicit event-ledger reader."""
        if not _allowed(relative) or relative.split("/")[3] != native_run:
            raise RecoveryRefused("native source path/run mismatch")
        seen = set()
        result = []
        # split on the newline character only, like iterating a text-mode file (str.splitlines
        # would also split inside JSON strings at U+2028/U+2029/U+0085)
        for number, line in enumerate(self.read_bytes(relative).decode("utf-8").split("\n"), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            sample = row.get("sample_id")
            if (not isinstance(sample, str) or not sample or sample in seen
                    or row.get("run_id") != native_run
                    or row.get("model_id", (row.get("model") or {}).get("id")) != model):
                raise RecoveryRefused("duplicate/foreign predecessor record")
            seen.add(sample)
            result.append(dict(source_run=native_run, source_artifact=relative,
                               source_artifact_sha256=self.files[relative]["raw_sha256"],
                               source_line=number, record=row))
        return result


def predecessor_iteration_run(variant, iteration):
    """Native identity of a predecessor iteration run (1..2 only)."""
    return iteration_run(PREDECESSOR, variant, iteration, 2)


def repair_dir(model, variant, run=PREDECESSOR):
    if variant not in VARIANTS:
        raise RecoveryRefused("unregistered variant")
    return "thesis/results/intermediate/%s/%s/repair/%s" % (run, model, variant)


def iteration_dir(run, model, area="intermediate"):
    if area not in ("raw", "intermediate"):
        raise RecoveryRefused("unregistered result area")
    return "thesis/results/%s/%s/%s" % (area, run, model)


def _decode_lines(data, relative):
    """JSONL rows in file order; a torn or undecodable line refuses."""
    rows = []
    text = data.decode("utf-8")
    if text and not text.endswith("\n"):
        raise RecoveryRefused("torn last line in predecessor artifact: " + relative)
    for number, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            raise RecoveryRefused("undecodable line %d in %s" % (number, relative))
        if not isinstance(row, dict):
            raise RecoveryRefused("non-object line %d in %s" % (number, relative))
        rows.append(row)
    return rows


class PredecessorView:
    """Verified read-only access to predecessor artifacts.

    Every read goes through the bound Snapshot (size + raw sha256 on EVERY
    read); nothing here opens a predecessor file for writing and nothing here
    is ever handed to a mutating legacy loader."""

    def __init__(self, snapshot):
        if not isinstance(snapshot, Snapshot):
            raise RecoveryRefused("predecessor reads require a bound snapshot")
        self.snapshot = snapshot
        self.root = snapshot.root

    def has(self, relative):
        return relative in self.snapshot.files

    def sha256(self, relative):
        if relative not in self.snapshot.files:
            raise RecoveryRefused("unregistered predecessor artifact: " + relative)
        return self.snapshot.files[relative]["raw_sha256"]

    def read_bytes(self, relative):
        return self.snapshot.read_bytes(relative)

    def read_text(self, relative):
        return self.read_bytes(relative).decode("utf-8")

    def read_json(self, relative):
        return json.loads(self.read_text(relative))

    def jsonl(self, relative):
        return _decode_lines(self.read_bytes(relative), relative)

    def unique_rows(self, relative, native_run, model):
        """sample_id -> record; duplicates, foreign runs or models refuse."""
        rows = OrderedDict()
        for envelope in self.snapshot.rows(relative, native_run, model):
            rows[envelope["record"]["sample_id"]] = envelope["record"]
        return rows

    def event_ledger(self, model, variant):
        """The predecessor state.jsonl as an ORDERED event ledger.

        Duplicate sample ids are legitimate (one row per decision); every row
        must carry the predecessor base identity of exactly this loop."""
        relative = repair_dir(model, variant) + "/state.jsonl"
        rows = self.jsonl(relative)
        for row in rows:
            if (row.get("run_id") != PREDECESSOR or row.get("model_id") != model
                    or row.get("variant") != variant or not row.get("sample_id")
                    or type(row.get("iteration")) is not int):
                raise RecoveryRefused("foreign row in predecessor state ledger: " + relative)
        return rows


def latest_by_sample(rows):
    """Native last-row-wins view of an event ledger (orchestrator.load_sample_states)."""
    states = OrderedDict()
    for row in rows:
        states[row["sample_id"]] = row
    return states


def absence_paths(root, model):
    """Every result path of MODEL that a fresh 004 loop must NOT find.

    004 starts the model from the full_ext_001 base: no repair evidence of it
    may exist in recovery_001, 002, 003 (and their iteration runs), in a
    parent repair directory or in a parent iteration run. Returns the sorted
    offending paths (empty = absent). Path-checked, no links."""
    root = Path(root).resolve()
    if not model or "/" in model or "\\" in model or model.startswith("."):
        raise RecoveryRefused("invalid model id")
    found = []
    for area in ("raw", "intermediate"):
        directory = root / "thesis/results" / area
        if not directory.is_dir():
            continue
        for run in sorted(directory.iterdir()):
            name = run.name
            foreign_repair = (name.startswith("full_ext_recovery_00") and not (
                name == SUCCESSOR or name.startswith(SUCCESSOR + "__")))
            parent_iteration = name.startswith("full_ext_001__")
            if not (foreign_repair or parent_iteration):
                continue
            checked_path(root, run.relative_to(root).as_posix())
            target = run / model
            if target.exists():
                found.extend(p.relative_to(root).as_posix() for p in target.rglob("*") if p.is_file())
                found.append(target.relative_to(root).as_posix())
        parent_repair = directory / "full_ext_001" / model / "repair"
        if parent_repair.exists():
            found.extend(p.relative_to(root).as_posix() for p in parent_repair.rglob("*"))
            found.append(parent_repair.relative_to(root).as_posix())
    return sorted(set(found))


# -- protected sibling runs ---------------------------------------------------

PROTECTED_SCHEMA = "successor_protected_run.v1"


def run_tree_paths(root, run_prefix):
    """Every file of the run trees <run_prefix> and <run_prefix>__* (raw and
    intermediate), path-checked (no links, no escapes)."""
    root = Path(root).resolve()
    if (not run_prefix or "/" in run_prefix or "\\" in run_prefix
            or run_prefix in (PREDECESSOR, SUCCESSOR)):
        raise RecoveryRefused("invalid protected run prefix")
    result = []
    for area in ("raw", "intermediate"):
        directory = root / "thesis/results" / area
        if not directory.is_dir():
            continue
        for run in sorted(directory.iterdir()):
            if run.name != run_prefix and not run.name.startswith(run_prefix + "__"):
                continue
            checked_path(root, run.relative_to(root).as_posix())
            if not run.is_dir():
                raise RecoveryRefused("protected run is not a directory")
            relatives = [path.relative_to(root).as_posix() for path in run.rglob("*")]

            def classify(relative):
                return relative if checked_path(root, relative).is_file() else None

            result.extend(r for r in parallel_map(classify, relatives) if r is not None)
    return sorted(result)


def protected_inventory(root, run_prefix):
    """Raw-byte inventory (sha256 + size per file) of a protected run."""
    root = Path(root).resolve()

    def facts(relative):
        data = checked_path(root, relative).read_bytes()
        return relative, OrderedDict([("raw_sha256", hashlib.sha256(data).hexdigest()),
                                      ("size", len(data))])

    files = OrderedDict(parallel_map(facts, run_tree_paths(root, run_prefix)))
    document = OrderedDict([("schema_version", PROTECTED_SCHEMA), ("run_prefix", run_prefix),
                            ("file_count", len(files)), ("files", files)])
    document["inventory_sha256"] = canonical_sha256(document)
    return document


def verify_protected(root, document):
    """Membership and bytes of a protected run are unchanged."""
    root = Path(root).resolve()
    body = OrderedDict((k, v) for k, v in document.items() if k != "inventory_sha256")
    if (document.get("schema_version") != PROTECTED_SCHEMA
            or canonical_sha256(body) != document.get("inventory_sha256")):
        raise RecoveryRefused("protected inventory is tampered")
    files = document["files"]
    if run_tree_paths(root, document["run_prefix"]) != sorted(files):
        raise RecoveryRefused("protected run %s membership changed" % document["run_prefix"])

    def check(relative):
        data = checked_path(root, relative).read_bytes()
        expected = files[relative]
        if len(data) != expected["size"] or hashlib.sha256(data).hexdigest() != expected["raw_sha256"]:
            raise RecoveryRefused("protected run file changed: " + relative)

    parallel_map(check, sorted(files))
    return True
