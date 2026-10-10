"""Persisted, hash-bound predecessor lineage of the successor run.

The successor (full_ext_recovery_003) continues recovery_001 loops BY
REFERENCE. This module freezes, in one self-hashed document, everything the
successor relies on:

* the complete predecessor byte snapshot (every file of the recovery_001 run
  trees; successor_handoff.Snapshot) - read-only, re-verified on every read;
* the predecessor contract / authorization / T0 evidence / git commit and the
  recovery_001 definition files (raw sha256);
* the parent (full_ext_001) lineage binding inherited from recovery_001;
* per loop, the HANDOFF facts the successor continues from (wave phase,
  ledger shape, answered requests, missing external tools).

Building the document is read-only. It grants no execution authority.

Python 3.8 compatible.
"""
from __future__ import annotations

import json
import threading
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.recovery_successor_003 import handoff as sh
from thesis.evaluation.condition_hashing import canonical_sha256, lf_normalized_sha256_bytes
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path

SCHEMA = "successor_lineage.v1"
SUCCESSOR = sh.SUCCESSOR
PREDECESSOR = sh.PREDECESSOR
PARENT = "full_ext_001"
PILOT = "pilot_002"
PROFILE = "recovery_successor_003"
MODELS = ("claude_fable_5", "claude_opus_5", "gemini_31_pro", "openai_gpt55")
VARIANTS = sh.VARIANTS
MAX_ITERATIONS = 2
CONTINUE_VARIANTS = ("static_feedback", "combined_feedback")
ADOPT_DONE_VARIANTS = ("test_feedback",)
EXTERNAL_TOOLS = ("parcoach", "llov")
# external tools a successor-owned supplement may add to a PREDECESSOR
# iteration-1 record (never present there for these models: recovery_001
# ran neither PARCOACH nor LLOV for them)
SUPPLEMENT_TOOLS = ("parcoach", "llov")

DEFINITIONS_REL = "thesis/evaluation/recovery/full_ext_recovery_003"
CONFIG_REL = "thesis/config/recovery_successor_003.yaml"
PREDECESSOR_DEFINITIONS_REL = "thesis/evaluation/recovery/full_ext_recovery_001"
PREDECESSOR_DEFINITION_FILES = ("composite_v2.json", "contract.json", "equivalence.json",
                                "lineage.json", "parent_report.json", "protected_history.json",
                                "readiness.json", "routing_test_evidence.json")
