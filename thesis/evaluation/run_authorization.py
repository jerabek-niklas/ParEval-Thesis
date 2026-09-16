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


# A provider child process signals a pre-run infrastructure failure with its
# OWN exit code, so the generation orchestrator can tell it apart from a
# provider/model failure and stop the whole contracted run instead of
# continuing with a silently incomplete population.
EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE = 3


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

RUN_ID_NOT_FRESH = "RUN_ID_NOT_FRESH"
CONTRACTED_MODEL_SET_NARROWED = "CONTRACTED_MODEL_SET_NARROWED"


def authorize_start(config: "Dict[str, Any]", config_path: "Any", profile: str,
                    run_id: str, contract_path: "Any", *,
                    prober: "Optional[Any]" = None,
                    allow_draft_contract: bool = False,
                    allow_prepopulated_run: bool = False,
                    requested_model_scope: "Optional[Any]" = None,
                    stage: str = "t0_authorization") -> "OrderedDict[str, Any]":
    """The full T0 sequence. Returns the authorization on success; raises a
    PreRunInfrastructureFailure (StartRefused / RuntimeUnresolved) otherwise.
    Installs the process context so the chokepoints can validate it.

    `prober`, `allow_draft_contract` and `allow_prepopulated_run` are FIXTURE
    injections: they are keyword-only, default to the productive behaviour
    (real docker probe, a READY contract required, a FRESH run required) and
    are not exposed by any CLI."""
    from thesis.evaluation import manifest_fragments as mf
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.evaluation import run_freshness
    from thesis.evaluation import run_manifest
    from thesis.generation.common import utc_now_iso

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])

    # 1./2. frozen contract + integrity
    frozen = prc.load_frozen(Path(contract_path))
    frozen_sha = frozen["contract_sha256"]
    if frozen.get("run_id") != run_id:
        raise StartRefused("the frozen contract is for run %r, not %r"
                           % (frozen.get("run_id"), run_id))

    # 2a. a FIRST START launches the FULL contracted model population: a
    # caller that authorizes for a strict subset (a single provider child
    # started by hand, --model-id / --provider narrowing) is refused; a
    # later per-model resume REHYDRATES the authorization instead
    if requested_model_scope is not None:
        requested = sorted(str(m) for m in requested_model_scope)
        contracted = sorted(str(m) for m in (frozen.get("model_ids") or []))
        if requested != contracted:
            raise StartRefused(
                "%s: run %s is contracted for %d model(s) but this first start requests %d (%s); "
                "missing: %s - the first start launches the full contracted population (planned "
                "methodical overrides: NONE)"
                % (CONTRACTED_MODEL_SET_NARROWED, run_id, len(contracted), len(requested),
                   ", ".join(requested) or "none",
                   ", ".join(sorted(set(contracted) - set(requested))) or "none"))

    # 2b. a FIRST START needs a FRESH run (NO_PILOT001_MEASUREMENT_REUSE):
    # a run directory that already carries generations, batch bookkeeping,
    # assembly, stage records, repair state, manifest fragments or iteration
    # runs would let copied historical records become this run's own inputs
    # (the generation resume skips by sample_id, the stages merge by
    # sample_id). Only the frozen contract itself may exist before T0.
    if not allow_prepopulated_run:
        freshness = run_freshness.inspect_run_freshness(config, run_id)
        if freshness["status"] != run_freshness.FRESH:
            raise StartRefused(
                "%s: run %s already carries result-bearing state before its first start "
                "(%s) - a contracted run never adopts existing records as its own inputs; "
                "use a fresh run id or remove nothing (historical records are read-only): %s"
                % (RUN_ID_NOT_FRESH, run_id, freshness["status"],
                   "; ".join(freshness["result_bearing_paths"] + freshness["problems"])[:2000]))

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

    # 7./8. bind the contract and the T0 runtime evidence. A conflict here is
    # a PRE_RUN_INFRASTRUCTURE_FAILURE like any other - it must never escape
    # unclassified, or the orchestrator would read it as a model failure.
    try:
        run_manifest.ensure_run_manifest(
            config, run_id, stage=stage, profile=profile,
            primary_compiler=frozen.get("primary_compiler") or "g++")
        run_manifest.register_contract(config, run_id, frozen_sha, frozen)

        evidence = t0_runtime_evidence(run_id, frozen_sha, readiness_sha, fresh, config)
        run_manifest.register_runtime_evidence(
            config, run_id, evidence, fingerprint=t0_evidence_fingerprint(evidence))
    except PreRunInfrastructureFailure:
        raise
    except Exception as error:  # noqa: BLE001 - classified, never a model failure
        raise StartRefused(
            "the contract/T0 runtime evidence could not be bound to run %s: %s: %s"
            % (run_id, type(error).__name__, error))

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
    except PreRunInfrastructureFailure:
        raise
    except Exception as error:  # noqa: BLE001 - an IO/lock failure is still
        # a pre-run infrastructure failure, never a model failure
        raise StartRefused("the start authorization for run %s could not be written: "
                           "%s: %s" % (run_id, type(error).__name__, error))
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


