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
  split        PARCOACH / LLOV per-model invocation MEMBERSHIP and
               COVERAGE against the contract-derived expected scopes
               (stage_runtime.split_static_invocation_matrix): records
               and runtime stamps never substitute for a missing
               per-model invocation
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


def _t0_runtime_sha(manifest: "Optional[Dict[str, Any]]") -> "Optional[str]":
    """The runtime condition T0 bound to the run. t0_runtime_evidence.v2
    records the freshly probed sha; the v1 shape carried the readiness sha
    under its own name."""
    evidence = (manifest or {}).get("runtime_evidence") or {}
    return (evidence.get("fresh_runtime_condition_sha256")
            or evidence.get("static_repair_runtime_condition_sha256"))


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
        ("static_repair_runtime_condition_sha256", _t0_runtime_sha(m)),
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


def check_authorization(report: Report, config: Dict[str, Any], run_id: str,
                        contract: "Optional[Dict[str, Any]]",
                        manifest: "Optional[Dict[str, Any]]") -> None:
    """The run must carry the start authorization that let the first
    cost-causing provider request happen, and it must belong to THIS run and
    contract."""
    from thesis.evaluation import manifest_fragments as mf
    from thesis.evaluation import run_authorization as ra

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    tampered = mf.verify_fragment_integrity(intermediate_dir, run_id)
    report.add("run_provenance_integrity", PASS if not tampered else FAIL,
               "%d fragment(s) whose content no longer matches their registered "
               "fingerprint" % len(tampered), {"tampered": tampered[:10]})

    state = ra.authorization_state(config, run_id)
    if not state["present"]:
        report.add("start_authorization_present", UNRESOLVED,
                   "the run carries no start authorization - it cannot be shown that the "
                   "first cost-causing request passed the T0 guard")
        return
    report.add("start_authorization_present", PASS, "authorization %s..."
               % str(state["authorization_sha256"])[:12])
    report.add("start_authorization_allowed",
               PASS if state["decision"] == ra.DECISION_ALLOWED else FAIL,
               "decision %r" % state["decision"])
    report.add("start_authorization_fingerprint_consistent",
               PASS if state["authorization_sha256"] == state["recomputed_sha256"] else FAIL,
               "stored %s... vs recomputed %s..."
               % (str(state["authorization_sha256"])[:12], str(state["recomputed_sha256"])[:12]))
    if contract is not None:
        report.add("start_authorization_matches_contract",
                   PASS if state["frozen_contract_sha256"] == contract.get("contract_sha256")
                   else FAIL,
                   "authorization contract %s... vs frozen %s..."
                   % (str(state["frozen_contract_sha256"])[:12],
                      str(contract.get("contract_sha256"))[:12]))
    evidence = (manifest or {}).get("runtime_evidence") or {}
    if not evidence:
        report.add("t0_runtime_evidence_present", UNRESOLVED,
                   "no T0 runtime evidence bound to the run")
        return
    report.add("t0_runtime_evidence_present", PASS,
               "T0 evidence %s (%s)" % (evidence.get("evidence_version"),
                                        evidence.get("probe_status")))
    report.add("t0_fresh_runtime_matched_readiness",
               PASS if evidence.get("fresh_runtime_condition_sha256")
               == evidence.get("readiness_runtime_condition_sha256") else FAIL,
               "fresh %s... vs readiness %s..."
               % (str(evidence.get("fresh_runtime_condition_sha256"))[:12],
                  str(evidence.get("readiness_runtime_condition_sha256"))[:12]))
    report.add("t0_authorization_runtime_consistent",
               PASS if evidence.get("fresh_runtime_condition_sha256")
               == state["fresh_t0_runtime_condition_sha256"] else FAIL,
               "evidence %s... vs authorization %s..."
               % (str(evidence.get("fresh_runtime_condition_sha256"))[:12],
                  str(state["fresh_t0_runtime_condition_sha256"])[:12]))
    domains = evidence.get("domains") or {}
    missing_identities = []
    for domain in evidence.get("required_runtime_domains") or []:
        entry = domains.get(domain) or {}
        if not entry.get("tool_identities"):
            missing_identities.append(domain)
        elif not (entry.get("image_id") or entry.get("repo_digests")
                  or entry.get("rootfs_layers_sha256")):
            missing_identities.append("%s (no immutable image identity)" % domain)
    report.add("t0_required_identities_present",
               PASS if not missing_identities else UNRESOLVED,
               "domains without a complete identity: %s" % (", ".join(missing_identities) or "none"))


