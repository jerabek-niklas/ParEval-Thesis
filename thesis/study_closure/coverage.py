"""Section "coverage" of the study closure: the verification EVIDENCE of the
seven runs, the retrospective read-only re-verification of the successors
002/003/004 through their native verifiers, and the explicit coverage maps
of the two runs without a persisted verification report (recovery_001,
recovery_002) under core.RETROSPECTIVE_SCOPE.

Evidence per run:

  pilot_002         persisted post-run verification (post_run_verification.v1 by
                    verify_pilot_run.v1; repair scope of every pilot loop);
  full_ext_001      persisted parent base-evidence report (BASE_ONLY scope, frozen
                    with recovery_001; bound to the recovery_001 lineage and the
                    full_ext_001 contract);
  recovery_003/004  persisted per-model successor reports (successor_model_
                    verification.v1); every obligation they listed as OPEN work
                    must be a phase-2 target of that model now;
  recovery_001/002  NO persisted report: a coverage map over REAL persisted
                    artifacts and the EXACT checks found in them (the census-owned
                    loops, the successors' iteration-1 / adopted checks, the byte
                    snapshots of the successor lineages and the phase-2 custody
                    chain, the phase-2 measurement completeness of every candidate,
                    the closure's own run bindings);
  phase2            covered by study.py (phase2:reports_present).

Option `reverify`: the native verifiers of 002/003/004 are re-run read-only
(004 with authority=None; 002/003 with the run's native ReadOnlyAuthority,
see NATIVE). The single expected failing check "successor contract and
authorization" ("no authority supplied" / the read-only refusal) is
SUBSTITUTED by the closure's own frozen-contract / authorization facts of the
run (the runs:<run>:frozen_contract and runs:<run>:authorization checks,
recomputed here from the frozen contract and the start authorization fragment
and cross-checked with ctx.cache["run_bindings"]); every other check must
PASS and, for 003/004, reproduce the persisted report (check names, statuses,
variants, counts). deep=True for the first model of a run; once a deep model
exceeded DEEP_SECONDS_LIMIT the remaining models run deep=False, which omits
exactly the two model-independent DEEP_ONLY_CHECKS (covered by the deep
model; recorded per model). Without the option the re-verification is a
data-only note (reverified: false) and never a PASS.

Determinism: check details carry repo-relative paths and raw sha256s only;
example lists are truncated to EXAMPLES, while the EXACT check names an
evidence entry relies on are kept complete (they are the evidence). The
durations of the re-verification live only in the cache records. The
section data (not the check details) carries COMPLETE inventories where the
items are evidence rather than examples: the per-report fact lists (path +
raw sha256) of the evidence entries and of runs_evidence, and the adopted /
continued / fresh loop ids of adopted_vs_new.

Evidence floor of a re-verification: besides the single expected authority
failure, every result must carry per variant exactly one PASS trajectory
verdict ("<variant>: continued|adopted|fresh"), the model-independent
provenance / T0 / invocation / endpoint checks, one immutability check and
a non-errored open_work block (the native verifiers swallow exceptions of
their open-work enumeration into {"error": ...}); for a run without a
persisted report the check names of every later model must equal those of
the run's deep model (minus DEEP_ONLY_CHECKS for shallow models).

Inputs produced by other sections (ctx.cache["run_bindings"] by runs,
ctx.cache["census"] by study) are never recomputed here: their absence is a
FAIL "input unavailable" (spec section 2).

Never claims a historical PASS that is not persisted: the in-process PASS of
the 002 verification exists only in a volatile container log and is recorded
as such. Read-only; no provider request (provider isolation is asserted before
and after every native verifier run). Python 3.8 compatible.
"""
from __future__ import annotations

import importlib
import time
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.evaluation.recovery_lineage import checked_path, fingerprint as lineage_fingerprint
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import verify as pv
from thesis.study_closure import core

SECTION = "coverage"
EXAMPLES = 10
PASS = core.PASS
FAIL = core.FAIL
# identities the persisted reports carry (definitions of the native verifiers,
# not measurements; the successor identity is cross-checked with the native
# modules at run time)
PILOT_SCHEMA = "post_run_verification.v1"
PILOT_VERIFIER = "verify_pilot_run.v1"
PARENT_SCHEMA = "parent_base_evidence_report.v1"
PARENT_SCOPE = "BASE_ONLY_NOT_FULL_RUN_ACCEPTANCE"
SUCCESSOR_SCHEMA = "successor_model_verification.v1"
SUCCESSOR_SCOPE = "SUCCESSOR_MODEL_REPAIR_SCOPE_NOT_FULL_RECOVERY_ACCEPTANCE"
SUCCESSOR_REPORT_SUFFIX = ".successor_verification.json"
PHASE2_REPORT_SUFFIX = ".phase2_verification.json"
VARIANT_DONE = "done"
PARENT_OPEN_WORK_KEY = "%s (iteration-0 candidates)" % core.PARENT
# the read-only re-verification: the one check no authority can satisfy
AUTHORITY_CHECK = "successor contract and authorization"
NO_AUTHORITY_DETAIL = "no authority supplied"
NULL_AUTHORITY_DETAIL = "RecoveryRefused: read-only mode cannot step a loop"
RETROSPECTIVE_PASS = "PASS_WITH_SUBSTITUTED_AUTHORITY_CHECK"
# checks the native verifiers add only with deep=True (model-independent facts)
DEEP_ONLY_CHECKS = ("protected pilot/full_ext history unchanged",
                    "1,980-cell methodical population unchanged")
DEEP_SECONDS_LIMIT = 300.0
# evidence floor of one read-only re-verification (names every native
# verifier emits unconditionally; only the immutability check is named
# differently by 004): per variant exactly one trajectory verdict
VARIANT_VERDICTS = ("continued", "adopted", "fresh")
FLOOR_CHECKS = ("successor run provenance intact", "stage runtime stamps match the successor T0",
                "successor invocations registered for the model", "provider endpoint binding")
IMMUTABILITY_CHECK_SUFFIX = "bytes, membership and bindings unchanged"
ENDPOINT_CHECK_PREFIX = "provider endpoint equals "
REVERIFIED_RUNS = core.OWNERS[1:]          # 002, 003, 004
REPORTED_RUNS = core.OWNERS[2:]            # 003, 004 (persisted per-model reports)
ORIGIN = core.OWNERS[0]                    # full_ext_recovery_001
SUCCESSOR_002 = core.OWNERS[1]
# native verifier module, the runner module (NullAuthority / ReadOnlyAuthority)
# and the read-only authority the verifier needs (probed on the real runs):
#   004  authority=None: verify_model records "no authority supplied" itself and
#        builds its loops with NullAuthority (the 004 loop class only calls
#        authority.check(), which a verification never does);
#   002/003  the native ReadOnlyAuthority(config): the PERSISTED frozen contract
#        and the fingerprint-checked start authorization, because the loop
#        classes bind the iteration-1 supplement rows (LLOV/PARCOACH) to that
#        authority and refuse None shas; its check() raises the read-only
#        refusal, so it can never step a loop.
AUTHORITY_NONE = "authority=None"
AUTHORITY_READ_ONLY = "ReadOnlyAuthority(config)"
NATIVE = OrderedDict([
    (core.OWNERS[1], ("thesis.evaluation.verify_successor_run", "thesis.repair.run_successor", AUTHORITY_READ_ONLY)),
    (core.OWNERS[2], ("thesis.recovery_successor_003.verify", "thesis.recovery_successor_003.run", AUTHORITY_READ_ONLY)),
    (core.OWNERS[3], ("thesis.recovery_successor_004.verify", "thesis.recovery_successor_004.run", AUTHORITY_NONE)),
])
NATIVE_STATUS_001 = "NOT_APPLICABLE_AFTER_HANDOFF"
NATIVE_STATUS_002 = "NOT_PERSISTED_INPROCESS_PASS"
INPROCESS_EVIDENCE_002 = "container log (volatile, not a verification artifact)"
CLOSURE_RUN_CHECKS = ("manifest_complete", "frozen_contract", "authorization", "fragment_integrity",
                      "runtime_t0", "stage_runtime_stamps", "models")


# -- small read-only helpers ------------------------------------------------------------

def lineage_relative(run):
    return "thesis/evaluation/recovery/%s/lineage.json" % run


def successor_report_relative(run, model):
    return "%s/%s%s" % (core.RUN_REGISTRY[run]["verification"], model, SUCCESSOR_REPORT_SUFFIX)


def phase2_report_relative(model):
    return "%s/%s%s" % (core.PHASE2_VERIFICATION_REL, model, PHASE2_REPORT_SUFFIX)


def wave_state_relative(run, model, variant):
    return "%s/%s/%s/repair/%s/wave_state.json" % (core.INTERMEDIATE_REL, run, model, variant)


