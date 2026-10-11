"""Persisted, hash-bound lineage of the successor run full_ext_recovery_004.

004 runs the five models that no repair run ever started (deepseek_v4_pro,
qwen36_35b_a3b, qwen37_max, gemini_36_flash, openai_gpt56_sol) FRESH from
the full_ext_001 base, natively through iterations 1 and 2. It adopts no
repair result of any earlier run. This module freezes, in one self-hashed
document, everything the successor relies on:

* the recovery_001 byte snapshot (every file of its run trees; handoff.Snapshot)
  - recovery_001 is the methodology ORIGIN: its contract / authorization /
  T0 evidence / commit, its definitions and its parent (full_ext_001)
  lineage are bound by hash; nothing of it is adopted;
* per loop, the ORIGIN facts the successor starts from: the parent artifacts
  of the model (raw sha256), complete parent evidence for the iteration-0
  decision (static incl. PARCOACH/LLOV, correctness, dynamic), and the proof
  that no repair evidence of the model exists anywhere (absence);
* the retirement record of recovery_001 and the protected byte inventories
  of the sibling successors full_ext_recovery_002 (retired) and
  full_ext_recovery_003 (complete).

Building the document is read-only. It grants no execution authority.

Python 3.8 compatible.
"""
from __future__ import annotations

import json
import threading
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.recovery_successor_004 import handoff as sh
from thesis.evaluation.condition_hashing import canonical_sha256, lf_normalized_sha256_bytes
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

SCHEMA = "successor_lineage_fresh.v1"
SUCCESSOR = sh.SUCCESSOR
PREDECESSOR = sh.PREDECESSOR
PARENT = "full_ext_001"
PILOT = "pilot_002"
PROFILE = "recovery_successor_004"
# the five models in the author's strict API priority order (doubles as the
# frozen scheduling priority: the Alibaba Model Studio models first)
MODELS = ("deepseek_v4_pro", "qwen36_35b_a3b", "qwen37_max", "gemini_36_flash", "openai_gpt56_sol")
VARIANTS = sh.VARIANTS
MAX_ITERATIONS = 2
# iterations whose requests, answers and analyses the successor owns
PROVIDER_ITERATIONS = (1, 2)
EXTERNAL_TOOLS = ("parcoach", "llov")
PARENT_STAGES = OrderedDict([("static_analysis", "static_analysis.jsonl"),
                             ("correctness_tests", "correctness.jsonl"),
                             ("dynamic_analysis", "dynamic_analysis.jsonl")])

DEFINITIONS_REL = "thesis/evaluation/recovery/full_ext_recovery_004"
CONFIG_REL = "thesis/config/recovery_successor_004.yaml"
PREDECESSOR_DEFINITIONS_REL = "thesis/evaluation/recovery/full_ext_recovery_001"
PREDECESSOR_DEFINITION_FILES = ("composite_v2.json", "contract.json", "equivalence.json",
                                "lineage.json", "parent_report.json", "protected_history.json",
                                "readiness.json", "routing_test_evidence.json")
PREDECESSOR_FRAGMENTS_REL = "thesis/results/intermediate/%s/run_manifest.fragments" % PREDECESSOR
POLICY = OrderedDict([
    ("historical_parent_repair", "EXCLUDE_ALL_PARENT_REPAIR"),
    ("iteration_0_evidence", "PARENT_FULL_EXT_001_BY_HASH_BOUND_REFERENCE_READ_ONLY_NEVER_REMEASURED"),
    ("iteration_0_decisions", "SUCCESSOR_NATIVE_FROM_PARENT_EVIDENCE"),
    ("iterations_1_2", "SUCCESSOR_NATIVE"),
    ("predecessor_repair", "NONE_ADOPTED_ABSENCE_PROVEN"),
    ("tool_entries", "PRESENT_INCLUDING_TIMEOUT_AND_TOOL_ERROR_NEVER_RERUN"),
    ("iteration_budget", "NATIVE_MAX_ITERATIONS_2_UNCHANGED"),
    ("feedback_history", "NATIVE_FROM_PARENT_AND_SUCCESSOR_ARTIFACTS"),
])


def fingerprint(document, field="lineage_sha256"):
    return canonical_sha256(OrderedDict((k, v) for k, v in document.items() if k != field))


def _read_bytes(root, relative):
    return checked_path(root, relative).read_bytes()


def _json_bytes(data):
    return json.loads(data.decode("utf-8"))


