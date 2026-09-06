"""Run start authorization and the provider chokepoint guard.

    NO cost-causing provider request can technically be executed without a
    valid run authorization.

That invariant cannot be established by calling a guard in every known
runner - a new runner forgets it. It is established here, at the two
chokepoints every provider request passes through:

    direct        thesis/generation/common.py::call_with_retries
    batch submit  thesis/generation/batch_api.py::submit_batch
    (batch poll   thesis/generation/batch_api.py::poll_batch - a status read
                  of an ALREADY authorized job: it validates the existing
                  authorization but neither creates one nor re-probes.)

`thesis/evaluation/provider_call_sites.py` proves by AST that every
cost-causing provider call in the repository is reachable only through
them (UNGUARDED_PROVIDER_CALL_SITES = []).

T0 order (never authorization first, evidence later):

     1. load the frozen contract
     2. verify its integrity (stored sha == content sha)
     3. rebuild the contract from the live state
     4. compare frozen sha vs rebuilt sha
     5. probe the runtime FRESH (main + parcoach + llov)
     6. compare the fresh runtime against the readiness artifact
     7. bind the contract to the run
     8. bind the T0 runtime evidence to the run
     9. validate the merged manifest/fragment state
    10. register the START AUTHORIZATION atomically
    11. read the authorization back from the run provenance and validate it
    12. only then may a provider request happen

The authorization's METHODICAL fingerprint covers the contract shas, the
runtime shas, the decision and the policy versions - never a timestamp, pid,
hostname, thread id or probe duration (those are recorded in the content,
`AUTHORIZATION_VOLATILE_FIELDS_EXCLUDED_FROM_FINGERPRINT = true`), so N
parallel first starts agree on ONE canonical authorization.

Every failure here is a PRE_RUN_INFRASTRUCTURE_FAILURE - never a model
refusal, an API error or a generation failure.

Python 3.8 compatible.
"""
from __future__ import annotations

import os
import platform
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

AUTHORIZATION_SCHEMA_VERSION = "run_start_authorization.v1"
AUTHORIZATION_POLICY_VERSION = "provider_authorization_policy.v1"
T0_RUNTIME_EVIDENCE_VERSION = "t0_runtime_evidence.v2"

DECISION_ALLOWED = "START_ALLOWED"
DECISION_REFUSED = "START_REFUSED"

AUTHORIZATION_FRAGMENT_KIND = "authorization"
AUTHORIZATION_FRAGMENT_OWNER = "start"

# Fields of the authorization that carry METHOD. Everything else is content.
FINGERPRINT_FIELDS = (
    "schema_version",
    "authorization_policy_version",
    "run_id",
    "frozen_contract_sha256",
    "rebuilt_contract_sha256",
    "readiness_runtime_condition_sha256",
    "fresh_t0_runtime_condition_sha256",
    "decision",
    "required_runtime_domains",
)
VOLATILE_FIELDS = (
    "authorized_at_utc", "checked_at_utc", "probe_duration_seconds", "hostname",
    "pid", "thread_id", "container_runtime", "temp_id", "diagnostics",
)
AUTHORIZATION_VOLATILE_FIELDS_EXCLUDED_FROM_FINGERPRINT = True

# What each chokepoint revalidates before the request. A NEW cost-causing
# submission re-probes the runtime; a direct request (inside an already
# authorized run) revalidates contract identity and the stored authorization;
# a pure status poll validates the authorization only.
CALL_KIND_DIRECT = "direct"
CALL_KIND_BATCH_SUBMIT = "batch_submit"
CALL_KIND_BATCH_POLL = "batch_poll"
REVALIDATION_POLICY = OrderedDict([
    (CALL_KIND_DIRECT, ("authorization_readback", "contract_rebuild")),
    (CALL_KIND_BATCH_SUBMIT, ("authorization_readback", "contract_rebuild", "fresh_runtime")),
    (CALL_KIND_BATCH_POLL, ("authorization_readback",)),
])
COST_CAUSING_KINDS = (CALL_KIND_DIRECT, CALL_KIND_BATCH_SUBMIT)

# T0 needs every runtime domain the pilot's measurement stages will use, so
# the start is deliberately coupled to docker and all three images.
REQUIRED_RUNTIME_DOMAINS = ("main", "parcoach", "llov")
T0_REQUIRES_DOCKER_AND_ALL_THREE_IMAGES = True


class PreRunInfrastructureFailure(RuntimeError):
    """Never a model failure, an API error or a generation failure."""

    failure_class = "PRE_RUN_INFRASTRUCTURE_FAILURE"