def open_work_source_run(key):
    """The phase-2 source run an open_work key of a successor report names."""
    return core.PARENT if key == PARENT_OPEN_WORK_KEY else key


def _exists(root, relative):
    try:
        return checked_path(Path(root).resolve(), relative).is_file()
    except Exception:  # noqa: BLE001 - an escaping path is simply not an artifact
        return False


def artifact_facts(root, relative):
    """{relative, exists, raw_sha256} of one repo-relative artifact."""
    exists = _exists(root, relative)
    return OrderedDict([("relative", relative), ("exists", exists),
                        ("raw_sha256", core.raw_sha256(root, relative) if exists else None)])


def check_statuses(report):
    return OrderedDict((c.get("check"), c.get("status")) for c in report.get("checks") or [])


def verified_lineage(root, run):
    """A frozen successor lineage document whose self-hash reproduces."""
    document = core.read_json(root, lineage_relative(run))
    if lineage_fingerprint(document) != document.get("lineage_sha256"):
        raise core.ClosureRefused("the frozen %s lineage does not reproduce its hash" % run)
    return document


def targets_by_model(table):
    """model -> sorted source runs of its phase-2 targets."""
    result = OrderedDict()
    for target in table.targets:
        result.setdefault(target.model_id, set()).add(target.source_run)
    return OrderedDict((model, sorted(runs)) for model, runs in result.items())


def targets_of_owner(table, run):
    """model -> sorted candidate source runs owned by run (iteration runs)."""
    result = OrderedDict()
    for target in table.targets:
        if target.source_run.startswith(run + "__"):
            result.setdefault(target.model_id, set()).add(target.source_run)
    return OrderedDict((model, sorted(runs)) for model, runs in result.items())


# -- pilot_002 / full_ext_001 ------------------------------------------------------------------

def pilot_report_problems(report, expected_loops, contract_sha256):
    """Problems of the persisted pilot post-run verification (empty == ok)."""
    problems = []
    for field, expected in (("schema_version", PILOT_SCHEMA), ("verifier_version", PILOT_VERIFIER),
                            ("run_id", core.PILOT), ("status", PASS)):
        if report.get(field) != expected:
            problems.append("%s is %r (expected %r)" % (field, report.get(field), expected))
    counts = report.get("counts") or {}
    if counts.get("FAIL") != 0 or counts.get("UNRESOLVED") != 0:
        problems.append("counts carry FAIL/UNRESOLVED: %s" % dict(counts))
    checks = report.get("checks") or []
    if not checks or len(checks) != counts.get("PASS") or any(c.get("status") != PASS for c in checks):
        problems.append("check list is not %s PASS checks" % counts.get("PASS"))
    scope = report.get("repair_scope") or {}
    loops = (scope.get("expected_loop_count"), scope.get("observed_loop_count"), scope.get("pass_loop_count"))
    if (scope.get("status") != PASS or loops != (expected_loops,) * 3
            or scope.get("fail_loop_count") != 0 or scope.get("unresolved_loop_count") != 0):
        problems.append("repair scope is not %d/%d PASS: %s" % (expected_loops, expected_loops, loops))
    if report.get("contract_sha256") != contract_sha256:
        problems.append("contract_sha256 differs from the frozen pilot contract")
    return problems


def pilot_report_facts(ctx):
    relative = core.PILOT_POST_RUN_REL
    report = core.read_json(ctx.root, relative)
    contract = ctx.frozen_contract(core.PILOT)["contract_sha256"]
    expected_loops = len(core.MODELS) * len(core.VARIANTS)
    problems = pilot_report_problems(report, expected_loops, contract)
    scope = report.get("repair_scope") or {}
    detail = OrderedDict([
        ("relative", relative), ("raw_sha256", core.raw_sha256(ctx.root, relative)),
        ("schema_version", report.get("schema_version")), ("verifier_version", report.get("verifier_version")),
        ("status", report.get("status")), ("counts", report.get("counts")),
        ("repair_scope", "%s/%s" % (scope.get("pass_loop_count"), scope.get("expected_loop_count"))),
        ("contract_sha256", report.get("contract_sha256")), ("problems", problems[:EXAMPLES])])
    return not problems, detail


def parent_report_problems(report, lineage_sha256, contract_sha256, expected_base_cells):
    """Problems of the persisted parent base-evidence report (empty == ok)."""
    problems = []
    for field, expected in (("schema_version", PARENT_SCHEMA), ("scope", PARENT_SCOPE), ("status", PASS),
                            ("source_run", core.PARENT), ("base_cells", expected_base_cells),
                            ("lineage_sha256", lineage_sha256), ("contract_sha256", contract_sha256),
                            ("historical_repair_adopted", False)):
        if report.get(field) != expected:
            problems.append("%s is %r (expected %r)" % (field, report.get(field), expected))
    checks = report.get("base_checks") or []
    if not checks or any(c.get("status") != PASS for c in checks):
        problems.append("base_checks are not all PASS")
    return problems


def parent_report_facts(ctx):
    relative = core.RUN_REGISTRY[core.PARENT]["verification"]
    report = core.read_json(ctx.root, relative)
    origin_lineage = core.read_json(ctx.root, lineage_relative(ORIGIN))
    if lineage_fingerprint(origin_lineage) != origin_lineage.get("lineage_sha256"):
        raise core.ClosureRefused("the frozen recovery_001 lineage does not reproduce its hash")
    lineage_sha = origin_lineage["lineage_sha256"]
    contract = ctx.frozen_contract(core.PARENT)["contract_sha256"]
    problems = parent_report_problems(report, lineage_sha, contract, pc.EXPECTED_POPULATION[core.PARENT])
    # the successors and the phase-2 custody bind the same recovery_001 lineage
    bound = OrderedDict()
    for run in REVERIFIED_RUNS:
        bound[run] = verified_lineage(ctx.root, run)["predecessor"].get("parent_lineage_sha256") == lineage_sha
    bound[core.PHASE2] = ctx.lineage.origin.get("parent_lineage_sha256") == lineage_sha
    if not all(bound.values()):
        problems.append("recovery_001 lineage not bound by: %s" % [r for r, ok in bound.items() if not ok])
    detail = OrderedDict([
        ("relative", relative), ("raw_sha256", core.raw_sha256(ctx.root, relative)),
        ("schema_version", report.get("schema_version")), ("scope", report.get("scope")),
        ("status", report.get("status")), ("base_cells", report.get("base_cells")),
        ("lineage_sha256", report.get("lineage_sha256")), ("contract_run", report.get("source_run")),
        ("contract_sha256", report.get("contract_sha256")),
        ("base_checks", len(report.get("base_checks") or [])), ("lineage_bound_by", bound),
        ("problems", problems[:EXAMPLES])])
    return not problems, detail


# -- recovery_003 / recovery_004 persisted reports ----------------------------------------------

def successor_reports_problems(run, models, reports, targets, schema=SUCCESSOR_SCHEMA,
                               scope=SUCCESSOR_SCOPE, unexpected_files=()):
    """Problems of the persisted per-model reports of a successor run.
    reports: model -> document (None = missing); targets: model -> source runs
    of its phase-2 targets (every open_work key must be one of them)."""
    problems = []
    if not models:
        problems.append("no contract model")
    for model in models:
        report = reports.get(model)
        if report is None:
            problems.append("%s: report missing" % model)
            continue
        for field, expected in (("schema_version", schema), ("scope", scope), ("run_id", run),
                                ("model_id", model), ("status", PASS)):
            if report.get(field) != expected:
                problems.append("%s: %s is %r (expected %r)" % (model, field, report.get(field), expected))
        variants = report.get("variants") or {}
        if list(variants) != list(core.VARIANTS) or any(v != VARIANT_DONE for v in variants.values()):
            problems.append("%s: variants not all done: %s" % (model, dict(variants)))
        if not report.get("written_at_utc"):
            problems.append("%s: written_at_utc missing" % model)
        checks = report.get("checks") or []
        if not checks or any(c.get("status") != PASS for c in checks):
            problems.append("%s: check list is not all PASS" % model)
        open_work = report.get("open_work") or {}
        if not open_work or "error" in open_work:
            problems.append("%s: open_work absent or errored" % model)
        known = set(targets.get(model) or ())
        for key in open_work:
            if open_work_source_run(key) not in known:
                problems.append("%s: open_work %r is not a phase-2 target of the model" % (model, key))
    for model in reports:
        if model not in models:
            problems.append("%s: report for a model outside the contract" % model)
    for name in unexpected_files:
        problems.append("unexpected file in the verification directory: %s" % name)
    return problems