def provider_endpoint_identities(config: "Dict[str, Any]") -> "OrderedDict[str, Any]":
    """Per enabled model: a sha256 of the RESOLVED provider endpoint (the
    literal base_url or the value of base_url_env) - the endpoint identity
    without its value. Models whose SDK fixes the endpoint (no base_url /
    base_url_env) record None; an unset env var records UNSET."""
    import hashlib
    import os

    identities = OrderedDict()
    for model in sorted((config.get("models") or []), key=lambda m: str(m.get("id"))):
        if not isinstance(model, dict) or not model.get("enabled", False):
            continue
        url = model.get("base_url")
        env = model.get("base_url_env")
        if not url and env:
            url = os.environ.get(str(env))
            if not url:
                identities[str(model.get("id"))] = "UNSET:%s" % env
                continue
        identities[str(model.get("id"))] = (hashlib.sha256(str(url).encode("utf-8")).hexdigest()
                                            if url else None)
    return identities


def t0_runtime_evidence(run_id: str, contract_sha: str, readiness_sha: str,
                        fresh: "Dict[str, Any]",
                        config: "Optional[Dict[str, Any]]" = None) -> "OrderedDict[str, Any]":
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
        # the provider endpoints the run was authorized for (hashes of the
        # resolved URLs; rehydration and the batch-submit chokepoint refuse a
        # process whose environment resolves another endpoint)
        ("provider_endpoint_identities", provider_endpoint_identities(config) if config is not None
         else None),
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
    try:
        return _require_provider_call(kind, label=label)
    except PreRunInfrastructureFailure:
        raise
    except Exception as error:  # noqa: BLE001
        # The guard's OWN revalidation failing (a contract rebuild raising, an
        # unreadable fragment, a probe crashing) is a pre-run infrastructure
        # failure, never a provider/model failure - otherwise the runner would
        # write it into the population as a generation error record.
        raise ProviderCallRefused(
            "PRE_RUN_INFRASTRUCTURE_FAILURE: the run-authorization revalidation for a "
            "%s provider call%s failed and the request is therefore refused: %s: %s"
            % (kind, ": %s" % label if label else "", type(error).__name__, error))


def _require_provider_call(kind: str, *, label: "Optional[str]" = None) -> "Dict[str, Any]":
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


# ---------------------------------------------------------------------------
# cross-process bootstrap: persistent run provenance is authoritative
# ---------------------------------------------------------------------------
#
# `_CONTEXT` is process-local, but the productive generation orchestrator
# starts every provider runner as a NEW process (generate.py -> subprocess ->
# generate-<provider>.py -> common.run_generation -> adapter.generate ->
# call_with_retries -> require_provider_call). Python RAM does not cross that
# boundary, so a child of an authorized parent used to be refused at its first
# request although a valid authorization was persisted.
#
#     PERSISTENT RUN PROVENANCE IS AUTHORITATIVE;
#     THE PROCESS CONTEXT IS ONLY A VALIDATED CACHE.
#
# The fix is NOT a weaker chokepoint - `require_provider_call` still refuses
# whenever no valid context is installed, and it never reads a file with
# implicit defaults on failure. The fix is that a productive process installs
# a context that was VALIDATED against the persisted provenance:
#
#     pure poll            -> hydrate + validate the existing authorization
#     authorization exists -> hydrate + validate (never a second authorization)
#     no authorization     -> full first-start authorize_start(...)
#
# Rehydration checks the same methodical identities the chokepoint needs; on
# tamper or drift it REFUSES instead of installing a context.

