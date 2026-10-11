"""Per-model verification of the successor run (scope: repair trajectories).

Scope string SUCCESSOR_MODEL_REPAIR_SCOPE_NOT_FULL_RECOVERY_ACCEPTANCE: a PASS
here proves, for ONE model, that all three feedback variants are terminal and
that every FRESH trajectory is the native one: the iteration-0 decision of
every parent cell, the iteration-1 and iteration-2 decisions re-derived with
the native rule, every request re-built byte-identically, 1:1 provider
outcomes per submission intent of each iteration, native coverage of every
analysis the decisions depend on - under the frozen successor
contract/authorization, with recovery_001, the sibling successors 002/003,
every protected historical byte and the 1,980-cell base population intact,
and no repair evidence of the model anywhere but in this run.

It does NOT claim phase-2 backfill or held-out (enhanced) acceptance; those
obligations are enumerated as OPEN work, never as PASS. A completed repair
state is not a successful model answer or program execution: the response,
correctness and terminal-status counts are reported separately.

Read-only. Python 3.8 compatible.
"""
from __future__ import annotations

import json
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.recovery_successor_004 import lineage as sl
from thesis.recovery_successor_004 import routing as sr
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.recovery_lineage import RecoveryRefused

SCHEMA = "successor_model_verification.v1"
SCOPE = "SUCCESSOR_MODEL_REPAIR_SCOPE_NOT_FULL_RECOVERY_ACCEPTANCE"
ROOT = Path(__file__).resolve().parents[2]
STATE_FIELDS = sr.STATE_FIELDS


class Report:
    def __init__(self, model):
        self.model = model
        self.checks = []

    def add(self, name, ok, detail=None):
        self.checks.append(OrderedDict([("check", name), ("status", "PASS" if ok else "FAIL"),
                                        ("detail", detail)]))
        return ok

    def guard(self, name, function, *args, **kwargs):
        try:
            detail = function(*args, **kwargs)
            return self.add(name, True, detail)
        except Exception as error:  # noqa: BLE001 - every failure is reported
            self.add(name, False, "%s: %s" % (type(error).__name__, error))
            return None

    @property
    def status(self):
        return "PASS" if all(c["status"] == "PASS" for c in self.checks) else "STOP"


def _rows(path):
    return sw.read_jsonl(path)


def _loops(config, config_path, model, lineage, parent, authority):
    from thesis.recovery_successor_004 import run as run_successor

    loops = OrderedDict()
    for loop in run_successor.build_loops(config, config_path, lineage, parent, authority, models=[model]):
        loops[loop.variant] = loop
    return loops


def reproduce_decisions(loop, iteration, rows_by_sample, prior_by_sample):
    """Re-derive the persisted decisions of one iteration with the native rule."""
    from thesis.repair import orchestrator

    static = loop.load_stage_records(iteration, "static_analysis")
    correctness = loop.load_stage_records(iteration, "correctness_tests") if loop.needs_tests() else {}
    dynamic = loop.load_stage_records(iteration, "dynamic_analysis") if loop.needs_dynamic() else {}
    mismatches = []
    for sample, row in rows_by_sample.items():
        prior = prior_by_sample.get(sample)
        decision = orchestrator.evaluate_stop(
            config=loop.config, variant=loop.variant, iteration=iteration,
            max_iterations=loop.settings["max_iterations"],
            static_record=static.get(sample), dynamic_record=dynamic.get(sample),
            correctness_record=correctness.get(sample),
            previous_low_confidence_keys=(prior.get("low_confidence_keys") if prior else None))
        expected = OrderedDict([("status", decision.status), ("stop_reason", decision.stop_reason),
                                ("counts", decision.counts), ("test_verdict", decision.test_verdict),
                                ("low_confidence_keys", decision.low_confidence_keys),
                                ("analysis_gaps", decision.analysis_gaps)])
        actual = OrderedDict((field, row.get(field)) for field in STATE_FIELDS)
        if json.loads(json.dumps(expected)) != json.loads(json.dumps(actual)):
            mismatches.append(sample)
    if mismatches:
        raise RecoveryRefused("%d persisted decision(s) do not reproduce: %s"
                              % (len(mismatches), ", ".join(mismatches[:5])))
    return len(rows_by_sample)