def successor_reports_facts(ctx, run):
    entry = core.RUN_REGISTRY[run]
    models = list(ctx.frozen_contract(run)["model_ids"])
    directory = checked_path(ctx.root, entry["verification"])
    names = sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []
    expected_names = ["%s%s" % (m, SUCCESSOR_REPORT_SUFFIX) for m in models]
    unexpected = [n for n in names if n not in expected_names]
    reports = OrderedDict()
    for model in models:
        relative = successor_report_relative(run, model)
        reports[model] = core.read_json(ctx.root, relative) if _exists(ctx.root, relative) else None
    targets = targets_by_model(ctx.table)
    problems = successor_reports_problems(run, models, reports, targets, unexpected_files=unexpected)
    per_model = OrderedDict()
    name_lists = []
    for model, report in reports.items():
        if report is None:
            per_model[model] = None
            continue
        open_work = report.get("open_work") or {}
        matched = [k for k in open_work if open_work_source_run(k) in set(targets.get(model) or ())]
        name_lists.append([c.get("check") for c in report.get("checks") or []])
        per_model[model] = OrderedDict([
            ("raw_sha256", core.raw_sha256(ctx.root, successor_report_relative(run, model))),
            ("status", report.get("status")), ("model_complete", report.get("model_complete")),
            ("model_complete_reason", report.get("model_complete_reason")),
            ("variants", report.get("variants")), ("checks", len(report.get("checks") or [])),
            ("open_work_keys", list(open_work)[:EXAMPLES]), ("open_work_entries", len(open_work)),
            ("open_work_phase2_targets", len(matched))])
    detail = OrderedDict([
        ("directory", entry["verification"]), ("models", models), ("files", len(names)),
        ("unexpected_files", unexpected[:EXAMPLES]),
        ("check_names_uniform", len(set(tuple(n) for n in name_lists)) <= 1),
        ("per_model", per_model), ("problems", problems[:EXAMPLES])])
    return not problems, detail


# -- retrospective re-verification (option reverify) ---------------------------------------------

def native_verifier(run):
    """(verifier module, runner module, authority policy) of a successor run;
    the native identity must be the one the persisted reports carry."""
    verifier_name, runner_name, policy = NATIVE[run]
    verifier = importlib.import_module(verifier_name)
    runner = importlib.import_module(runner_name)
    if (getattr(verifier, "SCHEMA", None), getattr(verifier, "SCOPE", None)) != (SUCCESSOR_SCHEMA, SUCCESSOR_SCOPE):
        raise core.ClosureRefused("native verifier identity of %s drifted" % run)
    return verifier, runner, policy


def read_only_authority(runner, policy, config, substitute):
    """The authority object of the policy (None, or the run's ReadOnlyAuthority
    whose persisted shas must be exactly the substitute's frozen contract and
    start authorization - otherwise the bound reads would refuse)."""
    if policy == AUTHORITY_NONE:
        return None, None
    authority = runner.ReadOnlyAuthority(config)
    bound = OrderedDict([("contract_sha256", authority.contract_sha256),
                         ("authorization_sha256", authority.authorization_sha256)])
    if (bound["contract_sha256"] != substitute["frozen_contract"]["contract_sha256"]
            or bound["authorization_sha256"] != substitute["authorization"]["authorization_sha256"]
            or not bound["contract_sha256"] or not bound["authorization_sha256"]):
        raise core.ClosureRefused("the read-only authority is not bound to the frozen contract / "
                                  "start authorization: %s" % dict(bound))
    return authority, bound


class IsolationViolated(core.ClosureRefused):
    """Provider isolation did not hold around a native verifier run."""


def isolated_load_dotenv():
    """The no-op the config loader's .env import is bound to right now
    (captured after isolate_providers; a later re-binding is detectable)."""
    import thesis.config.load_config as loader

    return loader.load_dotenv


def provider_isolation_problems(config, isolated=None):
    """The native verifiers may read persisted endpoint identities only: no
    configured provider variable in the environment, .env import disabled.
    isolated: the no-op captured before the run - it must still be bound
    (checked BEFORE re-isolating, otherwise the assertion is tautological)."""
    import thesis.config.load_config as loader

    problems = []
    if isolated is not None and loader.load_dotenv is not isolated:
        problems.append("load_dotenv was re-bound during the native run")
    pl.isolate_providers()
    present = pl.provider_environment(config)
    if present:
        problems.append("provider variables present: %s" % present)
    if loader.load_dotenv() is not False:
        problems.append("load_dotenv is not the no-op")
    return problems


def authority_substitute(ctx, run):
    """The closure's own facts replacing the one check a read-only
    re-verification cannot pass: the frozen contract (self-hash verified,
    READY, bound by the manifest) and the start authorization (fingerprint
    reproduces, START_ALLOWED, bound to that contract and the manifest). Cross-
    checked with ctx.cache["run_bindings"] of the runs section: the substitute
    names runs:<run>:authorization / frozen_contract as its backing, so the
    bindings must be present and agree (absent -> "input unavailable", not ok);
    statuses the bindings carry under "checks" must be PASS."""
    from thesis.evaluation import run_authorization as ra

    entry = core.RUN_REGISTRY[run]
    manifest = ctx.manifest(run)
    contract = ctx.frozen_contract(run)
    contract_sha = contract.get("contract_sha256")
    contract_ok = (contract.get("run_id") == run and contract.get("status") == "READY"
                   and contract.get("profile") == entry["profile"]
                   and bool(contract_sha) and contract_sha == manifest.get("contract_sha256"))
    content = ctx.authorization_fragment(run).get("content") or {}
    authorization_sha = content.get("authorization_sha256")
    manifest_sha = (manifest.get("authorization") or {}).get("authorization_sha256")
    authorization_ok = (content.get("run_id") == run and content.get("decision") == ra.DECISION_ALLOWED
                        and bool(authorization_sha) and ra.authorization_fingerprint(content) == authorization_sha
                        and content.get("frozen_contract_sha256") == contract_sha
                        and authorization_sha == manifest_sha)
    problems = []
    if not contract_ok:
        problems.append("frozen contract facts not ok")
    if not authorization_ok:
        problems.append("start authorization facts not ok")
    all_bindings = ctx.cache.get("run_bindings")
    bindings = (all_bindings or {}).get(run)
    agree = None
    if all_bindings is None:
        problems.append("input unavailable: run_bindings (runs section)")
    elif bindings is None:
        problems.append("input unavailable: run_bindings[%s]" % run)
    else:
        agree = (bindings.get("contract_sha256") == contract_sha
                 and bindings.get("authorization_sha256") == authorization_sha)
        if not agree:
            problems.append("run_bindings disagree with the recomputed contract / authorization shas")
        statuses = bindings.get("checks")
        if isinstance(statuses, dict):
            not_pass = [c for c in ("frozen_contract", "authorization") if statuses.get(c) != PASS]
            if not_pass:
                problems.append("runs section checks not PASS: %s" % not_pass)
    return OrderedDict([
        ("check", AUTHORITY_CHECK),
        ("replaced_by", ["runs:%s:authorization" % run, "runs:%s:frozen_contract" % run]),
        ("frozen_contract", OrderedDict([("ok", contract_ok), ("contract_sha256", contract_sha),
                                         ("status", contract.get("status")), ("profile", contract.get("profile"))])),
        ("authorization", OrderedDict([("ok", authorization_ok), ("decision", content.get("decision")),
                                       ("authorization_sha256", authorization_sha),
                                       ("frozen_contract_sha256", content.get("frozen_contract_sha256"))])),
        ("run_bindings_agree", agree),
        ("ok", bool(contract_ok and authorization_ok and agree is True and not problems)),
        ("problems", problems[:EXAMPLES]),
    ])


def evidence_floor_problems(checks):
    """The trajectory evidence every read-only re-verification must carry
    (a variant with zero checks counts as "done" for the native verifiers, so
    a skipped variant or a foreign verifier would otherwise pass silently)."""
    passing = [c.get("check") or "" for c in checks if c.get("status") == PASS]
    problems = []
    for variant in core.VARIANTS:
        verdicts = [n for n in passing if n in ["%s: %s" % (variant, v) for v in VARIANT_VERDICTS]]
        if len(verdicts) != 1:
            problems.append("%s: %d PASS trajectory verdicts (expected exactly one of %s)"
                            % (variant, len(verdicts), list(VARIANT_VERDICTS)))
    missing = [n for n in FLOOR_CHECKS if n not in passing]
    if missing:
        problems.append("model-independent checks missing or not PASS: %s" % missing)
    if not any(n.endswith(IMMUTABILITY_CHECK_SUFFIX) for n in passing):
        problems.append("no PASS immutability check (*%s)" % IMMUTABILITY_CHECK_SUFFIX)
    if not any(n.startswith(ENDPOINT_CHECK_PREFIX) for n in passing):
        problems.append("no PASS provider endpoint check (%s*)" % ENDPOINT_CHECK_PREFIX)
    return problems