PREDECESSOR_FRAGMENTS_REL = "thesis/results/intermediate/%s/run_manifest.fragments" % PREDECESSOR
POLICY = OrderedDict([
    ("historical_parent_repair", "EXCLUDE_ALL_PARENT_REPAIR"),
    ("predecessor_results", "ADOPT_BY_HASH_BOUND_REFERENCE_NEVER_COPY_NEVER_REWRITE"),
    ("predecessor_answered_requests", "NEVER_RESUBMIT"),
    ("predecessor_tool_entries", "PRESENT_INCLUDING_TIMEOUT_AND_TOOL_ERROR_NEVER_RERUN"),
    ("iteration_budget", "INHERITED_UNCHANGED"),
    ("feedback_history", "REBUILT_FROM_VERIFIED_PREDECESSOR_ARTIFACTS"),
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
    """Contract / authorization / T0 / commit facts of the predecessor run."""
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


def _requests_and_responses(view, model, variant, iteration):
    run = sh.predecessor_iteration_run(variant, iteration)
    requests_rel = "%s/iter%d/requests.jsonl" % (sh.repair_dir(model, variant), iteration)
    raw_dir = sh.iteration_dir(run, model, "raw")
    responses_rel = raw_dir + "/generations.jsonl"
    if not view.has(requests_rel):
        return None
    requests = view.jsonl(requests_rel)
    responses = [env["record"] for env in view.snapshot.rows(responses_rel, run, model)]
    for name in ("failed_responses.jsonl",):
        if view.has(raw_dir + "/" + name):
            raise RecoveryRefused("predecessor carries retry history (%s); explicit handoff "
                                  "validation required" % name)
    if view.has("%s/iter%d/batch.json" % (sh.repair_dir(model, variant), iteration)):
        raise RecoveryRefused("predecessor carries an open batch for %s/%s" % (model, variant))
    unanswered = sh.unanswered_requests(requests, responses, run, model, variant, iteration,
                                        MAX_ITERATIONS)
    if unanswered:
        raise RecoveryRefused("predecessor requests without terminal answers: %d" % len(unanswered))
    statuses = Counter("success" if (r.get("status") or {}).get("success") is True
                       else str((r.get("status") or {}).get("error_type")) for r in responses)
    return OrderedDict([
        ("requests", len(requests)), ("responses", len(responses)),
        ("response_statuses", OrderedDict(sorted(statuses.items()))),
        ("requests_sha256", view.sha256(requests_rel)),
        ("responses_sha256", view.sha256(responses_rel)),
    ])


def _missing_external(view, config, model, variant, iteration, assembled):
    from thesis.evaluation.tool_config import resolve_tool_settings

    run = sh.predecessor_iteration_run(variant, iteration)
    static_rel = sh.iteration_dir(run, model) + "/static_analysis.jsonl"
    records = view.unique_rows(static_rel, run, model)
    settings = resolve_tool_settings(config, "static_analysis")
    missing = OrderedDict()
    present = OrderedDict()
    for tool in EXTERNAL_TOOLS:
        applicable = [s for s in assembled
                      if settings[tool].enabled and settings[tool].applies_to(s.split("__")[-2])]
        missing[tool] = len([s for s in applicable
                             if tool not in ((records.get(s) or {}).get("tools") or {})])
        present[tool] = len(applicable) - missing[tool]
    if set(records) != set(assembled):
        raise RecoveryRefused("predecessor static records do not cover the assembled set")
    return missing, present, view.sha256(static_rel)


def loop_handoff(view, config, model, variant):
    """The exact state the successor continues (or adopts) for one loop."""
    rows = view.event_ledger(model, variant)
    latest = sh.latest_by_sample(rows)
    wave = view.read_json(sh.repair_dir(model, variant) + "/wave_state.json")
    if (wave.get("run_id") != PREDECESSOR or wave.get("model_id") != model
            or wave.get("variant") != variant):
        raise RecoveryRefused("foreign predecessor wave state")
    statuses = Counter((r.get("status"), r.get("iteration")) for r in latest.values())
    active = sorted(s for s, r in latest.items() if r.get("status") == "active")
    facts = OrderedDict([
        ("wave_iteration", wave.get("iteration")), ("wave_phase", wave.get("phase")),
        ("repair_condition_sha256", wave.get("repair_condition_sha256")),
        ("state_rows", len(rows)), ("state_samples", len(latest)),
        ("state_sha256", view.sha256(sh.repair_dir(model, variant) + "/state.jsonl")),
        ("latest_status_counts", OrderedDict(
            ("%s@%s" % key, count) for key, count in sorted(statuses.items(), key=str))),
        ("active_samples", len(active)),
        ("active_samples_sha256", canonical_sha256(active)),
        ("request_rounds_sha256", view.sha256(sh.repair_dir(model, variant) + "/request_rounds.json")),
    ])
    iterations = OrderedDict()
    for iteration in range(1, MAX_ITERATIONS + 1):
        exchange = _requests_and_responses(view, model, variant, iteration)
        if exchange is not None:
            iterations[str(iteration)] = exchange
    facts["iterations"] = iterations
    if variant in ADOPT_DONE_VARIANTS:
        mode = "ADOPT_DONE"
        if wave.get("phase") != "done" or active:
            raise RecoveryRefused("adopted predecessor loop %s/%s is not terminal" % (model, variant))
    else:
        mode = "CONTINUE"
        if wave.get("phase") != "analyzed_waiting_external" or wave.get("iteration") != 1:
            raise RecoveryRefused("predecessor loop %s/%s is not waiting at iteration 1" % (model, variant))
        if any(r.get("iteration") != 0 for r in rows) or len(rows) != len(latest):
            raise RecoveryRefused("predecessor loop %s/%s already decided iteration 1" % (model, variant))
        run = sh.predecessor_iteration_run(variant, 1)
        assembly_rel = sh.iteration_dir(run, model) + "/assembly.jsonl"
        assembly = view.unique_rows(assembly_rel, run, model)
        assembled = sorted(s for s, row in assembly.items() if row.get("assembled"))
        if assembled != active or iterations.get("1", {}).get("requests") != len(active):
            raise RecoveryRefused("predecessor iteration-1 assembly is not exactly the active set")
        missing, present, static_sha = _missing_external(view, config, model, variant, 1, assembled)
        # a supplement tool must be ENTIRELY absent from the predecessor
        # records (incl. out-of-scope NOT_APPLICABLE stubs): a partially
        # present tool would give one record two owners
        records = view.unique_rows(sh.iteration_dir(run, model) + "/static_analysis.jsonl", run, model)
        carried = OrderedDict()
        for tool in SUPPLEMENT_TOOLS:
            carried[tool] = len([s for s in assembled if tool in ((records.get(s) or {}).get("tools") or {})])
            if missing.get(tool) and carried[tool]:
                raise RecoveryRefused("predecessor iteration 1 of %s/%s carries %s for %d sample(s) but "
                                      "misses it for %d" % (model, variant, tool, carried[tool], missing[tool]))
        facts["iteration_1"] = OrderedDict([
            ("run_id", run), ("assembled", len(assembled)),
            ("assembly_sha256", view.sha256(assembly_rel)),
            ("static_sha256", static_sha),
            ("external_missing", missing), ("external_present", present),
            ("external_carried", carried),
        ])
        for tool in EXTERNAL_TOOLS:
            if missing.get(tool) and tool not in SUPPLEMENT_TOOLS:
                raise RecoveryRefused("predecessor iteration 1 misses %s, which is no successor supplement"
                                      % tool)
    facts["mode"] = mode
    return facts


def predecessor_retirement(view):
    """Explicit retirement record of the predecessor run.

    recovery_001 cannot complete any static/combined loop: its LLOV gate
    (recovery_contract.build in the python3.8 LLOV container) refuses before
    writing (portable_ast keeps ast.Index). The successor's single dispatch
    change in pilot_run_contract.py makes the predecessor contract
    non-rebuildable, which retires EVERY recovery_001 writer (all models)."""
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
        ("consequence", "after thesis/evaluation/pilot_run_contract.py gains the recovery_successor "
                        "dispatch, recovery_contract.build refuses (source pin drift), so no "
                        "recovery_001 writer can run; recovery_001 evidence stays byte-frozen"),
        ("frozen_waves", loops),
        ("runtime_and_invocation_history", stamps),
    ])