class StartRefused(PreRunInfrastructureFailure):
    """The run may not start (contract, runtime or authorization drift)."""


class ProviderCallRefused(PreRunInfrastructureFailure):
    """A provider call was attempted without a valid authorization."""


class RuntimeUnresolved(StartRefused):
    """The runtime could not be measured (docker down, image missing, probe
    error) - PRE_RUN_RUNTIME_UNRESOLVED, not a provider failure."""


# ---------------------------------------------------------------------------
# process context (installed ONLY by authorize_start)
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()
_CONTEXT = None  # type: Optional[Dict[str, Any]]


def current_context() -> "Optional[Dict[str, Any]]":
    with _LOCK:
        return dict(_CONTEXT) if _CONTEXT else None


def clear_context() -> None:
    global _CONTEXT
    with _LOCK:
        _CONTEXT = None


def _install_context(context: "Dict[str, Any]") -> None:
    global _CONTEXT
    with _LOCK:
        _CONTEXT = dict(context)


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------

def authorization_fingerprint(authorization: "Dict[str, Any]") -> str:
    """Methodical content address: the fields in FINGERPRINT_FIELDS only."""
    from thesis.evaluation.condition_hashing import canonical_sha256

    body = OrderedDict()
    for field in FINGERPRINT_FIELDS:
        body[field] = authorization.get(field)
    return canonical_sha256(body)


def volatile_fields_present(authorization: "Dict[str, Any]") -> "List[str]":
    return [f for f in VOLATILE_FIELDS if f in authorization]


# ---------------------------------------------------------------------------
# fresh runtime probe (reuses the readiness definition - no second identity)
# ---------------------------------------------------------------------------

def measure_fresh_runtime(config: "Dict[str, Any]",
                          prober: "Optional[Any]" = None) -> "OrderedDict[str, Any]":
    """Probe main/parcoach/llov NOW and content-address the result with the
    SAME definition the readiness gate used (static_provenance.runtime_condition).

    `prober` is an injection point for tests (a callable returning the
    environments mapping); production passes None and measures for real.
    """
    from thesis.evaluation import static_provenance
    from thesis.evaluation.check_static_repair_readiness import measure_runtime

    started = time.perf_counter()
    if prober is None:
        environments = measure_runtime(config)
    else:
        environments = prober(config)
    static_sha = static_provenance.static_analysis_condition_sha256(
        static_provenance.static_analysis_condition(config, "g++", None,
                                                    include_identities=False))
    repair_sha = static_provenance.repair_condition_sha256(
        static_provenance.repair_condition(config))
    condition = static_provenance.runtime_condition(environments, static_sha, repair_sha)
    sha = static_provenance.runtime_condition_sha256(condition)

    problems = []
    for domain in REQUIRED_RUNTIME_DOMAINS:
        environment = (environments or {}).get(domain)
        if not environment:
            problems.append("%s: runtime domain not probed" % domain)
            continue
        if environment.get("probe_error"):
            problems.append("%s: probe error: %s" % (domain, environment["probe_error"]))
        if not static_provenance.environment_is_pinned(environment):
            problems.append("%s: no immutable image identity (a tag is not an identity)"
                            % domain)
        if not (environment.get("tool_identities") or {}):
            problems.append("%s: no tool identities measured" % domain)
    return OrderedDict([
        ("environments", environments),
        ("condition", condition),
        ("sha256", sha),
        ("static_analysis_condition_sha256", static_sha),
        ("repair_condition_sha256", repair_sha),
        ("problems", problems),
        ("probe_duration_seconds", round(time.perf_counter() - started, 3)),
    ])


READINESS_ARTIFACT = REPO_ROOT / "thesis" / "evaluation" / "static_repair_readiness.json"


def readiness_runtime_sha(config: "Optional[Dict[str, Any]]" = None) -> "Optional[str]":
    """The runtime condition the readiness proof was measured under.

    `outputs.readiness_artifact` lets a fixture point at its own readiness
    proof; production has no such key and reads the repository artifact."""
    from thesis.analysis_overview.report_contracts import load_json

    path = ((config or {}).get("outputs") or {}).get("readiness_artifact")
    readiness = load_json(Path(path) if path else READINESS_ARTIFACT)
    return (readiness or {}).get("runtime_condition_sha256")


# ---------------------------------------------------------------------------
# T0
# ---------------------------------------------------------------------------