def classify_retrospective(result, persisted=None, substitute_ok=True, deep=True, authority_detail=None):
    """Verdict over one native read-only re-verification result: exactly the
    authority check fails (with the read-only detail - authority_detail when
    the policy is known, else either of the two), every other check passes,
    the evidence floor holds, open_work is enumerated without error, the
    substitute is PASS, and (003/004) the persisted report is reproduced -
    check names, statuses of every other check, variants, counts, open_work
    keys. deep=False tolerates only the absence of DEEP_ONLY_CHECKS."""
    checks = result.get("checks") or []
    names = [c.get("check") for c in checks]
    failing = [c.get("check") for c in checks if c.get("status") != PASS]
    problems = []
    if not checks:
        problems.append("no checks")
    authority = [c for c in checks if c.get("check") == AUTHORITY_CHECK]
    accepted = (authority_detail,) if authority_detail else (NO_AUTHORITY_DETAIL, NULL_AUTHORITY_DETAIL)
    if len(authority) != 1:
        problems.append("authority check occurs %d times" % len(authority))
    else:
        detail = str(authority[0].get("detail"))
        if authority[0].get("status") == PASS:
            problems.append("the authority check passed in read-only mode (unexpected)")
        elif detail not in accepted:
            problems.append("unexpected authority detail: %s" % detail[:120])
    other = [n for n in failing if n != AUTHORITY_CHECK]
    if other:
        problems.append("failing checks besides the authority check: %s" % other[:EXAMPLES])
    problems.extend(evidence_floor_problems(checks))
    variants = result.get("variants") or {}
    if list(variants) != list(core.VARIANTS) or any(v != VARIANT_DONE for v in variants.values()):
        problems.append("variants not all done: %s" % dict(variants))
    open_work = result.get("open_work")
    if not isinstance(open_work, dict) or not open_work or "error" in open_work:
        problems.append("open_work absent or errored: %s"
                        % str(open_work.get("error") if isinstance(open_work, dict) else open_work)[:120])
        open_work = {}
    if not substitute_ok:
        problems.append("the substituted closure checks (frozen contract / authorization) are not PASS")
    persisted_match = None
    differences = []
    if persisted is not None:
        then_names = [c.get("check") for c in persisted.get("checks") or []]
        expected = then_names if deep else [n for n in then_names if n not in DEEP_ONLY_CHECKS]
        if names != expected:
            differences.append("check names differ (only persisted: %s; only retrospective: %s)"
                               % ([n for n in expected if n not in names][:EXAMPLES],
                                  [n for n in names if n not in expected][:EXAMPLES]))
        then = check_statuses(persisted)
        drift = [c.get("check") for c in checks
                 if c.get("check") != AUTHORITY_CHECK and then.get(c.get("check")) != c.get("status")]
        if drift:
            differences.append("statuses differ: %s" % drift[:EXAMPLES])
        if core.json_stable(result.get("variants")) != core.json_stable(persisted.get("variants")):
            differences.append("variants differ")
        if core.json_stable(result.get("counts")) != core.json_stable(persisted.get("counts")):
            differences.append("counts differ")
        then_open = persisted.get("open_work") if isinstance(persisted.get("open_work"), dict) else {}
        if sorted(open_work) != sorted(then_open):
            differences.append("open_work keys differ (only persisted: %s; only retrospective: %s)"
                               % (sorted(k for k in then_open if k not in open_work)[:EXAMPLES],
                                  sorted(k for k in open_work if k not in then_open)[:EXAMPLES]))
        persisted_match = not differences
        if differences:
            problems.append("persisted report not reproduced: " + "; ".join(differences))
    return OrderedDict([
        ("retrospective_status", RETROSPECTIVE_PASS if not problems else FAIL),
        ("native_status", result.get("status")), ("failing", failing[:EXAMPLES]),
        ("persisted_match", persisted_match), ("differences", differences[:EXAMPLES]),
        ("problems", problems[:EXAMPLES])])


def retrospective_run_problems(records, models, persisted_expected):
    """Problems over the per-model records of one re-verified run. Without a
    persisted report (002) the check names of every model must equal those
    of the run's first deep model (minus DEEP_ONLY_CHECKS when shallow): the
    only cross-model name consistency available for that run."""
    problems = [] if models else ["no contract model"]
    problems.extend(("%s: not re-verified" % m) for m in models if m not in records)
    for model, record in records.items():
        if record.get("retrospective_status") != RETROSPECTIVE_PASS:
            problems.append("%s: %s" % (model, "; ".join(record.get("problems") or [])
                                         or str(record.get("retrospective_status"))))
        if persisted_expected and record.get("persisted_match") is not True:
            problems.append("%s: persisted report not reproduced" % model)
    deep_models = [m for m, r in records.items() if r.get("deep")]
    if records and not deep_models:
        problems.append("no model was re-verified with deep=True")
    if not persisted_expected and deep_models:
        reference = deep_models[0]
        expected_names = [c.get("check") for c in records[reference].get("checks") or []]
        for model, record in records.items():
            names = [c.get("check") for c in record.get("checks") or []]
            if model == reference or not names:
                continue
            expected = expected_names if record.get("deep") else [n for n in expected_names if n not in DEEP_ONLY_CHECKS]
            if names != expected:
                problems.append("%s: check names differ from the deep model %s (only reference: %s; only model: %s)"
                                % (model, reference, [n for n in expected if n not in names][:EXAMPLES],
                                   [n for n in names if n not in expected][:EXAMPLES]))
    if any(not r.get("deep") for r in records.values()):
        # the deep-only checks are model-independent: one deep PASS of the run covers them
        for name in DEEP_ONLY_CHECKS:
            covered = [m for m in deep_models
                       if check_statuses({"checks": records[m].get("checks") or []}).get(name) == PASS]
            if not covered:
                problems.append("deep-only check %r not covered by a deep model" % name)
    return problems


def reverify_model(ctx, run, model, deep=True, substitute=None):
    """One model of one successor run through its native verifier, read-only
    (authority per NATIVE policy); the full record is stored under
    ctx.cache["successor_reverification"] by retrospective_run."""
    verifier, runner, policy = native_verifier(run)
    config = ctx.run_config(run)
    before = provider_isolation_problems(config)
    if before:
        raise IsolationViolated("provider isolation violated before %s/%s: %s" % (run, model, before))
    isolated = isolated_load_dotenv()
    config_path = str((ctx.root / core.RUN_REGISTRY[run]["config"]).resolve())
    substitute = substitute if substitute is not None else authority_substitute(ctx, run)
    # the persisted report is resolved BEFORE the minutes-long native run (fail fast)
    persisted = None
    relative = successor_report_relative(run, model) if core.RUN_REGISTRY[run]["verification"] else None
    if relative is not None:
        if not _exists(ctx.root, relative):
            raise core.ClosureRefused("persisted report missing: " + relative)
        persisted = core.read_json(ctx.root, relative)
    authority, bound = read_only_authority(runner, policy, config, substitute)
    start = time.time()
    result = verifier.verify_model(config, config_path, model, authority=authority, root=ctx.root, deep=deep)
    seconds = round(time.time() - start, 1)
    after = provider_isolation_problems(config, isolated)
    if after:
        raise IsolationViolated("provider isolation violated after %s/%s: %s" % (run, model, after))
    identity = (result.get("run_id"), result.get("model_id"), result.get("schema_version"), result.get("scope"))
    if identity != (run, model, SUCCESSOR_SCHEMA, SUCCESSOR_SCOPE):
        raise core.ClosureRefused("native result identity drifted for %s/%s: %s" % (run, model, identity))
    expected_detail = NO_AUTHORITY_DETAIL if policy == AUTHORITY_NONE else NULL_AUTHORITY_DETAIL
    verdict = classify_retrospective(result, persisted, substitute["ok"], deep, expected_detail)
    open_work = result.get("open_work") if isinstance(result.get("open_work"), dict) else {}
    return OrderedDict([
        ("status", result.get("status")), ("retrospective_status", verdict["retrospective_status"]),
        ("checks", result.get("checks") or []), ("variants", result.get("variants")),
        ("counts", result.get("counts")), ("open_work_keys", list(open_work)),
        ("open_work_entries", len(open_work)), ("open_work_error", open_work.get("error")),
        ("substituted", substitute), ("persisted_report", relative),
        ("persisted_match", verdict["persisted_match"]), ("differences", verdict["differences"]),
        ("problems", verdict["problems"]), ("deep", deep), ("authority_variant", policy),
        ("authority_bound_to", bound), ("seconds", seconds)])


def failed_record(run, model, error, deep, substitute):
    """The record of a model whose re-verification raised (fail-closed, the
    run continues with the remaining models; the cause stays in the record)."""
    relative = successor_report_relative(run, model) if core.RUN_REGISTRY[run]["verification"] else None
    return OrderedDict([
        ("status", None), ("retrospective_status", FAIL), ("checks", []), ("variants", None),
        ("counts", None), ("open_work_keys", []), ("open_work_entries", 0), ("open_work_error", None),
        ("substituted", substitute), ("persisted_report", relative), ("persisted_match", None),
        ("differences", []), ("problems", ["%s: %s" % (type(error).__name__, error)]), ("deep", deep),
        ("authority_variant", NATIVE[run][2]), ("authority_bound_to", None), ("seconds", None)])


