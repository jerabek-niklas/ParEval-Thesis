"""Post-run verification (verify_pilot_run.v1).

Checks a finished run against its FROZEN contract (pilot_run_contract.py)
and against the evidence on disk, and writes post_run_verification.json.
Read-only: it never repairs, backfills or rewrites anything.

Every check reports PASS / FAIL / UNRESOLVED:

  PASS        the evidence proves the property
  FAIL        the evidence contradicts it (drift, gap, missing artifact)
  UNRESOLVED  the evidence needed to decide is absent (e.g. no runtime
              evidence was bound at T0) - never silently a PASS

Checked (per the pre-run contract):

  identity     run_id, base run is not a repair-iteration run, contract sha
               bound to the run BEFORE execution, model set EXACTLY the
               contracted one (missing AND extra models fail)
  population   per model: sample count, selected prompt keys, and the
               per-record prompt fingerprint against the contract's map
  invocation   execution models, primary compiler, run timeout
  assembly     per model: coverage, duplicates, orphans, source exists,
               raw bytes == recorded source_sha256, per-model
               assembly_set_sha256 and the assembly condition
  correctness  a correctness record per assembled sample
  static       a static record per assembled sample WITH an entry per
               required tool: a MISSING ENTRY fails; a terminal gap state
               (PARTIAL / NOT_ANALYZED / TOOL_ERROR / TIMEOUT) is a
               COVERAGE LIMITATION - the invocation completed, so it does
               not fail the run
  enhanced     exact (sample_id, spec_key) coverage against the contracted
               spec set, and candidate-source drift against the registered
               model execution fingerprint
  repair       verified separately; iteration artifacts are never counted
               as base population
  runtime      the runtime evidence bound at T0 vs the contract (a
               retrospective live measurement is additional diagnosis only,
               never a substitute)

    python thesis/evaluation/verify_pilot_run.py --config thesis/config/config.yaml \
        --run-id pilot_002 --contract <frozen.json> [--out post_run_verification.json]

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import condition_hashing as ch  # noqa: E402

VERIFIER_VERSION = "verify_pilot_run.v1"
PASS = "PASS"
FAIL = "FAIL"
UNRESOLVED = "UNRESOLVED"

# tool states that mean "the invocation completed but produced no
# trustworthy verdict" - a coverage limitation, not a missing artifact
TERMINAL_GAP_STATES = ("PARTIAL", "NOT_ANALYZED", "TOOL_ERROR", "TIMEOUT", "NOT_APPLICABLE")


class Report:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.checks: "List[OrderedDict[str, Any]]" = []

    def add(self, check_id: str, status: str, detail: str,
            evidence: "Optional[Dict[str, Any]]" = None) -> str:
        self.checks.append(OrderedDict([
            ("check", check_id), ("status", status), ("detail", detail),
            ("evidence", evidence or {}),
        ]))
        return status

    def status(self) -> str:
        statuses = [c["status"] for c in self.checks]
        if FAIL in statuses:
            return FAIL
        if UNRESOLVED in statuses:
            return UNRESOLVED
        return PASS

    def counts(self) -> "OrderedDict[str, int]":
        counter = Counter(c["status"] for c in self.checks)
        return OrderedDict([(s, counter.get(s, 0)) for s in (PASS, FAIL, UNRESOLVED)])


def _iter_jsonl(path: Path):
    if not Path(path).is_file():
        return
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def _sample_prompt_key(record: Dict[str, Any]) -> str:
    prompt = record.get("prompt") or {}
    return "%s|%s|%s" % (prompt.get("problem_type"), prompt.get("name"),
                         prompt.get("parallelism_model"))


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def check_identity(report: Report, run_id: str, contract: "Optional[Dict[str, Any]]",
                   manifest: "Optional[Dict[str, Any]]") -> None:
    if contract is None:
        report.add("contract_present", UNRESOLVED,
                   "no frozen contract given - contract-derived checks cannot be decided")
        return
    report.add("contract_present", PASS, "frozen contract loaded and self-consistent",
               {"contract_sha256": contract.get("contract_sha256")})

    expected_run = contract.get("run_id")
    report.add("run_id_matches_contract", PASS if run_id == expected_run else FAIL,
               "run_id %r vs contract %r" % (run_id, expected_run),
               {"run_id": run_id, "contract_run_id": expected_run})

    is_iteration = "__iter" in (run_id or "")
    report.add("base_run_is_not_a_repair_iteration", FAIL if is_iteration else PASS,
               "base run id %r" % run_id)

    bound = (manifest or {}).get("contract_sha256")
    if bound is None:
        report.add("contract_sha_bound_to_run", UNRESOLVED,
                   "the run manifest records no contract sha - it cannot be shown that the "
                   "contract was bound BEFORE the first request")
    else:
        report.add("contract_sha_bound_to_run",
                   PASS if bound == contract.get("contract_sha256") else FAIL,
                   "manifest contract sha %s... vs frozen %s..."
                   % (str(bound)[:12], str(contract.get("contract_sha256"))[:12]),
                   {"manifest": bound, "frozen": contract.get("contract_sha256")})


def check_conditions(report: Report, contract: "Optional[Dict[str, Any]]",
                     manifest: "Optional[Dict[str, Any]]") -> None:
    """Every condition the contract pins and the run can register must match.
    A run that executed under a different static-analysis or repair condition
    is a different experiment, however complete its coverage looks."""
    if contract is None:
        return
    contracted = contract.get("conditions") or {}
    m = manifest or {}
    pairs = [
        ("static_analysis_condition_sha256", m.get("static_analysis_condition_sha256")),
        ("repair_condition_sha256", m.get("repair_condition_sha256")),
        ("assembly_condition_sha256", m.get("assembly_condition_sha256")),
        ("enhanced_frozen_specs_sha256", (m.get("enhanced_specs") or {}).get("sha256")),
        ("static_repair_runtime_condition_sha256",
         (m.get("runtime_evidence") or {}).get("static_repair_runtime_condition_sha256")),
    ]
    mismatches = []
    unresolved = []
    for field, recorded in pairs:
        expected = contracted.get(field)
        if expected is None:
            continue
        if recorded is None:
            unresolved.append(field)
        elif recorded != expected:
            mismatches.append(OrderedDict([("field", field), ("contract", expected),
                                           ("run", recorded)]))
    if mismatches:
        status = FAIL
    elif unresolved:
        status = UNRESOLVED
    else:
        status = PASS
    report.add("contracted_conditions_registered", status,
               "%d condition(s) differ from the contract; %d not registered by the run"
               % (len(mismatches), len(unresolved)),
               {"mismatches": mismatches, "not_registered": unresolved})

    # profile identity: the contract describes ONE planned invocation
    if manifest is not None and contract.get("profile") is not None:
        recorded_profile = manifest.get("profile")
        report.add("profile_matches_contract",
                   PASS if recorded_profile == contract["profile"] else FAIL,
                   "manifest profile %r vs contract %r" % (recorded_profile, contract["profile"]))


def check_invocation(report: Report, contract: "Optional[Dict[str, Any]]",
                     manifest: "Optional[Dict[str, Any]]") -> None:
    if contract is None:
        return
    if manifest is None:
        report.add("invocation_parameters", UNRESOLVED, "no run manifest for this run")
        return
    frozen = manifest.get("resolved_config") or {}
    compiler = manifest.get("primary_compiler")
    report.add("primary_compiler", PASS if compiler == contract.get("primary_compiler") else FAIL,
               "manifest %r vs contract %r" % (compiler, contract.get("primary_compiler")))
    timeout = ((frozen.get("stages") or {}).get("correctness_tests") or {}).get("run_timeout_seconds")
    report.add("run_timeout_seconds", PASS if timeout == contract.get("run_timeout_seconds") else FAIL,
               "manifest %r vs contract %r" % (timeout, contract.get("run_timeout_seconds")))
    execution_models = ((frozen.get("prompts") or {}).get("execution_models"))
    report.add("execution_models",
               PASS if execution_models == contract.get("execution_models") else FAIL,
               "manifest %r vs contract %r" % (execution_models, contract.get("execution_models")))


def check_model_set(report: Report, contract: "Optional[Dict[str, Any]]",
                    observed_models: "List[str]") -> "List[str]":
    if contract is None:
        return observed_models
    expected = list(contract.get("model_ids") or [])
    missing = sorted(set(expected) - set(observed_models))
    extra = sorted(set(observed_models) - set(expected))
    status = PASS if not missing and not extra else FAIL
    report.add("model_set_exact", status,
               "missing: %s; unexpected: %s" % (missing or "none", extra or "none"),
               {"expected": expected, "observed": sorted(observed_models)})
    return expected


def check_population(report: Report, raw_dir: Path, run_id: str, model_id: str,
                     contract: "Optional[Dict[str, Any]]") -> None:
    if contract is None:
        return
    population = contract.get("population") or {}
    records = list(_iter_jsonl(raw_dir / run_id / model_id / "generations.jsonl"))
    expected_count = population.get("expected_sample_count")
    if expected_count is None:
        report.add("population_count:%s" % model_id, UNRESOLVED,
                   "the contract carries no expected sample count")
    else:
        report.add("population_count:%s" % model_id,
                   PASS if len(records) == expected_count else FAIL,
                   "%d generation record(s) vs contracted %d" % (len(records), expected_count))

    expected_keys = set(population.get("selected_prompt_keys") or [])
    observed_keys = set(_sample_prompt_key(r) for r in records)
    if expected_keys:
        missing = sorted(expected_keys - observed_keys)
        extra = sorted(observed_keys - expected_keys)
        report.add("population_selection:%s" % model_id,
                   PASS if not missing and not extra else FAIL,
                   "prompts missing: %d; outside the contracted population: %d"
                   % (len(missing), len(extra)),
                   {"missing": missing[:20], "unexpected": extra[:20]})

    # per-record prompt fingerprints against the contract's map: the text a
    # record was actually generated from must be the contracted text
    observed = OrderedDict()
    for record in records:
        observed[_sample_prompt_key(record)] = ch.utf8_sha256(
            ((record.get("prompt") or {}).get("prompt_text")) or "")
    drifted = _prompt_subset_matches(population, observed)
    if drifted is None:
        report.add("prompt_fingerprints:%s" % model_id, UNRESOLVED,
                   "the contract carries no per-prompt map to compare against "
                   "(prompt set sha %s...)" % str(population.get("prompt_set_sha256"))[:12],
                   {"observed_subset_sha256": ch.canonical_sha256(observed)})
    else:
        report.add("prompt_fingerprints:%s" % model_id, PASS if not drifted else FAIL,
                   "%d prompt(s) differ from the contracted text" % len(drifted),
                   {"drifted": drifted[:20]})


def _prompt_subset_matches(population: Dict[str, Any],
                           observed: "Dict[str, str]") -> "Optional[List[str]]":
    """Compare the observed per-prompt hashes with the contract's map.
    Returns the drifted keys, or None when the contract has no map."""
    contracted = population.get("prompt_hashes")
    if not contracted:
        return None
    drifted = []
    for key, sha in observed.items():
        expected = contracted.get(key)
        if expected is not None and expected != sha:
            drifted.append(key)
    return drifted


def check_assembly(report: Report, intermediate: Path, run_id: str, model_id: str,
                   manifest: "Optional[Dict[str, Any]]",
                   contract: "Optional[Dict[str, Any]]",
                   generation_sample_ids: "Optional[List[str]]" = None
                   ) -> "List[Dict[str, Any]]":
    from thesis.assembly import assembly_provenance as ap

    model_dir = intermediate / run_id / model_id
    entries = ap.load_assembly_entries(model_dir / "assembly.jsonl")
    # every assembly record must correspond to a generation record of this
    # run: an assembly record without one is fabricated candidate code
    verification = ap.verify_assembly(model_dir, entries=entries,
                                      expected_sample_ids=generation_sample_ids)
    status = {"PASS": PASS, "FAIL": FAIL}.get(verification["status"], UNRESOLVED)
    detail = "; ".join(verification["problems"]) if verification["problems"] else (
        "%d assembled, %d skipped, sources match their recorded hashes"
        % (verification["assembled"], verification["skipped"]))
    if verification["status"] == ap.LEGACY_ASSEMBLY_CLASS:
        detail = ("legacy %s: %d assembled record(s) carry no source hash - the assembled "
                  "bytes cannot be verified" % (ap.LEGACY_ASSEMBLY_CLASS,
                                                len(verification["legacy_unpinned"])))
    report.add("assembly_integrity:%s" % model_id, status, detail, verification)

    recomputed = ap.assembly_set_sha256(entries)
    registered = ((manifest or {}).get("assembly_model_sets") or {}).get(model_id) or {}
    if not registered:
        report.add("assembly_set_registered:%s" % model_id, UNRESOLVED,
                   "the run manifest records no assembly set for this model")
    else:
        report.add("assembly_set_registered:%s" % model_id,
                   PASS if registered.get("assembly_set_sha256") == recomputed else FAIL,
                   "manifest %s... vs recomputed %s..."
                   % (str(registered.get("assembly_set_sha256"))[:12], recomputed[:12]),
                   {"manifest": registered.get("assembly_set_sha256"), "recomputed": recomputed})
        if contract is not None:
            contracted = (contract.get("conditions") or {}).get("assembly_condition_sha256")
            report.add("assembly_condition:%s" % model_id,
                       PASS if registered.get("assembly_condition_sha256") == contracted else FAIL,
                       "manifest %s... vs contract %s..."
                       % (str(registered.get("assembly_condition_sha256"))[:12],
                          str(contracted)[:12]))
    return [e for e in entries if e.get("assembled")]


def check_evaluated_population(report: Report, model_id: str,
                               records: "List[Dict[str, Any]]",
                               assembled: "List[Dict[str, Any]]",
                               contract: "Optional[Dict[str, Any]]") -> None:
    """Coverage checks below are relative to the ASSEMBLED set, so a run in
    which nothing (or almost nothing) was assembled would otherwise pass them
    vacuously. Every SUCCESSFUL generation must have produced a source, and a
    contracted population must not end up with an empty evaluated set."""
    successful = [r for r in records if (r.get("status") or {}).get("success")]
    assembled_ids = {e["sample_id"] for e in assembled}
    missing = sorted(r["sample_id"] for r in successful if r["sample_id"] not in assembled_ids)
    report.add("assembly_covers_successful_generations:%s" % model_id,
               PASS if not missing else FAIL,
               "%d successful generation(s) without an assembled source (of %d successful, "
               "%d records)" % (len(missing), len(successful), len(records)),
               {"missing": missing[:20]})
    expected = ((contract or {}).get("population") or {}).get("expected_sample_count")
    if expected:
        report.add("evaluated_population_not_empty:%s" % model_id,
                   PASS if assembled else FAIL,
                   "%d of %d contracted sample(s) reached the evaluated (assembled) set"
                   % (len(assembled_ids), expected))


def check_correctness(report: Report, intermediate: Path, run_id: str, model_id: str,
                      assembled: "List[Dict[str, Any]]") -> None:
    records = {r.get("sample_id"): r for r in
               _iter_jsonl(intermediate / run_id / model_id / "correctness.jsonl")}
    missing = sorted(e["sample_id"] for e in assembled if e["sample_id"] not in records)
    report.add("correctness_coverage:%s" % model_id, PASS if not missing else FAIL,
               "%d assembled sample(s) without a correctness record" % len(missing),
               {"missing": missing[:20], "records": len(records)})


def check_static(report: Report, config: Dict[str, Any], intermediate: Path, run_id: str,
                 model_id: str, assembled: "List[Dict[str, Any]]") -> None:
    from thesis.evaluation import framework
    from thesis.evaluation.tool_config import resolve_tool_settings

    settings = resolve_tool_settings(config, "static_analysis")
    records = {r.get("sample_id"): r for r in
               _iter_jsonl(intermediate / run_id / model_id / "static_analysis.jsonl")}
    missing_records: "List[str]" = []
    missing_entries: "List[str]" = []
    coverage_limitations = Counter()
    for entry in assembled:
        sample_id = entry["sample_id"]
        execution_model = entry.get("execution_model") or sample_id.split("__")[-2]
        required = [name for name, s in settings.items()
                    if s.enabled and execution_model in s.execution_models]
        record = records.get(sample_id)
        if record is None:
            missing_records.append(sample_id)
            continue
        tools = record.get("tools") or {}
        for tool in required:
            if tool not in tools:
                missing_entries.append("%s/%s" % (sample_id, tool))
                continue
            state, _reason = framework.effective_tool_state(record, tool)
            state = state[0] if isinstance(state, tuple) else state
            if state in TERMINAL_GAP_STATES:
                coverage_limitations[tool] += 1
    status = PASS if not missing_records and not missing_entries else FAIL
    report.add("static_coverage:%s" % model_id, status,
               "%d sample(s) without a static record; %d missing tool entr(y/ies); "
               "%d terminal coverage limitation(s) (invocation completed - reported, "
               "not a failure)" % (len(missing_records), len(missing_entries),
                                   sum(coverage_limitations.values())),
               {"missing_records": missing_records[:20],
                "missing_entries": missing_entries[:20],
                "coverage_limitations": dict(coverage_limitations)})


def check_enhanced(report: Report, config: Dict[str, Any], intermediate: Path, run_id: str,
                   model_id: str, assembled: "List[Dict[str, Any]]",
                   contract: "Optional[Dict[str, Any]]",
                   manifest: "Optional[Dict[str, Any]]") -> None:
    from thesis.enhanced_tests.specs import build_benchmark_specs, spec_key
    from thesis.evaluation.run_enhanced_tests import load_llm_specs

    stage = (config.get("stages") or {}).get("enhanced_tests") or {}
    execution_models = stage.get("execution_models") or ["serial"]
    specs_path = None
    if contract is not None:
        specs_path = (contract.get("conditions") or {}).get("enhanced_frozen_specs_path")
    specs_path = Path(specs_path or stage.get("specs_file") or "")
    if not specs_path.is_absolute():
        specs_path = REPO_ROOT / specs_path
    if not specs_path.is_file():
        report.add("enhanced_coverage:%s" % model_id, UNRESOLVED,
                   "the contracted spec file is missing: %s" % specs_path)
        return

    llm_specs = load_llm_specs(specs_path)
    observed = set()
    unkeyable = 0
    for record in _iter_jsonl(intermediate / run_id / model_id / "enhanced_tests.jsonl"):
        spec = record.get("spec") or {}
        try:
            observed.add((record.get("sample_id"), spec_key(spec)))
        except (KeyError, TypeError, ValueError):
            # a record whose spec cannot be keyed is neither expected nor
            # unexpected - it must not become invisible
            unkeyable += 1

    expected = set()
    not_parameterizable = 0
    for entry in assembled:
        sample_id = entry["sample_id"]
        execution_model = entry.get("execution_model") or sample_id.split("__")[-2]
        if execution_model not in execution_models:
            continue
        benchmark = entry.get("benchmark")
        if not benchmark:
            parts = sample_id.split("__")
            benchmark = "%s/%s" % (parts[-4], parts[-3]) if len(parts) >= 4 else None
        cpu_cc = REPO_ROOT / "drivers" / "cpp" / "benchmarks" / str(benchmark) / "cpu.cc"
        if not cpu_cc.is_file() or "ENHANCED_TEST_SIZE_DEFAULT" not in cpu_cc.read_text(encoding="utf-8"):
            not_parameterizable += 1
            continue
        for spec in build_benchmark_specs(benchmark, llm_specs.get(benchmark, []), config):
            expected.add((sample_id, spec_key(spec)))

    missing = sorted("%s|%s" % (s, k) for s, k in (expected - observed))
    unexpected = sorted("%s|%s" % (s, k) for s, k in (observed - expected))
    status = PASS if not missing and not unexpected and not unkeyable else FAIL
    report.add("enhanced_coverage:%s" % model_id, status,
               "%d expected (sample, spec_key) pair(s) missing; %d not in the contracted "
               "spec set; %d record(s) whose spec cannot be keyed; %d sample(s) on "
               "non-parameterizable benchmarks"
               % (len(missing), len(unexpected), unkeyable, not_parameterizable),
               {"expected": len(expected), "observed": len(observed),
                "unkeyable_records": unkeyable,
                "missing": missing[:10], "unexpected": unexpected[:10]})

    check_enhanced_source_drift(report, intermediate, run_id, model_id, manifest)


def check_enhanced_source_drift(report: Report, intermediate: Path, run_id: str,
                                model_id: str, manifest: "Optional[Dict[str, Any]]") -> None:
    """Recompute the model execution fingerprint from the STORED global
    fingerprint plus the CURRENT candidate sources: a difference means the
    candidate code changed after the enhanced run."""
    from thesis.enhanced_tests import execution_provenance as ep

    recorded = ((manifest or {}).get("model_execution_fingerprints") or {}).get(model_id)
    global_fingerprint = (manifest or {}).get("enhanced_execution")
    if recorded is None or not global_fingerprint:
        report.add("enhanced_source_drift:%s" % model_id, UNRESOLVED,
                   "no registered model execution fingerprint for this model - "
                   "candidate-source drift cannot be decided")
        return
    candidate = ep.candidate_source_fingerprint(intermediate, run_id, model_id, REPO_ROOT)
    current = ep.model_fingerprint_sha(
        ep.model_execution_fingerprint(global_fingerprint, candidate))
    report.add("enhanced_source_drift:%s" % model_id, PASS if current == recorded else FAIL,
               "registered %s... vs recomputed %s..." % (str(recorded)[:12], str(current)[:12]),
               {"registered": recorded, "recomputed": current})


def check_repair(report: Report, config: Dict[str, Any], intermediate: Path, run_id: str,
                 model_ids: "List[str]", assembled_by_model: "Dict[str, List[str]]") -> None:
    """Repair evidence is verified SEPARATELY from the base population: an
    iteration artifact is never counted as a base sample."""
    from thesis.repair import orchestrator

    settings = orchestrator.repair_settings(config)
    iteration_runs = sorted(p.name for p in intermediate.iterdir()
                            if p.is_dir() and p.name.startswith(run_id + "__"))
    leaked = []
    for model_id in model_ids:
        base = set(assembled_by_model.get(model_id) or [])
        for iteration_run in iteration_runs:
            entries = list(_iter_jsonl(intermediate / iteration_run / model_id / "assembly.jsonl"))
            for entry in entries:
                if entry.get("assembled") and entry.get("run_id") == run_id:
                    leaked.append("%s/%s" % (iteration_run, entry.get("sample_id")))
        # a base sample must not be sourced from an iteration directory
        for sample_id in base:
            source = intermediate / run_id / model_id / "sources" / sample_id
            if not source.is_dir():
                leaked.append("%s (base source outside the base run dir)" % sample_id)
    report.add("repair_iterations_separate_from_base", PASS if not leaked else FAIL,
               "%d iteration run(s) inspected; %d leak(s) into the base population"
               % (len(iteration_runs), len(leaked)),
               {"iteration_runs": iteration_runs, "leaks": leaked[:20],
                "variants": settings.get("variants")})


def check_runtime(report: Report, manifest: "Optional[Dict[str, Any]]",
                  contract: "Optional[Dict[str, Any]]") -> None:
    evidence = (manifest or {}).get("runtime_evidence")
    if not evidence:
        report.add("runtime_evidence_bound_at_t0", UNRESOLVED,
                   "no runtime evidence was registered at T0 - the runtime the run "
                   "executed under cannot be proven; a live measurement now is "
                   "additional diagnosis only, never a substitute")
        return
    if contract is None:
        report.add("runtime_evidence_bound_at_t0", UNRESOLVED,
                   "runtime evidence present but no contract to compare it with")
        return
    conditions = contract.get("conditions") or {}
    mismatches = []
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        mismatches.append("contract_sha256")
    if evidence.get("static_repair_runtime_condition_sha256") != \
            conditions.get("static_repair_runtime_condition_sha256"):
        mismatches.append("static_repair_runtime_condition_sha256")
    report.add("runtime_evidence_bound_at_t0", PASS if not mismatches else FAIL,
               "runtime evidence %s" % ("matches the contract" if not mismatches
                                        else "differs in: " + ", ".join(mismatches)),
               {"mismatches": mismatches})


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def verify(config: Dict[str, Any], run_id: str,
           contract_path: "Optional[Path]" = None,
           skip_enhanced: bool = False) -> "OrderedDict[str, Any]":
    from thesis.analysis_overview.report_contracts import effective_config
    from thesis.evaluation.pilot_run_contract import load_frozen
    from thesis.evaluation.run_manifest import load_manifest

    report = Report(run_id)
    contract = None
    if contract_path is not None:
        try:
            contract = load_frozen(Path(contract_path))
        except Exception as exc:  # noqa: BLE001
            report.add("contract_present", FAIL, "frozen contract unusable: %s" % exc)
    manifest = load_manifest(config, run_id)
    intermediate = Path(config["outputs"]["intermediate_dir"])
    raw = Path(config["outputs"]["raw_dir"])
    # stage settings (required static tools, enhanced execution models and
    # spec settings) come from the FROZEN manifest, never from a live config
    # that may have changed since the run; only the paths stay live
    config, config_source = effective_config(config, manifest)
    report.add("config_source", PASS if config_source == "MANIFEST" else UNRESOLVED,
               "stage settings taken from %s" % config_source)

    check_identity(report, run_id, contract, manifest)
    check_invocation(report, contract, manifest)
    check_conditions(report, contract, manifest)

    raw_run = raw / run_id
    observed_models = sorted(p.name for p in raw_run.iterdir()
                             if p.is_dir() and (p / "generations.jsonl").is_file()) \
        if raw_run.is_dir() else []
    models = check_model_set(report, contract, observed_models)
    models = sorted(set(models) | set(observed_models)) if contract else observed_models

    assembled_by_model: "Dict[str, List[str]]" = {}
    for model_id in models:
        check_population(report, raw, run_id, model_id, contract)
        records = list(_iter_jsonl(raw / run_id / model_id / "generations.jsonl"))
        generation_ids = [r.get("sample_id") for r in records]
        assembled = check_assembly(report, intermediate, run_id, model_id, manifest, contract,
                                   generation_sample_ids=generation_ids or None)
        check_evaluated_population(report, model_id, records, assembled, contract)
        assembled_by_model[model_id] = [e["sample_id"] for e in assembled]
        check_correctness(report, intermediate, run_id, model_id, assembled)
        check_static(report, config, intermediate, run_id, model_id, assembled)
        if not skip_enhanced:
            check_enhanced(report, config, intermediate, run_id, model_id, assembled,
                           contract, manifest)
    if intermediate.is_dir():
        check_repair(report, config, intermediate, run_id, models, assembled_by_model)
    check_runtime(report, manifest, contract)

    return OrderedDict([
        ("schema_version", "post_run_verification.v1"),
        ("verifier_version", VERIFIER_VERSION),
        ("run_id", run_id),
        ("contract_sha256", (contract or {}).get("contract_sha256")),
        ("status", report.status()),
        ("counts", report.counts()),
        ("models", models),
        ("checks", report.checks),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--contract", default=None)
    parser.add_argument("--skip-enhanced", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    config = load_config(Path(args.config).resolve())
    report = verify(config, args.run_id,
                    Path(args.contract) if args.contract else None,
                    skip_enhanced=args.skip_enhanced)
    print("POST_RUN_VERIFICATION run=%s status=%s (PASS %d / FAIL %d / UNRESOLVED %d)"
          % (args.run_id, report["status"], report["counts"][PASS],
             report["counts"][FAIL], report["counts"][UNRESOLVED]))
    for check in report["checks"]:
        if check["status"] != PASS:
            print("  %-10s %s: %s" % (check["status"], check["check"], check["detail"]))
    if args.out:
        atomic_io.atomic_write_json(Path(args.out), report)
        print("written:", args.out)
    return 0 if report["status"] == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