def check_stage_runtime(report: Report, contract: "Optional[Dict[str, Any]]",
                        manifest: "Optional[Dict[str, Any]]") -> "List[OrderedDict]":
    """CONTRACT == T0 == STAGE per runtime domain. A missing stamp is
    UNRESOLVED - never PASS because result files exist."""
    from thesis.evaluation import stage_runtime as sr

    if contract is None:
        report.add("stage_runtime_matrix", UNRESOLVED,
                   "no frozen contract: the expected result-producing stages are unknown")
        return []
    matrix = sr.runtime_matrix(manifest, contract)
    not_expected = sr.not_expected_runtime_stages(contract)
    # The expected set itself is evidence: which runtime stages the FROZEN
    # contract demands, and why each other stage is NOT_APPLICABLE. Without
    # it a missing PARCOACH/LLOV/repair stamp would be indistinguishable from
    # "that stage was never contracted".
    unresolved_applicability = [row["stage"] for row in not_expected
                                if row["status"] == "UNRESOLVED"]
    report.add("stage_runtime_expected_set",
               UNRESOLVED if unresolved_applicability else PASS,
               ("the contract does not determine the applicability of %s, so the expected "
                "runtime stage set is not provable"
                % ", ".join(unresolved_applicability)) if unresolved_applicability else
               "%d expected runtime stage/domain row(s) derived from the frozen contract "
               "(%s): %s" % (len(matrix), sr.EXPECTED_RUNTIME_STAGE_POLICY,
                             ", ".join("%s/%s" % (r["stage"], r["domain"]) for r in matrix)
                             or "none"),
               {"expected": [OrderedDict([("stage", r["stage"]), ("domain", r["domain"]),
                                          ("reason", r["expected_because"])])
                             for r in matrix],
                "not_applicable": not_expected,
                "policy": sr.EXPECTED_RUNTIME_STAGE_POLICY,
                "result_files_substitute_for_runtime_stamp": False})
    for row in matrix:
        report.add("stage_runtime:%s.%s" % (row["stage"], row["domain"]),
                   row["status"], row["detail"],
                   {"expected_because": row["expected_because"],
                    "t0": row["t0"], "stage_observed": row["stage_observed"]})
    return matrix