def authorize_start(config: "Dict[str, Any]", config_path: "Any", profile: str,
                    run_id: str, contract_path: "Any", *,
                    prober: "Optional[Any]" = None,
                    allow_draft_contract: bool = False,
                    stage: str = "t0_authorization") -> "OrderedDict[str, Any]":
    """The full T0 sequence. Returns the authorization on success; raises a
    PreRunInfrastructureFailure (StartRefused / RuntimeUnresolved) otherwise.
    Installs the process context so the chokepoints can validate it.

    `prober` and `allow_draft_contract` are FIXTURE injections: they are
    keyword-only, default to the productive behaviour (real docker probe, a
    READY contract required) and are not exposed by any CLI."""
    from thesis.evaluation import manifest_fragments as mf
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.evaluation import run_manifest
    from thesis.generation.common import utc_now_iso

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])

    # 1./2. frozen contract + integrity
    frozen = prc.load_frozen(Path(contract_path))
    frozen_sha = frozen["contract_sha256"]
    if frozen.get("run_id") != run_id:
        raise StartRefused("the frozen contract is for run %r, not %r"
                           % (frozen.get("run_id"), run_id))

    # 3./4. rebuild live and compare
    rebuilt = prc.build_contract(config_path, profile, run_id)
    rebuilt_sha = prc.contract_sha256(rebuilt)
    drift = prc.contract_diff(frozen, rebuilt)
    if rebuilt_sha != frozen_sha or drift:
        raise StartRefused(
            "contract drift before the first request: frozen %s... vs rebuilt %s... (%s)"
            % (frozen_sha[:12], rebuilt_sha[:12], ", ".join(drift) or "sha mismatch"))
    if rebuilt.get("status") != prc.STATUS_READY and not allow_draft_contract:
        raise StartRefused("the contract is %s: %s" % (rebuilt.get("status"),
                                                       "; ".join(rebuilt.get("blockers") or [])))

    # 5. fresh runtime probe
    fresh = measure_fresh_runtime(config, prober=prober)
    if fresh["problems"]:
        raise RuntimeUnresolved("PRE_RUN_RUNTIME_UNRESOLVED: %s" % "; ".join(fresh["problems"]))

    # 6. compare with the readiness artifact AND the contract
    readiness_sha = readiness_runtime_sha(config)
    contracted_sha = (frozen.get("conditions") or {}).get("static_repair_runtime_condition_sha256")
    if readiness_sha is None:
        raise RuntimeUnresolved("PRE_RUN_RUNTIME_UNRESOLVED: no readiness runtime condition "
                                "recorded - re-run check_static_repair_readiness.py")
    if fresh["sha256"] != readiness_sha:
        raise StartRefused(
            "runtime drift since the readiness proof: readiness %s... vs fresh %s... - the "
            "stale readiness value must not mask an image/plugin change"
            % (readiness_sha[:12], fresh["sha256"][:12]))
    if contracted_sha is not None and contracted_sha != fresh["sha256"]:
        raise StartRefused("the contract pins runtime %s... but the fresh probe measures %s..."
                           % (str(contracted_sha)[:12], fresh["sha256"][:12]))

    # 7. bind the contract
    run_manifest.ensure_run_manifest(config, run_id, stage=stage, profile=profile,
                                     primary_compiler=frozen.get("primary_compiler") or "g++")
    run_manifest.register_contract(config, run_id, frozen_sha, frozen)

    # 8. bind the T0 runtime evidence
    evidence = t0_runtime_evidence(run_id, frozen_sha, readiness_sha, fresh)
    run_manifest.register_runtime_evidence(config, run_id, evidence,
                                           fingerprint=t0_evidence_fingerprint(evidence))

    # 9. validate the merged state BEFORE authorizing
    merged = run_manifest.load_manifest(config, run_id) or {}
    if merged.get("contract_sha256") != frozen_sha:
        raise StartRefused("the contract is not bound to the run (manifest records %r)"
                           % merged.get("contract_sha256"))
    stored_evidence = merged.get("runtime_evidence") or {}
    if stored_evidence.get("fresh_runtime_condition_sha256") != fresh["sha256"]:
        raise StartRefused("the T0 runtime evidence is not bound to the run")

    # 10. register the authorization atomically
    authorization = OrderedDict([
        ("schema_version", AUTHORIZATION_SCHEMA_VERSION),
        ("authorization_policy_version", AUTHORIZATION_POLICY_VERSION),
        ("run_id", run_id),
        ("frozen_contract_sha256", frozen_sha),
        ("rebuilt_contract_sha256", rebuilt_sha),
        ("readiness_runtime_condition_sha256", readiness_sha),
        ("fresh_t0_runtime_condition_sha256", fresh["sha256"]),
        ("decision", DECISION_ALLOWED),
        ("required_runtime_domains", list(REQUIRED_RUNTIME_DOMAINS)),
        # volatile content (never part of the fingerprint)
        ("authorized_at_utc", utc_now_iso()),
        ("hostname", platform.node()),
        ("pid", os.getpid()),
        ("thread_id", threading.get_ident()),
        ("probe_duration_seconds", fresh["probe_duration_seconds"]),
    ])
    fingerprint = authorization_fingerprint(authorization)
    authorization["authorization_sha256"] = fingerprint
    try:
        mf.register_fragment(intermediate_dir, run_id, AUTHORIZATION_FRAGMENT_KIND,
                             AUTHORIZATION_FRAGMENT_OWNER, authorization,
                             fingerprint=fingerprint, writer=stage)
    except mf.FragmentConflict as conflict:
        # another starter authorized this run under a DIFFERENT methodical
        # state: this process' state drifted - refuse, never write a second
        # contradicting authorization
        raise StartRefused("a different start authorization already exists for run %s: %s"
                           % (run_id, conflict))
    mf.write_snapshot(intermediate_dir, run_id)

    # 11. read back from the run provenance and validate
    stored = load_authorization(config, run_id)
    if stored is None:
        raise StartRefused("the authorization could not be read back from the run provenance")
    if stored.get("authorization_sha256") != fingerprint:
        raise StartRefused("authorization read-back mismatch: stored %s... vs computed %s..."
                           % (str(stored.get("authorization_sha256"))[:12], fingerprint[:12]))
    if authorization_fingerprint(stored) != fingerprint:
        raise StartRefused("the stored authorization does not match its own fingerprint")

    _install_context(OrderedDict([
        ("config", config),
        ("config_path", str(config_path)),
        ("profile", profile),
        ("run_id", run_id),
        ("contract_path", str(contract_path)),
        ("authorization_sha256", fingerprint),
        ("frozen_contract_sha256", frozen_sha),
        ("fresh_t0_runtime_condition_sha256", fresh["sha256"]),
        ("prober", prober),
    ]))
    return stored


