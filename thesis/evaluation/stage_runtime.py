"""Per-stage runtime evidence (stage_runtime_evidence.v1).

T0 proves the runtime at the cost-causing provider start. It proves nothing
about the runtime of the measurement stages, which may run hours or days
later, in a different container, after an image rebuild. So every
result-producing stage stamps the runtime it ACTUALLY runs under, compares
it against the contract and the T0 evidence, and refuses to produce results
on drift:

    CONTRACT == T0 EVIDENCE == STAGE EVIDENCE   per runtime domain

Domains follow the runtime roles the readiness gate already measures:

    main       correctness, dynamic, enhanced, static (compiler, gcc_analyzer,
               clang_tidy, cppcheck, infer), repair evaluation
    parcoach   the PARCOACH container
    llov       the LLOV container

Fragments (per-writer architecture, one owner each):

    runtime.stage.correctness        runtime.stage.static.main
    runtime.stage.dynamic            runtime.stage.static.parcoach
    runtime.stage.enhanced           runtime.stage.static.llov
    runtime.stage.repair_evaluation

A drift is STAGE_RUNTIME_DRIFT - a provenance failure BEFORE analysis, never
a TOOL_ERROR, a tool-state gap or a model failure, and it never produces a
result record.

Python 3.8 compatible.
"""
from __future__ import annotations

import json
import threading
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

STAGE_RUNTIME_EVIDENCE_VERSION = "stage_runtime_evidence.v1"

DOMAIN_MAIN = "main"
DOMAIN_PARCOACH = "parcoach"
DOMAIN_LLOV = "llov"

# stage -> (fragment owner, runtime domains that must match)
STAGE_DOMAINS = OrderedDict([
    ("correctness", ("stage.correctness", (DOMAIN_MAIN,))),
    ("dynamic", ("stage.dynamic", (DOMAIN_MAIN,))),
    ("enhanced", ("stage.enhanced", (DOMAIN_MAIN,))),
    ("static.main", ("stage.static.main", (DOMAIN_MAIN,))),
    ("static.parcoach", ("stage.static.parcoach", (DOMAIN_PARCOACH,))),
    ("static.llov", ("stage.static.llov", (DOMAIN_LLOV,))),
    ("repair_evaluation", ("stage.repair_evaluation", (DOMAIN_MAIN,))),
])

# Which measured identities a domain must expose for a stage stamp to count.
#
# PRESENCE vs DRIFT (pre-start fix 2026-09-16, STAGE_RUNTIME_MAIN_MPI_IDENTITY
# _NOT_MEASURABLE): the productive main probe (probe_runtime_identity.ROLE_TOOLS
# ["main"]) measures tool identities for compiler, gcc_analyzer, clang_tidy,
# cppcheck and infer; MPI is measured by the SAME probe as
# evidence.mpi_version_line (the first line of `mpirun --version`,
# probe_runtime_identity.main_evidence) - the canonical MPI value the readiness
# proof and the T0 evidence carry inside RUNTIME_ENVIRONMENT_FIELDS["evidence"].
# Demanding a tool identity named "mpi" therefore made every main-domain stage
# stamp of a contracted run STAGE_RUNTIME_UNRESOLVED (the committed fixtures
# only passed because their fake prober carried one). The requirement is now
# split by mechanism:
#   * REQUIRED_IDENTITIES  - tool identities that must be PRESENT
#   * REQUIRED_EVIDENCE    - evidence keys that must be PRESENT and non-empty
# Both are PRESENCE checks only (-> StageRuntimeUnresolved). Whether a present
# value CHANGED against the T0 evidence is decided exclusively by the existing
# domain comparison of the `tool_identities` and `evidence` fields
# (domain_diff -> StageRuntimeDrift); there is no second MPI identity
# definition and no second drift logic.
REQUIRED_IDENTITIES = OrderedDict([
    (DOMAIN_MAIN, ("compiler",)),
    (DOMAIN_PARCOACH, ("parcoach",)),
    (DOMAIN_LLOV, ("llov",)),
])

# Evidence keys (per domain) that must be PRESENT and non-empty in the fresh
# observation. `mpi_version_line` is exactly the value probe_runtime_identity
# already records for the main role - never a second measurement of MPI.
REQUIRED_EVIDENCE = OrderedDict([
    (DOMAIN_MAIN, ("mpi_version_line",)),
    (DOMAIN_PARCOACH, ()),
    (DOMAIN_LLOV, ()),
])

_CACHE_LOCK = threading.RLock()
_STAMPED = {}  # (run_id, stage) -> evidence


class StageRuntimeDrift(RuntimeError):
    """Runtime provenance drift before result production - NOT a tool error.

    Carries stage, runtime_domain, expected, observed, drift_fields and the
    recommendation, so a runner can print it verbatim and stop."""

    failure_class = "STAGE_RUNTIME_DRIFT"

    def __init__(self, stage: str, domain: str, expected: Any, observed: Any,
                 drift_fields: "List[str]", message: "Optional[str]" = None) -> None:
        self.stage = stage
        self.runtime_domain = domain
        self.expected = expected
        self.observed = observed
        self.drift_fields = list(drift_fields)
        self.recommendation = ("use a fresh run_id after a deliberate re-freeze, or restore "
                               "the pinned environment; this stage produced NO records")
        super().__init__(message or self.render())

    def render(self) -> str:
        return ("STAGE_RUNTIME_DRIFT (%s / %s): expected %s, observed %s; drift: %s. %s"
                % (self.stage, self.runtime_domain, _short(self.expected),
                   _short(self.observed), ", ".join(self.drift_fields) or "-",
                   self.recommendation))


class StageRuntimeUnresolved(StageRuntimeDrift):
    """The stage runtime could not be measured or no T0 evidence exists."""

    failure_class = "STAGE_RUNTIME_UNRESOLVED"


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= 20 else text[:17] + "..."


# How a stage can observe its own runtime, and which identity fields that
# observation can actually compare.
MODE_DOCKER = "docker_inspect"        # the launcher side: full image identity
MODE_INSIDE = "inside_container"      # inside the tool container: no docker
MODE_INJECTED = "injected"            # tests
COMPARED_FIELDS = {
    MODE_DOCKER: ("image_ref", "image_id", "repo_digests", "rootfs_layers_sha256",
                  "tool_identities", "evidence"),
    MODE_INJECTED: ("image_ref", "image_id", "repo_digests", "rootfs_layers_sha256",
                    "tool_identities", "evidence"),
    # A process running INSIDE the analysis container cannot inspect its own
    # image (no docker socket). What it CAN measure is exactly the identity
    # the tool result depends on: the tool binaries and their evidence
    # (PARCOACH executable sha + version + LLVM backend, LLOV clang + plugin
    # sha, the main compiler/MPI/analyzer identities). The image-level fields
    # stay pinned by T0 and are reported as not observable here.
    MODE_INSIDE: ("tool_identities", "evidence"),
}


def _all_fields() -> "Tuple[str, ...]":
    from thesis.evaluation import static_provenance as sp

    return tuple(sp.RUNTIME_ENVIRONMENT_FIELDS)


def domain_projection(environment: "Optional[Dict[str, Any]]",
                      fields: "Optional[Tuple[str, ...]]" = None) -> "OrderedDict[str, Any]":
    """The identity projection of one runtime domain, using the SAME field
    set and normalization the readiness/runtime condition uses."""
    from thesis.evaluation import static_provenance as sp

    environment = environment or {}
    projection = OrderedDict()
    for field in (fields or sp.RUNTIME_ENVIRONMENT_FIELDS):
        projection[field] = sp._canonical_runtime_value(environment.get(field))
    return projection


def domain_sha256(environment: "Optional[Dict[str, Any]]",
                  fields: "Optional[Tuple[str, ...]]" = None) -> str:
    from thesis.evaluation.condition_hashing import canonical_sha256

    return canonical_sha256(domain_projection(environment, fields))


def domain_diff(expected: "Optional[Dict[str, Any]]",
                observed: "Optional[Dict[str, Any]]",
                fields: "Optional[Tuple[str, ...]]" = None) -> "List[str]":
    a = domain_projection(expected, fields)
    b = domain_projection(observed, fields)
    return [field for field in a if a[field] != b[field]]


def docker_available() -> bool:
    import shutil
    import subprocess

    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                                capture_output=True, text=True, timeout=20)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def observe_runtime(config: "Dict[str, Any]", domains: "Tuple[str, ...]",
                    prober: "Optional[Any]" = None):
    """(mode, environments, full_fresh_or_None).

    With docker the stage observes the FULL identity of every domain exactly
    as T0 did. Inside an analysis container (no docker socket) it observes
    the tool identities of ITS OWN domain with the same in-container probe
    the readiness proof used - never a second identity definition."""
    from thesis.evaluation import run_authorization

    if prober is not None:
        return MODE_INJECTED, (prober(config) or {}), None
    if docker_available():
        fresh = run_authorization.measure_fresh_runtime(config)
        return MODE_DOCKER, (fresh["environments"] or {}), fresh
    from thesis.evaluation import probe_runtime_identity as pri

    environments = OrderedDict()
    for domain in domains:
        if domain not in pri.ROLE_TOOLS:
            continue
        observed = pri.probe(domain)
        environments[domain] = OrderedDict([
            ("tool_identities", observed.get("tool_identities")),
            ("evidence", observed.get("evidence")),
        ])
    return MODE_INSIDE, environments, None