def check_effective_invocation(report: Report, contract: "Optional[Dict[str, Any]]",
                               manifest: "Optional[Dict[str, Any]]") -> None:
    """The EFFECTIVE stage invocation (the real CLI values) must match the
    contract - a frozen config that agrees with the contract proves nothing
    about the value the stage actually ran with."""
    from thesis.evaluation import effective_invocation as ei
    from thesis.evaluation import stage_runtime as sr

    if contract is None:
        return
    for stage in sr.expected_stages(contract):
        # a stage invoked per model (the PARCOACH/LLOV containers, the repair
        # loop) registers ONE invocation per model scope - every one of them
        # must match the contract
        invocations = ei.invocations_for_stage(manifest, stage)
        check_id = "effective_invocation:%s" % stage
        if not invocations:
            report.add(check_id, UNRESOLVED,
                       "no effective invocation registered for %s - a methodical CLI "
                       "override cannot be excluded" % stage)
            continue
        problems = []
        rendered = []
        for invocation in invocations:
            if not isinstance(invocation, dict):
                problems.append("a registered invocation fragment is not an object")
                continue
            scope = invocation.get("model_scope")
            prefix = "" if not scope else "%s: " % ",".join(
                str(s) for s in (scope if isinstance(scope, (list, tuple)) else [scope]))
            # a fragment of a wrong SHAPE is a verdict (FAIL), never a crash
            try:
                problems += [prefix + problem
                             for problem in ei.check_against_contract(invocation, contract)]
                if ei.invocation_fingerprint(invocation) != invocation.get("invocation_sha256"):
                    problems.append(prefix + "the invocation fragment does not match its own "
                                             "fingerprint")
                values = invocation.get("effective_values")
                if not isinstance(values, dict):
                    raise TypeError("effective_values is not an object")
                rendered.append(prefix + ", ".join(
                    "%s=%s[%s]" % (name, (entry or {}).get("value"), (entry or {}).get("source"))
                    for name, entry in sorted(values.items())))
            except Exception as exc:  # noqa: BLE001 - malformed fragment
                problems.append(prefix + "the invocation fragment is not interpretable (%s: %s)"
                                % (type(exc).__name__, exc))
        report.add(check_id, PASS if not problems else FAIL,
                   "; ".join(problems) if problems else
                   "effective values match the contract in %d invocation(s): %s"
                   % (len(invocations), " | ".join(rendered)),
                   {"invocations": len(invocations),
                    "effective_values": [i.get("effective_values") for i in invocations
                                         if isinstance(i, dict)],
                    "override_policy": next((i.get("override_policy") for i in invocations
                                             if isinstance(i, dict)), None)})


def check_split_static_invocations(report: Report, contract: "Optional[Dict[str, Any]]",
                                   manifest: "Optional[Dict[str, Any]]",
                                   intermediate: Path, run_id: str
                                   ) -> "OrderedDict[str, Any]":
    """WAS EVERY CONTRACTED (stage, tool, model) SPLIT-CONTAINER INVOCATION
    ACTUALLY REGISTERED? membership (are the observed scopes allowed and
    consistent?) and coverage (is every expected scope evidenced?) are
    reported separately; a single valid fragment never covers a
    multi-model stage, records never substitute for the invocation, and
    the runtime stamp never does either."""
    from thesis.evaluation import stage_runtime as sr

    matrix = sr.split_static_invocation_matrix(manifest, contract, intermediate, run_id)
    expected = matrix["expected_set"]
    if contract is None:
        report.add("split_static_invocation_expected_set", UNRESOLVED, expected["reason"],
                   {"policy": matrix["policy"]})
        return matrix
    report.add("split_static_invocation_expected_set",
               PASS if expected["status"] in (PASS, "NOT_APPLICABLE") else expected["status"],
               "%s (%s): %s" % (matrix["policy"], matrix["identity"], expected["reason"]),
               {"status": expected["status"], "expected_scope_count": matrix["expected_scope_count"],
                "per_tool": expected["per_tool"], "not_expected": expected["not_expected"],
                "model_ids": expected["model_ids"],
                "runtime_stamp_substitutes_split_invocation": False,
                "record_coverage_substitutes_split_invocation": False})
    if expected["status"] == "NOT_APPLICABLE":
        report.add("split_static_invocation_membership",
                   FAIL if matrix["membership"] == FAIL else PASS,
                   matrix["detail"], {"unexpected": matrix["unexpected_scopes"]})
        return matrix
    if expected["status"] != PASS:
        report.add("split_static_invocation_coverage", UNRESOLVED, matrix["detail"],
                   {"expected_scope_count": 0})
        return matrix
    report.add("split_static_invocation_membership", matrix["membership"],
               "%d fragment(s) observed for %d scope(s); unexpected %d, contradicting %d, "
               "unkeyable %d, consistent duplicates %d (%s)"
               % (matrix["observed_fragment_count"], matrix["observed_scope_count"],
                  len(matrix["unexpected_scopes"]), len(matrix["contradicting_scopes"]),
                  len(matrix["unkeyable_fragments"]), len(matrix["consistent_duplicate_scopes"]),
                  matrix["duplicate_policy"]),
               {"unexpected": matrix["unexpected_scopes"],
                "contradicting": matrix["contradicting_scopes"],
                "unkeyable": matrix["unkeyable_fragments"],
                "consistent_duplicates": matrix["consistent_duplicate_scopes"]})
    report.add("split_static_invocation_coverage", matrix["coverage"], matrix["detail"],
               {"expected_scope_count": matrix["expected_scope_count"],
                "observed_scope_count": matrix["observed_scope_count"],
                "covered_scope_count": matrix["covered_scope_count"],
                "missing_scopes": matrix["missing_scopes"],
                "unexpected_scopes": matrix["unexpected_scopes"],
                "contradicting_scopes": matrix["contradicting_scopes"],
                "per_tool": matrix["per_tool"], "narrowing": matrix["narrowing"],
                "runtime_stamp_substitutes_split_invocation": False,
                "record_coverage_substitutes_split_invocation": False})
    for row in matrix["rows"]:
        report.add("split_static_invocation:%s/%s" % (row["stage"], row["model_id"]),
                   row["status"], row["detail"],
                   {"tool": row["tool"], "fragments": row["fragments"],
                    "records_with_entry": row["records_with_entry"],
                    "summary_invocations_running_tool": row["summary_invocations_running_tool"]})
    return matrix


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