REHYDRATION_POLICY_VERSION = "authorization_rehydration.v1"

MODE_FIRST_START = "FIRST_START"
MODE_REHYDRATED = "REHYDRATED_FROM_RUN_PROVENANCE"
MODE_PROCESS_CACHE = "PROCESS_CONTEXT_CACHE"
# a run with no frozen contract anywhere is not a contracted pilot run (smoke
# run, unit fixture, the historical pilot_001). The bootstrap installs NO
# context for it, so the unchanged chokepoint still refuses every provider
# request - legacy behaviour is classified, never silently authorized.
MODE_UNCONTRACTED = "UNCONTRACTED_RUN_NO_AUTHORIZATION_INSTALLED"

# A batch job whose bookkeeping predates the authorization policy carries no
# authorization at all. For a contracted pilot run that is fail-closed, never
# a silently invented authorization.
LEGACY_UNAUTHORIZED_BATCH_PROVENANCE = "LEGACY_UNAUTHORIZED_BATCH_PROVENANCE"

# The canonical per-run frozen contract. Deterministic from config + run id,
# so a child process finds the SAME contract as its parent without a hidden
# global, an inherited Python context or a hand-set test hook.
CANONICAL_CONTRACT_NAME = "run_contract.json"
CONTRACT_DISCOVERY_ORDER = ("explicit_contract_path", "canonical_run_location",
                            "bound_run_provenance")

# What rehydration verifies before it installs a context.
REHYDRATION_CHECKS = (
    "authorization_fragment_present", "run_provenance_integrity",
    "decision_is_start_allowed", "run_id_exact", "authorization_fingerprint_exact",
    "contract_bound_to_run_exact", "t0_runtime_evidence_present",
    "t0_evidence_belongs_to_same_contract", "authorization_runtime_sha_equals_t0",
    "frozen_contract_file_unchanged", "live_contract_rebuild_without_drift",
)


def canonical_contract_path(config: "Dict[str, Any]", run_id: str) -> Path:
    """<intermediate_dir>/<run_id>/run_contract.json"""
    return Path(config["outputs"]["intermediate_dir"]) / run_id / CANONICAL_CONTRACT_NAME


def discover_frozen_contract(config: "Dict[str, Any]", run_id: str,
                             contract_path: "Optional[Any]" = None
                             ) -> "OrderedDict[str, Any]":
    """Deterministic frozen-contract discovery for a fresh process.

    In CONTRACT_DISCOVERY_ORDER: an explicitly passed path, the canonical
    per-run location, and - for an already authorized run - the contract that
    is bound in the run provenance itself. No hidden global, no parent
    context, no implicit default."""
    from thesis.evaluation import run_manifest

    candidates = OrderedDict()
    if contract_path is not None:
        candidates["explicit_contract_path"] = Path(contract_path)
    candidates["canonical_run_location"] = canonical_contract_path(config, run_id)
    for source, path in candidates.items():
        if path.is_file():
            return OrderedDict([("source", source), ("path", path), ("contract", None)])
    manifest = run_manifest.load_manifest(config, run_id) or {}
    bound = manifest.get("contract")
    if bound:
        return OrderedDict([("source", "bound_run_provenance"), ("path", None),
                            ("contract", bound)])
    return OrderedDict([("source", None), ("path", None), ("contract", None),
                        ("searched", [str(p) for p in candidates.values()])])