def _fragment(view, name):
    return view.read_json("%s/%s" % (PREDECESSOR_FRAGMENTS_REL, name))


def predecessor_bindings(root, view):
    """Contract / authorization / T0 / commit facts of the origin run recovery_001."""
    from thesis.evaluation import pilot_run_contract as prc

    contract_rel = PREDECESSOR_DEFINITIONS_REL + "/contract.json"
    contract = prc.load_frozen(checked_path(root, contract_rel))
    authorization = _fragment(view, "authorization.start.json")
    evidence = _fragment(view, "runtime.evidence.json")
    global_fragment = _fragment(view, "global.json")
    content = authorization.get("content") or {}
    if (content.get("decision") != "START_ALLOWED" or content.get("run_id") != PREDECESSOR
            or content.get("frozen_contract_sha256") != contract["contract_sha256"]):
        raise RecoveryRefused("predecessor authorization is not bound to the predecessor contract")
    evidence_content = evidence.get("content") or {}
    if evidence_content.get("contract_sha256") != contract["contract_sha256"]:
        raise RecoveryRefused("predecessor T0 evidence is bound to another contract")
    missing = [m for m in MODELS if m not in (contract.get("model_ids") or [])]
    if missing:
        raise RecoveryRefused("the origin contract does not cover %s" % ", ".join(missing))
    git = (global_fragment.get("content") or {})
    commit = git.get("git_commit") or (git.get("run") or {}).get("git_commit")
    dirty = git.get("git_dirty") if "git_dirty" in git else (git.get("run") or {}).get("git_dirty")
    parent_lineage = _json_bytes(_read_bytes(root, PREDECESSOR_DEFINITIONS_REL + "/lineage.json"))
    definitions = OrderedDict()
    for name in PREDECESSOR_DEFINITION_FILES:
        rel = "%s/%s" % (PREDECESSOR_DEFINITIONS_REL, name)
        # LF-normalised: version-controlled definitions must survive autocrlf
        definitions[name] = OrderedDict([("path", rel),
                                         ("lf_sha256", lf_normalized_sha256_bytes(_read_bytes(root, rel)))])
    return OrderedDict([
        ("contract_path", contract_rel),
        ("contract_sha256", contract["contract_sha256"]),
        ("authorization_sha256", content.get("authorization_sha256")),
        ("authorization_fragment_content_sha256", authorization.get("content_sha256")),
        ("t0_runtime_evidence_fingerprint_sha256", evidence.get("fingerprint_sha256")),
        ("runtime_condition_sha256", content.get("fresh_t0_runtime_condition_sha256")),
        ("repair_condition_sha256", evidence_content.get("repair_condition_sha256")),
        ("static_analysis_condition_sha256", evidence_content.get("static_analysis_condition_sha256")),
        ("git_commit", commit),
        ("git_dirty", dirty),
        ("parent_lineage_sha256", parent_lineage.get("lineage_sha256")),
        ("definitions", definitions),
    ])


# -- per loop origin -----------------------------------------------------------

def _parent_relative(model, name, raw=False):
    return "thesis/results/%s/%s/%s/%s" % ("raw" if raw else "intermediate", PARENT, model, name)


def _parent_rows(root, refs, relative):
    """Rows of a parent artifact, verified against the parent lineage."""
    ref = refs.get(relative)
    if ref is None or ref.get("stage") == "historical_only":
        raise RecoveryRefused("the parent lineage does not register " + relative)
    import hashlib

    data = checked_path(root, relative).read_bytes()
    if len(data) != ref["size"] or hashlib.sha256(data).hexdigest() != ref["raw_sha256"]:
        raise RecoveryRefused("parent artifact drift: " + relative)
    rows = OrderedDict()
    text = data.decode("utf-8")
    if text and not text.endswith("\n"):
        raise RecoveryRefused("torn parent artifact: " + relative)
    for line in text.split("\n"):
        if not line.strip():
            continue
        row = json.loads(line)
        sample = row.get("sample_id")
        if not sample or sample in rows or row.get("run_id") != PARENT:
            raise RecoveryRefused("duplicate/foreign parent row in " + relative)
        rows[sample] = row
    return rows, ref["raw_sha256"]


def parent_refs(root):
    """path -> ref facts of the parent lineage bound by the origin definitions."""
    document = _json_bytes(_read_bytes(root, PREDECESSOR_DEFINITIONS_REL + "/lineage.json"))
    refs = OrderedDict()
    for row in document.get("artifacts") or []:
        refs[row["path"]] = row
    return refs


