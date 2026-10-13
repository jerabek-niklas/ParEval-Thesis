"""Persisted, hash-bound protection lineage of the phase-2 successor
full_ext_phase2_001 (profile recovery_successor_005).

Phase 2 measures candidates that belong to SIX completed historical runs
(pilot_002 only read for its completeness, full_ext_001 iteration-0 base
cells, the repair candidates of full_ext_recovery_001..004). None of their
bytes may change. This module freezes, in one self-hashed document:

* a raw-byte inventory (sha256 + size per file) of every run tree
  <prefix> / <prefix>__* (raw and intermediate) of the six protected runs;
* the chain of custody of those inventories: they must agree file-by-file
  with the inventories the earlier frozen definitions already recorded
  (recovery_001 protected_history.json for pilot_002/full_ext_001, the
  recovery_001 byte snapshot and the 002/003 sibling inventories recorded in
  the frozen full_ext_recovery_004 lineage);
* the frozen definitions of full_ext_recovery_001..004, the composite and
  population documents, the frozen enhanced specs and the historical
  successor configs (raw + LF sha256);
* the digest of the phase-2 target table (targets.py) and of the census.

Building the document is read-only. It grants no execution authority.

Python 3.8 compatible.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation.condition_hashing import canonical_sha256, lf_normalized_sha256_bytes
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

SCHEMA = "phase2_lineage.v1"
SUCCESSOR = "full_ext_phase2_001"
PROFILE = "recovery_successor_005"
PARENT = "full_ext_001"
PILOT = "pilot_002"
ORIGIN = "full_ext_recovery_001"
OWNERS = ("full_ext_recovery_001", "full_ext_recovery_002", "full_ext_recovery_003",
          "full_ext_recovery_004")
MODELS = ("claude_fable_5", "claude_opus_5", "deepseek_v4_flash", "deepseek_v4_pro",
          "gemini_31_pro", "gemini_36_flash", "openai_gpt55", "openai_gpt56_sol",
          "qwen36_35b_a3b", "qwen37_max", "qwen3_coder_api")
VARIANTS = ("static_feedback", "test_feedback", "combined_feedback")
MAX_ITERATIONS = 2
EXTERNAL_TOOLS = ("parcoach", "llov")
STAGES = ("static.main", "static.parcoach", "static.llov", "correctness", "dynamic", "enhanced")
PROTECTED_PREFIXES = (PILOT, PARENT) + OWNERS
# the aborted repair inside the base run: never a target, never measured
EXCLUDED_HISTORICAL_RUNS = ("full_ext_001__static_feedback__iter1",)
RESULTS_REL = "thesis/results/intermediate/" + SUCCESSOR
DEFINITIONS_REL = "thesis/evaluation/recovery/" + SUCCESSOR
CONFIG_REL = "thesis/config/recovery_successor_005.yaml"
HISTORICAL_DEFINITION_DIRS = tuple("thesis/evaluation/recovery/%s" % run for run in OWNERS)
HISTORICAL_DEFINITION_FILES = (
    "thesis/evaluation/full_001_composite.json",
    "thesis/evaluation/full_extension_equivalence.json",
    "thesis/evaluation/pilot_002_population.json",
    "thesis/evaluation/full_ext_001_population.json",
    "thesis/enhanced_tests/frozen/e3_final_specs.jsonl",
    "thesis/config/recovery.yaml",
    "thesis/config/recovery_successor.yaml",
    "thesis/config/recovery_successor_003.yaml",
    "thesis/config/recovery_successor_004.yaml",
)
PROTECTED_SCHEMA = "successor_protected_run.v1"  # the 004 sibling-inventory format
POLICY = OrderedDict([
    ("provider_calls", "NONE"),
    ("historical_results", "READ_ONLY_BYTE_PROTECTED"),
    ("new_measurements", "NEW_RESULT_IDENTITY_full_ext_phase2_001_BOUND_BY_CANDIDATE_SOURCE_SHA256"),
    ("existing_results", "PRESENT_WHATEVER_THEIR_STATE_NEVER_REMEASURED"),
    ("measurement_functions", "NATIVE_UNCHANGED"),
    ("enhanced_gate", "HELD_OUT_AFTER_ALL_66_REPAIR_LOOPS_TERMINAL"),
    ("excluded_historical_runs", list(EXCLUDED_HISTORICAL_RUNS)),
    ("pilot", "COMPLETE_READ_ONLY_REFERENCE"),
])
IO_WORKERS = 16


class GlobalStop(RecoveryRefused):
    """An integrity / contract / provenance / runtime conflict: the WHOLE
    phase-2 run stops (nothing further is measured in this invocation)."""


class TargetFailure(RuntimeError):
    """A failure confined to one (target, stage) - e.g. a tool container that
    exited with a tool error. The driver retries it once (missing-only) and
    otherwise leaves it open for the next invocation."""


def isolate_providers():
    """Disable the native config loader's .env import (load_config calls
    python-dotenv's load_dotenv) for this process. Phase 2 needs no provider
    key; without this, a .env in the repository root would put every API key
    into the driver, every measured program and every tool container, and the
    T0 evidence would bind whatever endpoints that file happens to resolve.
    Call BEFORE the first load_config of an entrypoint."""
    import thesis.config.load_config as loader

    loader.load_dotenv = lambda *args, **kwargs: False
    return True


def scrub_provider_environment(config):
    """Remove every configured provider key / endpoint variable from this
    process (e.g. passed with --env-file): T0 then records the deterministic
    UNSET endpoint identities, and no child inherits a key."""
    removed = []
    for model in config.get("models") or []:
        for field in ("api_key_env", "base_url_env"):
            name = model.get(field)
            if name and name in os.environ:
                os.environ.pop(name, None)
                removed.append(name)
    return sorted(set(removed))


def provider_environment(config):
    """Configured provider variables still present (must be empty)."""
    return sorted(set(model.get(field) for model in config.get("models") or []
                      for field in ("api_key_env", "base_url_env")
                      if model.get(field) and model.get(field) in os.environ))


def parallel_map(function, items):
    """list(map(function, items)) on IO_WORKERS threads (order preserved;
    the first exception propagates). File-system latency dominates on the
    Windows bind mount."""
    from concurrent.futures import ThreadPoolExecutor

    items = list(items)
    if len(items) < 2:
        return [function(item) for item in items]
    with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
        return list(pool.map(function, items))


def fingerprint(document, field="lineage_sha256"):
    return canonical_sha256(OrderedDict((k, v) for k, v in document.items() if k != field))


def _read_bytes(root, relative):
    return checked_path(Path(root), relative).read_bytes()


def _is_member(name, prefix):
    return name == prefix or name.startswith(prefix + "__")


# -- protected run trees ---------------------------------------------------------

def run_tree_paths(root, prefix):
    """Every file of the run trees <prefix> and <prefix>__* (raw and
    intermediate), path-checked (no links, no escapes)."""
    root = Path(root).resolve()
    if prefix not in PROTECTED_PREFIXES:
        raise RecoveryRefused("not a protected run prefix: %r" % prefix)
    result = []
    for area in ("raw", "intermediate"):
        directory = root / "thesis/results" / area
        if not directory.is_dir():
            continue
        for run in sorted(directory.iterdir()):
            if not _is_member(run.name, prefix):
                continue
            checked_path(root, run.relative_to(root).as_posix())
            if run.is_symlink() or not run.is_dir():
                raise RecoveryRefused("protected run is not a plain directory: %s" % run.name)
            relatives = [path.relative_to(root).as_posix() for path in run.rglob("*")]

            def classify(relative):
                return relative if checked_path(root, relative).is_file() else None

            result.extend(r for r in parallel_map(classify, relatives) if r is not None)
    return sorted(result)


def protected_inventory(root, prefix):
    """Raw-byte inventory (sha256 + size per file) of one protected run."""
    root = Path(root).resolve()

    def facts(relative):
        data = checked_path(root, relative).read_bytes()
        return relative, OrderedDict([("raw_sha256", hashlib.sha256(data).hexdigest()),
                                      ("size", len(data))])

    files = OrderedDict(parallel_map(facts, run_tree_paths(root, prefix)))
    document = OrderedDict([("schema_version", PROTECTED_SCHEMA), ("run_prefix", prefix),
                            ("file_count", len(files)), ("files", files)])
    document["inventory_sha256"] = canonical_sha256(document)
    return document


def verify_protected(root, document):
    """Membership and bytes of one protected run are unchanged."""
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


# -- chain of custody against the earlier frozen inventories --------------------

def _frozen_json(root, relative):
    return json.loads(_read_bytes(root, relative).decode("utf-8"), object_pairs_hook=OrderedDict)


def custody(root, inventories):
    """The fresh inventories agree with every inventory an earlier frozen
    definition recorded. pilot_002/full_ext_001: recovery_001's
    protected_history (raw sha256 per path, membership incl. the three
    evaluation documents). recovery_001: the byte snapshot frozen in the
    full_ext_recovery_004 lineage. 002/003: the sibling inventories frozen in
    the same lineage (exact document equality)."""
    root = Path(root).resolve()
    lineage_004 = _frozen_json(root, "thesis/evaluation/recovery/full_ext_recovery_004/lineage.json")
    if lineage_004.get("lineage_sha256") != fingerprint(lineage_004):
        raise RecoveryRefused("the frozen full_ext_recovery_004 lineage does not reproduce its hash")
    from thesis.evaluation import pilot_run_contract as prc

    contract_004 = prc.load_frozen(checked_path(root, "thesis/evaluation/recovery/full_ext_recovery_004/contract.json"))
    if (contract_004.get("successor_provenance") or {}).get("lineage_sha256") != lineage_004["lineage_sha256"]:
        raise RecoveryRefused("the frozen 004 contract does not bind the 004 lineage")
    authorization_004 = _frozen_json(
        root, "thesis/results/intermediate/full_ext_recovery_004/run_manifest.fragments/authorization.start.json")
    if (authorization_004.get("content") or {}).get("frozen_contract_sha256") != contract_004["contract_sha256"]:
        raise RecoveryRefused("the 004 start authorization is not bound to the frozen 004 contract")
    # every 001..003 definition the 004 lineage bound by LF hash (protected
    # history, contracts, proofs, lineages, readiness) is still those bytes
    anchors = list((lineage_004["predecessor"].get("definitions") or {}).values())
    for record in (lineage_004.get("sibling_successors") or {}).values():
        anchors.extend((record.get("definitions") or {}).values())
    for binding in anchors:
        if lf_normalized_sha256_bytes(_read_bytes(root, binding["path"])) != binding["lf_sha256"]:
            raise RecoveryRefused("an anchor definition drifted from the 004 lineage: " + binding["path"])
    history = _frozen_json(root, "thesis/evaluation/recovery/%s/protected_history.json" % ORIGIN)
    if history.get("schema_version") != "recovery_protected_history.v1":
        raise RecoveryRefused("recovery_001 protected history has an unexpected schema")
    historical = history["files"]
    for relative, sha in historical.items():
        if not relative.startswith("thesis/results/") and \
                hashlib.sha256(_read_bytes(root, relative)).hexdigest() != sha:
            raise RecoveryRefused("a protected evaluation document changed: " + relative)
    fresh = OrderedDict()
    for prefix in (PILOT, PARENT):
        for relative, facts in inventories[prefix]["files"].items():
            fresh[relative] = facts["raw_sha256"]
    recorded = OrderedDict((path, sha) for path, sha in historical.items()
                           if path.startswith("thesis/results/"))
    if sorted(fresh) != sorted(recorded):
        raise RecoveryRefused("pilot_002/full_ext_001 membership differs from recovery_001 "
                              "protected_history (%d vs %d files)" % (len(fresh), len(recorded)))
    changed = [path for path in fresh if fresh[path] != recorded[path]]
    if changed:
        raise RecoveryRefused("pilot_002/full_ext_001 bytes differ from protected_history: %s"
                              % changed[:5])
    snapshot = lineage_004["predecessor_snapshot"]["files"]
    own = inventories[ORIGIN]["files"]
    if sorted(snapshot) != sorted(own) or any(
            snapshot[p]["raw_sha256"] != own[p]["raw_sha256"] or snapshot[p]["size"] != own[p]["size"]
            for p in own):
        raise RecoveryRefused("recovery_001 differs from the snapshot frozen by full_ext_recovery_004")
    for run in ("full_ext_recovery_002", "full_ext_recovery_003"):
        frozen = lineage_004["sibling_successors"][run]["protected_inventory"]
        if frozen["files"] != inventories[run]["files"]:
            raise RecoveryRefused("%s differs from the inventory frozen by full_ext_recovery_004" % run)
    return OrderedDict([
        ("protected_history", OrderedDict([("path", "thesis/evaluation/recovery/%s/protected_history.json"
                                            % ORIGIN), ("result_files", len(recorded))])),
        ("full_ext_recovery_004_lineage_sha256", lineage_004["lineage_sha256"]),
        ("recovery_001_snapshot_files", len(snapshot)),
        ("sibling_inventories_sha256", OrderedDict(
            (run, lineage_004["sibling_successors"][run]["protected_inventory"]["inventory_sha256"])
            for run in ("full_ext_recovery_002", "full_ext_recovery_003"))),
        # the methodology origin (recovery_001 contract / authorization / T0 /
        # commit / runtime / repair condition), exactly as 004 bound it - the
        # bytes it was derived from are re-verified above
        ("origin_bindings", lineage_004["predecessor"]),
    ])


# -- frozen definitions ----------------------------------------------------------

def _machine_definitions(base):
    """The machine definitions of a historical definition directory: its
    JSON documents (contract, proof, lineage, readiness, evidence, ...).
    Human-written notes (IMPLEMENTATION_STATUS.md) and editor files are
    deliberately not bound - they carry no methodology."""
    return sorted(p for p in base.iterdir() if p.is_file() and p.suffix == ".json")


def definition_paths(root):
    root = Path(root).resolve()
    paths = []
    for directory in HISTORICAL_DEFINITION_DIRS:
        base = checked_path(root, directory)
        if not base.is_dir():
            raise RecoveryRefused("missing historical definitions: " + directory)
        paths.extend(p.relative_to(root).as_posix() for p in _machine_definitions(base))
    paths.extend(HISTORICAL_DEFINITION_FILES)
    return sorted(paths)


def definition_bindings(root):
    bindings = OrderedDict()
    for relative in definition_paths(root):
        data = _read_bytes(root, relative)
        bindings[relative] = OrderedDict([("raw_sha256", hashlib.sha256(data).hexdigest()),
                                          ("lf_sha256", lf_normalized_sha256_bytes(data))])
    return bindings


# -- document --------------------------------------------------------------------

def build(root, targets_sha256, census_digest):
    """The phase-2 lineage document (read-only; takes minutes: every protected
    byte is hashed)."""
    root = Path(root).resolve()
    inventories = OrderedDict((prefix, protected_inventory(root, prefix)) for prefix in PROTECTED_PREFIXES)
    document = OrderedDict([
        ("schema_version", SCHEMA),
        ("run_id", SUCCESSOR),
        ("profile", PROFILE),
        ("parent_run_id", PARENT),
        ("pilot_run_id", PILOT),
        ("owner_runs", list(OWNERS)),
        ("model_ids", list(MODELS)),
        ("variants", list(VARIANTS)),
        ("max_iterations", MAX_ITERATIONS),
        ("stages", list(STAGES)),
        ("policy", POLICY),
        ("protected", inventories),
        ("custody", custody(root, inventories)),
        ("definitions", definition_bindings(root)),
        ("targets_sha256", targets_sha256),
        ("census_digest", census_digest),
    ])
    document["lineage_sha256"] = fingerprint(document)
    return document


class PhaseLineage:
    """Loaded, self-hash-verified phase-2 lineage."""

    def __init__(self, root, document, expected_sha):
        self.root = Path(root).resolve()
        if (not expected_sha or document.get("lineage_sha256") != expected_sha
                or fingerprint(document) != expected_sha or document.get("schema_version") != SCHEMA
                or document.get("run_id") != SUCCESSOR or document.get("profile") != PROFILE
                or document.get("model_ids") != list(MODELS)
                or document.get("variants") != list(VARIANTS)
                or document.get("policy") != POLICY
                or list(document.get("protected") or {}) != list(PROTECTED_PREFIXES)):
            raise RecoveryRefused("invalid phase-2 lineage binding")
        for prefix, inventory in document["protected"].items():
            body = OrderedDict((k, v) for k, v in inventory.items() if k != "inventory_sha256")
            if (inventory.get("run_prefix") != prefix
                    or canonical_sha256(body) != inventory.get("inventory_sha256")):
                raise RecoveryRefused("protected inventory %s is tampered" % prefix)
        self.document = document

    @property
    def sha256(self):
        return self.document["lineage_sha256"]

    @property
    def targets_sha256(self):
        return self.document["targets_sha256"]

    @property
    def origin(self):
        """recovery_001 bindings (contract, authorization, T0, commit, runtime /
        static / repair conditions, definitions) as frozen by 004."""
        return self.document["custody"]["origin_bindings"]

    def protected_bytes(self, relative):
        """Bytes of a file inside a protected run tree, verified against the
        frozen inventory (read-only access path for definitions/fragments)."""
        parts = relative.split("/")
        for prefix, inventory in self.document["protected"].items():
            if len(parts) > 3 and _is_member(parts[3], prefix):
                facts = inventory["files"].get(relative)
                if facts is None:
                    break
                data = _read_bytes(self.root, relative)
                if len(data) != facts["size"] or hashlib.sha256(data).hexdigest() != facts["raw_sha256"]:
                    raise RecoveryRefused("protected file drifted: " + relative)
                return data
        raise RecoveryRefused("not an inventoried protected file: " + relative)

    def protected_file_counts(self):
        return OrderedDict((prefix, inventory["file_count"])
                           for prefix, inventory in self.document["protected"].items())

    def definition_paths(self):
        return sorted(self.document["definitions"])

    def _stat_key(self):
        return (str(self.root), self.sha256)

    def _protected_stats(self):
        definitions = []
        for relative in self.definition_paths():
            info = os.lstat(str(checked_path(self.root, relative)))
            definitions.append((relative, info.st_size, info.st_mtime_ns))
        listings = tuple((directory, tuple(p.name for p in _machine_definitions(checked_path(self.root, directory))))
                         for directory in HISTORICAL_DEFINITION_DIRS)
        return _stats(self.root, PROTECTED_PREFIXES) + tuple(definitions) + listings

    def verify_definitions(self):
        if definition_paths(self.root) != self.definition_paths():
            raise RecoveryRefused("historical definition membership changed")
        for relative, binding in self.document["definitions"].items():
            data = _read_bytes(self.root, relative)
            if hashlib.sha256(data).hexdigest() != binding["raw_sha256"]:
                raise RecoveryRefused("historical definition changed: " + relative)
        return True

    def verify(self):
        """Every protected byte, membership and frozen definition unchanged
        (stats are taken BEFORE the bytes are hashed, so a change during the
        verification can never be cached as verified)."""
        stats = self._protected_stats()
        for inventory in self.document["protected"].values():
            verify_protected(self.root, inventory)
        self.verify_definitions()
        with _STAT_LOCK:
            _VERIFIED_STATS[self._stat_key()] = stats
        return self.protected_file_counts()

    def verify_quick(self):
        """Per target batch: the full re-hash runs only if the membership or a
        (size, mtime_ns) of any protected file or definition changed since the
        last full verification in this process."""
        stats = self._protected_stats()
        with _STAT_LOCK:
            if _VERIFIED_STATS.get(self._stat_key()) == stats:
                return True
        self.verify()
        return True


_STAT_LOCK = threading.Lock()
_VERIFIED_STATS = {}


def _stats(root, prefixes):
    """(relative path, size, mtime_ns) of every file of the protected run
    trees, by directory scan without following links. A link refuses."""
    root = Path(root).resolve()

    def scan(directory):
        directories, files = [], []
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise RecoveryRefused("link in a protected run tree: " + entry.path)
                if entry.is_dir(follow_symlinks=False):
                    directories.append(entry.path)
                else:
                    info = entry.stat(follow_symlinks=False)
                    files.append((Path(entry.path).relative_to(root).as_posix(),
                                  info.st_size, info.st_mtime_ns))
        return directories, files

    pending = []
    for area in ("raw", "intermediate"):
        directory = root / "thesis/results" / area
        if not directory.is_dir():
            continue
        with os.scandir(str(directory)) as entries:
            for entry in entries:
                if any(_is_member(entry.name, p) for p in prefixes):
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        raise RecoveryRefused("protected run is not a plain directory: " + entry.path)
                    pending.append(entry.path)
    stats = []
    while pending:
        level = parallel_map(scan, pending)
        pending = []
        for directories, files in level:
            pending.extend(directories)
            stats.extend(files)
    return tuple(sorted(stats))


_LOAD_LOCK = threading.Lock()
_LOADED = {}


def load(root, relative=None):
    """The persisted lineage, self-hash verified; cached per (size, mtime)."""
    root = Path(root).resolve()
    relative = relative or DEFINITIONS_REL + "/lineage.json"
    path = checked_path(root, relative)
    info = path.stat()
    key = (str(root), relative)
    stamp = (info.st_size, info.st_mtime_ns)
    with _LOAD_LOCK:
        cached = _LOADED.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    lineage = PhaseLineage(root, document, document.get("lineage_sha256"))
    with _LOAD_LOCK:
        _LOADED[key] = (stamp, lineage)
    return lineage


def is_protected_relative(relative):
    """True if a repo-relative path lies inside a protected run tree."""
    parts = relative.replace("\\", "/").split("/")
    return (len(parts) >= 4 and parts[:2] == ["thesis", "results"] and parts[2] in ("raw", "intermediate")
            and any(_is_member(parts[3], p) for p in PROTECTED_PREFIXES))


def require_writable(root, path):
    """A phase-2 write target must lie inside the phase-2 results tree."""
    root = Path(root).resolve()
    relative = Path(path).resolve().relative_to(root).as_posix() if Path(path).is_absolute() else \
        str(path).replace("\\", "/")
    if not (relative == RESULTS_REL or relative.startswith(RESULTS_REL + "/")) or is_protected_relative(relative):
        raise RecoveryRefused("phase-2 writes only inside %s (refused: %s)" % (RESULTS_REL, relative))
    return checked_path(root, relative)