def retrospective_summary(record):
    """The deterministic part of a record (no durations, no full check list)."""
    return OrderedDict([
        ("retrospective_status", record.get("retrospective_status")), ("native_status", record.get("status")),
        ("checks", len(record.get("checks") or [])),
        ("failing", [c.get("check") for c in record.get("checks") or [] if c.get("status") != PASS][:EXAMPLES]),
        ("persisted_match", record.get("persisted_match")), ("deep", record.get("deep")),
        ("open_work_keys", list(record.get("open_work_keys") or [])[:EXAMPLES]),
        ("open_work_entries", record.get("open_work_entries")), ("open_work_error", record.get("open_work_error")),
        ("authority_variant", record.get("authority_variant")), ("problems", record.get("problems"))])


def retrospective_run(ctx, run):
    """Every contract model of the run; deep=True for the first model, and for
    the others only while a deep model stayed within DEEP_SECONDS_LIMIT. An
    exception of one model becomes its FAIL record and the run continues,
    except a provider-isolation violation, which stops the run."""
    models = list(ctx.frozen_contract(run)["model_ids"])
    substitute = authority_substitute(ctx, run)
    bucket = ctx.cache.setdefault("successor_reverification", OrderedDict()).setdefault(run, OrderedDict())
    deep = True
    for model in models:
        ctx.log("coverage: re-verifying %s/%s (deep=%s)" % (run, model, deep))
        try:
            record = reverify_model(ctx, run, model, deep, substitute)
        except Exception as error:  # noqa: BLE001 - fail-closed per model, the cause recorded
            record = failed_record(run, model, error, deep, substitute)
            bucket[model] = record
            if isinstance(error, IsolationViolated):
                break
            continue
        bucket[model] = record
        if deep and (record.get("seconds") or 0) > DEEP_SECONDS_LIMIT:
            deep = False
    problems = retrospective_run_problems(bucket, models, run in REPORTED_RUNS)
    detail = OrderedDict([
        ("models", models), ("per_model", OrderedDict((m, retrospective_summary(r)) for m, r in bucket.items())),
        ("substituted", substitute), ("deep_seconds_limit", DEEP_SECONDS_LIMIT),
        ("problems", problems[:EXAMPLES])])
    return not problems, detail


# -- coverage maps of recovery_001 / recovery_002 -------------------------------------------------

def report_identity_problems(document, expected):
    """Fields of a report that differ from its expected identity (a stale or
    foreign report carries the same check names - it must not count)."""
    return ["%s is %r (expected %r)" % (field, document.get(field), value)
            for field, value in (expected or {}).items() if document.get(field) != value]


def phase2_identities(models):
    """relative -> expected identity of the persisted phase-2 reports."""
    return OrderedDict((phase2_report_relative(m), OrderedDict([
        ("schema_version", pv.SCHEMA), ("scope", pv.SCOPE), ("run_id", core.PHASE2), ("model_id", m)]))
        for m in models)


def successor_identities(run, models):
    """relative -> expected identity of the persisted successor reports."""
    return OrderedDict((successor_report_relative(run, m), OrderedDict([
        ("schema_version", SUCCESSOR_SCHEMA), ("scope", SUCCESSOR_SCOPE), ("run_id", run), ("model_id", m)]))
        for m in models)


def evidence_entry(root, evidence, scope, reports=(), rule=None, artifacts=(), computed=None,
                   closure_checks=None, identities=None):
    """One covered_by entry: REAL persisted artifacts (repo-relative, raw
    sha256) and the EXACT checks found in the JSON reports (rule: predicate
    over check names; identities: relative -> expected identity fields of a
    report, a foreign report yields no check). PASS iff there is evidence at
    all, every artifact and report exists, every report yields >= 1 selected
    check, every selected check is PASS and the computed facts (if any) are
    ok. check_names: every selected name (the evidence); checks: <= EXAMPLES
    examples."""
    problems = []
    if not artifacts and not reports and computed is None:
        problems.append("no evidence")
    facts = [artifact_facts(root, relative) for relative in artifacts]
    report_facts = [artifact_facts(root, relative) for relative in reports]
    for fact in facts + report_facts:
        if not fact["exists"]:
            problems.append("missing artifact: " + fact["relative"])
    checks = []
    statuses = Counter()
    for fact in report_facts:
        if not fact["exists"]:
            continue
        document = core.read_json(root, fact["relative"])
        foreign = report_identity_problems(document, (identities or {}).get(fact["relative"]))
        if foreign:
            problems.append("%s: foreign report (%s)" % (fact["relative"], "; ".join(foreign)[:160]))
            continue
        selected = [c for c in document.get("checks") or [] if rule is None or rule(c.get("check") or "")]
        if not selected:
            problems.append("no matching check in " + fact["relative"])
        for check in selected:
            statuses[str(check.get("status"))] += 1
            checks.append(OrderedDict([("artifact", fact["relative"]), ("check", check.get("check")),
                                       ("status", check.get("status"))]))
            if check.get("status") != PASS:
                problems.append("%s: %s is %s" % (fact["relative"], check.get("check"), check.get("status")))
    if computed is not None and not computed.get("ok"):
        problems.append("computed facts not ok: %s" % (computed.get("problems") or "")[:EXAMPLES])
    return OrderedDict([
        ("evidence", evidence), ("scope", scope), ("artifacts", facts), ("reports", report_facts),
        ("check_count", len(checks)), ("check_statuses", pc.counts(statuses)),
        ("check_names", sorted(set(c["check"] for c in checks))), ("checks", checks[:EXAMPLES]),
        ("computed", computed), ("closure_checks", closure_checks),
        ("status", PASS if not problems else FAIL), ("problems", problems[:EXAMPLES])])


def evaluate_map(document):
    """PASS iff every covered_by entry is PASS, every owned loop is terminal
    and every retrospective result present is PASS_WITH_SUBSTITUTED..."""
    problems = []
    if not document.get("covered_by"):
        problems.append("no covered_by evidence")
    for entry in document.get("covered_by") or []:
        if entry.get("status") != PASS:
            problems.append("%s: %s" % (entry.get("evidence"), "; ".join(entry.get("problems") or [])))
    loops = document.get("owned_loops") or []
    if not loops:
        problems.append("no loop owned by the run in the census")
    if any(not loop.get("terminal") for loop in loops):
        problems.append("owned loops not terminal: %s"
                        % ["%s/%s" % (l.get("model"), l.get("variant")) for l in loops if not l.get("terminal")][:EXAMPLES])
    for run, summary in _retrospective_items(document.get("retrospective")):
        for model, record in (summary or {}).items():
            if record.get("retrospective_status") != RETROSPECTIVE_PASS:
                problems.append("retrospective %s/%s: %s" % (run, model, record.get("retrospective_status")))
    return not problems, problems


def _retrospective_items(retrospective):
    """(run, model -> summary) pairs of a map's retrospective block (None =
    not re-verified in this invocation; the report shows reverified: false)."""
    if not retrospective:
        return []
    if any(isinstance(v, dict) and "retrospective_status" in v for v in retrospective.values()):
        return [(None, retrospective)]
    return [(run, summary) for run, summary in retrospective.items() if summary]


def census_loops(ctx):
    """The census loops as study.collect cached them (never recomputed here:
    a cache miss is the FAIL "input unavailable" of spec section 2)."""
    census = ctx.cache.get("census")
    if census is None:
        raise core.ClosureRefused("input unavailable: census (study section)")
    return census["loops"], "ctx.cache[census]"


def owned_loops(loops, run):
    return [OrderedDict([("model", l.get("model")), ("variant", l.get("variant")), ("owner", l.get("owner")),
                         ("terminal", bool(l.get("terminal"))), ("iterations", l.get("iteration")),
                         ("kind", l.get("kind")), ("samples", l.get("samples")),
                         ("status_counts", l.get("status_counts"))])
            for l in loops if l.get("owner") == run]


def retrospective_block(ctx, runs):
    """run -> model -> summary of the cached re-verification (None when the
    run was not re-verified in this invocation)."""
    cached = ctx.cache.get("successor_reverification") or {}
    block = OrderedDict()
    for run in runs:
        records = cached.get(run)
        block[run] = (OrderedDict((m, retrospective_summary(r)) for m, r in records.items())
                      if records else None)
    return block