def _decisions(rows, iteration):
    """Analysis decisions of one iteration (bookkeeping rows of the response
    phase - unusable answers, provider exhaustion - excluded)."""
    from thesis.repair import orchestrator

    return OrderedDict((r["sample_id"], r) for r in rows if r["iteration"] == iteration
                       and r.get("status") not in (orchestrator.STATUS_UNUSABLE,
                                                   orchestrator.STATUS_API_EXHAUSTED))


def fresh_loop(loop, report, counts):
    """Trajectory integrity of one FRESH loop (any variant)."""
    from thesis.repair import orchestrator

    v = loop.variant
    wave = loop.load_wave_state()
    report.add("%s: wave done" % v, wave.get("phase") == "done" and wave.get("origin") == "FRESH",
               dict(wave))
    rows = loop.successor_state_rows()
    merged = loop.sample_states()
    assembly0 = loop.load_assembly_entries(0)
    parent_samples = sorted(assembly0)
    report.add("%s: every parent cell terminal" % v,
               sorted(merged) == parent_samples and all(
                   r.get("status") in orchestrator.TERMINAL_STATUSES for r in merged.values()),
               {"samples": len(merged), "parent_cells": len(parent_samples)})
    unassembled = sorted(s for s, e in assembly0.items() if not e.get("assembled"))
    unusable0 = sorted(r["sample_id"] for r in rows if r["iteration"] == 0
                       and r.get("status") == orchestrator.STATUS_UNUSABLE)
    decided = {0: _decisions(rows, 0)}
    report.add("%s: one iteration-0 decision per assembled parent cell" % v,
               sorted(decided[0]) == loop.iteration_samples(0) and unusable0 == unassembled
               and len([r for r in rows if r["iteration"] == 0]) == len(parent_samples),
               {"assembled": len(decided[0]), "unassembled": len(unassembled)})
    report.guard("%s: iteration-0 decisions reproduce" % v, reproduce_decisions, loop, 0, decided[0], {})
    exhausted = sorted(s for s, r in merged.items() if r.get("status") == orchestrator.STATUS_API_EXHAUSTED)
    at_bound = []
    for iteration in sl.PROVIDER_ITERATIONS:
        try:
            at_bound.extend(loop.verify_submission_ledger(iteration) or [])
        except Exception:  # noqa: BLE001 - reported by the per-iteration ledger check below
            pass
    unknown = sorted(set(r["sample_id"] for r in at_bound))
    report.add("%s: no request ended by provider exhaustion" % v, not exhausted,
               OrderedDict([
                   ("stopped_api_exhausted", exhausted),
                   ("outcome_unknown_at_native_bound", at_bound),
                   ("open_work", "infrastructure condition, not a model failure; the native bound forbids "
                                 "another automatic request; samples in outcome_unknown_at_native_bound were "
                                 "interrupted during their last allowed round - the provider may have "
                                 "answered and billed it; the others: provider unavailable")])
               if exhausted else None)
    report.add("%s: every ambiguous intent at the native bound ended its sample as exhausted" % v,
               all(s in exhausted for s in unknown), {"ambiguous_at_bound": unknown} if unknown else None)
    totals = Counter()
    for iteration in sl.PROVIDER_ITERATIONS:
        prior = decided[iteration - 1]
        active = sorted(s for s, r in prior.items() if r.get("status") == orchestrator.STATUS_ACTIVE)
        requests = loop.load_requests(iteration)
        report.add("%s: iteration-%d requests == active after iteration %d" % (v, iteration, iteration - 1),
                   sorted(r["sample_id"] for r in requests) == active and len(requests) == len(active),
                   {"requests": len(requests), "active": len(active)})

        def rebuilt_requests(iteration=iteration, requests=requests, active=active):
            rebuilt = {r["sample_id"]: r for r in loop.build_request_records(iteration, active)}
            for request in requests:
                mine = rebuilt[request["sample_id"]]
                if (any(mine.get(f) != request.get(f) for f in sr.REQUEST_FIELDS)
                        or request.get("run_id") != sl.SUCCESSOR
                        or request.get("built_from_iteration") != iteration - 1):
                    raise RecoveryRefused("request does not rebuild: " + request["sample_id"])
            return len(requests)

        report.guard("%s: iteration-%d requests rebuild byte-identically" % (v, iteration), rebuilt_requests)
        generations = loop.paths.iter_generations_path(iteration)
        responses = _rows(generations) if generations.exists() else []
        by_sample = Counter(r.get("sample_id") for r in responses)
        exhausted_here = set(r["sample_id"] for r in rows if r["iteration"] == iteration
                             and r.get("status") == orchestrator.STATUS_API_EXHAUSTED)
        report.add("%s: one terminal response per iteration-%d request" % (v, iteration),
                   sorted(by_sample) == sorted(r["sample_id"] for r in requests
                                               if r["sample_id"] not in exhausted_here)
                   and all(n == 1 for n in by_sample.values()), {"responses": len(responses)})
        report.guard("%s: iteration-%d submission intents == recorded outcomes (or at the bound)"
                     % (v, iteration), loop.verify_submission_ledger, iteration)
        ledger = loop.submission_ledger(iteration)
        intents = [r for r in ledger if r["kind"] == "intent"]
        refused = set(r["intent_id"] for r in ledger if r["kind"] == "refused_before_send")
        resolutions = [r for r in ledger if r["kind"] == "resolution"]
        rounds = loop.counted_rounds(iteration)
        report.add("%s: iteration-%d no resubmission beyond the native bound" % (v, iteration),
                   all(n <= loop.settings["request_retry_rounds"] for n in rounds.values()),
                   {"intents": len(intents), "refused_before_send": len(refused),
                    "resolutions": len(resolutions), "max_rounds": max(rounds.values()) if rounds else 0})
        decided[iteration] = _decisions(rows, iteration)
        entries = loop.load_assembly_entries(iteration) if requests else {}
        assembled = sorted(s for s, e in entries.items() if e.get("assembled"))
        requested = set(r["sample_id"] for r in requests)
        refusals = set(r.get("sample_id") for r in responses
                       if (r.get("status") or {}).get("error_type") in orchestrator.common.TERMINAL_ERROR_TYPES)
        unassembled_answers = set(s for s, e in entries.items() if not e.get("assembled"))
        rows_here = [r for r in rows if r["iteration"] == iteration]

        def bound_rows(iteration=iteration, rows_here=rows_here, requested=requested, refusals=refusals,
                       unassembled_answers=unassembled_answers, exhausted_here=exhausted_here):
            """Exactly one iteration-N row per requested sample, each with its
            native cause: a decision (assembled answer), repair_unusable (model
            refusal / reasoning budget / unassembled answer) or
            stopped_api_exhausted (no terminal answer within the bound)."""
            counted = Counter(r["sample_id"] for r in rows_here)
            problems = [s for s, n in counted.items() if n != 1 or s not in requested]
            for row in rows_here:
                status, sample = row.get("status"), row["sample_id"]
                if status == orchestrator.STATUS_UNUSABLE and sample not in (refusals | unassembled_answers):
                    problems.append("unusable without cause: " + sample)
                if status == orchestrator.STATUS_API_EXHAUSTED and sample in by_sample:
                    problems.append("exhausted with an answer: " + sample)
            missing = sorted(requested - set(counted))
            if problems or missing:
                raise RecoveryRefused("iteration-%d state rows are not bound to the requests: %s %s"
                                      % (iteration, problems[:5], missing[:5]))
            return OrderedDict(sorted(Counter(r.get("status") for r in rows_here).items()))

        if requests:
            report.guard("%s: one iteration-%d state row per request, with its native cause" % (v, iteration),
                         bound_rows)
        else:
            report.add("%s: no iteration-%d state row without a request" % (v, iteration), not rows_here, None)
        report.add("%s: iteration-%d decision per assembled response" % (v, iteration),
                   sorted(decided[iteration]) == assembled,
                   {"assembled": len(assembled), "decided": len(decided[iteration])})
        if assembled:
            report.guard("%s: iteration-%d decisions reproduce" % (v, iteration), reproduce_decisions,
                         loop, iteration, decided[iteration],
                         OrderedDict((s, prior[s]) for s in decided[iteration] if s in prior))
            report.add("%s: no internal stage missing at iteration %d" % (v, iteration),
                       loop.missing_internal_stages(iteration) == [], None)
            report.add("%s: no external tool pending at iteration %d" % (v, iteration),
                       loop.pending_external(iteration) == [], None)
        ok = sum(1 for r in responses if (r.get("status") or {}).get("success") is True)
        refusals = sum(1 for r in responses if (r.get("status") or {}).get("error_type") == "ModelRefusal")
        failed_archive = generations.with_name("failed_responses.jsonl")
        archived = sum(len(e.get("records") or []) for e in _rows(failed_archive)) \
            if failed_archive.exists() else 0
        totals.update({
            "iteration%d_requests" % iteration: len(requests),
            "iteration%d_responses" % iteration: len(responses),
            "iteration%d_successful_responses" % iteration: ok,
            "iteration%d_model_refusals" % iteration: refusals,
            "iteration%d_archived_failed_attempts" % iteration: archived,
            "iteration%d_submission_intents" % iteration: len(intents) - len(refused),
            "iteration%d_refused_before_send" % iteration: len(refused),
            "iteration%d_ambiguity_resolutions" % iteration: len(resolutions),
            "iteration%d_decisions" % iteration: len(decided[iteration]),
            "iteration%d_api_exhausted" % iteration: len(exhausted_here),
            "iteration%d_ambiguous_at_bound" % iteration: len([r for r in at_bound
                                                                if r["iteration"] == iteration])})
    supplements = Path(loop.paths.intermediate_root) / sl.SUCCESSOR / loop.model_id / "supplements"
    report.add("%s: no supplement ledger (native analyses only)" % v, not supplements.exists(), None)
    terminal = Counter(r.get("status") for r in merged.values())
    counts["new"].update(totals)
    counts["new"].update({"iteration0_decisions": len(decided[0]), "unusable_rows": len(
        [r for r in rows if r.get("status") == orchestrator.STATUS_UNUSABLE])})
    counts["terminal"][v] = OrderedDict(sorted(terminal.items()))
    return True