def loop_origin(root, view, refs, config, model, variant):
    """The exact state a FRESH successor loop starts from (pure read)."""
    from thesis.evaluation.tool_config import resolve_tool_settings
    from thesis.repair import feedback

    if variant not in VARIANTS:
        raise RecoveryRefused("unregistered variant")
    absent = sh.absence_paths(root, model)
    if absent:
        raise RecoveryRefused("repair evidence of %s already exists (%s); a fresh 004 loop would give "
                              "it a second owner" % (model, ", ".join(absent[:5])))
    snapshot_hits = [p for p in view.snapshot.files if "/%s/" % model in p]
    if snapshot_hits:
        raise RecoveryRefused("recovery_001 carries %s evidence: %s" % (model, snapshot_hits[:5]))
    assembly, assembly_sha = _parent_rows(root, refs, _parent_relative(model, "assembly.jsonl"))
    generations, generations_sha = _parent_rows(root, refs, _parent_relative(model, "generations.jsonl",
                                                                             raw=True))
    assembled = sorted(s for s, e in assembly.items() if e.get("assembled"))
    unassembled = sorted(s for s, e in assembly.items() if not e.get("assembled"))
    if set(assembly) - set(generations):
        raise RecoveryRefused("parent assembly of %s has samples without a generation record" % model)
    sources = feedback.strategy_sources(config, variant)
    needed = OrderedDict([("static_analysis", True),
                          ("correctness_tests", "correctness_verdicts" in sources),
                          ("dynamic_analysis", "dynamic_findings" in sources)])
    stages = OrderedDict()
    records = {}
    for stage, name in PARENT_STAGES.items():
        rows, sha = _parent_rows(root, refs, _parent_relative(model, name))
        missing = [s for s in assembled if s not in rows]
        if needed[stage] and missing:
            raise RecoveryRefused("parent %s of %s misses %d assembled sample(s)" % (stage, model, len(missing)))
        stages[stage] = OrderedDict([("raw_sha256", sha), ("records", len(rows)), ("needed", needed[stage])])
        records[stage] = rows
    settings = resolve_tool_settings(config, "static_analysis")
    external_missing = OrderedDict()
    if variant != "test_feedback":
        for tool in EXTERNAL_TOOLS:
            applicable = [s for s in assembled if settings[tool].enabled
                          and settings[tool].applies_to(s.split("__")[-2])]
            external_missing[tool] = len([s for s in applicable if tool not in (
                (records["static_analysis"].get(s) or {}).get("tools") or {})])
        if any(external_missing.values()):
            raise RecoveryRefused("parent iteration-0 external evidence of %s is incomplete %s; parent "
                                  "measurements are never backfilled" % (model, dict(external_missing)))
    sources_registered = [s for s in assembled
                          if _parent_relative(model, "sources/%s/generated-code.hpp" % s) in refs]
    if len(sources_registered) != len(assembled):
        raise RecoveryRefused("parent sources of %s are not all registered" % model)
    return OrderedDict([
        ("mode", "FRESH"),
        ("origin_run_id", PREDECESSOR),
        ("parent_run_id", PARENT),
        ("parent_cells", len(assembly)),
        ("parent_assembled", len(assembled)),
        ("parent_unassembled", len(unassembled)),
        ("parent_assembly_sha256", assembly_sha),
        ("parent_generations_sha256", generations_sha),
        ("parent_stages", stages),
        ("parent_external_missing", external_missing),
        ("parent_sources_registered", len(sources_registered)),
        ("predecessor_state", "ABSENT"),
        ("assembled_samples_sha256", canonical_sha256(assembled)),
    ])


