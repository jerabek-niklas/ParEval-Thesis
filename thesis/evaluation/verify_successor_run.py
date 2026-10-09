"""Per-model verification of the successor run (scope: repair trajectories).

Scope string SUCCESSOR_MODEL_REPAIR_SCOPE_NOT_FULL_RECOVERY_ACCEPTANCE: a PASS
here proves, for ONE model, that all three feedback variants are terminal and
that every successor trajectory continues its predecessor trajectory
exactly (re-derived stop decisions, re-built requests, 1:1 provider outcomes,
native coverage of every analysis the loop decisions depend on), under the
frozen successor contract/authorization, with the predecessor and every
protected historical byte unchanged and the 1,980-cell base population intact.

It does NOT claim phase-2 backfill or held-out (enhanced) acceptance; those
obligations are enumerated as OPEN work, never as PASS.

Read-only. Python 3.8 compatible.
"""
from __future__ import annotations

import json
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.evaluation import successor_handoff as sh
from thesis.evaluation import successor_lineage as sl
from thesis.evaluation import successor_writer as sw
from thesis.evaluation.condition_hashing import utf8_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused

SCHEMA = "successor_model_verification.v1"
SCOPE = "SUCCESSOR_MODEL_REPAIR_SCOPE_NOT_FULL_RECOVERY_ACCEPTANCE"
ROOT = Path(__file__).resolve().parents[2]
STATE_FIELDS = ("status", "stop_reason", "counts", "test_verdict", "low_confidence_keys",
                "analysis_gaps")


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


def _loop(config, config_path, model, variant, lineage, parent, authority):
    from thesis.repair import run_successor

    for loop in run_successor.build_loops(config, config_path, lineage, parent, authority,
                                          models=[model]):
        if loop.variant == variant:
            return loop
    raise RecoveryRefused("no successor loop for %s/%s" % (model, variant))


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