def stage_stamps(config, model, report):
    from thesis.evaluation import manifest_fragments as mf
    from thesis.evaluation import run_manifest

    intermediate = Path(config["outputs"]["intermediate_dir"])
    tampered = mf.verify_fragment_integrity(intermediate, sl.SUCCESSOR)
    report.add("successor run provenance intact", not tampered, tampered or None)
    manifest = run_manifest.load_manifest(config, sl.SUCCESSOR) or {}
    authorization = (manifest.get("authorization") or {}).get("authorization_sha256")
    contract = manifest.get("contract_sha256")
    stamps = OrderedDict()
    fragments = intermediate / sl.SUCCESSOR / "run_manifest.fragments"
    for path in sorted(fragments.glob("runtime.stage.*.json")):
        content = json.loads(path.read_text(encoding="utf-8")).get("content") or {}
        stamps[content.get("stage")] = (content.get("match") is True and not content.get("drift_fields")
                                        and content.get("authorization_sha256") == authorization
                                        and content.get("contract_sha256") == contract)
    report.add("stage runtime stamps match the successor T0", bool(stamps) and all(stamps.values()),
               dict(stamps))
    invocations = [name for name in sorted(p.name for p in fragments.glob("invocation.*.json"))
                   if "@%s@" % model in name]
    report.add("successor invocations registered for the model", bool(invocations), invocations)