def predecessor_retirement(view):
    """Explicit retirement record of recovery_001 (unchanged since 003)."""
    loops = OrderedDict()
    prefix = "thesis/results/intermediate/%s/" % PREDECESSOR
    for relative in sorted(view.snapshot.files):
        if relative.startswith(prefix) and relative.endswith("/wave_state.json") and "/repair/" in relative:
            wave = view.read_json(relative)
            loops["%s/%s" % (wave.get("model_id"), wave.get("variant"))] = OrderedDict([
                ("iteration", wave.get("iteration")), ("phase", wave.get("phase")),
                ("wave_state_sha256", view.sha256(relative))])
    stamps = []
    history = PREDECESSOR_FRAGMENTS_REL + "/history/"
    for relative in sorted(view.snapshot.files):
        name = relative[len(history):] if relative.startswith(history) else ""
        if name.startswith("runtime.stage.") or name.startswith("invocation.static."):
            fragment = view.read_json(relative)
            content = fragment.get("content") or {}
            stamps.append(OrderedDict([
                ("path", relative), ("raw_sha256", view.sha256(relative)),
                ("owner", fragment.get("owner")), ("registered_at_utc", fragment.get("registered_at_utc")),
                ("match", content.get("match")), ("contract_sha256", content.get("contract_sha256")),
                ("authorization_sha256", content.get("authorization_sha256"))]))
    return OrderedDict([
        ("decision", "RETIRED_FOR_ALL_MODELS_BY_SUCCESSOR_DISPATCH"),
        ("reason", "LLOV (python 3.8.0, pareval-llov) can never pass recovery_001's contract rebuild "
                   "(recovery_equivalence.portable_ast keeps ast.Index); successor_ast.index_v1 fixes "
                   "it only for a successor run"),
        ("consequence", "since thesis/evaluation/pilot_run_contract.py carries the successor dispatch, "
                        "recovery_contract.build refuses (source pin drift), so no recovery_001 writer "
                        "can run - also not for the five models it never started; recovery_001 evidence "
                        "stays byte-frozen"),
        ("frozen_waves", loops),
        ("runtime_and_invocation_history", stamps),
    ])


# Sibling successor runs this run never reads or writes, protected byte for
# byte (membership + raw sha256), re-checked on every step (stat-guarded).
SIBLINGS = OrderedDict([
    ("full_ext_recovery_002", OrderedDict([
        ("definitions", "thesis/evaluation/recovery/full_ext_recovery_002"),
        ("definition_files", ("contract.json", "equivalence.json", "lineage.json", "readiness.json")),
        ("decision", "RETIRED_BY_GENERIC_SUCCESSOR_DISPATCH"),
        ("reason", "full_ext_recovery_003 added the generic recovery_successor_NNN dispatch to "
                   "thesis/evaluation/pilot_run_contract.py (build_contract); the 002 proof pins the "
                   "previous bytes of that file, so its contract no longer rebuilds"),
    ])),
    ("full_ext_recovery_003", OrderedDict([
        ("definitions", "thesis/evaluation/recovery/full_ext_recovery_003"),
        ("definition_files", ("contract.json", "equivalence.json", "lineage.json", "readiness.json")),
        ("decision", "COMPLETE_FROZEN_PROTECTED"),
        ("reason", "all eight 003 loops are done and verified; 004 changes no file 003 pins (the "
                   "generic dispatch resolves this package without another edit), so 003 stays "
                   "rebuildable but has nothing left to write; its writer lock must be absent"),
    ])),
])


def sibling_successors(root):
    """Decision + byte inventory of every sibling successor run."""
    root = Path(root).resolve()
    result = OrderedDict()
    for run, spec in SIBLINGS.items():
        inventory = sh.protected_inventory(root, run)
        if not inventory["files"]:
            raise RecoveryRefused("sibling successor %s has no results to protect" % run)
        waves = OrderedDict()
        for relative in sorted(inventory["files"]):
            if "/repair/" in relative and relative.endswith("/wave_state.json"):
                wave = json.loads(checked_path(root, relative).read_text(encoding="utf-8"))
                waves["%s/%s" % (wave.get("model_id"), wave.get("variant"))] = OrderedDict([
                    ("iteration", wave.get("iteration")), ("phase", wave.get("phase")),
                    ("wave_state_sha256", inventory["files"][relative]["raw_sha256"])])
        if spec["decision"] == "COMPLETE_FROZEN_PROTECTED" and any(
                w["phase"] != "done" for w in waves.values()):
            raise RecoveryRefused("sibling successor %s is not complete" % run)
        definitions = OrderedDict()
        for name in spec["definition_files"]:
            rel = "%s/%s" % (spec["definitions"], name)
            definitions[name] = OrderedDict([("path", rel), ("lf_sha256", lf_normalized_sha256_bytes(
                _read_bytes(root, rel)))])
        result[run] = OrderedDict([
            ("decision", spec["decision"]),
            ("reason", spec["reason"]),
            ("consequence", "%s results stay byte-frozen (protected_inventory); this run never reads "
                            "or writes them" % run),
            ("frozen_waves", waves),
            ("definitions", definitions),
            ("protected_inventory", inventory),
        ])
    return result