# Volatile evidence fields: recorded, never fingerprinted - otherwise two
# concurrent first starters (or a legitimate re-authorization) would compute
# different evidence identities for the SAME measured runtime.
T0_EVIDENCE_VOLATILE_FIELDS = ("checked_at_utc", "probe_duration_seconds")


def t0_evidence_fingerprint(evidence: "Dict[str, Any]") -> str:
    from thesis.evaluation.condition_hashing import canonical_sha256

    body = OrderedDict((key, value) for key, value in sorted(evidence.items())
                       if key not in T0_EVIDENCE_VOLATILE_FIELDS)
    return canonical_sha256(body)


def t0_runtime_evidence(run_id: str, contract_sha: str, readiness_sha: str,
                        fresh: "Dict[str, Any]") -> "OrderedDict[str, Any]":
    from thesis.generation.common import utc_now_iso

    environments = fresh["environments"] or {}
    domains = OrderedDict()
    for name in sorted(environments):
        environment = environments[name] or {}
        domains[name] = OrderedDict([
            ("image_ref", environment.get("image_ref")),
            ("image_id", environment.get("image_id")),
            ("repo_digests", environment.get("repo_digests")),
            ("rootfs_layers_sha256", environment.get("rootfs_layers_sha256")),
            ("tool_identities", environment.get("tool_identities")),
            ("evidence", environment.get("evidence")),
            ("probe_error", environment.get("probe_error")),
        ])
    return OrderedDict([
        ("evidence_version", T0_RUNTIME_EVIDENCE_VERSION),
        ("run_id", run_id),
        ("contract_sha256", contract_sha),
        ("readiness_runtime_condition_sha256", readiness_sha),
        ("fresh_runtime_condition_sha256", fresh["sha256"]),
        ("runtime_condition", fresh["condition"]),
        ("static_analysis_condition_sha256", fresh["static_analysis_condition_sha256"]),
        ("repair_condition_sha256", fresh["repair_condition_sha256"]),
        ("domains", domains),
        ("probe_status", "OK"),
        ("required_runtime_domains", list(REQUIRED_RUNTIME_DOMAINS)),
        ("t0_requires_docker_and_all_three_images", T0_REQUIRES_DOCKER_AND_ALL_THREE_IMAGES),
        ("checked_at_utc", utc_now_iso()),
        ("probe_duration_seconds", fresh["probe_duration_seconds"]),
    ])