def t0_domains(manifest: "Optional[Dict[str, Any]]") -> "Dict[str, Any]":
    evidence = (manifest or {}).get("runtime_evidence") or {}
    domains = evidence.get("domains")
    if domains:
        return domains
    # t0_runtime_evidence.v1 (pre-enforcement) carried no per-domain block
    condition = evidence.get("runtime_condition") or {}
    return condition.get("environments") or {}


def enforcement_state(config: "Dict[str, Any]", run_id: str) -> "OrderedDict[str, Any]":
    """Enforcement binds a CONTRACTED run. A run without a frozen contract
    (smoke runs, the historical pilot_001, unit fixtures) has nothing to
    compare against: the stage records that honestly and proceeds, and the
    post-run verifier reports the missing stamps as UNRESOLVED rather than
    PASS. A run WITH a contract must pass every check."""
    from thesis.evaluation import run_manifest

    manifest = run_manifest.load_manifest(config, run_id) or {}
    contract = manifest.get("contract")
    return OrderedDict([
        ("enforced", contract is not None),
        ("contract_sha256", manifest.get("contract_sha256")),
        ("authorization_sha256", (manifest.get("authorization") or {}).get(
            "authorization_sha256")),
        ("reason", None if contract is not None
         else "no frozen run contract is bound to this run (PRE_RUN_ENFORCEMENT = "
              "NOT_APPLICABLE); a contracted pilot run binds one at T0"),
        ("manifest", manifest),
        ("contract", contract),
    ])


def enforce_stage(config: "Dict[str, Any]", run_id: str, stage: str, *,
                  effective_values: "Optional[Dict[str, Any]]" = None,
                  profile: "Optional[str]" = None,
                  model_scope: "Optional[Any]" = None,
                  prober: "Optional[Any]" = None,
                  writer: "Optional[str]" = None) -> "OrderedDict[str, Any]":
    """The pre-result sequence of a measurement stage, in the contracted order:

        1. load contract/authorization
        2. determine the effective invocation
        3. check the invocation against the contract
        4. measure the stage runtime FRESH
        5. check it against contract/T0
        6. register the invocation fragment
        7. register the stage runtime fragment
        8. (caller) only now write result records

    Raises InvocationRefused / StageRuntimeDrift BEFORE anything is written,
    so a drifted stage produces zero result records."""
    from thesis.evaluation import effective_invocation as ei

    state = enforcement_state(config, run_id)
    if not state["enforced"]:
        # a repair-iteration run of a CONTRACTED base run is analysed by the
        # repair loop itself (writer-attributed, repair_evaluation stamped on
        # the base run); a stage runner invoked directly on it would run
        # unenforced - refused
        base = iteration_base_run_id(run_id)
        if base is not None and enforcement_state(config, base)["enforced"]:
            raise StageRuntimeDrift(
                stage, "contract", base, run_id, ["run_id"],
                message="REPAIR_ITERATION_RUN_NOT_INVOCABLE (%s): %s is a repair-iteration run of the "
                        "contracted base run %s; its stages are analysed by the repair loop only (stage "
                        "runners must not be invoked on it directly); this stage produced NO records"
                        % (stage, run_id, base))
        return OrderedDict([("enforced", False), ("stage", stage),
                            ("reason", state["reason"])])

    contract = state["contract"]
    # config-only methodical values (niter, launch grid, enhanced launch,
    # timeouts, tool scopes, ...) live in the frozen run manifest; a live
    # config that deviates on a methodical key is refused before any record
    drift = methodical_config_drift(state["manifest"], config)
    if drift:
        raise StageRuntimeDrift(
            stage, "config", "the run manifest's frozen resolved_config", "the live configuration", drift,
            message="METHODICAL_CONFIG_DRIFT (%s): the live configuration deviates from the run manifest "
                    "frozen at the run's start on methodical keys: %s - a config edit after T0 is a "
                    "methodical override; re-decide and re-freeze instead of running; this stage "
                    "produced NO records" % (stage, ", ".join(drift)))
    invocation = None
    if effective_values is not None:
        invocation = ei.build_invocation(run_id, stage, profile, effective_values,
                                         model_scope=model_scope, contract=contract)
        problems = ei.check_against_contract(invocation, contract)
        if problems:
            raise ei.InvocationRefused("EFFECTIVE_INVOCATION_DRIFT (%s): %s"
                                       % (stage, "; ".join(problems)))

    evidence = stamp_stage_runtime(config, run_id, stage, prober=prober,
                                   writer=writer, register=False)

    if invocation is not None:
        ei.register_effective_invocation(config, run_id, stage, effective_values,
                                         profile=profile, model_scope=model_scope,
                                         writer=writer or stage)
    _register_stage_evidence(config, run_id, stage, evidence, writer=writer)
    return OrderedDict([("enforced", True), ("stage", stage),
                        ("stage_runtime_sha256", evidence.get("stage_runtime_sha256")),
                        ("invocation_sha256", (invocation or {}).get("invocation_sha256")),
                        ("contract_sha256", state["contract_sha256"]),
                        ("authorization_sha256", state["authorization_sha256"])])


# top-level config keys whose values are methodical (everything under
# `outputs` and `experiment` is operational)
METHODICAL_CONFIG_KEYS = ("stages", "generation_defaults", "prompts", "models", "profiles")


def iteration_base_run_id(run_id: str) -> "Optional[str]":
    """`<base>__<variant>__iterN` -> base; None for a base run id."""
    import re

    match = re.match(r"^(?P<base>.+?)__(?P<variant>[^_].*?)__iter(?P<n>\d+)$", run_id or "")
    return match.group("base") if match else None


def methodical_config_drift(manifest: "Optional[Dict[str, Any]]",
                            config: "Dict[str, Any]") -> "List[str]":
    """Dot-paths under the methodical top-level keys where the live config
    differs from the run manifest's frozen resolved_config."""
    from thesis.evaluation.run_manifest import _jsonable, config_key_diff

    frozen = (manifest or {}).get("resolved_config")
    if not isinstance(frozen, dict):
        return []
    live = _jsonable(config)
    drift = []
    for key in METHODICAL_CONFIG_KEYS:
        if key not in frozen and key not in live:
            continue
        drift.extend(config_key_diff(frozen.get(key), live.get(key), prefix=key))
    return drift


def _register_stage_evidence(config: "Dict[str, Any]", run_id: str, stage: str,
                             evidence: "Dict[str, Any]",
                             writer: "Optional[str]" = None) -> None:
    from thesis.evaluation import manifest_fragments as mf

    owner, domains = STAGE_DOMAINS[stage]
    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    try:
        mf.register_fragment(intermediate_dir, run_id, "runtime", owner, evidence,
                             fingerprint=evidence["stage_runtime_sha256"],
                             writer=writer or stage)
    except mf.FragmentConflict as conflict:
        raise StageRuntimeDrift(
            stage, ",".join(domains), "registered stage runtime", "different",
            ["stage_runtime_fragment"],
            "STAGE_RUNTIME_DRIFT (%s): this run already recorded a DIFFERENT stage "
            "runtime: %s" % (stage, conflict))
    mf.write_snapshot(intermediate_dir, run_id)
    with _CACHE_LOCK:
        _STAMPED[(run_id, stage)] = evidence