def build(root, config, snapshot_document=None):
    """Build (never persist) the lineage document from the live trees."""
    root = Path(root).resolve()
    if snapshot_document is None:
        snapshot_document = sh.build_snapshot(root)
    snapshot = sh.Snapshot(root, snapshot_document, snapshot_document["snapshot_sha256"])
    view = sh.PredecessorView(snapshot)
    bindings = predecessor_bindings(root, view)
    refs = parent_refs(root)
    origin = OrderedDict()
    for model in MODELS:
        for variant in VARIANTS:
            origin["%s/%s" % (model, variant)] = loop_origin(root, view, refs, config, model, variant)
    document = OrderedDict([
        ("schema_version", SCHEMA),
        ("run_id", SUCCESSOR),
        ("predecessor_run_id", PREDECESSOR),
        ("parent_run_id", PARENT),
        ("pilot_run_id", PILOT),
        ("model_ids", list(MODELS)),
        ("model_priority", list(MODELS)),
        ("variants", list(VARIANTS)),
        ("max_iterations", MAX_ITERATIONS),
        ("provider_iterations", list(PROVIDER_ITERATIONS)),
        ("successor_base_cells", 0),
        ("policy", POLICY),
        ("predecessor", bindings),
        ("predecessor_snapshot", snapshot_document),
        ("predecessor_retirement", predecessor_retirement(view)),
        ("sibling_successors", sibling_successors(root)),
        ("origin", origin),
    ])
    document["lineage_sha256"] = fingerprint(document)
    return document