# Sibling successor runs this run never reads or writes, protected byte for
# byte. full_ext_recovery_002 is retired by the generic successor dispatch
# this run adds to pilot_run_contract.build_contract (its proof pins the
# previous bytes of that file).
SIBLINGS = OrderedDict([
    ("full_ext_recovery_002", OrderedDict([
        ("definitions", "thesis/evaluation/recovery/full_ext_recovery_002"),
        ("definition_files", ("contract.json", "equivalence.json", "lineage.json", "readiness.json")),
    ])),
])


def sibling_successors(root):
    """Retirement + byte inventory of every sibling successor run."""
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
        definitions = OrderedDict()
        for name in spec["definition_files"]:
            rel = "%s/%s" % (spec["definitions"], name)
            definitions[name] = OrderedDict([("path", rel), ("lf_sha256", lf_normalized_sha256_bytes(
                _read_bytes(root, rel)))])
        result[run] = OrderedDict([
            ("decision", "RETIRED_BY_GENERIC_SUCCESSOR_DISPATCH"),
            ("reason", "full_ext_recovery_003 adds the generic recovery_successor_NNN dispatch to "
                       "thesis/evaluation/pilot_run_contract.py (build_contract); the %s proof pins the "
                       "previous bytes of that file, so its contract no longer rebuilds and none of "
                       "its writers can run" % run),
            ("consequence", "%s results stay byte-frozen (protected_inventory); this run never reads "
                            "or writes them; later runs adopt them by reference only" % run),
            ("frozen_waves", waves),
            ("definitions", definitions),
            ("protected_inventory", inventory),
        ])
    return result


def build(root, config, snapshot_document=None):
    """Build (never persist) the lineage document from the live predecessor tree."""
    root = Path(root).resolve()
    if snapshot_document is None:
        snapshot_document = sh.build_snapshot(root)
    snapshot = sh.Snapshot(root, snapshot_document, snapshot_document["snapshot_sha256"])
    view = sh.PredecessorView(snapshot)
    handoff = OrderedDict()
    for model in MODELS:
        for variant in VARIANTS:
            handoff["%s/%s" % (model, variant)] = loop_handoff(view, config, model, variant)
    document = OrderedDict([
        ("schema_version", SCHEMA),
        ("run_id", SUCCESSOR),
        ("predecessor_run_id", PREDECESSOR),
        ("parent_run_id", PARENT),
        ("pilot_run_id", PILOT),
        ("model_ids", list(MODELS)),
        ("variants", list(VARIANTS)),
        ("max_iterations", MAX_ITERATIONS),
        ("successor_base_cells", 0),
        ("policy", POLICY),
        ("predecessor", predecessor_bindings(root, view)),
        ("predecessor_snapshot", snapshot_document),
        ("predecessor_retirement", predecessor_retirement(view)),
        ("sibling_successors", sibling_successors(root)),
        ("handoff", handoff),
    ])
    document["lineage_sha256"] = fingerprint(document)
    return document