def _census_entry(ctx, run, loops):
    mine = owned_loops(loops, run)
    artifacts = [wave_state_relative(run, l["model"], l["variant"]) for l in mine]
    computed = OrderedDict([("ok", bool(mine) and all(l["terminal"] for l in mine)),
                            ("loops", len(mine)), ("terminal", sum(1 for l in mine if l["terminal"])),
                            ("by_variant", pc.counts(Counter(l["variant"] for l in mine))),
                            ("problems", [] if mine else ["no owned loop"])])
    return evidence_entry(ctx.root, "repair-loop census: the loops owned by %s are terminal (owner = the "
                          "unique run with the loop's wave state)" % run,
                          "population:census_66_66 (thesis.recovery_successor_004.census, read-only)",
                          artifacts=artifacts, computed=computed)


def _phase2_entry(ctx, run):
    """Measurement completeness of every candidate of run: the phase-2 reports'
    full_ext:<run>__*:* checks, and the set of source runs they cover equals
    the run's targets of the frozen table."""
    expected = targets_of_owner(ctx.table, run)
    prefix = "full_ext:%s__" % run
    reports = [phase2_report_relative(model) for model in expected]
    found = OrderedDict()
    problems = []
    identities = phase2_identities(list(expected))
    for model in expected:
        relative = phase2_report_relative(model)
        if not _exists(ctx.root, relative):
            problems.append("missing report of " + model)
            continue
        document = core.read_json(ctx.root, relative)
        foreign = report_identity_problems(document, identities[relative])
        if foreign:
            problems.append("%s: foreign report (%s)" % (model, "; ".join(foreign)[:160]))
            continue
        names = [c.get("check") or "" for c in document.get("checks") or []]
        found[model] = sorted(set(n.split(":")[1] for n in names if n.startswith(prefix) and n.count(":") >= 2))
        if found[model] != expected[model]:
            problems.append("%s: checks cover %s, targets are %s" % (model, found[model], expected[model]))
    computed = OrderedDict([("ok", bool(expected) and not problems), ("targets", sum(len(v) for v in expected.values())),
                            ("models", list(expected)), ("source_runs_by_model", expected),
                            ("problems", problems[:EXAMPLES])])
    return evidence_entry(ctx.root, "phase-2 measurement completeness of every %s candidate (static, "
                          "correctness, dynamic, enhanced; provenance and binding)" % run, pv.SCOPE,
                          reports=reports, rule=lambda name: name.startswith(prefix), computed=computed,
                          identities=identities)


def _bindings_entry(ctx, run):
    """The run's frozen contract, start authorization and manifest (the
    closure's runs section verifies them; the substitute facts recomputed)."""
    entry = core.RUN_REGISTRY[run]
    artifacts = [entry["contract"], "%s/%s/run_manifest.json" % (core.INTERMEDIATE_REL, run),
                 "%s/%s/run_manifest.fragments/authorization.start.json" % (core.INTERMEDIATE_REL, run)]
    substitute = authority_substitute(ctx, run)
    computed = OrderedDict(substitute)
    computed["problems"] = list(substitute.get("problems") or ([] if substitute["ok"] else ["not ok"]))
    return evidence_entry(ctx.root, "contract, authorization, manifest, runtime and config drift of %s "
                          "(closure section runs; frozen contract and start authorization recomputed here)" % run,
                          core.SCOPE, artifacts=artifacts, computed=computed,
                          closure_checks=["runs:%s:%s" % (run, c) for c in CLOSURE_RUN_CHECKS])


def inventory_differences(reference, other):
    """Paths whose {raw_sha256, size} entry differs between two inventory
    maps (missing on one side included); sorted, complete."""
    reference = reference or {}
    other = other or {}
    return sorted(p for p in set(reference) | set(other) if reference.get(p) != other.get(p))


def _snapshot_entry(ctx):
    """Byte protection of recovery_001: the predecessor snapshots frozen by the
    002/003/004 lineages (their per-file maps must equal the phase-2 protected
    inventory of recovery_001 - the only current tie between the historical
    snapshots and the bytes phase 2 protects now), the phase-2 custody chain
    (origin bindings) and the phase-2 reports' global immutability
    (lineage.verify incl. custody)."""
    origin_contract = ctx.frozen_contract(ORIGIN)["contract_sha256"]
    custody = ctx.lineage.document["custody"]
    protected = ctx.lineage.document["protected"].get(ORIGIN) or {}
    protected_files = protected.get("files") or {}
    snapshots = OrderedDict()
    problems = []
    if not protected_files or not protected.get("inventory_sha256") or protected.get("run_prefix") != ORIGIN:
        problems.append("the phase-2 lineage protects no %s inventory" % ORIGIN)
    for run in REVERIFIED_RUNS:
        document = verified_lineage(ctx.root, run)
        snapshot = document.get("predecessor_snapshot") or {}
        predecessor = document.get("predecessor") or {}
        differing = inventory_differences(protected_files, snapshot.get("files") or {})
        snapshots[run] = OrderedDict([("source_run", snapshot.get("source_run")), ("files", len(snapshot.get("files") or {})),
                                      ("snapshot_sha256", snapshot.get("snapshot_sha256")),
                                      ("lineage_sha256", document.get("lineage_sha256")),
                                      ("predecessor_contract_sha256", predecessor.get("contract_sha256")),
                                      ("paths_differing_from_phase2_protected", len(differing))])
        if snapshot.get("source_run") != ORIGIN:
            problems.append("%s snapshot is not of %s" % (run, ORIGIN))
        if predecessor.get("contract_sha256") != origin_contract:
            problems.append("%s binds another %s contract" % (run, ORIGIN))
        if differing:
            problems.append("%s snapshot differs from the phase-2 protected %s inventory at %d paths: %s"
                            % (run, ORIGIN, len(differing), differing[:EXAMPLES]))
    files = set(s["files"] for s in snapshots.values())
    if len(files) != 1 or custody.get("recovery_001_snapshot_files") not in files or len(protected_files) not in files:
        problems.append("snapshot membership differs: %s vs custody %s vs protected %d"
                        % (sorted(files), custody.get("recovery_001_snapshot_files"), len(protected_files)))
    if custody.get("full_ext_recovery_004_lineage_sha256") != snapshots[core.OWNERS[3]]["lineage_sha256"]:
        problems.append("the phase-2 custody binds another 004 lineage")
    if (custody.get("origin_bindings") or {}).get("contract_sha256") != origin_contract:
        problems.append("the phase-2 origin bindings name another %s contract" % ORIGIN)
    computed = OrderedDict([("ok", not problems), ("snapshots", snapshots),
                            ("custody", OrderedDict((k, v) for k, v in custody.items() if k != "origin_bindings")),
                            ("phase2_protected_inventory_sha256", protected.get("inventory_sha256")),
                            ("phase2_protected_files", len(protected_files)),
                            ("origin_contract_sha256", origin_contract), ("problems", problems[:EXAMPLES])])
    return evidence_entry(ctx.root, "byte protection of %s: predecessor snapshots of the 002/003/004 "
                          "lineages (per-file maps equal to the phase-2 protected inventory), the phase-2 "
                          "custody chain and lineage immutability" % ORIGIN,
                          pl.SCHEMA + " custody / " + pv.SCOPE,
                          reports=[phase2_report_relative(m) for m in core.MODELS],
                          rule=lambda name: name == "global:immutability",
                          artifacts=[lineage_relative(r) for r in REVERIFIED_RUNS] + [lineage_relative(core.PHASE2)],
                          computed=computed, identities=phase2_identities(core.MODELS))


