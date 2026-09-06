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

import threading
from collections import OrderedDict
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
REQUIRED_IDENTITIES = OrderedDict([
    (DOMAIN_MAIN, ("compiler", "mpi")),
    (DOMAIN_PARCOACH, ("parcoach",)),
    (DOMAIN_LLOV, ("llov",)),
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
        return OrderedDict([("enforced", False), ("stage", stage),
                            ("reason", state["reason"])])

    contract = state["contract"]
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


def expected_stages(contract: "Optional[Dict[str, Any]]") -> "List[str]":
    """The result-producing stages a contract expects, mapped to the runtime
    stages that must therefore carry a stamp."""
    stages = list((contract or {}).get("expected_stages") or [])
    required = []
    if "correctness_tests" in stages:
        required.append("correctness")
    if "dynamic_analysis" in stages:
        required.append("dynamic")
    if "enhanced_tests" in stages:
        required.append("enhanced")
    if "static_analysis" in stages:
        required.append("static.main")
    return required


def registered_stage_runtimes(manifest: "Optional[Dict[str, Any]]") -> "Dict[str, Any]":
    return (manifest or {}).get("stage_runtime_evidence") or {}


def runtime_matrix(manifest: "Optional[Dict[str, Any]]",
                   contract: "Optional[Dict[str, Any]]") -> "List[OrderedDict]":
    """CONTRACT == T0 == STAGE per domain, machine-readable."""
    evidence = (manifest or {}).get("runtime_evidence") or {}
    contract_sha = ((contract or {}).get("conditions") or {}).get(
        "static_repair_runtime_condition_sha256")
    t0_sha = evidence.get("fresh_runtime_condition_sha256")
    stamps = registered_stage_runtimes(manifest)
    rows = []
    for stage in expected_stages(contract):
        owner, domains = STAGE_DOMAINS[stage]
        stamp = stamps.get(owner)
        for domain in domains:
            observed = None
            status = "UNRESOLVED"
            if stamp:
                observed = ((stamp.get("domains") or {}).get(domain) or {}).get(
                    "observed_domain_sha256")
                expected = ((stamp.get("domains") or {}).get(domain) or {}).get(
                    "expected_t0_domain_sha256")
                if observed and expected and observed == expected \
                        and stamp.get("contract_sha256") == (contract or {}).get("contract_sha256"):
                    status = "PASS"
                elif observed and expected and observed != expected:
                    status = "FAIL"
                elif stamp.get("contract_sha256") != (contract or {}).get("contract_sha256"):
                    status = "FAIL"
            rows.append(OrderedDict([
                ("stage", stage),
                ("domain", domain),
                ("contract", contract_sha),
                ("t0", t0_sha),
                ("stage_observed", observed),
                ("status", status),
            ]))
    return rows