def reconcile_repair_evaluation_expectation(report: Report,
                                            matrix: "Optional[Dict[str, Any]]") -> None:
    """The global expectation and the per-loop rule must not contradict each
    other.

    stage_runtime.expected_runtime_stages demands a repair_evaluation runtime
    stamp (and effective invocation) for every contracted repair plan, because
    a repair loop normally analyses candidates. The repair matrix can PROVE
    that no contracted loop of THIS run ever analysed anything - every loop
    stopped at iteration 0 with base records the loop did not have to produce -
    and in that case the productive orchestrator registers no repair_evaluation
    invocation at all, so the two generic checks would report UNRESOLVED on a
    complete, correct run.

    The downgrade is deliberately narrow: it needs a PASS matrix with at least
    one expected loop, EVERY row not requiring an invocation and none present,
    and it only rewrites an UNRESOLVED verdict - if any loop required one, or
    anything else about the repair scope is unresolved or failed, both checks
    stand exactly as they were."""
    from thesis.evaluation import repair_scope as rs

    if not matrix or matrix.get("status") != rs.PASS:
        return
    rows = matrix.get("rows") or []
    if not rows or not all(not row.get("invocation_required")
                           and not row.get("invocation_count") for row in rows):
        return
    if matrix.get("repair_evaluation_stamp_present"):
        # the stamp is registered by _run_analysis_stages only: SOME loop ran
        # an internal analysis, yet no loop is attributed - the writer
        # provenance of that analysis is lost. Never downgrade to
        # NOT_APPLICABLE on that contradiction; say so instead.
        for check in report.checks:
            if check["check"] == "effective_invocation:%s" % rs.STAGE \
                    and check["status"] == UNRESOLVED:
                check["detail"] = ("%s - the run carries a %s runtime stamp (registered "
                                   "only by the loop's own internal analysis) but no loop "
                                   "is attributed: the writer provenance of that analysis "
                                   "is lost" % (check["detail"], rs.STAGE))
                check["evidence"] = dict(check.get("evidence") or {},
                                         repair_evaluation_stamp_present=True,
                                         downgrade_refused=True)
        return
    reason = ("the repair matrix proves that none of the %d contracted loop(s) analysed an "
              "iteration, so the productive orchestrator registers no %s at all "
              "(repair_scope_matrix.v1)" % (len(rows), rs.STAGE))
    for check in report.checks:
        if check["check"] in ("stage_runtime:%s.main" % rs.STAGE,
                              "effective_invocation:%s" % rs.STAGE) \
                and check["status"] == UNRESOLVED:
            check["status"] = rs.NOT_APPLICABLE
            check["detail"] = "%s - NOT_APPLICABLE: %s" % (check["detail"], reason)
            check["evidence"] = dict(check.get("evidence") or {},
                                     reconciled_with="repair_scope_complete")


