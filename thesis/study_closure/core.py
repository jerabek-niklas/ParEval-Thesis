"""Shared core of the study closure: identities, the run registry, the check
accumulator, the verification context and small read-only helpers.

Every section module (runs, study, coverage, acceptance, disclosures) takes
a Context and returns a Section; run.py assembles them into the closure
document (report.py). Nothing here writes.

Python 3.8 compatible syntax (main container, Python 3.12, is the only
productive interpreter; the native verifiers of the successors are imported
lazily by the section modules).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.condition_hashing import canonical_sha256  # noqa: E402
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402
from thesis.recovery_successor_005 import composite as pc  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.recovery_successor_005 import targets as pt  # noqa: E402

# -- identities -----------------------------------------------------------------------

CLOSURE_ID = "study_closure_001"
SCHEMA = "study_global_verification.v1"
SCOPE = "STUDY_GLOBAL_VERIFICATION_SEVEN_RUNS_READ_ONLY"
# the unique scope of the retrospective, read-only re-verification the closure
# performs for the runs without a persisted verification report (001, 002)
RETROSPECTIVE_SCOPE = "RETROSPECTIVE_READONLY_COVERAGE_OF_RECOVERY_001_002_BY_STUDY_CLOSURE_001"
DISCLOSURES_SCHEMA = "study_disclosure_register.v1"
ACCEPTANCE_READINESS_SCHEMA = "pilot_002_acceptance_readiness.v1"
PASS = "PASS"
FAIL = "FAIL"

PILOT = pl.PILOT                      # pilot_002
PARENT = pl.PARENT                    # full_ext_001
OWNERS = pl.OWNERS                    # full_ext_recovery_001..004
PHASE2 = pl.SUCCESSOR                 # full_ext_phase2_001
MODELS = pl.MODELS
VARIANTS = pl.VARIANTS
EXCLUDED_RUNS = pl.EXCLUDED_HISTORICAL_RUNS   # full_ext_001__static_feedback__iter1
# the seven runs in evidence order
RUNS = (PILOT, PARENT) + OWNERS + (PHASE2,)

INTERMEDIATE_REL = pt.INTERMEDIATE_REL
RAW_REL = pt.RAW_REL
ARTIFACT_DIR_REL = "thesis/evaluation/closure/" + CLOSURE_ID
COMPOSITE_REL = pc.DOCUMENT_REL                       # phase-2 results tree
PHASE2_RESULTS_REL = pl.RESULTS_REL
PHASE2_VERIFICATION_REL = PHASE2_RESULTS_REL + "/verification"
PILOT_POST_RUN_REL = INTERMEDIATE_REL + "/" + PILOT + "/post_run_verification.json"
PUBLICATION_POLICY_REL = "thesis/evaluation/pilot_002_publication_policy.json"
RESULT_ACCEPTANCE_REL = "thesis/evaluation/pilot_002_result_acceptance.json"
# result directories that exist but are outside the seven-run study
OUT_OF_STUDY_PREFIXES = ("pilot_001", "smoke_", "repair_smoke_", "model_check_")

# closure artifacts (relative to ARTIFACT_DIR_REL)
GLOBAL_JSON = "global_verification.json"
GLOBAL_MD = "global_verification.md"
DISCLOSURES_JSON = "disclosures.json"
DISCLOSURES_MD = "disclosures.md"
ACCEPTANCE_TEMPLATE = "pilot_002_result_acceptance.TEMPLATE.json"
ACCEPTANCE_READINESS = "pilot_002_acceptance_readiness.json"
STATUS_MD = "IMPLEMENTATION_STATUS.md"

# -- run registry ---------------------------------------------------------------------
# role: how the run contributes evidence; block: which population block;
# config/profile: the run's own configuration (post-run reads only);
# contract: the FROZEN contract (self-hashed), the authority of the run;
# definitions: the frozen definition directory (successors only);
# verification: where the run's own persisted verification evidence lives
# (None = no persisted report; documented by coverage.py).


def _run(role, block, config, profile, contract, definitions, verification, verifier):
    return OrderedDict([("role", role), ("block", block), ("config", config), ("profile", profile),
                        ("contract", contract), ("definitions", definitions),
                        ("verification", verification), ("verifier", verifier)])


RUN_REGISTRY = OrderedDict([
    (PILOT, _run("pilot block: base cells, repair loops and candidates, complete phase 2", "pilot",
                 "thesis/config/config.yaml", "pilot",
                 INTERMEDIATE_REL + "/" + PILOT + "/run_contract.json", None,
                 PILOT_POST_RUN_REL, "thesis/evaluation/verify_pilot_run.py (post_run_verification.v1)")),
    (PARENT, _run("full-extension base cells (iteration 0); its aborted repair is excluded", "full_ext",
                  "thesis/config/config.yaml", "full_extension",
                  INTERMEDIATE_REL + "/" + PARENT + "/run_contract.json", None,
                  "thesis/evaluation/recovery/full_ext_recovery_001/parent_report.json",
                  "thesis/evaluation/verify_parent_base_evidence.py (parent_base_evidence_report.v1, "
                  "BASE_ONLY scope, frozen with recovery_001)")),
    (OWNERS[0], _run("full-extension repair origin: 6 terminal test_feedback loops, iteration 1 of the "
                     "12 continued static/combined loops", "full_ext",
                     "thesis/config/recovery.yaml", "recovery",
                     "thesis/evaluation/recovery/full_ext_recovery_001/contract.json",
                     "thesis/evaluation/recovery/full_ext_recovery_001", None,
                     "thesis/evaluation/verify_recovery_run.py (never persisted; acceptance predicate "
                     "33/33 within recovery_001 unsatisfiable after the successor handoff)")),
    (OWNERS[1], _run("successor: 4 continued loops (iteration 2) of deepseek_v4_flash, qwen3_coder_api; "
                     "2 adopted test_feedback loops; LLOV supplements of iteration 1", "full_ext",
                     "thesis/config/recovery_successor.yaml", "recovery_successor",
                     "thesis/evaluation/recovery/full_ext_recovery_002/contract.json",
                     "thesis/evaluation/recovery/full_ext_recovery_002", None,
                     "thesis/evaluation/verify_successor_run.py (in-process PASS, no persisted report)")),
    (OWNERS[2], _run("successor: 8 continued loops (iteration 2) of claude_fable_5, claude_opus_5, "
                     "gemini_31_pro, openai_gpt55; 4 adopted test_feedback loops; PARCOACH/LLOV "
                     "supplements of iteration 1", "full_ext",
                     "thesis/config/recovery_successor_003.yaml", "recovery_successor_003",
                     "thesis/evaluation/recovery/full_ext_recovery_003/contract.json",
                     "thesis/evaluation/recovery/full_ext_recovery_003",
                     INTERMEDIATE_REL + "/full_ext_recovery_003/verification",
                     "thesis/recovery_successor_003/verify.py (successor_model_verification.v1)")),
    (OWNERS[3], _run("successor: 15 fresh loops of deepseek_v4_pro, gemini_36_flash, openai_gpt56_sol, "
                     "qwen36_35b_a3b, qwen37_max", "full_ext",
                     "thesis/config/recovery_successor_004.yaml", "recovery_successor_004",
                     "thesis/evaluation/recovery/full_ext_recovery_004/contract.json",
                     "thesis/evaluation/recovery/full_ext_recovery_004",
                     INTERMEDIATE_REL + "/full_ext_recovery_004/verification",
                     "thesis/recovery_successor_004/verify.py (successor_model_verification.v1)")),
    (PHASE2, _run("phase 2: backfill (correctness/dynamic of static_feedback, static tools of "
                  "test_feedback) and held-out enhanced tests of every full-extension candidate",
                  "full_ext", "thesis/config/recovery_successor_005.yaml", "recovery_successor_005",
                  "thesis/evaluation/recovery/full_ext_phase2_001/contract.json",
                  "thesis/evaluation/recovery/full_ext_phase2_001", PHASE2_VERIFICATION_REL,
                  "thesis/recovery_successor_005/verify.py (phase2_model_verification.v1)")),
])

# modules whose behaviour the closure relies on (pinned in the report)
REUSED_MODULES = (
    "thesis/recovery_successor_005/composite.py", "thesis/recovery_successor_005/verify.py",
    "thesis/recovery_successor_005/plan.py", "thesis/recovery_successor_005/ledger.py",
    "thesis/recovery_successor_005/targets.py", "thesis/recovery_successor_005/lineage.py",
    "thesis/recovery_successor_004/census.py", "thesis/recovery_successor_004/verify.py",
    "thesis/recovery_successor_003/verify.py", "thesis/evaluation/verify_successor_run.py",
    "thesis/evaluation/verify_pilot_run.py", "thesis/evaluation/pilot_freeze.py",
    "thesis/evaluation/pilot_run_contract.py", "thesis/evaluation/run_authorization.py",
    "thesis/evaluation/manifest_fragments.py", "thesis/evaluation/stage_runtime.py",
    "thesis/evaluation/composite_study.py", "thesis/evaluation/condition_hashing.py",
)


class ClosureRefused(RecoveryRefused):
    """The closure cannot proceed (integrity, ownership or state problem)."""


# -- small helpers --------------------------------------------------------------------

def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(root, relative):
    path = checked_path(Path(root).resolve(), relative)
    if not path.is_file():
        raise ClosureRefused("missing artifact: " + relative)
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def read_jsonl(root, relative):
    return pt.read_jsonl(root, relative)


def raw_sha256(root, relative):
    path = checked_path(Path(root).resolve(), relative)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lf_sha256(root, relative):
    """sha256 of the LF-normalised text (host-independent source pin)."""
    path = checked_path(Path(root).resolve(), relative)
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def short(value, n=12):
    return str(value)[:n] if value is not None else None


def git_state(root):
    """HEAD, branch, clean flag and the uncommitted paths (porcelain)."""
    root = Path(root).resolve()
    git = ["git", "-c", "safe.directory=" + root.as_posix(), "-C", str(root)]
    head = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    try:
        branch = subprocess.check_output(git + ["rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    except subprocess.CalledProcessError:
        branch = None
    status = subprocess.check_output(git + ["status", "--porcelain"], text=True)
    paths = sorted(line[3:].strip() for line in status.splitlines() if line.strip())
    return OrderedDict([("head", head), ("branch", branch), ("clean", not paths),
                        ("uncommitted_paths", paths[:50]), ("uncommitted_count", len(paths))])


def closure_source_pins(root):
    """LF sha256 of every closure module and of every reused module."""
    root = Path(root).resolve()
    package = sorted(p for p in (root / "thesis/study_closure").glob("*.py"))
    pins = OrderedDict()
    for path in package:
        relative = path.relative_to(root).as_posix()
        pins[relative] = lf_sha256(root, relative)
    reused = OrderedDict((relative, lf_sha256(root, relative)) for relative in REUSED_MODULES)
    return OrderedDict([("closure", pins), ("reused", reused)])


# -- check accumulation ------------------------------------------------------------------

class Section:
    """Checks of one closure section. add()/guard() mirror the phase-2
    verifier: every exception is a FAIL with its message (fail-closed)."""

    def __init__(self, name):
        self.name = name
        self.checks = []
        self.data = OrderedDict()

    def add(self, check_id, ok, detail=None):
        self.checks.append(OrderedDict([("check", "%s:%s" % (self.name, check_id)),
                                        ("status", PASS if ok else FAIL), ("detail", detail)]))
        return bool(ok)

    def guard(self, check_id, function, *args, **kwargs):
        """function returns (ok, detail); an exception is a FAIL."""
        try:
            ok, detail = function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - every failure is reported
            return self.add(check_id, False, "%s: %s" % (type(error).__name__, error))
        return self.add(check_id, ok, detail)

    def failing(self):
        return [c["check"] for c in self.checks if c["status"] != PASS]

    @property
    def status(self):
        return PASS if self.checks and not self.failing() else FAIL

    def document(self):
        return OrderedDict([("section", self.name), ("status", self.status),
                            ("checks", len(self.checks)), ("failing", self.failing()),
                            ("data", self.data), ("check_list", self.checks)])


# -- context -----------------------------------------------------------------------------

class Context:
    """Shared state of one closure invocation: the phase-2 config (loaded
    under provider isolation), lazily the phase-2 lineage and target table,
    per-run configs/manifests/contracts, and a cache for expensive shared
    results (e.g. the lineage verification, the composite cells)."""

    def __init__(self, root, config, config_path, options=None, log=None):
        self.root = Path(root).resolve()
        self.config = config
        self.config_path = str(config_path)
        self.options = OrderedDict(options or {})
        self._log = log or (lambda message: None)
        self.cache = OrderedDict()
        self._lineage = None
        self._table = None
        self._run_configs = OrderedDict()
        self.started_utc = utc_now()
        self.timings = OrderedDict()

    def log(self, message):
        self._log(message)

    def timed(self, key, function, *args, **kwargs):
        start = time.time()
        try:
            return function(*args, **kwargs)
        finally:
            self.timings[key] = round(time.time() - start, 3)

    @property
    def lineage(self):
        if self._lineage is None:
            self._lineage = pl.load(self.root)
        return self._lineage

    @property
    def table(self):
        if self._table is None:
            self._table = pt.load_table(self.root, self.lineage.targets_sha256)
        return self._table

    def run_config(self, run_id):
        """The run's own config, loaded under provider isolation and scrubbed
        (post-run reads only; never used for a provider request)."""
        if run_id not in self._run_configs:
            from thesis.config.load_config import load_config

            entry = RUN_REGISTRY[run_id]
            pl.isolate_providers()
            config = load_config(str((self.root / entry["config"]).resolve()))
            pl.scrub_provider_environment(config)
            self._run_configs[run_id] = config
        return self._run_configs[run_id]

    def manifest(self, run_id):
        return read_json(self.root, "%s/%s/run_manifest.json" % (INTERMEDIATE_REL, run_id))

    def frozen_contract(self, run_id):
        """The run's frozen contract, self-hash verified (pilot_run_contract.load_frozen)."""
        from thesis.evaluation import pilot_run_contract as prc

        return prc.load_frozen(checked_path(self.root, RUN_REGISTRY[run_id]["contract"]))

    def authorization_fragment(self, run_id):
        return read_json(self.root, "%s/%s/run_manifest.fragments/authorization.start.json"
                         % (INTERMEDIATE_REL, run_id))


def load_context(root=REPO_ROOT, options=None, log=None, config_rel=pl.CONFIG_REL):
    """Context over the phase-2 config (the config of the composite view)."""
    from thesis.config.load_config import load_config

    root = Path(root).resolve()
    pl.isolate_providers()
    config_path = (root / config_rel).resolve()
    config = load_config(str(config_path))
    pl.scrub_provider_environment(config)
    return Context(root, config, config_path, options=options, log=log)


def self_hash(document, field):
    """sha_rule of the pilot artifacts: canonical sha256 of the document
    without `volatile` and without the self-hash field."""
    body = OrderedDict((k, v) for k, v in document.items() if k not in ("volatile", field))
    return canonical_sha256(body)


def json_stable(value):
    return json.loads(json.dumps(value, default=str), object_pairs_hook=OrderedDict)