def endpoints(config, lineage, model, report):
    """The successor T0 bound the origin's provider endpoint (hashes)."""
    from thesis.evaluation import run_manifest
    from thesis.recovery_successor_004 import readiness as successor_readiness

    manifest = run_manifest.load_manifest(config, sl.SUCCESSOR) or {}
    identities = (manifest.get("runtime_evidence") or {}).get("provider_endpoint_identities") or {}
    expected = successor_readiness.predecessor_endpoints(lineage)[model]
    # None is a recorded identity too (SDK-fixed endpoint); a missing key is not
    report.add("provider endpoint equals the origin authorization",
               model in identities and identities[model] == expected,
               {"successor_t0": str(identities.get(model, "MISSING"))[:12],
                "origin_t0": str(expected)[:12]})


def immutability(config, lineage, report, deep):
    def protected_runs():
        lineage.verify(config, deep=deep)
        return {"recovery_001_files": len(lineage.snapshot.files),
                "snapshot_sha256": lineage.document["predecessor_snapshot"]["snapshot_sha256"],
                "siblings": lineage.verify_siblings()}

    report.guard("recovery_001 and sibling successor bytes, membership and bindings unchanged",
                 protected_runs)
    report.guard("no repair evidence of a 004 model outside 004", lineage.verify_origin_absence)
    if deep:
        def protected():
            from thesis.evaluation import recovery_protected_history

            binding = lineage.document["predecessor"]["definitions"]["protected_history.json"]
            document = json.loads((lineage.root / binding["path"]).read_text(encoding="utf-8"))
            return recovery_protected_history.verify(lineage.root, document)

        report.guard("protected pilot/full_ext history unchanged", protected)