def check_repair_scope(report: Report, contract: "Optional[Dict[str, Any]]",
                       config: Dict[str, Any], run_id: str,
                       manifest: "Optional[Dict[str, Any]]",
                       assembled_by_model: "Optional[Dict[str, List[str]]]" = None,
                       known_by_model: "Optional[Dict[str, List[str]]]" = None
                       ) -> "OrderedDict[str, Any]":
    """WERE ALL CONTRACTED (model_id x variant) REPAIR LOOPS ACTUALLY AND
    COMPLETELY EVIDENCED? The expected set comes from the FROZEN contract
    only (no repair_plan -> UNRESOLVED, never a live-config fallback); every
    expected loop needs its own invocation, its own state file and
    sample-level terminality (run_backfill.loop_state_terminality). A valid
    global repair_evaluation runtime stamp never substitutes for a loop."""
    from thesis.evaluation import repair_scope as rs

    matrix = rs.build_repair_matrix(contract, config, run_id, manifest, assembled_by_model,
                                    known_by_model)
    expected = matrix["expected_set"]
    report.add("repair_expected_set",
               PASS if expected["status"] == rs.NOT_APPLICABLE else expected["status"],
               "%s (%s): %s" % (expected["policy"], expected["rule"], expected["reason"]),
               {"model_ids": expected["model_ids"], "variants": expected["variants"],
                "max_iterations": expected["max_iterations"],
                "expected_loop_count": matrix["expected_loop_count"]})
    if matrix["status"] == rs.NOT_APPLICABLE:
        # the report knows PASS/FAIL/UNRESOLVED only; NOT_APPLICABLE is kept
        # verbatim in the evidence and in report["repair_scope"]
        report.add("repair_scope_complete", PASS,
                   "NOT_APPLICABLE: %s" % matrix["detail"],
                   {"aggregate": rs.NOT_APPLICABLE, "expected_loop_count": 0,
                    "observed_loop_count": matrix["observed_loop_count"]})
        return matrix
    if expected["status"] != PASS:
        # no usable expected set (missing or invalid frozen repair plan):
        # nothing below is decidable, and the aggregate carries the verdict
        report.add("repair_scope_complete", matrix["status"], matrix["detail"],
                   {"expected_loop_count": 0, "observed_loop_count": matrix["observed_loop_count"],
                    "runtime_stamp_substitutes_missing_repair_loop": False})
        return matrix
    invocations = matrix["invocations"]
    report.add("repair_invocation_membership", invocations["membership"],
               "%d observed repair invocation scope(s); unexpected %d, duplicate %d, "
               "unkeyable %d, contradicting %d"
               % (invocations["observed_scope_count"], len(invocations["unexpected_scopes"]),
                  len(invocations["duplicate_scopes"]), len(invocations["unkeyable"]),
                  len(invocations["contradicting_contract"])),
               {"unexpected": invocations["unexpected_scopes"],
                "duplicate": invocations["duplicate_scopes"],
                "unkeyable": invocations["unkeyable"],
                "contradicting": invocations["contradicting_contract"]})
    report.add("repair_invocation_coverage", invocations["coverage"],
               "%d/%d expected repair invocation scope(s) present, %d not required "
               "(the loop analysed nothing), %d required and absent%s"
               % (invocations["present_scope_count"], invocations["expected_scope_count"],
                  invocations["not_required_scope_count"], len(invocations["missing_scopes"]),
                  ("; " + matrix["narrowing"]["reason"]) if matrix["narrowing"]["narrowed"]
                  else ""),
               {"missing": invocations["missing_scopes"], "narrowing": matrix["narrowing"]})
    for row in matrix["rows"]:
        report.add("repair_loop:%s/%s" % (row["model_id"], row["variant"]), row["status"],
                   row["detail"],
                   {"terminal": row["terminal"], "samples_total": row["samples_total"],
                    "samples_active": row["samples_active"],
                    "terminal_breakdown": row["terminal_breakdown"],
                    "max_iteration_observed": row["max_iteration_observed"],
                    "limitations": row["limitations"]})
    if matrix["iteration_identity_violations"]:
        report.add("repair_iteration_identity", FAIL,
                   "; ".join(matrix["iteration_identity_violations"][:10]),
                   {"violations": matrix["iteration_identity_violations"]})
    else:
        report.add("repair_iteration_identity", PASS,
                   "%d iteration artifact run(s) bound to contracted (model, variant, iteration) "
                   "identities" % len(matrix["iteration_artifacts"]))
    totals = matrix["sample_totals"]
    report.add("repair_scope_complete", matrix["status"], matrix["detail"], {
        "expected_loop_count": matrix["expected_loop_count"],
        "observed_loop_count": matrix["observed_loop_count"],
        "pass_loop_count": matrix["pass_loop_count"],
        "unresolved_loop_count": matrix["unresolved_loop_count"],
        "fail_loop_count": matrix["fail_loop_count"],
        "terminal_loop_count": matrix["terminal_loop_count"],
        "missing": matrix["missing"], "unexpected": matrix["unexpected"],
        "duplicate": matrix["duplicate"], "unkeyable": matrix["unkeyable"],
        # SAMPLE-level, deliberately separate from the LOOP counts above
        "total_repair_samples": totals["total_repair_samples"],
        "terminal_repair_samples": totals["terminal_repair_samples"],
        "active_repair_samples": totals["active_repair_samples"],
        "sample_terminal_breakdown": totals["sample_terminal_breakdown"],
        "limitations": matrix["limitations"],
        "runtime_stamp_substitutes_missing_repair_loop": False,
    })
    return matrix


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
    if _t0_runtime_sha(manifest) != conditions.get("static_repair_runtime_condition_sha256"):
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
    check_authorization(report, config, run_id, contract, manifest)
    runtime_matrix = check_stage_runtime(report, contract, manifest)
    check_effective_invocation(report, contract, manifest)
    split_matrix = check_split_static_invocations(report, contract, manifest, intermediate,
                                                  run_id)

    raw_run = raw / run_id
    observed_models = sorted(p.name for p in raw_run.iterdir()
                             if p.is_dir() and (p / "generations.jsonl").is_file()) \
        if raw_run.is_dir() else []
    models = check_model_set(report, contract, observed_models)
    models = sorted(set(models) | set(observed_models)) if contract else observed_models

    assembled_by_model: "Dict[str, List[str]]" = {}
    # every sample the base run has an assembly ENTRY for, assembled or not:
    # _decide(0)'s bootstrap marks the skipped ones repair_unusable, so they
    # belong in the repair loop's state and must not read as fabricated
    known_by_model: "Dict[str, List[str]]" = {}
    for model_id in models:
        check_population(report, raw, run_id, model_id, contract)
        records = list(_iter_jsonl(raw / run_id / model_id / "generations.jsonl"))
        generation_ids = [r.get("sample_id") for r in records]
        assembled = check_assembly(report, intermediate, run_id, model_id, manifest, contract,
                                   generation_sample_ids=generation_ids or None)
        check_evaluated_population(report, model_id, records, assembled, contract)
        assembled_by_model[model_id] = [e["sample_id"] for e in assembled]
        try:
            from thesis.assembly import assembly_provenance as _ap

            known_by_model[model_id] = [
                e.get("sample_id") for e in _ap.load_assembly_entries(
                    intermediate / run_id / model_id / "assembly.jsonl")
                if e.get("sample_id")]
        except Exception:  # noqa: BLE001 - reported by check_assembly already
            known_by_model[model_id] = list(assembled_by_model[model_id])
        check_correctness(report, intermediate, run_id, model_id, assembled)
        check_static(report, config, intermediate, run_id, model_id, assembled)
        if not skip_enhanced:
            check_enhanced(report, config, intermediate, run_id, model_id, assembled,
                           contract, manifest)
    if intermediate.is_dir():
        check_repair(report, config, intermediate, run_id, models, assembled_by_model)
    repair_matrix = check_repair_scope(report, contract, config, run_id, manifest,
                                       assembled_by_model, known_by_model)
    reconcile_repair_evaluation_expectation(report, repair_matrix)
    check_runtime(report, manifest, contract)

    return OrderedDict([
        ("schema_version", "post_run_verification.v1"),
        ("verifier_version", VERIFIER_VERSION),
        ("run_id", run_id),
        ("contract_sha256", (contract or {}).get("contract_sha256")),
        ("status", report.status()),
        ("counts", report.counts()),
        ("models", models),
        ("runtime_matrix", runtime_matrix),
        ("retrospective_runtime_substitution_allowed", False),
        ("split_static_invocations", split_matrix),
        ("split_static_invocation_coverage", OrderedDict([
            ("policy", split_matrix["policy"]),
            ("membership", split_matrix["membership"]),
            ("coverage", split_matrix["coverage"]),
            ("expected_scope_count", split_matrix["expected_scope_count"]),
            ("observed_scope_count", split_matrix["observed_scope_count"]),
            ("covered_scope_count", split_matrix["covered_scope_count"]),
            ("missing_scopes", split_matrix["missing_scopes"]),
            ("unexpected_scopes", split_matrix["unexpected_scopes"]),
            ("contradicting_scopes", split_matrix["contradicting_scopes"]),
            ("unkeyable_fragments", split_matrix["unkeyable_fragments"]),
            ("observed_fragment_count", split_matrix["observed_fragment_count"]),
            ("consistent_duplicate_scopes", split_matrix["consistent_duplicate_scopes"]),
            ("narrowing", split_matrix["narrowing"]),
            ("per_tool", split_matrix["per_tool"]),
            ("runtime_stamp_substitutes_split_invocation", False),
            ("record_coverage_substitutes_split_invocation", False),
        ])),
        ("repair_matrix", repair_matrix),
        ("repair_scope", OrderedDict([
            ("status", repair_matrix["status"]),
            ("expected_loop_count", repair_matrix["expected_loop_count"]),
            ("observed_loop_count", repair_matrix["observed_loop_count"]),
            ("pass_loop_count", repair_matrix["pass_loop_count"]),
            ("unresolved_loop_count", repair_matrix["unresolved_loop_count"]),
            ("fail_loop_count", repair_matrix["fail_loop_count"]),
            ("sample_totals", repair_matrix["sample_totals"]),
        ])),
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
    from thesis.evaluation import repair_scope as _rs

    scope = report.get("repair_scope") or {}
    print("REPAIR_SCOPE_COMPLETE = %s (expected loops %s, observed %s, PASS %s, UNRESOLVED %s, "
          "FAIL %s)" % (scope.get("status"), scope.get("expected_loop_count"),
                        scope.get("observed_loop_count"), scope.get("pass_loop_count"),
                        scope.get("unresolved_loop_count"), scope.get("fail_loop_count")))
    totals = scope.get("sample_totals") or {}
    print("REPAIR_SAMPLES total=%s terminal=%s active=%s breakdown=%s"
          % (totals.get("total_repair_samples"), totals.get("terminal_repair_samples"),
             totals.get("active_repair_samples"), dict(totals.get("sample_terminal_breakdown") or {})))
    for line in _rs.matrix_table(report.get("repair_matrix") or {}):
        print("  " + line)
    for check in report["checks"]:
        if check["status"] != PASS:
            print("  %-10s %s: %s" % (check["status"], check["check"], check["detail"]))
    if args.out:
        atomic_io.atomic_write_json(Path(args.out), report)
        print("written:", args.out)
    return 0 if report["status"] == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