def load_and_validate_run_authorization(config: "Dict[str, Any]", run_id: str, *,
                                        config_path: "Any", profile: str,
                                        contract_path: "Optional[Any]" = None
                                        ) -> "OrderedDict[str, Any]":
    """Load the PERSISTED run authorization and validate it against the same
    methodical identities the provider chokepoint needs.

    Never "the file exists -> install a context": every check in
    REHYDRATION_CHECKS must hold. Raises StartRefused otherwise.

    EVERY failure here is classified. The run provenance layer can raise
    outside this module's hierarchy - a torn fragment makes json.loads raise
    inside the integrity check, a sibling fragment with a foreign run id makes
    merge_fragments raise FragmentConflict - and an unclassified exception
    would leave the runner with a traceback and exit code 1, which the
    generation orchestrator reads as an ordinary model failure and skips under
    --continue-on-error. That is exactly the hole this wave closes."""
    try:
        return _load_and_validate_run_authorization(
            config, run_id, config_path=config_path, profile=profile,
            contract_path=contract_path)
    except PreRunInfrastructureFailure:
        raise
    except Exception as error:  # noqa: BLE001
        raise StartRefused(
            "the run provenance of %s could not be validated (%s: %s) - a provider "
            "request is refused until it can be" % (run_id, type(error).__name__, error))


def _load_and_validate_run_authorization(config: "Dict[str, Any]", run_id: str, *,
                                         config_path: "Any", profile: str,
                                         contract_path: "Optional[Any]" = None
                                         ) -> "OrderedDict[str, Any]":
    from thesis.evaluation import manifest_fragments as mf
    from thesis.evaluation import pilot_run_contract as prc
    from thesis.evaluation import run_manifest

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])

    stored = load_authorization(config, run_id)
    if stored is None:
        raise StartRefused(
            "%s: no run authorization is persisted for run %s - a cost-causing provider "
            "call in a fresh process cannot be authorized retrospectively"
            % (LEGACY_UNAUTHORIZED_BATCH_PROVENANCE, run_id))

    # fail-closed: ANY fragment whose content no longer matches its registered
    # fingerprint invalidates the run provenance this rehydration is about to
    # trust - not only the ones whose name happens to start with a known kind
    tampered = mf.verify_fragment_integrity(intermediate_dir, run_id)
    if tampered:
        raise StartRefused("the run provenance of %s was tampered with: %s"
                           % (run_id, "; ".join("%s (%s)" % (p.get("fragment"), p.get("problem"))
                                                for p in tampered)))
    if stored.get("decision") != DECISION_ALLOWED:
        raise StartRefused("the persisted run authorization for %s is %r"
                           % (run_id, stored.get("decision")))
    if stored.get("run_id") != run_id:
        raise StartRefused("the persisted authorization belongs to run %r, not %r"
                           % (stored.get("run_id"), run_id))
    recomputed = authorization_fingerprint(stored)
    if recomputed != stored.get("authorization_sha256"):
        raise StartRefused(
            "the persisted authorization does not match its own methodical fingerprint "
            "(stored %s... vs recomputed %s...)"
            % (str(stored.get("authorization_sha256"))[:12], recomputed[:12]))

    manifest = run_manifest.load_manifest(config, run_id) or {}
    frozen_sha = stored.get("frozen_contract_sha256")
    if manifest.get("contract_sha256") != frozen_sha:
        raise StartRefused("the run provenance binds contract %s..., the authorization %s..."
                           % (str(manifest.get("contract_sha256"))[:12], str(frozen_sha)[:12]))

    evidence = manifest.get("runtime_evidence") or {}
    if not evidence:
        raise StartRefused("the authorized run carries no T0 runtime evidence")
    if evidence.get("contract_sha256") != frozen_sha:
        raise StartRefused("the T0 runtime evidence belongs to contract %s..., not %s..."
                           % (str(evidence.get("contract_sha256"))[:12], str(frozen_sha)[:12]))
    if evidence.get("run_id") not in (None, run_id):
        raise StartRefused("the T0 runtime evidence belongs to run %r, not %r"
                           % (evidence.get("run_id"), run_id))
    t0_sha = evidence.get("fresh_runtime_condition_sha256")
    if t0_sha != stored.get("fresh_t0_runtime_condition_sha256"):
        raise StartRefused(
            "the authorization pins T0 runtime %s... but the run's T0 evidence records %s..."
            % (str(stored.get("fresh_t0_runtime_condition_sha256"))[:12], str(t0_sha)[:12]))

    discovery = discover_frozen_contract(config, run_id, contract_path)
    if discovery.get("path") is not None:
        frozen = prc.load_frozen(discovery["path"])
        if frozen.get("contract_sha256") != frozen_sha:
            raise StartRefused(
                "the frozen contract at %s is %s..., the authorization was granted for %s..."
                % (discovery["path"], str(frozen.get("contract_sha256"))[:12],
                   str(frozen_sha)[:12]))
        if frozen.get("run_id") != run_id:
            raise StartRefused("the frozen contract at %s is for run %r, not %r"
                               % (discovery["path"], frozen.get("run_id"), run_id))

    rebuilt = prc.build_contract(config_path, profile, run_id)
    rebuilt_sha = prc.contract_sha256(rebuilt)
    if rebuilt_sha != frozen_sha:
        raise StartRefused(
            "contract drift in a fresh process: the authorization was granted for %s... but "
            "the live state rebuilds to %s... - a provider request under a changed contract "
            "is refused" % (str(frozen_sha)[:12], rebuilt_sha[:12]))
    authorized_endpoints = evidence.get("provider_endpoint_identities")
    if isinstance(authorized_endpoints, dict):
        current_endpoints = provider_endpoint_identities(config)
        drifted = sorted(model for model, identity in authorized_endpoints.items()
                         if current_endpoints.get(model) != identity)
        if drifted:
            raise StartRefused(
                "provider endpoint drift since T0 for %s: this process resolves another endpoint "
                "(base_url / base_url_env value) than the one the run was authorized for"
                % ", ".join(drifted))

    return OrderedDict([
        ("authorization", stored),
        ("contract_discovery", discovery.get("source")),
        ("contract_path", str(discovery["path"]) if discovery.get("path") else None),
        ("rebuilt_contract_sha256", rebuilt_sha),
        ("checks", list(REHYDRATION_CHECKS)),
    ])