def population(lineage, report):
    from thesis.evaluation import composite_study

    def cells():
        document = json.loads((lineage.root / "thesis/evaluation/full_001_composite.json")
                              .read_text(encoding="utf-8"))
        rows = composite_study.read_base_cells(document, lineage.root)
        if len(rows) != 1980:
            raise RecoveryRefused("base population is %d cells, not 1980" % len(rows))
        base = lineage.root / "thesis/results/intermediate" / sl.SUCCESSOR
        forbidden = [p.name for p in base.glob("*/*.jsonl")] if base.exists() else []
        raw = lineage.root / "thesis/results/raw" / sl.SUCCESSOR
        if forbidden or raw.exists():
            raise RecoveryRefused("the successor carries base-population files: %s" % forbidden)
        return {"base_cells": len(rows), "successor_base_cells": 0}

    report.guard("1,980-cell methodical population unchanged", cells)


def _coverage(config, samples, static, correctness, dynamic):
    from thesis.evaluation.tool_config import resolve_tool_settings
    from thesis.repair import orchestrator

    settings = resolve_tool_settings(config, "static_analysis")
    missing = Counter()
    for sample in samples:
        tools = (static.get(sample) or {}).get("tools") or {}
        model = orchestrator.execution_model_of(sample)
        for name, setting in settings.items():
            if setting.enabled and setting.applies_to(model) and name not in tools:
                missing[name] += 1
    return OrderedDict([
        ("samples", len(samples)),
        ("static_entries_missing", OrderedDict(sorted(missing.items()))),
        ("correctness_missing", len([s for s in samples if s not in correctness])),
        ("dynamic_missing", len([s for s in samples if s not in dynamic])),
        ("enhanced_records", 0),
    ])