def _sibling_entry(ctx):
    """Byte protection of recovery_002: its inventory frozen by the 003 AND
    the 004 lineage (both shas, file counts and per-file maps must equal the
    phase-2 custody sha and the protected inventory of the phase-2 lineage -
    the 002 map is the only evidence for recovery_002, so a change between
    the 003 freeze and the 004 freeze must surface here)."""
    custody = ctx.lineage.document["custody"]
    protected = ctx.lineage.document["protected"].get(SUCCESSOR_002) or {}
    lineage_003 = verified_lineage(ctx.root, core.OWNERS[2])
    lineage_004 = verified_lineage(ctx.root, core.OWNERS[3])
    frozen_003 = (lineage_003.get("sibling_successors") or {}).get(SUCCESSOR_002) or {}
    frozen_003_inv = frozen_003.get("protected_inventory") or {}
    frozen_004 = ((lineage_004.get("sibling_successors") or {}).get(SUCCESSOR_002) or {}).get("protected_inventory") or {}
    custody_sha = (custody.get("sibling_inventories_sha256") or {}).get(SUCCESSOR_002)
    problems = []
    if not frozen_003 or not frozen_003_inv.get("inventory_sha256"):
        problems.append("the 003 lineage freezes no %s inventory" % SUCCESSOR_002)
    if not frozen_004.get("inventory_sha256"):
        problems.append("the 004 lineage freezes no %s inventory" % SUCCESSOR_002)
    if not protected.get("inventory_sha256") or protected.get("run_prefix") != SUCCESSOR_002:
        problems.append("the phase-2 lineage protects no %s inventory" % SUCCESSOR_002)
    shas = OrderedDict([("frozen_by_003", frozen_003_inv.get("inventory_sha256")),
                        ("frozen_by_004", frozen_004.get("inventory_sha256")),
                        ("phase2_custody", custody_sha), ("phase2_protected", protected.get("inventory_sha256"))])
    if len(set(shas.values())) != 1:
        problems.append("the %s inventory shas disagree: %s" % (SUCCESSOR_002, dict(shas)))
    counts = OrderedDict([("frozen_by_003", len(frozen_003_inv.get("files") or {})),
                          ("frozen_by_004", len(frozen_004.get("files") or {})),
                          ("phase2_protected", len(protected.get("files") or {}))])
    if len(set(counts.values())) != 1 or not all(counts.values()):
        problems.append("the %s inventory file counts disagree: %s" % (SUCCESSOR_002, dict(counts)))
    for name, inventory in (("003", frozen_003_inv), ("004", frozen_004)):
        differing = inventory_differences(protected.get("files") or {}, inventory.get("files") or {})
        if differing:
            problems.append("the %s inventory frozen by %s differs from the phase-2 protected inventory at %d "
                            "paths: %s" % (SUCCESSOR_002, name, len(differing), differing[:EXAMPLES]))
    computed = OrderedDict([
        ("ok", not problems), ("frozen_by_003", OrderedDict([("decision", frozen_003.get("decision"))])),
        ("frozen_by_003_inventory_sha256", shas["frozen_by_003"]), ("frozen_by_003_files", counts["frozen_by_003"]),
        ("frozen_by_004_inventory_sha256", shas["frozen_by_004"]), ("frozen_by_004_files", counts["frozen_by_004"]),
        ("phase2_custody_inventory_sha256", custody_sha),
        ("phase2_protected_inventory_sha256", shas["phase2_protected"]),
        ("phase2_protected_files", counts["phase2_protected"]), ("problems", problems[:EXAMPLES])])
    return evidence_entry(ctx.root, "byte protection of %s: inventories frozen by the 003/004 lineages "
                          "(shas, counts and per-file maps equal), the phase-2 custody chain and lineage "
                          "immutability" % SUCCESSOR_002,
                          pl.SCHEMA + " custody / " + pv.SCOPE,
                          reports=[phase2_report_relative(m) for m in core.MODELS],
                          rule=lambda name: name == "global:immutability",
                          artifacts=[lineage_relative(core.OWNERS[2]), lineage_relative(core.OWNERS[3]),
                                     lineage_relative(core.PHASE2)],
                          computed=computed, identities=phase2_identities(core.MODELS))


def _successor_report_entry(ctx, run, evidence, rule):
    models = list(ctx.frozen_contract(run)["model_ids"])
    return evidence_entry(ctx.root, evidence, SUCCESSOR_SCOPE,
                          reports=[successor_report_relative(run, m) for m in models], rule=rule,
                          identities=successor_identities(run, models))


def adopted_vs_new(loops, contracts):
    """Per successor: the test_feedback loops it adopted from recovery_001 and
    the loops it continued (census kind) or started fresh."""
    result = OrderedDict()
    for run in REVERIFIED_RUNS:
        models = contracts.get(run) or []
        adopted = ["%s/%s" % (l["model"], l["variant"]) for l in loops
                   if l.get("owner") == ORIGIN and l.get("model") in models]
        continued = ["%s/%s" % (l["model"], l["variant"]) for l in loops
                     if l.get("owner") == run and l.get("kind") == "continued"]
        native = ["%s/%s" % (l["model"], l["variant"]) for l in loops
                  if l.get("owner") == run and l.get("kind") == "native"]
        result[run] = OrderedDict([("models", models), ("adopted_from_%s" % ORIGIN, adopted),
                                   ("continued_from_%s" % ORIGIN, continued), ("fresh", native)])
    return result


def recovery_001_coverage(ctx):
    loops, census_source = census_loops(ctx)
    contracts = OrderedDict((run, list(ctx.frozen_contract(run)["model_ids"])) for run in REVERIFIED_RUNS)
    covered_by = [
        _census_entry(ctx, ORIGIN, loops),
        _successor_report_entry(ctx, core.OWNERS[2], "%s verifier: iteration-1 (predecessor) decisions and "
                                "supplements of the continued loops, adopted test_feedback loops" % core.OWNERS[2],
                                lambda name: "iteration-1" in name or "adopted" in name),
        _successor_report_entry(ctx, core.OWNERS[2], "%s verifier: predecessor bytes, membership and bindings "
                                "unchanged" % core.OWNERS[2],
                                lambda name: name == "predecessor bytes, membership and bindings unchanged"),
        _successor_report_entry(ctx, core.OWNERS[3], "%s verifier: recovery_001 (and sibling) bytes, membership "
                                "and bindings unchanged" % core.OWNERS[3], lambda name: "recovery_001" in name),
        _snapshot_entry(ctx),
        _phase2_entry(ctx, ORIGIN),
        _bindings_entry(ctx, ORIGIN),
    ]
    document = OrderedDict([
        ("run_id", ORIGIN), ("persisted_verification_report", None),
        ("native_verifier", core.RUN_REGISTRY[ORIGIN]["verifier"]),
        ("native_verifier_status", NATIVE_STATUS_001),
        ("census_source", census_source), ("owned_loops", owned_loops(loops, ORIGIN)),
        ("covered_by", covered_by),
        ("historically_performed", [OrderedDict([
            ("evidence", "%s in-process per-model verification (verify_successor_run) incl. the iteration-1 "
                         "checks of the continued loops of its models" % SUCCESSOR_002),
            ("models", contracts[SUCCESSOR_002]), ("artifact", None),
            ("note", INPROCESS_EVIDENCE_002)])]),
        ("missing_historical_reports", [OrderedDict([
            ("artifact", "%s/%s/post_run_verification.json" % (core.INTERMEDIATE_REL, ORIGIN)),
            ("verifier", "thesis/evaluation/verify_recovery_run.py (recovery_post_run_verification.v1)"),
            ("reason", "never persisted (the verifier prints only); its acceptance predicate - every loop "
                       "terminal within recovery_001 - is unsatisfiable after the successor handoff by design")])]),
        ("adopted_vs_new", adopted_vs_new(loops, contracts)),
        ("retrospective", retrospective_block(ctx, (core.OWNERS[1], core.OWNERS[2]))),
        ("scope", core.RETROSPECTIVE_SCOPE),
    ])
    return document


def recovery_002_coverage(ctx):
    loops, census_source = census_loops(ctx)
    contracts = OrderedDict((run, list(ctx.frozen_contract(run)["model_ids"])) for run in REVERIFIED_RUNS)
    covered_by = [
        _census_entry(ctx, SUCCESSOR_002, loops),
        _successor_report_entry(ctx, core.OWNERS[3], "%s verifier: recovery_001 and sibling successor bytes, "
                                "membership and bindings unchanged" % core.OWNERS[3],
                                lambda name: "sibling" in name),
        _sibling_entry(ctx),
        _phase2_entry(ctx, SUCCESSOR_002),
        _bindings_entry(ctx, SUCCESSOR_002),
    ]
    retrospective = retrospective_block(ctx, (SUCCESSOR_002,))[SUCCESSOR_002]
    document = OrderedDict([
        ("run_id", SUCCESSOR_002), ("persisted_verification_report", None),
        ("native_verifier", core.RUN_REGISTRY[SUCCESSOR_002]["verifier"]),
        ("native_verifier_status", NATIVE_STATUS_002),
        ("historical_inprocess_evidence", INPROCESS_EVIDENCE_002),
        ("census_source", census_source), ("owned_loops", owned_loops(loops, SUCCESSOR_002)),
        ("covered_by", covered_by),
        ("historically_performed", [OrderedDict([
            ("evidence", "SUCCESSOR_MODEL_VERIFICATION <model> PASS printed in-process for every contract model"),
            ("models", contracts[SUCCESSOR_002]), ("artifact", None), ("note", INPROCESS_EVIDENCE_002)])]),
        ("missing_historical_reports", [OrderedDict([
            ("artifact", "%s/%s/verification/%s%s" % (core.INTERMEDIATE_REL, SUCCESSOR_002, model,
                                                      SUCCESSOR_REPORT_SUFFIX)),
            ("verifier", "thesis/evaluation/verify_successor_run.py"),
            ("reason", "never persisted (the verifier has no write_report)")]) for model in contracts[SUCCESSOR_002]]),
        ("adopted_vs_new", adopted_vs_new(loops, contracts).get(SUCCESSOR_002)),
        ("retrospective", retrospective),
        ("scope", core.RETROSPECTIVE_SCOPE),
    ])
    return document