def continued_loop(loop, report, counts):
    """Trajectory integrity of one CONTINUE loop (static/combined)."""
    from thesis.repair import orchestrator

    wave = loop.load_wave_state()
    report.add("%s: wave done" % loop.variant, wave.get("phase") == "done"
               and not wave.get("seeded_from_predecessor"), dict(wave))
    predecessor = loop.predecessor_states()
    successor = loop.successor_state_rows()
    merged = loop.sample_states()
    parent_samples = sorted(loop.load_assembly_entries(0))
    report.add("%s: every parent cell terminal" % loop.variant,
               sorted(merged) == parent_samples and all(
                   r.get("status") in orchestrator.TERMINAL_STATUSES for r in merged.values()),
               {"samples": len(merged), "parent_cells": len(parent_samples)})
    handoff_active = sorted(s for s, r in predecessor.items() if r.get("status") == "active")
    decided1 = OrderedDict((r["sample_id"], r) for r in successor if r["iteration"] == 1
                           and r.get("status") != orchestrator.STATUS_UNUSABLE)
    unusable = [r for r in successor if r.get("status") == orchestrator.STATUS_UNUSABLE]
    report.add("%s: one iteration-1 decision per predecessor-active sample" % loop.variant,
               sorted(decided1) == handoff_active and len(decided1) == len(
                   [r for r in successor if r["iteration"] == 1 and r.get("status") != orchestrator.STATUS_UNUSABLE]),
               {"active_at_handoff": len(handoff_active), "decided": len(decided1)})
    report.guard("%s: iteration-1 decisions reproduce" % loop.variant, reproduce_decisions,
                 loop, 1, decided1, predecessor)
    active_after_1 = sorted(s for s, r in decided1.items() if r.get("status") == "active")
    requests = loop.load_requests(2)
    report.add("%s: iteration-2 requests == active after iteration 1" % loop.variant,
               sorted(r["sample_id"] for r in requests) == active_after_1
               and len(requests) == len(active_after_1), {"requests": len(requests)})

    def rebuilt_requests():
        rebuilt = {r["sample_id"]: r for r in loop.build_request_records(2, active_after_1)}
        for request in requests:
            mine = rebuilt[request["sample_id"]]
            if (mine["request"] != request["request"] or request.get("run_id") != sl.SUCCESSOR
                    or request.get("built_from_iteration") != 1 or request.get("iteration") != 2):
                raise RecoveryRefused("request does not rebuild: " + request["sample_id"])
        return len(requests)

    report.guard("%s: iteration-2 requests rebuild byte-identically" % loop.variant, rebuilt_requests)
    generations = loop.paths.iter_generations_path(2)
    responses = _rows(generations) if generations.exists() else []
    by_sample = Counter(r.get("sample_id") for r in responses)
    # provider exhaustion (stopped_api_exhausted) is an INFRASTRUCTURE end:
    # such a request legitimately has no terminal response, but the variant
    # is not a measured PASS - it stays open work (never a model failure)
    exhausted = sorted(s for s, r in merged.items()
                       if r.get("status") == orchestrator.STATUS_API_EXHAUSTED)
    report.add("%s: one terminal response per request" % loop.variant,
               sorted(by_sample) == sorted(r["sample_id"] for r in requests
                                           if r["sample_id"] not in exhausted)
               and all(v == 1 for v in by_sample.values()), {"responses": len(responses)})
    report.add("%s: no request ended by provider exhaustion" % loop.variant, not exhausted,
               {"stopped_api_exhausted": exhausted,
                "open_work": "provider unavailable; infrastructure condition, not a model "
                             "failure; the native bound forbids another automatic request"}
               if exhausted else None)
    report.guard("%s: submission intents == recorded outcomes" % loop.variant,
                 loop.verify_submission_ledger, 2)
    intents = loop.submission_intents()
    refused = set(r["intent_id"] for r in loop.submission_ledger() if r["kind"] == "refused_before_send")
    # the loop's own (native) round rule: an intent refused before sending is no round
    rounds = loop.counted_rounds()
    report.add("%s: no resubmission beyond the native bound" % loop.variant,
               all(n <= loop.settings["request_retry_rounds"] for n in rounds.values()),
               {"intents": len(intents), "refused_before_send": len(refused),
                "max_rounds": max(rounds.values()) if rounds else 0})
    # analysis decisions only: unusable answers and provider exhaustion are
    # bookkeeping rows of the response phase, not stop decisions
    decided2 = OrderedDict((r["sample_id"], r) for r in successor if r["iteration"] == 2
                           and r.get("status") not in (orchestrator.STATUS_UNUSABLE,
                                                       orchestrator.STATUS_API_EXHAUSTED))
    assembled2 = sorted(s for s, e in loop.load_assembly_entries(2).items() if e.get("assembled"))
    report.add("%s: iteration-2 decision per assembled response" % loop.variant,
               sorted(decided2) == assembled2, {"assembled": len(assembled2), "decided": len(decided2)})
    prior2 = OrderedDict((s, decided1[s]) for s in decided2 if s in decided1)
    if assembled2:
        report.guard("%s: iteration-2 decisions reproduce" % loop.variant, reproduce_decisions,
                     loop, 2, decided2, prior2)
        report.add("%s: no internal stage missing at iteration 2" % loop.variant,
                   loop.missing_internal_stages(2) == [], None)
    report.add("%s: no external tool pending at iterations 1/2" % loop.variant,
               loop.pending_external(1) == [] and (not assembled2 or loop.pending_external(2) == []),
               None)
    supplement_rows = sum(len(loop.supplement_rows(t)) for t in loop.settings["external_tools"])
    counts["reused"].update({"predecessor_iteration1_requests": len(handoff_active),
                             "predecessor_iteration1_responses": len(handoff_active),
                             "predecessor_iteration1_static_records": len(loop.load_stage_records(1, "static_analysis"))})
    counts["new"].update({"llov_supplement_entries": supplement_rows,
                          "iteration2_requests": len(requests), "iteration2_responses": len(responses),
                          "iteration2_submission_intents": len(intents) - len(refused),
                          "iteration2_refused_before_send": len(refused),
                          "iteration1_decisions": len(decided1), "iteration2_decisions": len(decided2),
                          "unusable_rows": len(unusable), "api_exhausted_samples": len(exhausted)})
    return True


def adopted_loop(lineage, config, model, variant, report, counts):
    from thesis.repair import orchestrator

    facts = lineage.handoff(model, variant)
    rows = lineage.view.event_ledger(model, variant)
    latest = sh.latest_by_sample(rows)
    report.add("%s: adopted predecessor loop terminal" % variant,
               facts["mode"] == "ADOPT_DONE" and facts["wave_phase"] == "done" and all(
                   r.get("status") in orchestrator.TERMINAL_STATUSES for r in latest.values()),
               {"samples": len(latest)})
    successor_dir = lineage.root / ("thesis/results/intermediate/%s/%s/repair/%s"
                                    % (sl.SUCCESSOR, model, variant))
    report.add("%s: no successor writes for an adopted loop" % variant, not successor_dir.exists(), None)
    for iteration, exchange in facts["iterations"].items():
        counts["reused"]["predecessor_%s_iter%s_requests" % (variant, iteration)] = exchange["requests"]
        counts["reused"]["predecessor_%s_iter%s_responses" % (variant, iteration)] = exchange["responses"]


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
    """The successor T0 bound the predecessor's provider endpoint (hashes)."""
    from thesis.evaluation import run_manifest
    from thesis.evaluation import successor_readiness

    manifest = run_manifest.load_manifest(config, sl.SUCCESSOR) or {}
    bound = ((manifest.get("runtime_evidence") or {}).get("provider_endpoint_identities") or {}).get(model)
    expected = successor_readiness.predecessor_endpoints(lineage).get(model)
    report.add("provider endpoint equals the predecessor authorization", bool(expected) and bound == expected,
               {"successor_t0": str(bound)[:12], "predecessor_t0": str(expected)[:12]})