def stamp_stage_runtime(config: "Dict[str, Any]", run_id: str, stage: str, *,
                        prober: "Optional[Any]" = None,
                        writer: "Optional[str]" = None,
                        force: bool = False,
                        register: bool = True) -> "OrderedDict[str, Any]":
    """Measure the runtime this stage runs under, compare it against the
    contract and the T0 evidence, register the fragment and return it.

    Raises StageRuntimeDrift / StageRuntimeUnresolved BEFORE any result is
    produced. Idempotent per (run_id, stage) within one process."""
    from thesis.evaluation import manifest_fragments as mf
    from thesis.evaluation import run_authorization, run_manifest
    from thesis.generation.common import utc_now_iso

    if stage not in STAGE_DOMAINS:
        raise KeyError("unknown measurement stage %r (known: %s)"
                       % (stage, ", ".join(STAGE_DOMAINS)))
    key = (run_id, stage)
    with _CACHE_LOCK:
        if not force and key in _STAMPED:
            return _STAMPED[key]

    owner, domains = STAGE_DOMAINS[stage]
    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    manifest = run_manifest.load_manifest(config, run_id) or {}
    contract_sha = manifest.get("contract_sha256")
    authorization_sha = (manifest.get("authorization") or {}).get("authorization_sha256")
    expected_domains = t0_domains(manifest)
    t0_sha = (manifest.get("runtime_evidence") or {}).get("fresh_runtime_condition_sha256")

    if not expected_domains:
        raise StageRuntimeUnresolved(
            stage, ",".join(domains), "T0 runtime evidence", "none",
            ["t0_runtime_evidence"],
            "STAGE_RUNTIME_UNRESOLVED (%s): the run carries no T0 runtime evidence, so the "
            "stage runtime cannot be bound to the authorized start. Authorize the run "
            "first (run_authorization.authorize_start)." % stage)

    mode, observed_environments, fresh = observe_runtime(config, domains, prober=prober)

    domain_reports = OrderedDict()
    for domain in domains:
        expected = expected_domains.get(domain)
        observed = observed_environments.get(domain)
        if observed is None or observed.get("probe_error"):
            raise StageRuntimeUnresolved(
                stage, domain, domain_sha256(expected), "unmeasurable",
                ["probe_error"],
                "STAGE_RUNTIME_UNRESOLVED (%s / %s): %s" % (
                    stage, domain,
                    (observed or {}).get("probe_error") or "domain not probed"))
        missing = [tool for tool in REQUIRED_IDENTITIES.get(domain, ())
                   if not (observed.get("tool_identities") or {}).get(tool)]
        if missing:
            raise StageRuntimeUnresolved(
                stage, domain, "identities %s" % ",".join(REQUIRED_IDENTITIES[domain]),
                "missing %s" % ",".join(missing), ["tool_identities"],
                "STAGE_RUNTIME_UNRESOLVED (%s / %s): required identities not measurable: %s"
                % (stage, domain, ", ".join(missing)))
        # PRESENCE of the required evidence keys (e.g. main: mpi_version_line);
        # a present-but-changed value is caught below by domain_diff(`evidence`)
        missing_evidence = [key for key in REQUIRED_EVIDENCE.get(domain, ())
                            if not (observed.get("evidence") or {}).get(key)]
        if missing_evidence:
            raise StageRuntimeUnresolved(
                stage, domain, "evidence %s" % ",".join(REQUIRED_EVIDENCE[domain]),
                "missing %s" % ",".join(missing_evidence), ["evidence"],
                "STAGE_RUNTIME_UNRESOLVED (%s / %s): required evidence not measurable: %s"
                % (stage, domain, ", ".join(missing_evidence)))
        if expected is None:
            raise StageRuntimeUnresolved(
                stage, domain, "T0 domain", "absent", ["t0_domain_missing"],
                "STAGE_RUNTIME_UNRESOLVED (%s / %s): T0 recorded no evidence for this "
                "runtime domain" % (stage, domain))
        compared_fields = COMPARED_FIELDS[mode]
        drift = domain_diff(expected, observed, fields=compared_fields)
        if drift:
            raise StageRuntimeDrift(stage, domain,
                                    domain_sha256(expected, fields=compared_fields),
                                    domain_sha256(observed, fields=compared_fields), drift)
        domain_reports[domain] = OrderedDict([
            ("observation_mode", mode),
            ("compared_fields", list(compared_fields)),
            ("not_observable_fields", [f for f in _all_fields() if f not in compared_fields]),
            ("expected_t0_domain_sha256", domain_sha256(expected, fields=compared_fields)),
            ("observed_domain_sha256", domain_sha256(observed, fields=compared_fields)),
            ("match", True),
            ("image_ref", observed.get("image_ref")),
            ("image_id", observed.get("image_id")),
            ("rootfs_layers_sha256", observed.get("rootfs_layers_sha256")),
            ("tool_identities", observed.get("tool_identities")),
            ("evidence", observed.get("evidence")),
        ])

    observed_condition_sha = fresh["sha256"] if fresh else None
    evidence = OrderedDict([
        ("schema_version", STAGE_RUNTIME_EVIDENCE_VERSION),
        ("run_id", run_id),
        ("stage", stage),
        ("runtime_domains", list(domains)),
        ("observation_mode", mode),
        ("contract_sha256", contract_sha),
        ("authorization_sha256", authorization_sha),
        ("expected_t0_runtime_condition_sha256", t0_sha),
        ("observed_runtime_condition_sha256", observed_condition_sha),
        # the per-domain identities always matched at this point; the
        # run-wide condition is only observable with docker
        ("match", True if observed_condition_sha is None
         else observed_condition_sha == t0_sha),
        ("drift_fields", []),
        ("domains", domain_reports),
        ("checked_at_utc", utc_now_iso()),
        ("probe_duration_seconds", fresh["probe_duration_seconds"] if fresh else None),
    ])
    if not evidence["match"]:
        # the per-domain identities matched but the run-wide condition did
        # not: another domain changed - report it rather than hide it
        evidence["drift_fields"] = ["runtime_condition_sha256"]
        raise StageRuntimeDrift(stage, ",".join(domains), t0_sha, observed_condition_sha,
                                ["runtime_condition_sha256"])

    fingerprint = _evidence_fingerprint(evidence)
    evidence["stage_runtime_sha256"] = fingerprint
    if register:
        _register_stage_evidence(config, run_id, stage, evidence, writer=writer)
    return evidence


def _evidence_fingerprint(evidence: "Dict[str, Any]") -> str:
    """Methodical fields only - no timestamp, no probe duration."""
    from thesis.evaluation.condition_hashing import canonical_sha256

    body = OrderedDict()
    for field in ("schema_version", "run_id", "stage", "runtime_domains", "observation_mode",
                  "contract_sha256", "authorization_sha256",
                  "expected_t0_runtime_condition_sha256",
                  "observed_runtime_condition_sha256", "match"):
        body[field] = evidence.get(field)
    body["domains"] = OrderedDict(
        (name, OrderedDict([("expected_t0_domain_sha256", d["expected_t0_domain_sha256"]),
                            ("observed_domain_sha256", d["observed_domain_sha256"])]))
        for name, d in (evidence.get("domains") or {}).items())
    return canonical_sha256(body)


def reset_cache() -> None:
    with _CACHE_LOCK:
        _STAMPED.clear()


def static_stages_for_tools(tools: "List[str]") -> "List[str]":
    """Which runtime domains a static invocation will actually produce
    findings in. A container that runs only PARCOACH stamps only the
    PARCOACH domain; the main domain is stamped whenever any host-side tool
    runs. The stamp therefore always covers the runtime that produced the
    findings of THIS invocation."""
    tools = [t for t in tools or []]
    stages = []
    if any(t not in ("parcoach", "llov") for t in tools):
        stages.append("static.main")
    if "parcoach" in tools:
        stages.append("static.parcoach")
    if "llov" in tools:
        stages.append("static.llov")
    return stages


EXPECTED_RUNTIME_STAGE_POLICY = "expected_runtime_stages.v2"

# Static tools that run in their OWN container, with the execution model that
# makes them applicable at all. A tool is only EXPECTED when the contract
# enables it AND its effective scope intersects the contracted population -
# PARCOACH is MPI-relevant, LLOV is OpenMP-relevant, so a serial-only
# population must not produce a false requirement.
SPLIT_CONTAINER_TOOLS = OrderedDict([
    ("parcoach", ("static.parcoach", DOMAIN_PARCOACH)),
    ("llov", ("static.llov", DOMAIN_LLOV)),
])


def _contracted_execution_models(contract: "Optional[Dict[str, Any]]") -> "List[str]":
    models = (contract or {}).get("execution_models")
    if models is None:
        models = ((contract or {}).get("population") or {}).get("execution_models")
    return list(models or [])


def _static_toolset(contract: "Optional[Dict[str, Any]]",
                    config: "Optional[Dict[str, Any]]" = None) -> "OrderedDict[str, Any]":
    """The contracted static toolset. The FROZEN contract decides; the live
    config is only a fallback for a run whose contract predates v2 (and is
    marked as such by the caller)."""
    toolset = (contract or {}).get("static_toolset")
    if isinstance(toolset, dict) and toolset and "error" not in toolset:
        return OrderedDict(sorted(toolset.items()))
    if config is None:
        return OrderedDict()
    from thesis.evaluation.tool_config import resolve_tool_settings

    try:
        settings = resolve_tool_settings(config, "static_analysis")
    except Exception:  # noqa: BLE001 - an unusable config yields no expectation
        return OrderedDict()
    return OrderedDict((name, OrderedDict([("enabled", settings[name].enabled),
                                           ("execution_models",
                                            list(settings[name].execution_models))]))
                       for name in sorted(settings))