def load_authorization(config: "Dict[str, Any]", run_id: str) -> "Optional[Dict[str, Any]]":
    from thesis.evaluation import manifest_fragments as mf

    path = mf.fragment_path(Path(config["outputs"]["intermediate_dir"]), run_id,
                            AUTHORIZATION_FRAGMENT_KIND, AUTHORIZATION_FRAGMENT_OWNER)
    if not path.is_file():
        return None
    import json

    try:
        fragment = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return fragment.get("content")


# ---------------------------------------------------------------------------
# the guard used by the chokepoints
# ---------------------------------------------------------------------------

def require_provider_call(kind: str, *, label: "Optional[str]" = None) -> "Dict[str, Any]":
    """Called by a chokepoint BEFORE the provider request happens.

    Refuses unless a valid authorization exists for this process' run and
    still matches the live state under the policy for `kind`."""
    if kind not in REVALIDATION_POLICY:
        raise ProviderCallRefused("unknown provider call kind %r" % kind)
    context = current_context()
    if context is None:
        raise ProviderCallRefused(
            "PRE_RUN_INFRASTRUCTURE_FAILURE: no run authorization is installed in this "
            "process - a cost-causing provider call (%s%s) was attempted without passing "
            "the T0 start guard (thesis/evaluation/run_authorization.authorize_start). "
            "This is not a model or API failure."
            % (kind, ": %s" % label if label else ""))

    config = context["config"]
    run_id = context["run_id"]
    steps = REVALIDATION_POLICY[kind]

    # (a) authorization read-back from the run provenance
    stored = load_authorization(config, run_id)
    if stored is None:
        raise ProviderCallRefused("the run authorization for %s disappeared from the run "
                                  "provenance" % run_id)
    if stored.get("decision") != DECISION_ALLOWED:
        raise ProviderCallRefused("the run authorization for %s is %r"
                                  % (run_id, stored.get("decision")))
    if authorization_fingerprint(stored) != context["authorization_sha256"]:
        raise ProviderCallRefused(
            "the stored run authorization no longer matches the authorized state "
            "(stored %s... vs authorized %s...)"
            % (authorization_fingerprint(stored)[:12], context["authorization_sha256"][:12]))

    # (b) contract still identical
    if "contract_rebuild" in steps:
        from thesis.evaluation import pilot_run_contract as prc

        rebuilt = prc.build_contract(context["config_path"], context["profile"], run_id)
        rebuilt_sha = prc.contract_sha256(rebuilt)
        if rebuilt_sha != stored["frozen_contract_sha256"]:
            raise ProviderCallRefused(
                "NEW_SUBMISSION_REFUSED: the contract changed since the authorization "
                "(authorized %s... vs current %s...)"
                % (stored["frozen_contract_sha256"][:12], rebuilt_sha[:12]))

    # (c) a NEW cost-causing submission re-probes the runtime
    if "fresh_runtime" in steps:
        fresh = measure_fresh_runtime(config, prober=context.get("prober"))
        if fresh["problems"]:
            raise RuntimeUnresolved("PRE_RUN_RUNTIME_UNRESOLVED before a new submission: %s"
                                    % "; ".join(fresh["problems"]))
        if fresh["sha256"] != stored["fresh_t0_runtime_condition_sha256"]:
            raise ProviderCallRefused(
                "NEW_SUBMISSION_REFUSED: runtime drift since T0 (authorized %s... vs fresh "
                "%s...)" % (stored["fresh_t0_runtime_condition_sha256"][:12],
                            fresh["sha256"][:12]))
    return stored


def authorization_state(config: "Dict[str, Any]", run_id: str) -> "OrderedDict[str, Any]":
    """Read-only view for the preflight and the post-run verifier."""
    stored = load_authorization(config, run_id)
    if stored is None:
        return OrderedDict([("present", False), ("decision", None),
                            ("authorization_sha256", None)])
    return OrderedDict([
        ("present", True),
        ("decision", stored.get("decision")),
        ("authorization_sha256", stored.get("authorization_sha256")),
        ("recomputed_sha256", authorization_fingerprint(stored)),
        ("frozen_contract_sha256", stored.get("frozen_contract_sha256")),
        ("fresh_t0_runtime_condition_sha256", stored.get("fresh_t0_runtime_condition_sha256")),
        ("readiness_runtime_condition_sha256", stored.get("readiness_runtime_condition_sha256")),
        ("schema_version", stored.get("schema_version")),
        ("policy_version", stored.get("authorization_policy_version")),
    ])