def coverage_map_facts(ctx, builder):
    document = builder(ctx)
    ok, problems = evaluate_map(document)
    document["status"] = PASS if ok else FAIL
    document["problems"] = problems[:EXAMPLES]
    return ok, document


# -- scopes / evidence table ----------------------------------------------------------------------

def scopes_table(pilot_scope, parent_scope, successor_scope, phase2_scope):
    """Every verification scope of the study with what it proves and what it
    does NOT prove (definitions, not measurements)."""
    return [
        OrderedDict([("scope", pilot_scope), ("runs", [core.PILOT]),
                     ("verifier", core.RUN_REGISTRY[core.PILOT]["verifier"]),
                     ("proves", "the pilot run's contract, authorization, runtime identity, invocation "
                                "coverage and the terminality of every pilot repair loop"),
                     ("does_not_prove", "result acceptance (a separate author decision); nothing about "
                                        "the full-extension block")]),
        OrderedDict([("scope", parent_scope), ("runs", [core.PARENT]),
                     ("verifier", core.RUN_REGISTRY[core.PARENT]["verifier"]),
                     ("proves", "the full_ext_001 base cells (iteration 0) under the frozen full_ext_001 "
                                "contract, frozen together with recovery_001"),
                     ("does_not_prove", "the aborted full_ext_001 repair (excluded) and any repair candidate")]),
        OrderedDict([("scope", successor_scope), ("runs", list(REPORTED_RUNS) + [SUCCESSOR_002 + " (in-process only)"]),
                     ("verifier", "thesis/evaluation/verify_successor_run.py, thesis/recovery_successor_003/verify.py, "
                                  "thesis/recovery_successor_004/verify.py"),
                     ("proves", "for one model: every variant terminal and every successor trajectory native "
                                "(re-derived decisions, re-built requests, 1:1 provider outcomes) under the "
                                "frozen successor contract, predecessor and protected bytes unchanged"),
                     ("does_not_prove", "phase-2 backfill, held-out enhanced tests, full recovery acceptance "
                                        "(listed as open work)")]),
        OrderedDict([("scope", phase2_scope), ("runs", [core.PHASE2]),
                     ("verifier", core.RUN_REGISTRY[core.PHASE2]["verifier"]),
                     ("proves", "measurement completeness of every pilot and full-extension cell and "
                                "candidate; protected bytes and the base population unchanged"),
                     ("does_not_prove", "the repair trajectories themselves (successor scope); result acceptance")]),
        OrderedDict([("scope", core.SCOPE), ("runs", list(core.RUNS)), ("verifier", "thesis/study_closure"),
                     ("proves", "read-only global consistency of the seven runs, their bindings and the "
                                "composite; nothing measured, generated or repaired"),
                     ("does_not_prove", "result acceptance; any claim beyond the persisted artifacts")]),
        OrderedDict([("scope", core.RETROSPECTIVE_SCOPE), ("runs", [ORIGIN, SUCCESSOR_002]),
                     ("verifier", "thesis/study_closure/coverage.py"),
                     ("proves", "coverage of recovery_001/002 by persisted artifacts and the exact checks in "
                                "them, and (option reverify) the native successor verifiers re-run read-only "
                                "with the authority check substituted by the closure's run bindings"),
                     ("does_not_prove", "a persisted historical PASS of recovery_001/002; the acceptance "
                                        "predicate of verify_recovery_run")]),
    ]


def scopes_problems(rows):
    scopes = [row.get("scope") for row in rows]
    problems = []
    if any(not s for s in scopes):
        problems.append("empty scope")
    if len(set(scopes)) != len(scopes):
        problems.append("scopes not distinct: %s" % pc.counts(Counter(s for s in scopes if scopes.count(s) > 1)))
    return problems


def _report_row(root, relative, scope_field="scope"):
    fact = artifact_facts(root, relative)
    if fact["exists"]:
        document = core.read_json(root, relative)
        fact["status"] = document.get("status")
        fact["scope"] = document.get(scope_field)
        fact["schema_version"] = document.get("schema_version")
    return fact


def runs_evidence(ctx, contracts):
    """Per run: the persisted report paths + raw shas, status, scope."""
    evidence = OrderedDict()
    for run in core.RUNS:
        entry = core.RUN_REGISTRY[run]
        if run == core.PILOT:
            reports = [_report_row(ctx.root, core.PILOT_POST_RUN_REL, "verifier_version")]
        elif run == core.PARENT:
            reports = [_report_row(ctx.root, entry["verification"])]
        elif run in REPORTED_RUNS:
            reports = [_report_row(ctx.root, successor_report_relative(run, m)) for m in contracts.get(run) or []]
        elif run == core.PHASE2:
            reports = [_report_row(ctx.root, phase2_report_relative(m)) for m in core.MODELS]
        else:
            reports = []
        evidence[run] = OrderedDict([
            ("verification", entry["verification"]), ("verifier", entry["verifier"]),
            ("persisted", bool(reports) and all(r["exists"] for r in reports)),
            ("native_verifier_status", NATIVE_STATUS_001 if run == ORIGIN else NATIVE_STATUS_002
             if run == SUCCESSOR_002 else None),
            ("reports", reports)])
    return evidence


# -- section ----------------------------------------------------------------------------------------

def collect(ctx):
    section = core.Section(SECTION)
    section.guard("pilot_report", pilot_report_facts, ctx)
    section.guard("parent_report", parent_report_facts, ctx)
    for run in REPORTED_RUNS:
        section.guard("successor_reports:%s" % run, successor_reports_facts, ctx, run)
    reverify = bool(ctx.options.get("reverify"))
    section.data["reverified"] = reverify
    if reverify:
        for run in REVERIFIED_RUNS:
            section.guard("retrospective_reverification:%s" % run, ctx.timed,
                          "coverage.retrospective:%s" % run, retrospective_run, ctx, run)
    else:
        section.data["retrospective_note"] = ("retrospective re-verification skipped by option "
                                              "(reverify=False); no check emitted, nothing claimed")
    maps = OrderedDict()
    for run, builder in ((ORIGIN, recovery_001_coverage), (SUCCESSOR_002, recovery_002_coverage)):
        check_id = "%s_map" % run.replace("full_ext_", "")
        try:
            ok, document = coverage_map_facts(ctx, builder)
        except Exception as error:  # noqa: BLE001 - fail-closed with the message
            section.add(check_id, False, "%s: %s" % (type(error).__name__, error))
            continue
        maps[run] = document
        section.add(check_id, ok, OrderedDict([
            ("run_id", run), ("status", document["status"]), ("native_verifier_status", document["native_verifier_status"]),
            ("owned_loops", len(document["owned_loops"])),
            ("covered_by", [OrderedDict([("evidence", e["evidence"]), ("status", e["status"]),
                                         ("check_count", e["check_count"])]) for e in document["covered_by"]]),
            ("retrospective", document.get("retrospective")), ("problems", document["problems"])]))
    section.data["maps"] = maps

    def scopes():
        pilot = core.read_json(ctx.root, core.PILOT_POST_RUN_REL)
        parent = core.read_json(ctx.root, core.RUN_REGISTRY[core.PARENT]["verification"])
        successor = OrderedDict()
        for run in REPORTED_RUNS:
            for model in ctx.frozen_contract(run)["model_ids"]:
                relative = successor_report_relative(run, model)
                if _exists(ctx.root, relative):
                    successor[core.read_json(ctx.root, relative).get("scope")] = run
        phase2 = OrderedDict()
        for model in core.MODELS:
            relative = phase2_report_relative(model)
            if _exists(ctx.root, relative):
                phase2[core.read_json(ctx.root, relative).get("scope")] = model
        problems = []
        if list(successor) != [SUCCESSOR_SCOPE]:
            problems.append("successor reports carry the scopes %s" % list(successor))
        if list(phase2) != [pv.SCOPE]:
            problems.append("phase-2 reports carry the scopes %s" % list(phase2))
        rows = scopes_table("%s / %s" % (pilot.get("verifier_version"), pilot.get("schema_version")),
                            parent.get("scope"), SUCCESSOR_SCOPE, pv.SCOPE)
        problems.extend(scopes_problems(rows))
        section.data["scopes"] = rows
        return not problems, OrderedDict([("scopes", [r["scope"] for r in rows]), ("problems", problems[:EXAMPLES])])

    section.guard("scopes_unique", scopes)
    try:
        contracts = OrderedDict((run, list(ctx.frozen_contract(run)["model_ids"])) for run in REPORTED_RUNS)
        section.data["runs_evidence"] = runs_evidence(ctx, contracts)
    except Exception as error:  # noqa: BLE001 - the table is data; a failure is reported as a check
        section.add("runs_evidence", False, "%s: %s" % (type(error).__name__, error))
    if reverify:
        section.data["retrospective"] = retrospective_block(ctx, REVERIFIED_RUNS)
    return section