class SuccessorLineage:
    """Loaded, self-hash-verified lineage with a bound recovery_001 view."""

    def __init__(self, root, document, expected_sha):
        self.root = Path(root).resolve()
        if (not expected_sha or document.get("lineage_sha256") != expected_sha
                or fingerprint(document) != expected_sha or document.get("schema_version") != SCHEMA
                or document.get("run_id") != SUCCESSOR
                or document.get("predecessor_run_id") != PREDECESSOR
                or document.get("parent_run_id") != PARENT
                or document.get("successor_base_cells") != 0
                or document.get("max_iterations") != MAX_ITERATIONS
                or document.get("provider_iterations") != list(PROVIDER_ITERATIONS)
                or document.get("model_ids") != list(MODELS)
                or document.get("model_priority") != list(MODELS)
                or document.get("policy") != POLICY
                or sorted(document.get("origin") or {}) != sorted(
                    "%s/%s" % (m, v) for m in MODELS for v in VARIANTS)):
            raise RecoveryRefused("invalid successor lineage binding")
        snapshot_document = document["predecessor_snapshot"]
        self.snapshot = sh.Snapshot(self.root, snapshot_document, snapshot_document.get("snapshot_sha256"))
        self.view = sh.PredecessorView(self.snapshot)
        self.document = document

    @property
    def sha256(self):
        return self.document["lineage_sha256"]

    def origin(self, model, variant):
        try:
            facts = self.document["origin"]["%s/%s" % (model, variant)]
        except KeyError:
            raise RecoveryRefused("model/variant outside the successor scope")
        if facts.get("mode") != "FRESH":
            raise RecoveryRefused("only FRESH loops exist in this successor")
        return facts

    def _stat_key(self):
        return (str(self.root), self.document["predecessor_snapshot"]["snapshot_sha256"],
                tuple(sorted(self.document.get("sibling_successors") or {})))

    def verify_quick(self):
        """Per step / provider call: full re-hash of recovery_001 AND of every
        protected sibling successor only if any of their files' (size,
        mtime_ns) or the membership changed since the last full verification
        in this process."""
        stats = self._protected_stats()
        key = self._stat_key()
        with _STAT_LOCK:
            if _VERIFIED_STATS.get(key) == stats:
                return True
        self.snapshot.verify_all()
        self.verify_siblings()
        if predecessor_bindings(self.root, self.view) != self.document["predecessor"]:
            raise RecoveryRefused("predecessor bindings drifted")
        with _STAT_LOCK:
            _VERIFIED_STATS[key] = stats
        return True

    def protected_prefixes(self):
        return (PREDECESSOR,) + tuple(sorted(self.document.get("sibling_successors") or {}))

    def definition_paths(self):
        """The frozen definition files of recovery_001 and the siblings."""
        paths = [binding["path"] for binding in self.document["predecessor"]["definitions"].values()]
        for record in (self.document.get("sibling_successors") or {}).values():
            paths.extend(binding["path"] for binding in (record.get("definitions") or {}).values())
        return sorted(paths)

    def _protected_stats(self):
        """(path, size, mtime_ns) of every protected result file AND every bound
        definition file - any change triggers the full re-verification."""
        import os

        definitions = []
        for relative in self.definition_paths():
            info = os.lstat(str(checked_path(self.root, relative)))
            definitions.append((relative, info.st_size, info.st_mtime_ns))
        return _stats(self.root, self.protected_prefixes()) + tuple(definitions)

    def verify(self, config=None, deep=False):
        """Origin bytes and membership unchanged; bindings reproduce; siblings
        byte-identical. deep=True additionally re-derives every origin fact
        (incl. the absence proof) and the retirement record from the bytes."""
        # the stats are taken BEFORE the bytes are verified (as verify_quick):
        # a change during the verification can never be cached as verified
        stats = self._protected_stats()
        self.snapshot.verify_all()
        self.verify_siblings()
        bindings = predecessor_bindings(self.root, self.view)
        if bindings != self.document["predecessor"]:
            raise RecoveryRefused("predecessor bindings drifted")
        if deep:
            if config is None:
                raise RecoveryRefused("deep lineage verification needs the configuration")
            if predecessor_retirement(self.view) != self.document["predecessor_retirement"]:
                raise RecoveryRefused("predecessor retirement record drifted")
            refs = parent_refs(self.root)
            for model in MODELS:
                for variant in VARIANTS:
                    if loop_origin(self.root, self.view, refs, config, model, variant) != \
                            self.document["origin"]["%s/%s" % (model, variant)]:
                        raise RecoveryRefused("origin facts drifted for %s/%s" % (model, variant))
        # cached only after EVERY check passed (as verify_quick)
        with _STAT_LOCK:
            _VERIFIED_STATS[self._stat_key()] = stats
        return True

    def verify_origin_absence(self):
        """The per-model absence proof, re-derived (cheap; used by the verifier)."""
        found = OrderedDict((model, sh.absence_paths(self.root, model)) for model in MODELS)
        offending = OrderedDict((m, p) for m, p in found.items() if p)
        if offending:
            raise RecoveryRefused("repair evidence of a 004 model appeared outside 004: %s"
                                  % json.dumps(offending)[:400])
        return True

    def verify_siblings(self):
        """Every protected sibling successor run is byte-identical, and its
        frozen definitions (contract, proof, lineage, readiness) unchanged."""
        siblings = self.document.get("sibling_successors") or {}
        if sorted(siblings) != sorted(SIBLINGS):
            raise RecoveryRefused("sibling successor membership drifted")
        for run, record in siblings.items():
            sh.verify_protected(self.root, record["protected_inventory"])
            spec = SIBLINGS[run]
            definitions = record.get("definitions") or {}
            if list(definitions) != list(spec["definition_files"]):
                raise RecoveryRefused("sibling successor %s definition set drifted" % run)
            for name, binding in definitions.items():
                if (binding.get("path") != "%s/%s" % (spec["definitions"], name)
                        or lf_normalized_sha256_bytes(_read_bytes(self.root, binding["path"]))
                        != binding.get("lf_sha256")):
                    raise RecoveryRefused("sibling successor %s definition %s drifted" % (run, name))
        return OrderedDict((run, record["protected_inventory"]["file_count"])
                           for run, record in siblings.items())


_STAT_LOCK = threading.Lock()
_VERIFIED_STATS = {}


def _stats(root, prefixes):
    """(relative path, size, mtime_ns) of every file of the protected run
    trees (recovery_001 and the sibling successors), by directory scan
    without following links (one lstat per entry; the full path validation
    of checked_path runs in every full verification). A link anywhere in the
    protected trees refuses."""
    import os

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
                if any(entry.name == p or entry.name.startswith(p + "__") for p in prefixes):
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        raise RecoveryRefused("protected run is not a plain directory: " + entry.path)
                    pending.append(entry.path)
    stats = []
    while pending:
        level = sh.parallel_map(scan, pending)
        pending = []
        for directories, files in level:
            pending.extend(directories)
            stats.extend(files)
    return tuple(sorted(stats))


_LOAD_LOCK = threading.Lock()
_LOADED = {}


def load(root, relative=None):
    """The persisted lineage, self-hash verified. Re-loaded (and re-verified,
    including every snapshot path) whenever lineage.json changed size/mtime;
    otherwise the already verified instance of this process is returned (a
    contract rebuild runs on every step and every provider call)."""
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
    lineage = SuccessorLineage(root, document, document.get("lineage_sha256"))
    with _LOAD_LOCK:
        _LOADED[key] = (stamp, lineage)
    return lineage