def expected_runtime_stages(contract: "Optional[Dict[str, Any]]",
                            config: "Optional[Dict[str, Any]]" = None
                            ) -> "List[OrderedDict]":
    """The runtime stages a FROZEN CONTRACT expects, each with the reason.

    Derived from the frozen contract's expected stages, its static toolset,
    the applicable execution models and its repair plan - never from the
    result files that happen to lie on disk (result files never imply a
    runtime). Every entry must carry a stage runtime stamp; everything not
    listed is NOT_APPLICABLE and is never required."""
    stages = list((contract or {}).get("expected_stages") or [])
    population = _contracted_execution_models(contract)
    expected: "List[OrderedDict]" = []

    def add(stage, reason):
        owner, domains = STAGE_DOMAINS[stage]
        expected.append(OrderedDict([
            ("stage", stage), ("owner", owner), ("domains", list(domains)),
            ("reason", reason)]))

    if "correctness_tests" in stages:
        add("correctness", "the contract expects the correctness stage")
    if "dynamic_analysis" in stages:
        add("dynamic", "the contract expects the dynamic analysis stage")
    if "enhanced_tests" in stages:
        add("enhanced", "the contract expects the enhanced test stage")

    if "static_analysis" in stages:
        toolset = _static_toolset(contract, config)
        main_tools = [name for name, entry in toolset.items()
                      if name not in SPLIT_CONTAINER_TOOLS and (entry or {}).get("enabled")
                      and _applicable((entry or {}).get("execution_models"), population)]
        if main_tools:
            add("static.main", "the contract expects static analysis with main-container "
                               "tools (%s)" % ", ".join(main_tools))
        elif not toolset:
            # a contract without a toolset view (pre-v2, or a resolver error at
            # freeze time): the historical behaviour, so a missing main stamp
            # is still reported
            add("static.main", "the contract expects static analysis (no frozen toolset "
                               "view: main-container expectation assumed)")
        for tool, (stage, _domain) in SPLIT_CONTAINER_TOOLS.items():
            if not toolset:
                # applicability is UNRESOLVED, not proven inapplicable: without
                # a frozen toolset we cannot claim the tool was not contracted,
                # so it is demanded fail-closed and the reason says why
                add(stage, "the contract expects static analysis but carries no frozen "
                           "static toolset (pre-v2 contract or a toolset resolution "
                           "error), so %s applicability is UNRESOLVED and the stamp is "
                           "required fail-closed" % tool)
                continue
            entry = toolset.get(tool) or {}
            if not entry.get("enabled"):
                continue
            scope = entry.get("execution_models")
            if not _applicable(scope, population):
                continue
            overlap = sorted(set(scope or []) & set(population)) or list(scope or []) \
                or ["(scope unknown)"]
            add(stage, "the contract enables %s for execution model(s) %s, which the "
                       "contracted population contains" % (tool, ", ".join(overlap)))

    if "repair" in stages:
        plan = (contract or {}).get("repair_plan")
        if plan is None:
            add("repair_evaluation", "the contract expects the repair stage (no frozen "
                                     "repair plan: evaluation expectation assumed)")
        elif plan.get("enabled") and plan.get("evaluates_repair_candidates"):
            add("repair_evaluation", "the contract expects a repair loop that evaluates "
                                     "repair candidates with the base evaluation stages")
    return expected


def _applicable(scope: "Optional[List[str]]", population: "List[str]") -> bool:
    """A tool is applicable when its effective execution-model scope meets the
    contracted population.

    An UNKNOWN scope (None - the contract does not say) or an unknown
    population cannot prove non-applicability, so it stays applicable
    (fail-closed). An EMPTY scope is different: the tool provably cannot
    analyse any execution model (the config narrowed it outside the tool's
    hard capabilities), so it is not applicable and must not be required."""
    if scope is not None and len(scope) == 0:
        return False
    if not scope or not population:
        return True
    return bool(set(scope) & set(population))


def expected_stages(contract: "Optional[Dict[str, Any]]",
                    config: "Optional[Dict[str, Any]]" = None) -> "List[str]":
    """The stage names of expected_runtime_stages (compatibility view)."""
    return [entry["stage"] for entry in expected_runtime_stages(contract, config)]


def registered_stage_runtimes(manifest: "Optional[Dict[str, Any]]") -> "Dict[str, Any]":
    return (manifest or {}).get("stage_runtime_evidence") or {}


def runtime_matrix(manifest: "Optional[Dict[str, Any]]",
                   contract: "Optional[Dict[str, Any]]",
                   config: "Optional[Dict[str, Any]]" = None) -> "List[OrderedDict]":
    """CONTRACT == T0 == STAGE per expected runtime domain, machine-readable.

    ONE status ladder for the matrix and the post-run verifier, so a row and
    its check can never disagree:

        no stamp                      -> UNRESOLVED (result files never imply
                                         a runtime, and a retrospective probe
                                         never substitutes for one)
        stamp of another contract     -> FAIL
        no comparable identity        -> UNRESOLVED
        T0 domain != stage domain     -> FAIL
        stamp taken against other T0  -> FAIL
        otherwise                     -> PASS

    Every expected (stage, domain) produces a row; nothing silently vanishes.
    """
    evidence = (manifest or {}).get("runtime_evidence") or {}
    contract_runtime_sha = ((contract or {}).get("conditions") or {}).get(
        "static_repair_runtime_condition_sha256")
    contract_sha = (contract or {}).get("contract_sha256")
    t0_sha = evidence.get("fresh_runtime_condition_sha256")
    stamps = registered_stage_runtimes(manifest)
    rows = []
    for entry in expected_runtime_stages(contract, config):
        stage = entry["stage"]
        owner = entry["owner"]
        stamp = stamps.get(owner)
        for domain in entry["domains"]:
            domain_entry = ((stamp or {}).get("domains") or {}).get(domain) or {}
            expected_sha = domain_entry.get("expected_t0_domain_sha256")
            observed = domain_entry.get("observed_domain_sha256")
            stamped_t0 = (stamp or {}).get("expected_t0_runtime_condition_sha256")
            if stamp is None:
                status, detail = "UNRESOLVED", (
                    "no stage runtime stamp for %s - the runtime that produced these "
                    "records is unproven (result files do not substitute for it, and a "
                    "retrospective probe now never does)" % stage)
            elif contract_sha is not None and stamp.get("contract_sha256") != contract_sha:
                status, detail = "FAIL", (
                    "the stage runtime stamp belongs to contract %s..., not %s..."
                    % (str(stamp.get("contract_sha256"))[:12], str(contract_sha)[:12]))
            elif not expected_sha or not observed:
                status, detail = "UNRESOLVED", (
                    "the stamp carries no comparable identity for domain %s" % domain)
            elif expected_sha != observed:
                status, detail = "FAIL", ("T0 %s... vs stage %s..."
                                          % (expected_sha[:12], observed[:12]))
            elif t0_sha and stamped_t0 and stamped_t0 != t0_sha:
                status, detail = "FAIL", (
                    "the stamp was taken against another T0 runtime (%s... vs %s...)"
                    % (str(stamped_t0)[:12], str(t0_sha)[:12]))
            else:
                status, detail = "PASS", ("contract == T0 == stage (%s, %s)"
                                          % (domain, stamp.get("observation_mode")))
            rows.append(OrderedDict([
                ("stage", stage),
                ("domain", domain),
                ("owner", owner),
                ("expected_because", entry["reason"]),
                ("contract", contract_runtime_sha),
                ("t0", t0_sha),
                ("stage_expected", expected_sha),
                ("stage_observed", observed),
                ("status", status),
                ("detail", detail),
            ]))
    return rows


def not_expected_runtime_stages(contract: "Optional[Dict[str, Any]]",
                                config: "Optional[Dict[str, Any]]" = None
                                ) -> "List[OrderedDict]":
    """Stages the contract does NOT expect, with the reason - so a missing
    stamp there is visibly NOT_APPLICABLE instead of silently absent."""
    expected = {entry["stage"] for entry in expected_runtime_stages(contract, config)}
    stages = list((contract or {}).get("expected_stages") or [])
    toolset = _static_toolset(contract, config)
    population = _contracted_execution_models(contract)
    reasons = OrderedDict()
    for stage in STAGE_DOMAINS:
        if stage in expected:
            continue
        if stage == "correctness":
            reason = "the contract does not expect the correctness stage"
        elif stage == "dynamic":
            reason = "the contract does not expect the dynamic analysis stage"
        elif stage == "enhanced":
            reason = "the contract does not expect the enhanced test stage"
        elif stage == "repair_evaluation":
            reason = ("the contract does not expect a repair loop"
                      if "repair" not in stages else "the frozen repair plan is disabled")
        elif stage == "static.main":
            reason = ("the contract does not expect static analysis" if "static_analysis"
                      not in stages else "no main-container static tool is contracted")
        else:
            tool = "parcoach" if stage.endswith("parcoach") else "llov"
            entry = toolset.get(tool) or {}
            scope = entry.get("execution_models")
            if "static_analysis" not in stages:
                reason = "the contract does not expect static analysis"
            elif not toolset:
                # never claim "not enabled" when the contract simply does not
                # say - that would be a false assertion in the report
                reason = ("UNRESOLVED: the contract carries no frozen static toolset, so "
                          "%s applicability cannot be determined" % tool)
            elif not entry.get("enabled"):
                reason = "%s is not enabled in the frozen static toolset" % tool
            elif scope is not None and len(scope) == 0:
                reason = ("%s has an EMPTY effective execution-model scope (the config "
                          "narrowed it outside the tool's hard capabilities), so it can "
                          "analyse no sample" % tool)
            else:
                reason = ("%s is applicable to %s only, which the contracted population "
                          "(%s) does not contain"
                          % (tool, ", ".join(scope or ["(scope unknown)"]),
                             ", ".join(population) or "(unknown)"))
        reasons[stage] = reason
    return [OrderedDict([("stage", stage),
                         ("status", "UNRESOLVED" if reason.startswith("UNRESOLVED")
                          else "NOT_APPLICABLE"),
                         ("reason", reason)])
            for stage, reason in reasons.items()]