class SuccessorLineage:
    """Loaded, self-hash-verified lineage with a bound predecessor view."""

    def __init__(self, root, document, expected_sha):
        self.root = Path(root).resolve()
        if (not expected_sha or document.get("lineage_sha256") != expected_sha
                or fingerprint(document) != expected_sha or document.get("schema_version") != SCHEMA
                or document.get("run_id") != SUCCESSOR
                or document.get("predecessor_run_id") != PREDECESSOR
                or document.get("parent_run_id") != PARENT
                or document.get("successor_base_cells") != 0
                or document.get("max_iterations") != MAX_ITERATIONS
                or document.get("model_ids") != list(MODELS)
                or document.get("policy") != POLICY):
            raise RecoveryRefused("invalid successor lineage binding")
        snapshot_document = document["predecessor_snapshot"]
        self.snapshot = sh.Snapshot(self.root, snapshot_document, snapshot_document.get("snapshot_sha256"))
        self.view = sh.PredecessorView(self.snapshot)
        self.document = document

    @property
    def sha256(self):
        return self.document["lineage_sha256"]

    def handoff(self, model, variant):
        try:
            return self.document["handoff"]["%s/%s" % (model, variant)]
        except KeyError:
            raise RecoveryRefused("model/variant outside the successor scope")

    def verify_quick(self):
        """Per provider call: full re-hash only if any predecessor file's
        (size, mtime_ns) or the membership changed since the last full
        verification in this process."""
        stats = _stats(self.root)
        key = (str(self.root), self.document["predecessor_snapshot"]["snapshot_sha256"])
        with _STAT_LOCK:
            if _VERIFIED_STATS.get(key) == stats:
                return True
        self.snapshot.verify_all()
        with _STAT_LOCK:
            _VERIFIED_STATS[key] = stats
        return True

    def verify(self, config=None, deep=False):
        """Predecessor bytes and membership unchanged; bindings reproduce.

        deep=True additionally rebuilds every handoff fact from the bytes."""
        self.snapshot.verify_all()
        with _STAT_LOCK:
            _VERIFIED_STATS[(str(self.root), self.document["predecessor_snapshot"]["snapshot_sha256"])] = _stats(self.root)
        bindings = predecessor_bindings(self.root, self.view)
        if bindings != self.document["predecessor"]:
            raise RecoveryRefused("predecessor bindings drifted")
        if deep:
            if config is None:
                raise RecoveryRefused("deep lineage verification needs the configuration")
            if predecessor_retirement(self.view) != self.document["predecessor_retirement"]:
                raise RecoveryRefused("predecessor retirement record drifted")
            self.verify_siblings()
            for model in MODELS:
                for variant in VARIANTS:
                    if loop_handoff(self.view, config, model, variant) != self.handoff(model, variant):
                        raise RecoveryRefused("handoff facts drifted for %s/%s" % (model, variant))
        return True


    def verify_siblings(self):
        """Every protected sibling successor run is byte-identical."""
        siblings = self.document.get("sibling_successors") or {}
        for run, record in siblings.items():
            sh.verify_protected(self.root, record["protected_inventory"])
        return OrderedDict((run, record["protected_inventory"]["file_count"])
                           for run, record in siblings.items())


_STAT_LOCK = threading.Lock()
_VERIFIED_STATS = {}


def _stats(root):
    """(relative path, size, mtime_ns) of every predecessor file, by directory
    scan without following links (one lstat per entry; the full path
    validation of checked_path runs in every full verification). A link
    anywhere in the predecessor trees refuses."""
    import os

    root = Path(root).resolve()

    def scan(directory):
        directories, files = [], []
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise RecoveryRefused("link in the predecessor trees: " + entry.path)
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
                if entry.name == sh.PREDECESSOR or entry.name.startswith(sh.PREDECESSOR + "__"):
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        raise RecoveryRefused("predecessor run is not a plain directory: " + entry.path)
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