def immutability(config, lineage, report, deep):
    def predecessor():
        lineage.verify(config, deep=deep)
        return {"files": len(lineage.snapshot.files),
                "snapshot_sha256": lineage.document["predecessor_snapshot"]["snapshot_sha256"]}

    report.guard("predecessor bytes, membership and bindings unchanged", predecessor)
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
    (4 predecessor-owned + 2 successor-owned iteration runs + the parent base
    candidates). Reported as OPEN work - never as PASS - because backfill and
    held-out (enhanced) tests are outside the successor repair scope."""
    view = lineage.view
    targets = OrderedDict()
    targets["%s (iteration-0 candidates)" % sl.PARENT] = OrderedDict([
        ("owner", sl.PARENT),
        ("samples", lineage.handoff(model, sl.CONTINUE_VARIANTS[0])["state_samples"]),
        ("enhanced_records", 0),
        ("open", "held-out enhanced tests")])
    for variant in sl.VARIANTS:
        loop = loops.get(variant)
        for iteration in (1, 2):
            if loop is not None and iteration == 2:
                run = loop.paths.iter_run_id(2)
                samples = [s for s, e in loop.load_assembly_entries(2).items() if e.get("assembled")]
                static = loop.load_stage_records(2, "static_analysis")
                correctness = loop.load_stage_records(2, "correctness_tests")
                dynamic = loop.load_stage_records(2, "dynamic_analysis")
                owner = sl.SUCCESSOR
            else:
                run = sh.predecessor_iteration_run(variant, iteration)
                base = sh.iteration_dir(run, model)
                if not view.has(base + "/assembly.jsonl"):
                    continue
                assembly = view.unique_rows(base + "/assembly.jsonl", run, model)
                samples = [s for s, e in assembly.items() if e.get("assembled")]
                static = (loop.load_stage_records(1, "static_analysis") if loop is not None
                          else view.unique_rows(base + "/static_analysis.jsonl", run, model))
                correctness = (view.unique_rows(base + "/correctness.jsonl", run, model)
                               if view.has(base + "/correctness.jsonl") else {})
                dynamic = (view.unique_rows(base + "/dynamic_analysis.jsonl", run, model)
                           if view.has(base + "/dynamic_analysis.jsonl") else {})
                owner = sl.PREDECESSOR
            entry = _coverage(config, samples, static, correctness, dynamic)
            entry["owner"] = owner
            entry["supplement_owner_if_backfilled"] = sl.SUCCESSOR
            targets[run] = entry
    return targets


def verify_model(config, config_path, model, authority=None, root=None, deep=True):
    from thesis.repair import run_successor

    report = Report(model)
    counts = OrderedDict([("reused", Counter()), ("new", Counter())])
    lineage, parent = run_successor.load_lineages(Path(root) if root else ROOT)
    if authority is not None:
        report.guard("successor contract and authorization", authority.check)
    else:
        report.add("successor contract and authorization", False, "no authority supplied")
    immutability(config, lineage, report, deep)
    if deep:
        population(lineage, report)
    loops = OrderedDict()
    for variant in sl.VARIANTS:
        if variant in sl.ADOPT_DONE_VARIANTS:
            report.guard("%s: adopted" % variant, adopted_loop, lineage, config, model, variant,
                         report, counts)
        else:
            loop = _loop(config, config_path, model, variant, lineage, parent, authority)
            loops[variant] = loop
            report.guard("%s: continued" % variant, continued_loop, loop, report, counts)
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
        ("predecessor_repair_adopted", True),
        ("counts", OrderedDict((k, OrderedDict(sorted(v.items()))) for k, v in counts.items())),
        ("open_work", _safe_open_work(config, lineage, loops, model)),
        ("checks", report.checks),
    ])


def _safe_open_work(config, lineage, loops, model):
    try:
        return open_work(config, lineage, loops, model)
    except Exception as error:  # noqa: BLE001 - reported, never hidden
        return {"error": "%s: %s" % (type(error).__name__, error)}


def summary(result):
    failing = [c["check"] for c in result["checks"] if c["status"] != "PASS"]
    return OrderedDict([("status", result["status"]), ("scope", result["scope"]),
                        ("variants", result["variants"]), ("model_complete", result["model_complete"]),
                        ("counts", result["counts"]), ("failing_checks", failing)])