# ---------------------------------------------------------------------------
# Split-container invocation coverage (technical provenance cleanup wave)
#
# The PARCOACH and LLOV containers are invoked once per model
# (`run_static_analysis.py --model-id <m> --tools <tool>`, the productive
# external_tool_commands) or once for every enabled model (the documented
# base-run container command without --model-id), and every invocation
# registers ONE effective invocation fragment - `invocation.<stage>@<model>
# @tools-<tool>` resp. `invocation.<stage>@tools-<tool>` - BEFORE it writes a
# record, and appends one entry with its condition to each processed model's
# static_analysis_summary.json. `effective_invocation:<stage>` checks every
# fragment that exists against the contract - MEMBERSHIP. It never asked
# whether every contracted model HAS one - COVERAGE - so a run whose PARCOACH
# findings exist for all eleven models but whose invocation provenance
# survived for one of them verified PASS (STATIC_SPLIT_INVOCATION_COVERAGE_GAP).
# Static record coverage catches a container that never ran (no entries); it
# cannot see a lost invocation behind complete records, and a stage runtime
# stamp proves the runtime of the container, not which models it was invoked
# for.
#
# The expected scopes come from the FROZEN CONTRACT only: model_ids x the
# split tools its static toolset enables x the execution models that toolset
# scope shares with the contracted population. No model count and no tool
# scope is hard-coded here.
# ---------------------------------------------------------------------------

SPLIT_INVOCATION_COVERAGE_POLICY = "split_static_invocation_coverage.v1"
SPLIT_SCOPE_IDENTITY = "(stage, tool, model_id)"
RUNTIME_STAMP_SUBSTITUTES_SPLIT_INVOCATION = False
RECORD_COVERAGE_SUBSTITUTES_SPLIT_INVOCATION = False
# Fragments of the same stage whose non-scope effective values agree cover
# their scopes jointly (a per-model container run and a whole-run container
# run, a resumed run re-registering idempotently); differing values under one
# scope contradict each other, and so does a model history that records an
# execution under a condition no fragment carries.
SPLIT_DUPLICATE_POLICY = "CONSISTENT_DUPLICATES_ALLOWED_CONTRADICTIONS_FAIL"
# A whole-run fragment (model_scope null) proves the invocation CONDITION;
# the model's own summary entry under the SAME condition proves the model
# was processed under it. Neither alone covers a scope.
SPLIT_WHOLE_RUN_RULE = "WHOLE_RUN_FRAGMENT_COVERS_ONLY_WITH_MATCHING_MODEL_HISTORY"

SCOPE_PASS = "PASS"
SCOPE_UNRESOLVED = "UNRESOLVED"
SCOPE_FAIL = "FAIL"

# effective values that do NOT belong to the invocation's scope: two fragments
# covering one scope, and a fragment and the model history it covers, must
# agree on every one of them. The static summary records the same values per
# invocation (run_static_analysis.run_model), replace_tool_entries as the
# list of tools (non-empty <=> the fragment's True).
_SPLIT_CONDITION_FIELDS = ("primary_compiler", "replace_tool_entries", "rerun_gaps",
                           "replace_legacy_record")