def open_work(config, lineage, loops, model):
    """Phase-2 coverage of EVERY candidate target of the model's trajectories
    (the parent base candidates + the six successor-owned iteration runs).
    Reported as OPEN work - never as PASS - because backfill and held-out
    (enhanced) tests are outside the successor repair scope."""
    targets = OrderedDict()
    any_loop = next(iter(loops.values()))
    targets["%s (iteration-0 candidates)" % sl.PARENT] = OrderedDict([
        ("owner", sl.PARENT), ("samples", len(any_loop.iteration_samples(0))),
        ("enhanced_records", 0), ("open", "held-out enhanced tests")])
    for variant in sl.VARIANTS:
        loop = loops[variant]
        for iteration in sl.PROVIDER_ITERATIONS:
            run = loop.paths.iter_run_id(iteration)
            if not loop.paths.assembly_path(iteration).exists():
                continue
            samples = [s for s, e in loop.load_assembly_entries(iteration).items() if e.get("assembled")]
            entry = _coverage(config, samples, loop.load_stage_records(iteration, "static_analysis"),
                              loop.load_stage_records(iteration, "correctness_tests"),
                              loop.load_stage_records(iteration, "dynamic_analysis"))
            entry["owner"] = sl.SUCCESSOR
            targets[run] = entry
    return targets


def verify_model(config, config_path, model, authority=None, root=None, deep=True):
    from thesis.recovery_successor_004 import run as run_successor

    report = Report(model)
    counts = OrderedDict([("reused", Counter()), ("new", Counter()), ("terminal", OrderedDict())])
    lineage, parent = run_successor.load_lineages(Path(root) if root else ROOT)
    if authority is not None:
        report.guard("successor contract and authorization", authority.check)
    else:
        report.add("successor contract and authorization", False, "no authority supplied")
    immutability(config, lineage, report, deep)
    if deep:
        population(lineage, report)
    loops = _loops(config, config_path, model, lineage, parent, authority or run_successor.NullAuthority())
    for variant in sl.VARIANTS:
        report.guard("%s: fresh" % variant, fresh_loop, loops[variant], report, counts)
    stage_stamps(config, model, report)
    report.guard("provider endpoint binding", endpoints, config, lineage, model, report)
    variants = OrderedDict()
    for variant in sl.VARIANTS:
        failing = [c for c in report.checks if c["check"].startswith(variant + ":")
                   and c["status"] != "PASS"]
        variants[variant] = "done" if not failing else "STOP"
    return OrderedDict([
        ("schema_version", SCHEMA), ("scope", SCOPE), ("run_id", sl.SUCCESSOR),
        ("model_id", model), ("status", report.status), ("variants", variants),
        ("model_complete", False),
        ("model_complete_reason", "phase-2 backfill and held-out enhanced tests are open work"),
        ("predecessor_repair_adopted", False),
        ("repair_origin", "FRESH_FROM_PARENT_ITERATION_0"),
        ("counts", OrderedDict([("reused", OrderedDict(sorted(counts["reused"].items()))),
                                ("new", OrderedDict(sorted(counts["new"].items()))),
                                ("terminal", counts["terminal"])])),
        ("open_work", _safe_open_work(config, lineage, loops, model)),
        ("checks", report.checks),
    ])


def _safe_open_work(config, lineage, loops, model):
    try:
        return open_work(config, lineage, loops, model)
    except Exception as error:  # noqa: BLE001 - reported, never hidden
        return {"error": "%s: %s" % (type(error).__name__, error)}


def report_path(config, model):
    return (Path(config["outputs"]["intermediate_dir"]) / sl.SUCCESSOR / "verification"
            / ("%s.successor_verification.json" % model))


def write_report(config, result):
    """Persist one model verification (atomic; a later verification of the
    same model replaces it and is itself recorded)."""
    from thesis.evaluation import atomic_io
    from thesis.generation.common import utc_now_iso

    document = OrderedDict(result)
    document["written_at_utc"] = utc_now_iso()
    path = report_path(config, result["model_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_io.atomic_write_json(path, document)
    return path


def summary(result):
    failing = [c["check"] for c in result["checks"] if c["status"] != "PASS"]
    return OrderedDict([("status", result["status"]), ("scope", result["scope"]),
                        ("variants", result["variants"]), ("model_complete", result["model_complete"]),
                        ("counts", result["counts"]), ("failing_checks", failing)])