def hydrate_authorized_run_context(config: "Dict[str, Any]", run_id: str, *,
                                   config_path: "Any", profile: str,
                                   contract_path: "Optional[Any]" = None,
                                   prober: "Optional[Any]" = None
                                   ) -> "OrderedDict[str, Any]":
    """Validate the persisted authorization and install it as this process'
    context. The context carries validated PERSISTED provenance only: it
    creates no authorization, rewrites no historical one, and the persisted
    fragments stay the source of truth."""
    validated = load_and_validate_run_authorization(
        config, run_id, config_path=config_path, profile=profile,
        contract_path=contract_path)
    stored = validated["authorization"]
    _install_context(OrderedDict([
        ("config", config),
        ("config_path", str(config_path)),
        ("profile", profile),
        ("run_id", run_id),
        ("contract_path", validated["contract_path"]),
        ("authorization_sha256", stored["authorization_sha256"]),
        ("frozen_contract_sha256", stored["frozen_contract_sha256"]),
        ("fresh_t0_runtime_condition_sha256", stored["fresh_t0_runtime_condition_sha256"]),
        ("prober", prober),
        ("hydrated_from_persistent_provenance", True),
        ("rehydration_policy_version", REHYDRATION_POLICY_VERSION),
    ]))
    return validated


def bootstrap_provider_run(config: "Dict[str, Any]", config_path: "Any", profile: str,
                           run_id: str, *, contract_path: "Optional[Any]" = None,
                           pure_poll: bool = False,
                           prior_submission: bool = False,
                           prober: "Optional[Any]" = None,
                           stage: str = "provider_bootstrap",
                           requested_model_scope: "Optional[Any]" = None
                           ) -> "OrderedDict[str, Any]":
    """The central bootstrap every productive provider process runs BEFORE it
    can reach a chokepoint.

        if pure_poll:              hydrate the existing authorization only
        elif authorization exists: hydrate + validate
        else:                      authorize the first start

    A pure poll neither probes the runtime nor creates an authorization.

    EVERY failure is classified as a PreRunInfrastructureFailure - a corrupt
    frozen contract, an unreadable fragment, a lock that cannot be taken - so
    a provider process never ends with a bare traceback that its orchestrator
    would mistake for a model failure."""
    try:
        return _bootstrap_provider_run(
            config, config_path, profile, run_id, contract_path=contract_path,
            pure_poll=pure_poll, prior_submission=prior_submission, prober=prober,
            stage=stage,
            requested_model_scope=requested_model_scope)
    except PreRunInfrastructureFailure:
        raise
    except Exception as error:  # noqa: BLE001
        raise StartRefused(
            "the run bootstrap for %s failed (%s: %s) - no provider request is made"
            % (run_id, type(error).__name__, error))