def _safe_text(value: Any, limit: int = 120) -> str:
    try:
        text = json.dumps(value, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        text = repr(value)
    return text[:limit]


def expected_split_static_invocations(contract: "Optional[Dict[str, Any]]"
                                      ) -> "OrderedDict[str, Any]":
    """Every logical split-container invocation scope the FROZEN contract
    demands: one per (stage, tool, model_id), with the execution models the
    tool is contracted to analyse and the contract binding it must carry.

    status PASS            the expected set is derivable from the contract
           NOT_APPLICABLE  the contract expects no split-container tool
           UNRESOLVED      the contract does not determine it (no contract,
                           no frozen toolset, no model set, malformed shapes)
                           - fail-closed: coverage can then never be PASS
    """
    result: "OrderedDict[str, Any]" = OrderedDict([
        ("policy", SPLIT_INVOCATION_COVERAGE_POLICY),
        ("identity", SPLIT_SCOPE_IDENTITY),
        ("status", SCOPE_UNRESOLVED),
        ("reason", None),
        ("contract_sha256", None),
        ("model_ids", []),
        ("population_execution_models", []),
        ("scopes", []),
        ("per_tool", OrderedDict()),
        ("not_expected", []),
    ])
    try:
        return _expected_split_static_invocations(contract, result)
    except Exception as exc:  # noqa: BLE001 - a contract of an unusable shape
        result["status"] = SCOPE_UNRESOLVED
        result["reason"] = "the frozen contract could not be interpreted: %s: %s" % (
            type(exc).__name__, exc)
        result["scopes"] = []
        return result


def _expected_split_static_invocations(contract, result):
    if not isinstance(contract, dict):
        result["reason"] = "no frozen contract: the expected split invocation scopes are unknown"
        return result
    result["contract_sha256"] = contract.get("contract_sha256")
    stages = contract.get("expected_stages")
    if not isinstance(stages, list):
        result["reason"] = "the frozen contract carries no usable expected_stages list"
        return result
    if "static_analysis" not in stages:
        result["status"] = "NOT_APPLICABLE"
        result["reason"] = "the contract does not expect static analysis"
        return result
    model_ids = contract.get("model_ids")
    if not isinstance(model_ids, list) or not model_ids \
            or not all(isinstance(m, str) and m for m in model_ids):
        result["reason"] = "the frozen contract carries no usable model_ids list"
        return result
    toolset = _static_toolset(contract)
    if not toolset:
        result["reason"] = ("the frozen contract carries no frozen static toolset (pre-v2 "
                            "contract or a toolset resolution error), so the split-container "
                            "expectation cannot be derived")
        return result
    population = _contracted_execution_models(contract)
    if not isinstance(population, list) or not all(isinstance(m, str) for m in population):
        result["reason"] = "the frozen contract carries no usable execution_models list"
        return result
    result["model_ids"] = sorted(model_ids)
    result["population_execution_models"] = list(population)
    scopes = []
    for tool, (stage, _domain) in SPLIT_CONTAINER_TOOLS.items():
        entry = toolset.get(tool)
        if not isinstance(entry, dict):
            result["reason"] = ("the frozen static toolset entry of %s is not an object (%s)"
                                % (tool, _safe_text(entry)))
            result["scopes"] = []
            result["status"] = SCOPE_UNRESOLVED
            return result
        scope = entry.get("execution_models")
        if scope is not None and (not isinstance(scope, list)
                                  or not all(isinstance(m, str) for m in scope)):
            result["reason"] = ("the frozen execution_models of %s is not a list of names (%s)"
                                % (tool, _safe_text(scope)))
            result["scopes"] = []
            result["status"] = SCOPE_UNRESOLVED
            return result
        if not entry.get("enabled"):
            result["not_expected"].append(OrderedDict([
                ("tool", tool), ("stage", stage),
                ("reason", "%s is not enabled in the frozen static toolset" % tool)]))
            result["per_tool"][tool] = OrderedDict([("stage", stage), ("expected", False),
                                                    ("scope_count", 0)])
            continue
        if not _applicable(scope, population):
            result["not_expected"].append(OrderedDict([
                ("tool", tool), ("stage", stage),
                ("reason", "%s is applicable to %s only, which the contracted population (%s) "
                           "does not contain"
                           % (tool, ", ".join(scope or ["(none)"]), ", ".join(population) or "(unknown)"))]))
            result["per_tool"][tool] = OrderedDict([("stage", stage), ("expected", False),
                                                    ("scope_count", 0)])
            continue
        applicable = sorted(set(scope or []) & set(population)) if scope and population \
            else list(scope or population or [])
        for model_id in sorted(model_ids):
            scopes.append(OrderedDict([
                ("stage", stage), ("tool", tool), ("model_id", model_id),
                ("applicable_execution_models", applicable),
                ("contract_binding", OrderedDict([
                    ("contract_sha256", contract.get("contract_sha256")),
                    ("model_ids_source", "contract.model_ids"),
                    ("toolset_source", "contract.static_toolset.%s" % tool),
                    ("population_source", "contract.execution_models"),
                ])),
            ]))
        result["per_tool"][tool] = OrderedDict([("stage", stage), ("expected", True),
                                                ("applicable_execution_models", applicable),
                                                ("scope_count", len(model_ids))])
    result["scopes"] = scopes
    result["status"] = SCOPE_PASS if scopes else "NOT_APPLICABLE"
    result["reason"] = ("%d expected split invocation scope(s) derived from the frozen contract "
                        "(%d model(s) x %s)" % (len(scopes), len(model_ids),
                                                ", ".join(t for t, v in result["per_tool"].items()
                                                          if v["expected"]) or "no split tool")
                        if scopes else "no contracted split-container tool applies to the "
                                       "contracted population")
    return result


# the three switches default to False in the productive runner (source
# DEFAULT); a fragment or history entry that does not record one is read as
# that default, so an override can never hide behind an absent field
_SPLIT_SWITCH_DEFAULTS = OrderedDict([("replace_tool_entries", False), ("rerun_gaps", False),
                                      ("replace_legacy_record", False)])


def _fragment_condition(values: "Dict[str, Any]") -> "OrderedDict[str, Any]":
    condition: "OrderedDict[str, Any]" = OrderedDict()
    for field in _SPLIT_CONDITION_FIELDS:
        entry = values.get(field)
        if isinstance(entry, dict):
            value = entry.get("value")
            if field in _SPLIT_SWITCH_DEFAULTS:
                value = bool(value)
            condition[field] = value
        elif field in _SPLIT_SWITCH_DEFAULTS:
            condition[field] = _SPLIT_SWITCH_DEFAULTS[field]
    return condition


def _summary_condition(invocation: "Dict[str, Any]") -> "OrderedDict[str, Any]":
    """The condition a static summary invocation entry records, in the
    fragment's terms (the switches as bools, absent switches as their
    defaults)."""
    condition: "OrderedDict[str, Any]" = OrderedDict()
    for field in _SPLIT_CONDITION_FIELDS:
        if field not in invocation:
            if field in _SPLIT_SWITCH_DEFAULTS:
                condition[field] = _SPLIT_SWITCH_DEFAULTS[field]
            continue
        value = invocation.get(field)
        if field in _SPLIT_SWITCH_DEFAULTS:
            value = bool(value)
        condition[field] = value
    return condition


def _conditions_agree(a: "Dict[str, Any]", b: "Dict[str, Any]") -> bool:
    """Two recorded conditions agree when every field KNOWN on both sides is
    equal (an unrecorded field cannot contradict)."""
    for field in set(a) & set(b):
        if a[field] != b[field]:
            return False
    return True


def _split_fragment_view(owner: str, invocation: Any, contract: "Dict[str, Any]",
                         run_id: "Optional[str]", contracted_models: "Any") -> "OrderedDict[str, Any]":
    """One registered invocation fragment, classified: which (stage, tool,
    model) scopes it claims and why it is unkeyable / unexpected /
    contradicting. A body of a wrong SHAPE is reported and never handed to
    the contract check (which assumes the productive shape)."""
    from thesis.evaluation import effective_invocation as ei

    view: "OrderedDict[str, Any]" = OrderedDict([
        ("owner", owner), ("stage", None), ("tools", []), ("model_scope", None),
        ("whole_run", False), ("problems", []), ("unexpected_models", []),
        ("condition", OrderedDict()),
    ])
    if not isinstance(invocation, dict):
        view["problems"].append("fragment %s is not an object" % owner)
        return view
    stage = invocation.get("stage")
    if not isinstance(stage, str):
        view["problems"].append("stage %s is not a string" % _safe_text(stage))
        stage = None
    view["stage"] = stage
    if invocation.get("schema_version") != ei.EFFECTIVE_INVOCATION_VERSION:
        view["problems"].append("schema_version %s is not %s"
                                % (_safe_text(invocation.get("schema_version")),
                                   ei.EFFECTIVE_INVOCATION_VERSION))
    if run_id is not None and invocation.get("run_id") != run_id:
        view["problems"].append("fragment belongs to run %s, not %r"
                                % (_safe_text(invocation.get("run_id")), run_id))
    values = invocation.get("effective_values")
    if not isinstance(values, dict) or not all(isinstance(v, dict) for v in values.values()):
        view["problems"].append("effective_values is not an object of {value, source} entries")
        values = {}
    tools_entry = values.get("tools")
    tools = tools_entry.get("value") if isinstance(tools_entry, dict) else None
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        view["problems"].append("effective_values.tools is not a list of tool names")
        tools = []
    view["tools"] = sorted(tools)
    scope = invocation.get("model_scope")
    if scope is None:
        view["whole_run"] = True
    elif isinstance(scope, list) and scope and all(isinstance(m, str) and m for m in scope):
        view["model_scope"] = sorted(scope)
        if len(scope) > 1:
            # the static runner takes exactly one --model-id: a split fragment
            # names one model or every enabled model (null), never a list
            view["problems"].append("model_scope names %d models; a split-container invocation "
                                    "carries one model or null" % len(scope))
        if isinstance(contracted_models, set):
            view["unexpected_models"] = sorted(m for m in scope if m not in contracted_models)
    else:
        view["problems"].append("model_scope %s is neither null nor a non-empty list of model ids"
                                % _safe_text(scope))
    if view["problems"]:
        return view
    try:
        if ei.invocation_fingerprint(invocation) != invocation.get("invocation_sha256"):
            view["problems"].append("the fragment does not match its own fingerprint")
    except Exception as exc:  # noqa: BLE001 - unkeyable content
        view["problems"].append("fingerprint not computable: %s" % exc)
    try:
        from thesis.evaluation import manifest_fragments as mf

        expected_owner = ei.invocation_owner(stage, scope, values)
        # the merged manifest keys fragments by their sanitised file name
        if owner not in (expected_owner, mf._safe(expected_owner)):
            view["problems"].append("owner %s does not match the fragment body (%s)"
                                    % (owner, expected_owner))
    except Exception as exc:  # noqa: BLE001
        view["problems"].append("owner not derivable from the body: %s" % exc)
    try:
        # the model-set problem is classified as UNEXPECTED (below), every
        # other contract contradiction as a problem of the fragment
        view["problems"] += [p for p in ei.check_against_contract(invocation, contract)
                             if not p.startswith("model_scope ")]
    except Exception as exc:  # noqa: BLE001
        view["problems"].append("contract check not computable: %s: %s" % (type(exc).__name__, exc))
    view["condition"] = _fragment_condition(values)
    return view


def _model_tool_evidence(intermediate_dir: "Optional[Path]", run_id: "Optional[str]",
                         model_id: str, tool: str) -> "OrderedDict[str, Any]":
    """What the model's own static artifacts say about the tool: records with
    an entry of the tool (any state, NOT_APPLICABLE included - the container
    writes those itself) and the per-model summary invocations that ran it,
    each with the condition it recorded. A file of a wrong shape is reported
    as unreadable, never a crash and never evidence."""
    evidence: "OrderedDict[str, Any]" = OrderedDict([
        ("records_with_entry", 0), ("records_total", 0), ("records_unreadable", None),
        ("summary_invocations", []), ("summary_unreadable", None),
    ])
    if intermediate_dir is None or run_id is None:
        return evidence
    model_dir = Path(intermediate_dir) / run_id / model_id
    records_path = model_dir / "static_analysis.jsonl"
    if records_path.is_file():
        try:
            for line in records_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                evidence["records_total"] += 1
                tools = record.get("tools") if isinstance(record, dict) else None
                if isinstance(tools, dict) and tool in tools:
                    evidence["records_with_entry"] += 1
        except Exception as exc:  # noqa: BLE001 - unreadable or wrongly shaped
            evidence["records_unreadable"] = "%s: %s" % (type(exc).__name__, exc)
    summary_path = model_dir / "static_analysis_summary.json"
    if not summary_path.is_file():
        if evidence["records_total"] > 0:
            # the static runner writes its summary together with its records:
            # records without a history are a lost provenance artifact
            evidence["summary_unreadable"] = ("static_analysis_summary.json absent although %d "
                                              "static record(s) exist - the runner writes it on "
                                              "every invocation" % evidence["records_total"])
    else:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(summary, dict):
                raise ValueError("not a JSON object (%s)" % type(summary).__name__)
            if summary.get("model_id") not in (None, model_id):
                raise ValueError("summary names model %s inside %s's directory"
                                 % (_safe_text(summary.get("model_id")), model_id))
            invocations = summary.get("invocations")
            if not invocations and evidence["records_total"] > 0:
                raise ValueError("no invocation entry although %d static record(s) exist - the "
                                 "runner appends one on every invocation"
                                 % evidence["records_total"])
            if invocations is None:
                invocations = []
            if not isinstance(invocations, list):
                raise ValueError("invocations is not a list")
            for index, invocation in enumerate(invocations):
                if not isinstance(invocation, dict):
                    raise ValueError("invocation %d is not an object" % index)
                tools_run = invocation.get("tools_run")
                if tools_run is not None and not isinstance(tools_run, list):
                    raise ValueError("invocation %d: tools_run is not a list" % index)
                if not tools_run or tool not in tools_run:
                    continue
                skipped = invocation.get("tools_skipped") or []
                skipped_names = [s.get("tool") if isinstance(s, dict) else s
                                 for s in (skipped if isinstance(skipped, list) else [])]
                if tool in skipped_names:
                    continue
                # the repair loop's internal static run never runs the split
                # tools (orchestrator.internal_static_settings excludes the
                # external ones): only a base-writer entry can evidence the
                # container invocation
                label = invocation.get("label")
                if invocation.get("writer") not in (None, "base") or (
                        isinstance(label, str) and label.startswith("repair ")):
                    continue
                evidence["summary_invocations"].append(OrderedDict([
                    ("index", index), ("label", label if isinstance(label, str) else None),
                    ("condition", _summary_condition(invocation)),
                ]))
        except Exception as exc:  # noqa: BLE001
            evidence["summary_unreadable"] = "%s: %s" % (type(exc).__name__, exc)
            evidence["summary_invocations"] = []
    return evidence


def _narrowing_evidence(manifest: "Optional[Dict[str, Any]]",
                        contract: "Dict[str, Any]") -> "OrderedDict[str, Any]":
    """Run-level provenance that the model set was DELIBERATELY narrowed
    below the contract: the frozen resolved_config enables a strict subset
    of the contracted models. A recorded config drift that touched the model
    list carries no before/after set, so it is reported, never probative."""
    contracted = set(m for m in (contract.get("model_ids") or []) if isinstance(m, str))
    frozen = ((manifest or {}).get("resolved_config") or {})
    frozen = frozen.get("models") if isinstance(frozen, dict) else None
    enabled = None
    if isinstance(frozen, list):
        enabled = sorted(str(m.get("id")) for m in frozen
                         if isinstance(m, dict) and m.get("enabled", False) and m.get("id"))
    drift = [d for d in ((manifest or {}).get("config_drift") or [])
             if isinstance(d, dict)
             and any(str(k).startswith("models") for k in (d.get("changed_keys") or []))]
    narrowed = bool(enabled is not None and contracted and set(enabled) < contracted)
    reason = None
    if narrowed:
        reason = ("the run's frozen resolved_config enables only %s of the %d contracted "
                  "model(s)" % (", ".join(enabled), len(contracted)))
    return OrderedDict([("narrowed", narrowed), ("reason", reason),
                        ("frozen_enabled_models", enabled),
                        ("model_list_drift_records", len(drift)),
                        ("model_list_drift_note", ("a recorded config drift touched the model list "
                                                   "after the run started; it carries no model set, "
                                                   "so narrowing can neither be proven nor excluded "
                                                   "from it") if drift else None)])


def split_static_invocation_matrix(manifest: "Optional[Dict[str, Any]]",
                                   contract: "Optional[Dict[str, Any]]",
                                   intermediate_dir: "Optional[Path]" = None,
                                   run_id: "Optional[str]" = None) -> "OrderedDict[str, Any]":
    """MEMBERSHIP and COVERAGE of the split-container invocations, separately.

    membership  every observed split fragment is an allowed scope (contracted
                model, contracted+applicable tool, correct stage/tool
                identity, own fingerprint and owner, contract-bound) and the
                fragments and model histories that share a scope agree on
                their condition
    coverage    every EXPECTED scope carries at least one valid, contract-
                bound invocation (a function of the expected scopes only)
    status      the combined verdict (FAIL if either fails, else UNRESOLVED
                if coverage is, else PASS)

    Per expected scope:
        VALID INVOCATION PRESENT                    PASS
        RECORDS PRESENT, INVOCATION MISSING         UNRESOLVED (the results
                                                    exist, the methodical
                                                    execution is not bound)
        RECORDS MISSING, INVOCATION MISSING         UNRESOLVED here; static
                                                    record coverage FAILs the
                                                    run on its own
        DELIBERATE NARROWING EVIDENCE               FAIL
        INVOCATION FOR A NON-APPLICABLE SCOPE       FAIL (membership)
        CONTRACT / FINGERPRINT / OWNER CONTRADICTION FAIL (membership)
        UNKEYABLE / MALFORMED FRAGMENT              FAIL (membership)
        HISTORY UNDER A CONDITION NO FRAGMENT CARRIES FAIL (contradiction)

    A whole-run fragment (model_scope null: the runner was started for every
    enabled model) covers a model only together with that model's own summary
    invocation of the tool UNDER THE SAME CONDITION - the fragment proves the
    invocation condition, the per-model history proves the model was
    processed under it.
    """
    from thesis.evaluation import effective_invocation as ei

    expected = expected_split_static_invocations(contract)
    matrix: "OrderedDict[str, Any]" = OrderedDict([
        ("policy", SPLIT_INVOCATION_COVERAGE_POLICY),
        ("identity", SPLIT_SCOPE_IDENTITY),
        ("duplicate_policy", SPLIT_DUPLICATE_POLICY),
        ("whole_run_rule", SPLIT_WHOLE_RUN_RULE),
        ("runtime_stamp_substitutes_split_invocation", RUNTIME_STAMP_SUBSTITUTES_SPLIT_INVOCATION),
        ("record_coverage_substitutes_split_invocation", RECORD_COVERAGE_SUBSTITUTES_SPLIT_INVOCATION),
        ("expected_set", expected),
        ("membership", SCOPE_UNRESOLVED), ("coverage", SCOPE_UNRESOLVED),
        ("status", SCOPE_UNRESOLVED), ("detail", None),
        ("expected_scope_count", len(expected["scopes"])),
        ("observed_scope_count", 0), ("covered_scope_count", 0),
        ("observed_fragment_count", 0),
        ("missing_scopes", []), ("unexpected_scopes", []), ("contradicting_scopes", []),
        ("unkeyable_fragments", []), ("consistent_duplicate_scopes", []),
        ("narrowing", OrderedDict([("narrowed", False), ("reason", None)])),
        ("per_tool", OrderedDict()), ("rows", []),
    ])
    split_stages = {stage for stage, _d in SPLIT_CONTAINER_TOOLS.values()}

    def is_split_fragment(owner, invocation):
        stage = invocation.get("stage") if isinstance(invocation, dict) else None
        if isinstance(stage, str) and stage in split_stages:
            return True
        return isinstance(owner, str) and any(owner == s or owner.startswith(s + "@")
                                              for s in split_stages)

    registered = [(str(owner), inv) for owner, inv in ei.registered_invocations(manifest).items()
                  if is_split_fragment(owner, inv)]
    if expected["status"] == "NOT_APPLICABLE":
        matrix["membership"] = matrix["coverage"] = matrix["status"] = "NOT_APPLICABLE"
        matrix["detail"] = expected["reason"]
        # an observed split fragment on a run that contracts no split tool is
        # an unexpected invocation: membership must still say so
        if registered:
            matrix["unexpected_scopes"] = [
                OrderedDict([("owner", o), ("stage", (i or {}).get("stage") if isinstance(i, dict) else None),
                             ("reason", "no split-container tool is contracted")])
                for o, i in registered]
            matrix["observed_fragment_count"] = len(registered)
            matrix["membership"] = matrix["status"] = SCOPE_FAIL
            matrix["detail"] = "%d split-container invocation(s) registered although the contract " \
                               "expects none" % len(registered)
        return matrix
    if expected["status"] != SCOPE_PASS:
        matrix["detail"] = expected["reason"]
        return matrix

    contracted_models = set(expected["model_ids"])
    expected_by_stage: "Dict[str, Dict[str, Any]]" = {}
    for scope in expected["scopes"]:
        expected_by_stage.setdefault(scope["stage"], {})[scope["model_id"]] = scope
    tool_of_stage = {stage: tool for tool, (stage, _d) in SPLIT_CONTAINER_TOOLS.items()}
    stage_of_tool = {tool: stage for tool, (stage, _d) in SPLIT_CONTAINER_TOOLS.items()}

    # ---- observed fragments -------------------------------------------------
    observed: "Dict[Tuple[str, str, str], List[OrderedDict]]" = {}
    unexpected: "List[OrderedDict]" = []
    unkeyable: "List[OrderedDict]" = []
    contradicting: "List[OrderedDict]" = []
    whole_run: "Dict[str, List[OrderedDict]]" = {}
    for owner, invocation in sorted(registered, key=lambda x: x[0]):
        view = _split_fragment_view(owner, invocation, contract, run_id, contracted_models)
        stage = view["stage"]
        tool = tool_of_stage.get(stage) if stage is not None else None
        if tool is None:
            view["problems"].append("stage %s is not a split-container stage" % _safe_text(stage))
        elif view["tools"] and tool not in view["tools"]:
            view["problems"].append("stage %s registered without %s in its tools (%s)"
                                    % (stage, tool, ", ".join(view["tools"]) or "none"))
        foreign_tools = [t for t in view["tools"] if t in stage_of_tool and t != tool]
        if foreign_tools:
            view["problems"].append("stage %s claims the split tool(s) %s of another stage"
                                    % (stage, ", ".join(foreign_tools)))
        if view["problems"]:
            unkeyable.append(OrderedDict([("owner", owner), ("stage", stage),
                                          ("problems", view["problems"])]))
            continue
        if stage not in expected_by_stage:
            # the stage's tool is contracted but not applicable / not enabled
            unexpected.append(OrderedDict([
                ("owner", owner), ("stage", stage), ("model_scope", view["model_scope"]),
                ("reason", "%s is not an expected split tool of this contract (%s)"
                           % (tool, "; ".join(n["reason"] for n in expected["not_expected"]
                                              if n["tool"] == tool) or "not contracted"))]))
            continue
        if view["unexpected_models"]:
            for model_id in view["unexpected_models"]:
                unexpected.append(OrderedDict([
                    ("owner", owner), ("stage", stage), ("model_id", model_id),
                    ("reason", "model %s is not part of the contracted model set" % model_id)]))
            continue
        if view["whole_run"]:
            whole_run.setdefault(stage, []).append(view)
            continue
        for model_id in view["model_scope"]:
            observed.setdefault((stage, tool, model_id), []).append(view)

    narrowing = _narrowing_evidence(manifest, contract)

    # ---- rows per expected scope ---------------------------------------------
    rows: "List[OrderedDict]" = []
    covered = 0
    observed_scopes = 0
    missing: "List[OrderedDict]" = []
    duplicates: "List[OrderedDict]" = []
    per_tool_counts: "Dict[str, Counter]" = {}
    for scope in expected["scopes"]:
        stage, tool, model_id = scope["stage"], scope["tool"], scope["model_id"]
        key = (stage, tool, model_id)
        per_model = list(observed.get(key, []))
        whole = list(whole_run.get(stage, []))
        evidence = _model_tool_evidence(intermediate_dir, run_id, model_id, tool)
        history = evidence["summary_invocations"]
        problems: "List[str]" = []
        notes: "List[str]" = []
        covering = list(per_model)
        # a whole-run fragment covers this model only with a matching history
        for view in whole:
            if any(_conditions_agree(view["condition"], h["condition"]) for h in history):
                covering.append(view)
            else:
                notes.append("whole-run fragment %s ignored: %s's own static summary records no "
                             "base invocation of %s under its condition"
                             % (view["owner"], model_id, tool))
        if evidence["summary_unreadable"]:
            notes.append("static summary unreadable: %s" % evidence["summary_unreadable"])
        if evidence["records_unreadable"]:
            notes.append("static records unreadable: %s" % evidence["records_unreadable"])
        # every base invocation the model's history records must be carried by
        # a fragment that covers this scope. With NO covering fragment the scope
        # is simply missing (records present, invocation missing); with a
        # covering fragment, a history entry under another condition is a
        # second, unregistered execution of the same scope - a contradiction
        # between the registered provenance and what happened
        unregistered = [entry for entry in history
                        if not any(_conditions_agree(v["condition"], entry["condition"])
                                   for v in covering)]
        if covering:
            for entry in unregistered:
                problems.append("%s's static summary records a base invocation of %s (entry %d: %s) "
                                "under a condition no covering fragment carries"
                                % (model_id, tool, entry["index"], _safe_text(entry["condition"])))
        elif unregistered:
            notes.append("%s's static summary records %d base invocation(s) of %s (%s) with no "
                         "fragment carrying that condition"
                         % (model_id, len(unregistered), tool,
                            "; ".join(_safe_text(e["condition"]) for e in unregistered)))
        conditions = []
        for view in covering:
            condition = json.dumps(view["condition"], sort_keys=True)
            if condition not in conditions:
                conditions.append(condition)
        if len(conditions) > 1:
            problems.append("%d fragments cover this scope under different conditions: %s"
                            % (len(covering), " | ".join(conditions)))
        if per_model or any(v in covering for v in whole):
            observed_scopes += 1
        if problems:
            status = SCOPE_FAIL
            detail = "; ".join(problems)
            contradicting.append(OrderedDict([("stage", stage), ("tool", tool),
                                              ("model_id", model_id), ("problems", problems)]))
        elif covering:
            status = SCOPE_PASS
            detail = "%d valid contract-bound invocation(s) (%s)" % (
                len(covering), ", ".join(v["owner"] for v in covering))
            covered += 1
            if len(covering) > 1:
                duplicates.append(OrderedDict([("stage", stage), ("tool", tool),
                                               ("model_id", model_id), ("fragments", len(covering))]))
                detail += " - consistent duplicates"
        elif narrowing["narrowed"] and model_id not in set(narrowing.get("frozen_enabled_models") or []):
            # only the models the frozen config disabled were deliberately left
            # out; an enabled model that lost its fragment is missing, not narrowed
            status = SCOPE_FAIL
            detail = "no invocation and the run's provenance shows a deliberate narrowing: %s" \
                     % narrowing["reason"]
            missing.append(OrderedDict([("stage", stage), ("tool", tool), ("model_id", model_id),
                                        ("status", status)]))
        elif evidence["records_with_entry"] > 0:
            status = SCOPE_UNRESOLVED
            detail = ("records present (%d of %d records carry a %s entry) but no invocation "
                      "provenance - the results exist, the methodical execution is not "
                      "contract-bound" % (evidence["records_with_entry"],
                                          evidence["records_total"], tool))
            missing.append(OrderedDict([("stage", stage), ("tool", tool), ("model_id", model_id),
                                        ("status", status), ("records_present", True)]))
        else:
            status = SCOPE_UNRESOLVED
            detail = ("no invocation provenance and no %s record entry for %s - static record "
                      "coverage decides the run; the missing invocation is not excused by it"
                      % (tool, model_id))
            missing.append(OrderedDict([("stage", stage), ("tool", tool), ("model_id", model_id),
                                        ("status", status), ("records_present", False)]))
        if status == SCOPE_PASS and (evidence["summary_unreadable"] or evidence["records_unreadable"]):
            # the model's own artifacts cannot be read: the history could hide a
            # contradiction, so the scope is not provable - fail-closed
            status = SCOPE_UNRESOLVED
            detail = "invocation present but the model's static artifacts are not readable: " + detail
            missing.append(OrderedDict([("stage", stage), ("tool", tool), ("model_id", model_id),
                                        ("status", status), ("evidence_unreadable", True)]))
        if notes:
            detail += "; " + "; ".join(notes)
        counts = per_tool_counts.setdefault(tool, Counter())
        counts[status] += 1
        rows.append(OrderedDict([
            ("stage", stage), ("tool", tool), ("model_id", model_id),
            ("applicable_execution_models", scope["applicable_execution_models"]),
            ("fragments", [v["owner"] for v in covering]),
            ("records_with_entry", evidence["records_with_entry"]),
            ("records_total", evidence["records_total"]),
            ("summary_invocations_running_tool", len(history)),
            ("evidence_unreadable", [n for n in notes if "unreadable" in n] or None),
            ("status", status), ("detail", detail),
        ]))

    membership_problems = len(unexpected) + len(unkeyable) + len(contradicting)
    matrix["membership"] = SCOPE_FAIL if membership_problems else SCOPE_PASS
    if any(r["status"] == SCOPE_FAIL for r in rows):
        coverage = SCOPE_FAIL
    elif any(r["status"] == SCOPE_UNRESOLVED for r in rows):
        coverage = SCOPE_UNRESOLVED
    else:
        coverage = SCOPE_PASS
    matrix["coverage"] = coverage
    if matrix["membership"] == SCOPE_FAIL or coverage == SCOPE_FAIL:
        matrix["status"] = SCOPE_FAIL
    else:
        matrix["status"] = coverage
    matrix["observed_scope_count"] = observed_scopes
    matrix["observed_fragment_count"] = len(registered)
    matrix["covered_scope_count"] = covered
    matrix["missing_scopes"] = missing
    matrix["unexpected_scopes"] = unexpected
    matrix["contradicting_scopes"] = contradicting
    matrix["unkeyable_fragments"] = unkeyable
    matrix["consistent_duplicate_scopes"] = duplicates
    matrix["narrowing"] = narrowing
    matrix["rows"] = rows
    for tool, info in expected["per_tool"].items():
        counts = per_tool_counts.get(tool, Counter())
        matrix["per_tool"][tool] = OrderedDict([
            ("stage", info["stage"]), ("expected_scope_count", info["scope_count"]),
            ("covered_scope_count", counts.get(SCOPE_PASS, 0)),
            ("unresolved_scope_count", counts.get(SCOPE_UNRESOLVED, 0)),
            ("fail_scope_count", counts.get(SCOPE_FAIL, 0)),
        ])
    matrix["detail"] = ("%d/%d expected split invocation scope(s) covered; %d missing; %d unexpected; "
                        "%d contradicting; %d unkeyable fragment(s); %d consistent duplicate scope(s)%s%s"
                        % (covered, len(rows), len(missing), len(unexpected), len(contradicting),
                           len(unkeyable), len(duplicates),
                           "; " + narrowing["reason"] if narrowing["narrowed"] else "",
                           "; " + narrowing["model_list_drift_note"]
                           if narrowing.get("model_list_drift_note") else ""))
    return matrix