def _bootstrap_provider_run(config: "Dict[str, Any]", config_path: "Any", profile: str,
                            run_id: str, *, contract_path: "Optional[Any]" = None,
                            pure_poll: bool = False,
                            prior_submission: bool = False,
                            prober: "Optional[Any]" = None,
                            stage: str = "provider_bootstrap",
                            requested_model_scope: "Optional[Any]" = None
                            ) -> "OrderedDict[str, Any]":
    context = current_context()
    if context is not None and context.get("run_id") == run_id:
        # the process cache is only valid after the same validation
        validated = load_and_validate_run_authorization(
            config, run_id, config_path=config_path, profile=profile,
            contract_path=contract_path)
        return OrderedDict([
            ("mode", MODE_PROCESS_CACHE),
            ("run_id", run_id),
            ("authorization_sha256", validated["authorization"]["authorization_sha256"]),
            ("contract_discovery", validated["contract_discovery"]),
            ("fresh_runtime_probed", False),
        ])

    stored = load_authorization(config, run_id)
    if stored is None:
        discovery = discover_frozen_contract(config, run_id, contract_path)
        if discovery.get("path") is not None and (pure_poll or prior_submission):
            # A CONTRACTED run with EVIDENCE of an earlier provider submission
            # (a poll, or existing batch bookkeeping) but no authorization: that
            # submission happened outside the authorization policy. Classify it
            # - never invent an authorization for legacy batch provenance, and
            # never let a poll or a resume retro-authorize one.
            raise StartRefused(
                "%s: run %s carries %s but no persisted start authorization, so this "
                "process must not authorize it retrospectively. A poll or a resume never "
                "creates an authorization - authorize the run "
                "(thesis/evaluation/pilot_run_contract.py t0) and re-submit."
                % (LEGACY_UNAUTHORIZED_BATCH_PROVENANCE, run_id,
                   "a batch poll request" if pure_poll else "batch bookkeeping from an "
                   "earlier submission"))
        if discovery.get("path") is None:
            # No frozen contract anywhere: this is not a contracted pilot run
            # (a smoke run, a unit fixture, the historical pilot_001). The
            # bootstrap does NOT invent an authorization and installs NO
            # context - so every cost-causing provider request still hits the
            # unchanged, fail-closed chokepoint and is refused there. A
            # CONTRACTED run always has its contract at the canonical location
            # and therefore never takes this path.
            return OrderedDict([
                ("mode", MODE_UNCONTRACTED),
                ("run_id", run_id),
                ("authorization_sha256", None),
                ("contract_discovery", None),
                ("fresh_runtime_probed", False),
                ("searched", discovery.get("searched")),
                ("note", "no frozen run contract for run %s (searched: %s). No "
                         "authorization is installed: any provider request will be "
                         "REFUSED by the chokepoint. Freeze the contract first "
                         "(pilot_run_contract.py freeze --out %s)."
                         % (run_id, ", ".join(discovery.get("searched") or []),
                            canonical_contract_path(config, run_id))),
            ])
        authorization = authorize_start(config, config_path, profile, run_id,
                                        discovery["path"], prober=prober, stage=stage,
                                        requested_model_scope=requested_model_scope)
        return OrderedDict([
            ("mode", MODE_FIRST_START),
            ("run_id", run_id),
            ("authorization_sha256", authorization["authorization_sha256"]),
            ("contract_discovery", discovery["source"]),
            ("fresh_runtime_probed", True),
        ])

    validated = hydrate_authorized_run_context(
        config, run_id, config_path=config_path, profile=profile,
        contract_path=contract_path, prober=prober)
    return OrderedDict([
        ("mode", MODE_REHYDRATED),
        ("run_id", run_id),
        ("authorization_sha256", validated["authorization"]["authorization_sha256"]),
        ("contract_discovery", validated["contract_discovery"]),
        # a rehydration never probes: only a NEW cost-causing submission does,
        # and that happens at the chokepoint under REVALIDATION_POLICY
        ("fresh_runtime_probed", False),
        ("pure_poll", bool(pure_poll)),
    ])


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
