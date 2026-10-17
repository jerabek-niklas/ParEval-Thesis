"""Section `disclosures`: the computed disclosure register of the study and
its markdown rendering.

Every methodological limitation the thesis text must disclose is an item
with a fixed id. Its evidence is COMPUTED from the artifacts of this
repository at closure time - never typed from memory - and every evidence
entry names the artifact or computation it comes from (`source`). Item
statuses: ARTIFACT_BOUND (an existing artifact carries the disclosure
text), COMPUTED (the numbers are computed here), AUTHOR_TEXT_REQUIRED (the
thesis text must state it; the closure provides the facts). An item whose
inputs are missing is INPUT_UNAVAILABLE, one whose builder failed is
BUILD_FAILED; both fail the section - a register with holes is no register.

Composite-derived counts come from ctx.cache["composite_cells"] /
["composite_document"] (study section), the census from
ctx.cache["census"] / ["census_summary"], the phase-2 incidents from
ctx.cache["phase2_reports"]. The Infer runtime scan streams every static
record of the study (historical static_analysis.jsonl of the base runs and
iteration directories, the 002/003/phase-2 static supplement ledgers).

    python3 -B -m thesis.study_closure.disclosures --print [--markdown] [--compute-composite]

Read-only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import pilot_freeze as pf  # noqa: E402
from thesis.evaluation.recovery_lineage import checked_path  # noqa: E402
from thesis.recovery_successor_005 import composite as pc  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.recovery_successor_005 import targets as pt  # noqa: E402
from thesis.study_closure import core  # noqa: E402

SECTION = "disclosures"
EXAMPLES = 10
ARTIFACT_BOUND = "ARTIFACT_BOUND"
COMPUTED = "COMPUTED"
AUTHOR_TEXT_REQUIRED = "AUTHOR_TEXT_REQUIRED"
INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
BUILD_FAILED = "BUILD_FAILED"
FINAL_STATUSES = (ARTIFACT_BOUND, COMPUTED, AUTHOR_TEXT_REQUIRED)
KINDS = ("count", "number", "value")
# reporting threshold of the Infer runtime scan (one hour): a reporting
# convention of the register, not a measurement
OUTLIER_SECONDS = 3600
TOP_ENTRIES = 5
REASONING_KEYS = ("reasoning_effort", "thinking_level", "thinking", "effort", "enable_thinking",
                  "thinking_budget")
GENERATION_KEYS = ("temperature", "max_output_tokens", "top_p", "timeout_seconds", "retry_attempts",
                   "api_mode")
# assembly cleaning flags whose truthy value is an intervention on the
# generated text (keys of assembly.jsonl `cleaning`)
CLEANING_FLAGS = ("used_fence", "dropped_leading_lines", "dropped_trailing_lines",
                  "signature_matched_patched", "dropped_duplicated_prompt_lines",
                  "kept_pre_signature_lines", "relocated_includes", "auto_closed", "signature_suspect")
CLEANING_ANOMALIES = ("braces_balanced", "signature_found_in_output")  # false = anomaly
ASSEMBLY_FILE = "assembly.jsonl"
METHODOLOGY_FREEZE_REL = "thesis/evaluation/pilot_002_methodology_freeze.json"
TECHNICAL_PROVENANCE_REL = "thesis/evaluation/technical_provenance_cleanup.json"
ENHANCED_POLICY_REL = "thesis/enhanced_tests/enhanced_policy.json"
ENHANCED_RUNNER_REL = "thesis/evaluation/run_enhanced_tests.py"
LINEAGE_MODULE_REL = "thesis/recovery_successor_005/lineage.py"
TOOL_VALIDATION_RELS = ("thesis/tool_validation/results/metrics.csv",
                        "thesis/tool_validation/results/summary.md",
                        "thesis/tool_validation/results/metrics_by_language.csv")
STAGE_HISTORY_REL = core.PHASE2_RESULTS_REL + "/phase2_stage_invocations.jsonl"
PHASE2_LEDGER_CHECK = "full_ext:phase2_ledgers_bound_to_targets"
PHASE2_PROVENANCE_SUFFIX = ":phase2_provenance"
CACHE_KEYS = ("composite_cells", "composite_document", "census", "census_summary", "phase2_reports")

# id -> (title, requirement, applies_to); the order is the register order
ITEMS = OrderedDict([
    ("policy_mandatory_sources", (
        "Mandatory disclosure sources of the pilot publication policy",
        "Every disclosure the pilot_002 publication policy declares as mandatory is carried by its "
        "artifact and must accompany any published pilot result.", "pilot")),
    ("pilot_label", (
        "Pilot label",
        "Every pilot_002 result is presented under the pilot label and never as the full "
        "60-benchmark study.", "pilot")),
    ("max_two_repair_iterations", (
        "At most two repair iterations",
        "Repair loops stop after at most max_iterations iterations; stopped_budget samples are "
        "unresolved by construction, not by evidence.", "both")),
    ("reasoning_policy_differences", (
        "Reasoning settings differ between models",
        "The models run with provider-specific reasoning settings (effort, thinking levels, "
        "budgets) that are not equalised; comparisons across models carry this difference.", "both")),
    ("cleaning_and_pipeline_interventions", (
        "Cleaning and pipeline interventions",
        "Generated text passed a deterministic cleaning/assembly condition and the technical "
        "provenance cleanup wave before measurement; the interventions are counted, not hidden.",
        "both")),
    ("baseline_incompatibilities", (
        "Baseline-incompatible enhanced tests",
        "Enhanced test pairs whose serial oracle is incompatible with the input are "
        "baseline_incompatible and never counted against a model.", "both")),
    ("static_analysis_gaps", (
        "Static analysis gaps",
        "Static tool entries in a gap state (PARTIAL, NOT_ANALYZED, TOOL_ERROR, TIMEOUT) carry no "
        "trustworthy verdict and are reported per tool and block.", "both")),
    ("dynamic_analysis_gaps", (
        "Dynamic analysis gaps",
        "Dynamic tool entries that did not run or ended in a gap state are reported per tool and "
        "block.", "both")),
    ("tool_timeouts_and_errors", (
        "Tool timeouts, tool errors and non-pass verdicts",
        "Timeouts and tool errors of the analysis tools and the non-pass correctness verdicts are "
        "measurement limits, not model findings.", "both")),
    ("single_tool_finding_validity", (
        "Validity of single-tool findings",
        "Findings of a single low-precision tool are fed back as low-confidence hints only; the "
        "tool validation artifacts bound the precision.", "both")),
    ("numerical_tolerance", (
        "Numerical tolerance of the enhanced oracle",
        "Enhanced pairs whose serial oracle is numerically unstable under the fast-math probe are "
        "numerically_unstable and never counted against a model; the enhanced policy fixes the "
        "input domains.", "both")),
    ("frozen_thread_rank_configuration", (
        "Frozen thread/rank and timeout configuration",
        "Parallel samples run at the frozen thread/rank grid and timeouts of the methodology "
        "freeze; performance is not measured.", "both")),
    ("infer_runtime_outlier", (
        "Infer runtime outlier",
        "One Infer run exceeded the one-hour reporting threshold by far; the recorded duration is "
        "wall-clock time and the tool completed.", "both")),
    ("one_generation_per_base_cell", (
        "One generation per base cell",
        "Every base cell holds exactly one generated sample per prompt (num_samples_per_prompt = "
        "1); there is no sampling distribution per prompt.", "both")),
    ("excluded_aborted_parent_repair", (
        "Excluded aborted parent repair",
        "The aborted repair iteration of the parent run is excluded from the study: it is never a "
        "phase-2 target and no study candidate derives from it.", "full_ext")),
    ("phase2_operational_incidents", (
        "Phase-2 operational incidents",
        "Interrupted stage invocations, archived torn ledger tails and repeated build groups of "
        "the phase-2 run are operational incidents without effect on the measurements.", "full_ext")),
    ("verification_scopes", (
        "Verification scopes",
        "Every verification artifact of the study has its own scope; none of them is a "
        "publication decision.", "both")),
])
ITEM_IDS = tuple(ITEMS.keys())
# what each verification scope proves and does not prove (definitions)
SCOPE_NOTES = OrderedDict([
    ("post_run_verification.v1", ("the pilot run's contract, runtime, config, stages and repair "
                                  "scope after the run",
                                  "the result acceptance of the author")),
    ("parent_base_evidence_report.v1", ("the full_ext_001 base cells (iteration 0) under the "
                                        "recovery_001 lineage", "the aborted parent repair, any "
                                        "candidate")),
    ("successor_model_verification.v1", ("the successor's repair loops, iteration bindings and "
                                         "adopted loops per model", "the then-open phase-2 backfill "
                                         "and enhanced tests")),
    ("phase2_model_verification.v1", ("every pilot and full_ext measurement is present and bound "
                                      "to the lineage", "the quality of the measurements")),
    (core.SCHEMA, ("the seven runs, the population, the composite and the gate state read-only",
                   "the author's result acceptance")),
])
# the schema every persisted report of a verification kind must carry (a
# foreign document in a report directory is refused, never described)
POST_RUN_SCHEMA = "post_run_verification.v1"
PARENT_SCHEMA = "parent_base_evidence_report.v1"
SUCCESSOR_SCHEMA = "successor_model_verification.v1"
PHASE2_SCHEMA = "phase2_model_verification.v1"
# the pilot post-run report carries a verifier_version instead of a scope
SCOPELESS_SCHEMAS = (POST_RUN_SCHEMA,)


class Unavailable(core.ClosureRefused):
    """A producer section's result is missing from ctx.cache."""


# -- evidence helpers --------------------------------------------------------------------------

def ev(value, source, kind="value"):
    """One evidence entry: the value, the artifact/computation it comes
    from, and its kind (count: int leaves; number: int/float; value: any)."""
    if kind not in KINDS:
        raise core.ClosureRefused("unknown evidence kind " + str(kind))
    if not isinstance(source, str) or not source.strip():
        raise core.ClosureRefused("an evidence entry needs a source")
    return OrderedDict([("value", value), ("source", source), ("kind", kind)])


def count(value, source):
    return ev(value, source, "count")


def number(value, source):
    return ev(value, source, "number")


def source(root, relative):
    """A repo-relative artifact with its raw sha256 (missing -> raises)."""
    return OrderedDict([("relative", relative), ("raw_sha256", core.raw_sha256(root, relative))])


def composite_source(root, document):
    """The persisted composite when it exists (it must be THE document the
    study section reconstructed), else the in-memory document identity."""
    relative = core.COMPOSITE_REL
    path = checked_path(Path(root).resolve(), relative)
    if path.is_file():
        persisted = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=OrderedDict)
        if persisted.get("composite_sha256") != document.get("composite_sha256"):
            raise core.ClosureRefused("persisted composite %s differs from the reconstructed %s"
                                      % (persisted.get("composite_sha256"), document.get("composite_sha256")))
        return OrderedDict([("relative", relative), ("raw_sha256", core.raw_sha256(root, relative)),
                            ("composite_sha256", document.get("composite_sha256")), ("persisted", True)])
    return OrderedDict([("relative", relative), ("raw_sha256", None),
                        ("composite_sha256", document.get("composite_sha256")), ("persisted", False)])


def _item(item_id, status, sources, evidence, narrative=None):
    title, requirement, applies_to = ITEMS[item_id]
    return OrderedDict([("id", item_id), ("title", title), ("requirement", requirement),
                        ("applies_to", applies_to), ("status", status), ("sources", list(sources)),
                        ("evidence", evidence), ("narrative", narrative)])


def _placeholder(item_id, status, message):
    return _item(item_id, status, [], OrderedDict([("problem", ev(message, "thesis.study_closure.disclosures"))]))


def _need(inputs, key):
    if inputs.get(key) is None:
        raise Unavailable("input unavailable: " + key)
    return inputs[key]


def _flag(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _config_rel(ctx):
    path = Path(ctx.config_path)
    try:
        return path.resolve().relative_to(Path(ctx.root).resolve()).as_posix()
    except ValueError:
        return pl.CONFIG_REL


def _same(a, b):
    """Structural equality of two JSON-able values regardless of key order
    and of int/float spelling (0 == 0.0), via plain dicts."""
    return json.loads(json.dumps(a, default=str)) == json.loads(json.dumps(b, default=str))


def _counter_table(nested):
    """Counter leaves -> key-sorted OrderedDicts (pc.counts), recursively."""
    if isinstance(nested, Counter):
        return pc.counts(nested)
    if isinstance(nested, dict):
        return OrderedDict((key, _counter_table(value)) for key, value in nested.items())
    return nested


# -- pure computations over composite cells ------------------------------------------------------

def iteration_counts(cells):
    """block -> {iter0 (base), iter1, ...} cell counts and the observed max."""
    table = OrderedDict((block, Counter()) for block in pc.BLOCKS)
    observed = 0
    for cell in cells:
        table[cell["block"]]["iter%d" % cell["iteration"]] += 1
        observed = max(observed, int(cell["iteration"]))
    return OrderedDict([("per_block", _counter_table(table)), ("observed_max_iteration", observed)])


def static_gap_counts(cells):
    """block -> tool -> state -> cells; plus the cells without a static record."""
    table = OrderedDict((block, OrderedDict()) for block in pc.BLOCKS)
    without = Counter()
    for cell in cells:
        static = cell.get("static")
        if static is None:
            without[cell["block"]] += 1
            continue
        for tool, state in (static.get("tools") or {}).items():
            table[cell["block"]].setdefault(tool, Counter())[str(state)] += 1
    return OrderedDict([("states", _counter_table(table)),
                        ("cells_without_static", OrderedDict((b, without.get(b, 0)) for b in pc.BLOCKS))])


def dynamic_gap_counts(cells):
    """block -> tool -> {analysis_state: {...}, ran: {true/false/null}}."""
    table = OrderedDict((block, OrderedDict()) for block in pc.BLOCKS)
    without = Counter()
    for cell in cells:
        dynamic = cell.get("dynamic")
        if dynamic is None:
            without[cell["block"]] += 1
            continue
        for tool, entry in (dynamic.get("tools") or {}).items():
            bucket = table[cell["block"]].setdefault(
                tool, OrderedDict([("analysis_state", Counter()), ("ran", Counter())]))
            bucket["analysis_state"][str((entry or {}).get("analysis_state"))] += 1
            bucket["ran"][_flag((entry or {}).get("ran"))] += 1
    return OrderedDict([("states", _counter_table(table)),
                        ("cells_without_dynamic", OrderedDict((b, without.get(b, 0)) for b in pc.BLOCKS))])


def correctness_counts(cells):
    """block -> verdict -> cells; plus the cells without a correctness record."""
    table = OrderedDict((block, Counter()) for block in pc.BLOCKS)
    without = Counter()
    for cell in cells:
        record = cell.get("correctness")
        if record is None:
            without[cell["block"]] += 1
            continue
        table[cell["block"]][str(record.get("verdict"))] += 1
    return OrderedDict([("verdicts", _counter_table(table)),
                        ("cells_without_correctness", OrderedDict((b, without.get(b, 0)) for b in pc.BLOCKS))])


def gap_subset(states_table, wanted):
    """block -> tool -> {state: n} restricted to the wanted states."""
    result = OrderedDict()
    for block, tools in states_table.items():
        result[block] = OrderedDict()
        for tool, states in tools.items():
            subset = OrderedDict((state, n) for state, n in states.items() if state in wanted)
            if subset:
                result[block][tool] = subset
    return result


def enhanced_statuses(document):
    """block -> {status: pairs} and pairs per block from the composite."""
    coverage = document.get("stage_coverage") or {}
    statuses = OrderedDict()
    pairs = OrderedDict()
    for block in pc.BLOCKS:
        enhanced = ((coverage.get(block) or {}).get("enhanced") or {})
        statuses[block] = OrderedDict((str(k), v) for k, v in (enhanced.get("statuses") or {}).items())
        pairs[block] = enhanced.get("pairs")
    return OrderedDict([("statuses", statuses), ("pairs", pairs)])


def status_per_block(statuses, name):
    return OrderedDict((block, int((statuses.get(block) or {}).get(name, 0))) for block in pc.BLOCKS)


# -- pure computations over configs ------------------------------------------------------------

def _walk_keys(node, prefix, found):
    """Every reasoning-related key at its exact path, whatever its value
    (a provider may nest the setting in an object such as
    thinking: {type, budget_tokens}); dict values are recorded AND walked
    so nested reasoning keys keep their own paths."""
    for key, value in node.items():
        path = key if not prefix else prefix + "." + key
        if key in REASONING_KEYS:
            found[path] = value
        if isinstance(value, dict):
            _walk_keys(value, path, found)


def reasoning_settings(models_config, model_ids=None):
    """model id -> provider, model name and every reasoning-related key found
    anywhere in the model entry (exact key paths, e.g. extra_body.thinking_budget)."""
    entries = OrderedDict()
    for entry in models_config or []:
        if isinstance(entry, dict) and entry.get("id"):
            found = OrderedDict()
            _walk_keys(entry, "", found)
            entries[entry["id"]] = OrderedDict([("provider", entry.get("provider")),
                                                ("model_name", entry.get("model_name")),
                                                ("enabled", entry.get("enabled")), ("reasoning", found)])
    if model_ids is None:
        return entries
    missing = [m for m in model_ids if m not in entries]
    if missing:
        raise core.ClosureRefused("models without a config entry: %s" % ", ".join(missing))
    return OrderedDict((m, entries[m]) for m in model_ids)


def freeze_reasoning(freeze, model_ids):
    """model id -> flattened reasoning_configuration of the methodology
    freeze's effective provider plan."""
    plan = ((freeze.get("generation") or {}).get("effective_provider_plan") or {})
    result = OrderedDict()
    for model in model_ids:
        found = OrderedDict()
        _walk_keys((plan.get(model) or {}).get("reasoning_configuration") or {}, "", found)
        result[model] = found
    return result


# -- scans over the results tree ----------------------------------------------------------------------

def study_run_dirs(root):
    """run -> block for every study results directory that exists: the two
    base runs, then the iteration directories of every loop owner
    (<owner>__<variant>__iter<N>, N <= MAX_ITERATIONS). The excluded run is
    never a study directory."""
    root = Path(root).resolve()
    runs = OrderedDict()
    for run, block in ((core.PILOT, pc.PILOT_BLOCK), (core.PARENT, pc.FULL_BLOCK)):
        if (root / core.INTERMEDIATE_REL / run).is_dir():
            runs[run] = block
    for owner in (core.PILOT,) + tuple(core.OWNERS):
        block = pc.PILOT_BLOCK if owner == core.PILOT else pc.FULL_BLOCK
        for variant in core.VARIANTS:
            for iteration in range(1, pl.MAX_ITERATIONS + 1):
                run = pt.iteration_run(owner, variant, iteration)
                if run in core.EXCLUDED_RUNS:
                    continue
                if (root / core.INTERMEDIATE_REL / run).is_dir():
                    runs[run] = block
    return runs


def _model_dirs(base):
    return sorted(p for p in base.iterdir() if p.is_dir() and p.name in core.MODELS)


def _stream(path):
    """Rows of a JSONL file, one line at a time (a torn or undecodable line
    raises - the scan is fail-closed)."""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def infer_scan(root, runs=None, supplement_owners=None, threshold=OUTLIER_SECONDS, top=TOP_ENTRIES):
    """Every Infer entry of the study: tools.infer of every historical
    static_analysis.jsonl (study runs) and the `entry` of every tool == infer
    row of the static supplement ledgers (002, 003, phase 2). Reports the
    duration key, the maximum, the top entries and the entries above the
    threshold - deterministic order, repo-relative paths; every entry
    carries the DATE part of its record's created_at_utc (recorded_date)
    so a narrative can be checked against the record, never typed."""
    root = Path(root).resolve()
    runs = runs if runs is not None else study_run_dirs(root)
    owners = tuple(supplement_owners) if supplement_owners is not None \
        else tuple(pt.SUPPLEMENT_OWNERS) + (core.PHASE2,)
    files = records = entries = ran = non_numeric = wall = 0
    items = []
    duration_keys = Counter()

    def consider(entry, relative, run, source_run, row):
        nonlocal entries, ran, non_numeric, wall
        entries += 1
        if entry.get("ran") is True:
            ran += 1
        if "wall_seconds" in entry:
            wall += 1
        for key in ("duration_seconds", "wall_seconds"):
            if key in entry:
                duration_keys[key] += 1
        seconds = entry.get("duration_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            non_numeric += 1
            return
        items.append(OrderedDict([("seconds", seconds), ("run", run), ("source_run", source_run),
                                  ("model", row.get("model_id")), ("sample_id", row.get("sample_id")),
                                  ("analysis_state", entry.get("analysis_state")),
                                  ("recorded_date", str(row.get("created_at_utc") or "")[:10]),
                                  ("relative", relative)]))

    for run in runs:
        base = root / core.INTERMEDIATE_REL / run
        if not base.is_dir():
            continue
        for model_dir in _model_dirs(base):
            path = model_dir / pt.STATIC_FILE
            if not path.is_file():
                continue
            files += 1
            relative = path.relative_to(root).as_posix()
            for row in _stream(path):
                records += 1
                entry = (row.get("tools") or {}).get("infer")
                if isinstance(entry, dict):
                    consider(entry, relative, run, run, row)
    for owner in owners:
        base = root / core.INTERMEDIATE_REL / owner
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*/supplements/*/static.*.jsonl")):
            if path.parent.parent.parent.name not in core.MODELS:
                continue
            files += 1
            relative = path.relative_to(root).as_posix()
            for row in _stream(path):
                records += 1
                if row.get("tool") != "infer":
                    continue
                entry = row.get("entry")
                if isinstance(entry, dict):
                    consider(entry, relative, owner, row.get("candidate_source_run"), row)
    items.sort(key=lambda i: (-i["seconds"], i["relative"], str(i["sample_id"])))
    above = [i for i in items if i["seconds"] > threshold]
    return OrderedDict([
        ("duration_key", "duration_seconds"),
        ("duration_keys_seen", pc.counts(duration_keys)),
        ("runs_scanned", list(runs)), ("supplement_owners_scanned", list(owners)),
        ("files", files), ("records", records), ("infer_entries", entries), ("infer_entries_ran", ran),
        ("non_numeric_durations", non_numeric), ("wall_seconds_entries", wall),
        ("threshold_seconds", threshold),
        ("max_seconds", items[0]["seconds"] if items else None),
        ("top", items[:top]),
        ("above_threshold", len(above)), ("above_threshold_entries", above[:EXAMPLES]),
    ])


def assembly_scan(root, runs=None):
    """Per block over every assembly.jsonl of the study runs: rows,
    assembled / generation_truncated flags, the assembly condition(s) and
    the cleaning interventions."""
    root = Path(root).resolve()
    runs = runs if runs is not None else study_run_dirs(root)
    blocks = OrderedDict()
    for block in pc.BLOCKS:
        blocks[block] = OrderedDict([("files", 0), ("rows", 0), ("assembled", Counter()),
                                     ("generation_truncated", Counter()), ("conditions", Counter()),
                                     ("condition_versions", Counter()), ("cleaning", Counter()),
                                     ("anomalies", Counter())])
    for run, block in runs.items():
        base = root / core.INTERMEDIATE_REL / run
        if not base.is_dir():
            continue
        for model_dir in _model_dirs(base):
            path = model_dir / ASSEMBLY_FILE
            if not path.is_file():
                continue
            entry = blocks[block]
            entry["files"] += 1
            for row in _stream(path):
                entry["rows"] += 1
                entry["assembled"][_flag(row.get("assembled"))] += 1
                entry["generation_truncated"][_flag(row.get("generation_truncated"))] += 1
                entry["conditions"][str(row.get("assembly_condition_sha256"))] += 1
                entry["condition_versions"][str(row.get("assembly_condition_version"))] += 1
                cleaning = row.get("cleaning") if isinstance(row.get("cleaning"), dict) else {}
                for flag in CLEANING_FLAGS:
                    if cleaning.get(flag):
                        entry["cleaning"][flag] += 1
                for flag in CLEANING_ANOMALIES:
                    if cleaning.get(flag) is False:
                        entry["anomalies"][flag] += 1
    return OrderedDict([("runs_scanned", list(runs)), ("blocks", _counter_table(blocks))])


def assembly_pins_uniform(blocks, expected):
    """block -> True iff every assembly row of the block carries exactly the
    assembly condition ITS OWN contract pins (pilot rows: the pilot
    contract, full_ext rows: the parent contract); a block without rows is
    False."""
    return OrderedDict((block, list(((blocks.get(block) or {}).get("conditions") or {}).keys()) == [expected.get(block)])
                       for block in pc.BLOCKS)


def stage_history(root):
    """Per phase-2 stage: invoked / completed counts, interrupted invocations
    (an invoked followed by another invoked before a completed) and the last
    status with its open items. A missing or empty ledger is refused (the
    JSONL reader would otherwise yield a clean zero history)."""
    if not checked_path(Path(root).resolve(), STAGE_HISTORY_REL).is_file():
        raise core.ClosureRefused("missing artifact: " + STAGE_HISTORY_REL)
    rows = core.read_jsonl(root, STAGE_HISTORY_REL)
    if not rows:
        raise core.ClosureRefused("empty stage history: " + STAGE_HISTORY_REL)
    stages = OrderedDict()
    for stage in pl.STAGES:
        stages[stage] = OrderedDict([("invoked", 0), ("completed", 0), ("other", 0), ("interrupted", 0),
                                     ("last_status", None), ("last_open_items", None)])
    pending = {}
    for row in rows:
        stage = str(row.get("stage"))
        entry = stages.setdefault(stage, OrderedDict([("invoked", 0), ("completed", 0), ("other", 0),
                                                      ("interrupted", 0), ("last_status", None),
                                                      ("last_open_items", None)]))
        status = row.get("status")
        if status == "invoked":
            if pending.get(stage):
                entry["interrupted"] += 1
            pending[stage] = True
            entry["invoked"] += 1
        elif status == "completed":
            pending[stage] = False
            entry["completed"] += 1
        else:
            entry["other"] += 1
        entry["last_status"] = status
        entry["last_open_items"] = row.get("open_items")
    return OrderedDict([("rows", len(rows)), ("stages", stages),
                        ("interrupted_invocations", sum(e["interrupted"] for e in stages.values()))])


def phase2_incidents(reports):
    """From the persisted phase-2 reports: torn tails, temporary files, stray
    ledgers (ledger hygiene check) and repeated build groups (provenance
    checks), per model and in total."""
    per_model = OrderedDict()
    totals = Counter()
    for model, report in reports.items():
        checks = OrderedDict((c.get("check"), c) for c in (report.get("checks") or []))
        ledger = checks.get(PHASE2_LEDGER_CHECK)
        if ledger is None or not isinstance(ledger.get("detail"), dict):
            raise core.ClosureRefused("report of %s lacks %s" % (model, PHASE2_LEDGER_CHECK))
        detail = ledger["detail"]
        entry = OrderedDict()
        for key in ("archived_torn_tails", "temporary_files", "stray"):
            if not isinstance(detail.get(key), list):
                raise core.ClosureRefused("%s of %s: %s is not a list" % (PHASE2_LEDGER_CHECK, model, key))
            entry[key] = len(detail[key])
        repeated = 0
        provenance_checks = 0
        for check_id, check in checks.items():
            if str(check_id).endswith(PHASE2_PROVENANCE_SUFFIX):
                provenance_checks += 1
                value = (check.get("detail") or {}).get("repeated_build_groups") \
                    if isinstance(check.get("detail"), dict) else None
                if isinstance(value, bool) or not isinstance(value, int):
                    raise core.ClosureRefused("%s of %s: repeated_build_groups is %r" % (check_id, model, value))
                repeated += value
        entry["repeated_build_groups"] = repeated
        entry["provenance_checks"] = provenance_checks
        entry["ledger_check_status"] = ledger.get("status")
        per_model[model] = entry
        for key in ("archived_torn_tails", "temporary_files", "stray", "repeated_build_groups"):
            totals[key] += entry[key]
    return OrderedDict([("per_model", per_model), ("totals", pc.counts(totals))])


def _reports(root, directory):
    """Every persisted report (*.json, sorted) of a verification directory."""
    base = checked_path(Path(root).resolve(), directory)
    files = sorted(p for p in base.iterdir() if p.is_file() and p.suffix == ".json") if base.is_dir() else []
    if not files:
        raise core.ClosureRefused("no verification report under " + directory)
    return [p.relative_to(Path(root).resolve()).as_posix() for p in files]


def verification_scopes(root, reverification=None):
    """The scope of every verification artifact kind of the study, read
    from EVERY persisted report of the kind (all must agree and carry the
    kind's schema; a foreign, unknown or scope-less document is refused),
    plus the closure scopes."""
    root = Path(root).resolve()
    entries = []

    def add(run_ids, relatives, expected_schema):
        """One entry per verification KIND; every artifact of the kind must
        carry the same schema and scope (003 and 004 share the successor
        scope by design)."""
        documents = [core.read_json(root, relative) for relative in relatives]
        identities = set((d.get("schema_version"), d.get("scope"), d.get("verifier_version")) for d in documents)
        if len(identities) != 1:
            raise core.ClosureRefused("verification artifacts of one kind disagree on their scope: %s" % relatives)
        schema, scope, verifier = identities.pop()
        if schema != expected_schema or schema not in SCOPE_NOTES:
            raise core.ClosureRefused("verification artifacts %s carry schema %r, expected %s"
                                      % (relatives, schema, expected_schema))
        if scope is None and schema not in SCOPELESS_SCHEMAS:
            raise core.ClosureRefused("verification artifacts without a scope: %s" % relatives)
        proves, not_proves = SCOPE_NOTES[schema]
        entries.append(OrderedDict([
            ("run_ids", list(run_ids)), ("artifacts", list(relatives)), ("schema_version", schema),
            ("scope", scope), ("verifier_version", verifier), ("proves", proves), ("does_not_prove", not_proves)]))

    add((core.PILOT,), [core.PILOT_POST_RUN_REL], POST_RUN_SCHEMA)
    add((core.PARENT,), [core.RUN_REGISTRY[core.PARENT]["verification"]], PARENT_SCHEMA)
    successors = (core.OWNERS[2], core.OWNERS[3])
    add(successors, [relative for run in successors
                     for relative in _reports(root, core.RUN_REGISTRY[run]["verification"])], SUCCESSOR_SCHEMA)
    add((core.PHASE2,), _reports(root, core.PHASE2_VERIFICATION_REL), PHASE2_SCHEMA)
    closure_artifact = core.ARTIFACT_DIR_REL + "/" + core.GLOBAL_JSON
    entries.append(OrderedDict([
        ("run_ids", list(core.RUNS)), ("artifacts", [closure_artifact]),
        ("schema_version", core.SCHEMA), ("scope", core.SCOPE), ("verifier_version", core.CLOSURE_ID),
        ("proves", SCOPE_NOTES[core.SCHEMA][0]), ("does_not_prove", SCOPE_NOTES[core.SCHEMA][1])]))
    entries.append(OrderedDict([
        ("run_ids", [core.OWNERS[0], core.OWNERS[1]]), ("artifacts", [closure_artifact]),
        ("schema_version", core.SCHEMA), ("scope", core.RETROSPECTIVE_SCOPE), ("verifier_version", core.CLOSURE_ID),
        ("proves", "read-only coverage of the two runs without a persisted report by the successors' "
                   "verifiers, the census, the custody chain and the phase-2 reports"),
        ("does_not_prove", "a historical PASS that was never persisted")]))
    retrospective = OrderedDict()
    if isinstance(reverification, dict):
        for run, models in reverification.items():
            statuses = Counter()
            deep = Counter()
            for result in (models or {}).values():
                statuses[str((result or {}).get("retrospective_status"))] += 1
                deep[_flag((result or {}).get("deep"))] += 1
            retrospective[run] = OrderedDict([("models", len(models or {})), ("statuses", pc.counts(statuses)),
                                              ("deep", pc.counts(deep))])
    scopes = [(e["schema_version"], e["scope"]) for e in entries]
    return OrderedDict([("entries", entries), ("distinct", len(set(scopes)) == len(scopes)),
                        ("retrospective", retrospective)])


# -- inputs ---------------------------------------------------------------------------------------

def gather_inputs(ctx):
    """Everything the item builders read: the small artifacts, the shared
    cache results (None when a producer did not run) and the two scans
    (cached under ctx.cache infer_scan / assembly_scan once computed)."""
    root = ctx.root
    inputs = OrderedDict()
    inputs["policy"] = core.read_json(root, core.PUBLICATION_POLICY_REL)
    inputs["freeze"] = core.read_json(root, METHODOLOGY_FREEZE_REL)
    inputs["pilot_contract"] = ctx.frozen_contract(core.PILOT)
    inputs["parent_contract"] = ctx.frozen_contract(core.PARENT)
    for key in CACHE_KEYS + ("successor_reverification",):
        inputs[key] = ctx.cache.get(key)
    if ctx.cache.get("infer_scan") is None:
        ctx.cache["infer_scan"] = ctx.timed("disclosures.infer_scan", infer_scan, root)
    inputs["infer_scan"] = ctx.cache["infer_scan"]
    if ctx.cache.get("assembly_scan") is None:
        ctx.cache["assembly_scan"] = ctx.timed("disclosures.assembly_scan", assembly_scan, root)
    inputs["assembly_scan"] = ctx.cache["assembly_scan"]
    return inputs


# -- item builders ------------------------------------------------------------------------------------

def item_policy_sources(ctx, inputs):
    policy = inputs["policy"]
    states = pf.disclosure_sources_state(policy, ctx.root)
    artifacts = OrderedDict()
    entries = []
    satisfied = 0
    for state in states:
        ok = bool(state.get("artifact_readable")) and bool(state.get("field_present")) and not state.get("problems")
        satisfied += 1 if ok else 0
        if state.get("artifact"):
            artifacts[state["artifact"]] = True
        entries.append(OrderedDict([("id", state.get("id")), ("artifact", state.get("artifact")),
                                    ("field", state.get("field")), ("artifact_readable", state.get("artifact_readable")),
                                    ("field_present", state.get("field_present")), ("problems", state.get("problems")),
                                    ("satisfied", ok)]))
    sources = [source(ctx.root, core.PUBLICATION_POLICY_REL)] + [source(ctx.root, a) for a in artifacts]
    evidence = OrderedDict([
        ("sources_declared", count(len(states), core.PUBLICATION_POLICY_REL + " mandatory_disclosure_sources")),
        ("sources_satisfied", count(satisfied, "pilot_freeze.disclosure_sources_state(policy, root)")),
        ("entries", ev(entries, "pilot_freeze.disclosure_sources_state(policy, root)")),
    ])
    return _item("policy_mandatory_sources", ARTIFACT_BOUND, sources, evidence)


def item_pilot_label(ctx, inputs):
    policy = inputs["policy"]
    state = pf.verify_publication_policy(policy)
    # the requirement text is unconditional: a policy that is not FRESH,
    # allows the full-study presentation or carries no label contradicts it
    if state.get("status") != pf.FRESH:
        raise core.ClosureRefused("publication policy is %s, not FRESH: %s"
                                  % (state.get("status"), "; ".join(state.get("problems") or [])))
    if policy.get("may_be_presented_as_full_60_benchmark_study") is not False:
        raise core.ClosureRefused("policy may_be_presented_as_full_60_benchmark_study is %r, the pilot label "
                                  "requires False" % (policy.get("may_be_presented_as_full_60_benchmark_study"),))
    if not isinstance(policy.get("pilot_label"), str) or not policy.get("pilot_label").strip():
        raise core.ClosureRefused("policy pilot_label is empty")
    evidence = OrderedDict([
        ("pilot_label", ev(policy.get("pilot_label"), core.PUBLICATION_POLICY_REL + " pilot_label")),
        ("may_be_presented_as_full_60_benchmark_study",
         ev(policy.get("may_be_presented_as_full_60_benchmark_study"),
            core.PUBLICATION_POLICY_REL + " may_be_presented_as_full_60_benchmark_study")),
        ("pilot_results_must_be_labelled_as_pilot",
         ev(policy.get("pilot_results_must_be_labelled_as_pilot"),
            core.PUBLICATION_POLICY_REL + " pilot_results_must_be_labelled_as_pilot")),
        ("policy_state", ev(state.get("status"), "pilot_freeze.verify_publication_policy")),
        ("publication_policy_sha256", ev(policy.get("publication_policy_sha256"),
                                         core.PUBLICATION_POLICY_REL + " publication_policy_sha256")),
    ])
    return _item("pilot_label", ARTIFACT_BOUND, [source(ctx.root, core.PUBLICATION_POLICY_REL)], evidence)


def item_max_iterations(ctx, inputs):
    config_rel = _config_rel(ctx)
    configured = ((ctx.config.get("stages") or {}).get("repair") or {}).get("max_iterations")
    frozen = ((inputs["freeze"].get("repair") or {}).get("max_iterations"))
    if configured != pl.MAX_ITERATIONS or frozen != pl.MAX_ITERATIONS:
        raise core.ClosureRefused("max_iterations disagree: config %r, freeze %r, package %r"
                                  % (configured, frozen, pl.MAX_ITERATIONS))
    cells = _need(inputs, "composite_cells")
    summary = _need(inputs, "census_summary")
    document = _need(inputs, "composite_document")
    iterations = iteration_counts(cells)
    blocks = summary.get("blocks") or {}
    sample_states = OrderedDict((b, OrderedDict((blocks.get(b) or {}).get("sample_states") or {}))
                                for b in pc.BLOCKS)
    evidence = OrderedDict([
        ("configured_max_iterations", count(configured, config_rel + " stages.repair.max_iterations")),
        ("frozen_max_iterations", count(frozen, METHODOLOGY_FREEZE_REL + " repair.max_iterations")),
        ("package_constant", count(pl.MAX_ITERATIONS, LINEAGE_MODULE_REL + " MAX_ITERATIONS")),
        ("observed_max_iteration", count(iterations["observed_max_iteration"], "composite cells: max(iteration)")),
        ("cells_per_iteration", count(iterations["per_block"], "composite cells: count by block and iteration (iter0 = base)")),
        ("repair_sample_states", count(sample_states, "census summary: blocks.<block>.sample_states "
                                                       "(thesis.recovery_successor_004.census.summary)")),
        ("stopped_budget", count(OrderedDict((b, int(sample_states[b].get("stopped_budget", 0))) for b in pc.BLOCKS),
                                 "census summary: blocks.<block>.sample_states.stopped_budget")),
        ("loops_done", ev(summary.get("total_repair_loops_done"), "census summary: total_repair_loops_done")),
    ])
    sources = [source(ctx.root, config_rel), source(ctx.root, METHODOLOGY_FREEZE_REL),
               source(ctx.root, LINEAGE_MODULE_REL), composite_source(ctx.root, document)]
    return _item("max_two_repair_iterations", COMPUTED, sources, evidence)


def item_reasoning(ctx, inputs):
    config_rel = _config_rel(ctx)
    freeze = inputs["freeze"]
    settings = reasoning_settings(ctx.config.get("models"), list(core.MODELS))
    frozen = freeze_reasoning(freeze, list(core.MODELS))
    profiles = Counter(json.dumps(entry["reasoning"], sort_keys=True) for entry in settings.values())
    without = [m for m, entry in settings.items() if not entry["reasoning"]]
    matches = OrderedDict((m, _same(settings[m]["reasoning"], frozen[m])) for m in core.MODELS)
    defaults = ctx.config.get("generation_defaults") or {}
    frozen_defaults = (freeze.get("generation") or {}).get("settings") or {}
    config_generation = OrderedDict((k, defaults.get(k)) for k in GENERATION_KEYS)
    freeze_generation = OrderedDict((k, frozen_defaults.get(k)) for k in GENERATION_KEYS)
    evidence = OrderedDict([
        ("per_model", ev(settings, config_rel + " models[] (keys %s at their exact paths)" % ", ".join(REASONING_KEYS))),
        ("distinct_reasoning_profiles", count(len(profiles), config_rel + " models[]: distinct reasoning settings")),
        ("models_without_reasoning_setting", ev(without, config_rel + " models[]")),
        ("freeze_effective_reasoning", ev(frozen, METHODOLOGY_FREEZE_REL
                                          + " generation.effective_provider_plan.<model>.reasoning_configuration")),
        ("config_equals_freeze", ev(matches, "comparison config models[] vs freeze effective_provider_plan")),
        ("generation_defaults", ev(config_generation, config_rel + " generation_defaults")),
        ("frozen_generation_settings", ev(freeze_generation, METHODOLOGY_FREEZE_REL + " generation.settings")),
        ("generation_defaults_equal_freeze", ev(_same(config_generation, freeze_generation),
                                                "comparison config generation_defaults vs freeze generation.settings")),
    ])
    return _item("reasoning_policy_differences", COMPUTED,
                 [source(ctx.root, config_rel), source(ctx.root, METHODOLOGY_FREEZE_REL)], evidence)


def item_cleaning(ctx, inputs):
    tpc = core.read_json(ctx.root, TECHNICAL_PROVENANCE_REL)
    pilot = inputs["pilot_contract"]
    parent = inputs["parent_contract"]
    pilot_rel = core.RUN_REGISTRY[core.PILOT]["contract"]
    parent_rel = core.RUN_REGISTRY[core.PARENT]["contract"]
    conditions = pilot.get("conditions") or {}
    scan = _need(inputs, "assembly_scan")
    cells = inputs.get("composite_cells")
    blocks = scan["blocks"]
    rows = OrderedDict((b, blocks[b]["rows"]) for b in pc.BLOCKS)
    cells_per_block = OrderedDict((b, sum(1 for c in cells if c["block"] == b)) for b in pc.BLOCKS) \
        if cells is not None else None
    expected_pins = OrderedDict([(pc.PILOT_BLOCK, conditions.get("assembly_condition_sha256")),
                                 (pc.FULL_BLOCK, (parent.get("conditions") or {}).get("assembly_condition_sha256"))])
    uniform = assembly_pins_uniform(blocks, expected_pins)
    evidence = OrderedDict([
        ("technical_provenance_cleanup", ev(OrderedDict([(k, tpc.get(k)) for k in
                                                         ("schema_version", "wave", "date", "all_tests_pass",
                                                          "next_step", "artifact_sha256")]),
                                            TECHNICAL_PROVENANCE_REL)),
        ("contract_pins_cleanup", ev(OrderedDict([
            ("technical_provenance_cleanup_sha256", conditions.get("technical_provenance_cleanup_sha256")),
            ("technical_provenance_cleanup_status", conditions.get("technical_provenance_cleanup_status")),
            ("pin_matches_artifact", conditions.get("technical_provenance_cleanup_sha256") == tpc.get("artifact_sha256"))]),
            pilot_rel + " conditions")),
        ("cleaning_conditions", ev(OrderedDict([
            ("pilot", OrderedDict((k, conditions.get(k)) for k in
                                  ("generation_cleaning_condition_sha256", "assembly_condition_version",
                                   "assembly_condition_sha256"))),
            ("full_ext", OrderedDict((k, (parent.get("conditions") or {}).get(k)) for k in
                                     ("generation_cleaning_condition_sha256", "assembly_condition_version",
                                      "assembly_condition_sha256")))]),
            pilot_rel + " / " + parent_rel + " conditions")),
        ("assembly_rows", count(rows, "study assembly.jsonl files (streamed)")),
        ("assembly_files", count(OrderedDict((b, blocks[b]["files"]) for b in pc.BLOCKS), "study assembly.jsonl files")),
        ("assembled", count(OrderedDict((b, blocks[b]["assembled"]) for b in pc.BLOCKS), "assembly rows: assembled")),
        ("generation_truncated", count(OrderedDict((b, blocks[b]["generation_truncated"]) for b in pc.BLOCKS),
                                       "assembly rows: generation_truncated")),
        ("assembly_conditions_observed", count(OrderedDict((b, blocks[b]["conditions"]) for b in pc.BLOCKS),
                                               "assembly rows: assembly_condition_sha256")),
        ("assembly_condition_pins", ev(expected_pins, "%s (pilot) / %s (full_ext) conditions.assembly_condition_sha256"
                                       % (pilot_rel, parent_rel))),
        ("assembly_condition_uniform_and_pinned", ev(uniform, "assembly rows vs the block's own contract pin "
                                                             "(pilot: %s, full_ext: %s)" % (pilot_rel, parent_rel))),
        ("cleaning_interventions", count(OrderedDict((b, blocks[b]["cleaning"]) for b in pc.BLOCKS),
                                         "assembly rows: cleaning.<flag> truthy (%s)" % ", ".join(CLEANING_FLAGS))),
        ("cleaning_anomalies", count(OrderedDict((b, blocks[b]["anomalies"]) for b in pc.BLOCKS),
                                     "assembly rows: cleaning.<flag> false (%s)" % ", ".join(CLEANING_ANOMALIES))),
        ("composite_cells_per_block", ev(cells_per_block, "composite cells (None when unavailable)")),
        ("runs_scanned", ev(scan["runs_scanned"], "study_run_dirs(root)")),
    ])
    return _item("cleaning_and_pipeline_interventions", COMPUTED,
                 [source(ctx.root, TECHNICAL_PROVENANCE_REL), source(ctx.root, pilot_rel), source(ctx.root, parent_rel)],
                 evidence)


def item_baseline(ctx, inputs):
    document = _need(inputs, "composite_document")
    summary = _need(inputs, "census_summary")
    census = _need(inputs, "census")
    statuses = enhanced_statuses(document)
    blocks = summary.get("blocks") or {}
    stopped = OrderedDict((b, int(((blocks.get(b) or {}).get("sample_states") or {}).get("stopped_baseline_incompatible", 0)))
                          for b in pc.BLOCKS)
    evidence = OrderedDict([
        ("enhanced_statuses", count(statuses["statuses"], "composite stage_coverage.<block>.enhanced.statuses")),
        ("enhanced_pairs", count(statuses["pairs"], "composite stage_coverage.<block>.enhanced.pairs")),
        ("baseline_incompatible", count(status_per_block(statuses["statuses"], "baseline_incompatible"),
                                        "composite stage_coverage.<block>.enhanced.statuses.baseline_incompatible")),
        ("repair_stopped_baseline_incompatible", count(stopped, "census summary: blocks.<block>.sample_states"
                                                                 ".stopped_baseline_incompatible (0 when absent)")),
        ("non_model_terminal_statuses", ev(list(census.get("non_model_terminal_statuses") or []),
                                           "census result: non_model_terminal_statuses")),
    ])
    return _item("baseline_incompatibilities", COMPUTED, [composite_source(ctx.root, document)], evidence)


def item_static_gaps(ctx, inputs):
    cells = _need(inputs, "composite_cells")
    document = _need(inputs, "composite_document")
    gaps = static_gap_counts(cells)
    from thesis.evaluation import framework

    evidence = OrderedDict([
        ("states", count(gaps["states"], "composite cells: static.tools.<tool> state per block")),
        ("gap_states", count(gap_subset(gaps["states"], framework.ANALYSIS_GAP_STATES),
                             "composite cells: static.tools states in %s" % ", ".join(framework.ANALYSIS_GAP_STATES))),
        ("cells_without_static", count(gaps["cells_without_static"], "composite cells: static is null")),
        ("analysis_states", ev(list(framework.ANALYSIS_STATES), "thesis/evaluation/framework.py ANALYSIS_STATES")),
    ])
    return _item("static_analysis_gaps", COMPUTED, [composite_source(ctx.root, document)], evidence)


def item_dynamic_gaps(ctx, inputs):
    cells = _need(inputs, "composite_cells")
    document = _need(inputs, "composite_document")
    gaps = dynamic_gap_counts(cells)
    evidence = OrderedDict([
        ("states", count(gaps["states"], "composite cells: dynamic.tools.<tool>.analysis_state / ran per block")),
        ("cells_without_dynamic", count(gaps["cells_without_dynamic"], "composite cells: dynamic is null")),
    ])
    return _item("dynamic_analysis_gaps", COMPUTED, [composite_source(ctx.root, document)], evidence)


def item_timeouts(ctx, inputs):
    cells = _need(inputs, "composite_cells")
    document = _need(inputs, "composite_document")
    static = static_gap_counts(cells)["states"]
    dynamic = dynamic_gap_counts(cells)["states"]
    dynamic_states = OrderedDict((b, OrderedDict((tool, entry["analysis_state"]) for tool, entry in tools.items()))
                                 for b, tools in dynamic.items())
    wanted = ("TIMEOUT", "TOOL_ERROR")
    verdicts = correctness_counts(cells)
    evidence = OrderedDict([
        ("static_timeouts_and_errors", count(gap_subset(static, wanted), "composite cells: static.tools states TIMEOUT/TOOL_ERROR")),
        ("dynamic_timeouts_and_errors", count(gap_subset(dynamic_states, wanted),
                                              "composite cells: dynamic.tools analysis_state TIMEOUT/TOOL_ERROR")),
        ("correctness_verdicts", count(verdicts["verdicts"], "composite cells: correctness.verdict per block")),
        ("cells_without_correctness", count(verdicts["cells_without_correctness"], "composite cells: correctness is null")),
    ])
    return _item("tool_timeouts_and_errors", COMPUTED, [composite_source(ctx.root, document)], evidence)


def item_single_tool(ctx, inputs):
    config_rel = _config_rel(ctx)
    repair = (ctx.config.get("stages") or {}).get("repair") or {}
    frozen_repair = inputs["freeze"].get("repair") or {}
    tools = ((ctx.config.get("stages") or {}).get("static_analysis") or {}).get("tools") or {}
    precision = OrderedDict((tool, OrderedDict([("low_precision_warning", bool(entry.get("low_precision_warning"))),
                                                ("low_precision_families", list(entry.get("low_precision_families") or []))]))
                            for tool, entry in tools.items() if isinstance(entry, dict))
    evidence = OrderedDict([
        ("low_confidence_prefix", ev((repair.get("feedback") or {}).get("low_confidence_prefix"),
                                     config_rel + " stages.repair.feedback.low_confidence_prefix")),
        ("low_confidence_stop_mode", ev(repair.get("low_confidence_stop_mode"), config_rel + " stages.repair.low_confidence_stop_mode")),
        ("frozen_low_confidence_prefix", ev((frozen_repair.get("feedback") or {}).get("low_confidence_prefix"),
                                            METHODOLOGY_FREEZE_REL + " repair.feedback.low_confidence_prefix")),
        ("frozen_low_confidence_stop_mode", ev(frozen_repair.get("low_confidence_stop_mode"),
                                               METHODOLOGY_FREEZE_REL + " repair.low_confidence_stop_mode")),
        ("config_equals_freeze", ev((repair.get("feedback") or {}).get("low_confidence_prefix")
                                    == (frozen_repair.get("feedback") or {}).get("low_confidence_prefix")
                                    and repair.get("low_confidence_stop_mode") == frozen_repair.get("low_confidence_stop_mode"),
                                    "comparison config stages.repair vs freeze repair")),
        ("tool_precision_settings", ev(precision, config_rel + " stages.static_analysis.tools.<tool>")),
        ("tool_validation_artifacts", ev(list(TOOL_VALIDATION_RELS), "thesis/tool_validation/results (not parsed)")),
    ])
    sources = [source(ctx.root, config_rel), source(ctx.root, METHODOLOGY_FREEZE_REL)] + \
              [source(ctx.root, rel) for rel in TOOL_VALIDATION_RELS]
    return _item("single_tool_finding_validity", ARTIFACT_BOUND, sources, evidence)


def item_numerical(ctx, inputs):
    document = _need(inputs, "composite_document")
    statuses = enhanced_statuses(document)
    policy = core.read_json(ctx.root, ENHANCED_POLICY_REL)
    conditions = inputs["pilot_contract"].get("conditions") or {}
    frozen = inputs["freeze"].get("enhanced") or {}
    lf = core.lf_sha256(ctx.root, ENHANCED_POLICY_REL)
    evidence = OrderedDict([
        ("numerically_unstable", count(status_per_block(statuses["statuses"], "numerically_unstable"),
                                       "composite stage_coverage.<block>.enhanced.statuses.numerically_unstable (0 when absent)")),
        ("enhanced_statuses", count(statuses["statuses"], "composite stage_coverage.<block>.enhanced.statuses")),
        ("enhanced_policy", ev(OrderedDict([("status", policy.get("status")),
                                            ("derivation_version", (policy.get("_meta") or {}).get("derivation_version")),
                                            ("benchmarks", len(policy.get("benchmarks") or {})),
                                            ("lf_sha256", lf),
                                            ("contract_pin_lf_sha256", conditions.get("enhanced_policy_sha256_lf_normalized")),
                                            ("pin_matches", lf == conditions.get("enhanced_policy_sha256_lf_normalized")),
                                            ("contract_pin_status", conditions.get("enhanced_policy_status"))]),
                               ENHANCED_POLICY_REL + " / pilot contract conditions")),
        ("frozen_enhanced_block", ev(OrderedDict((k, v) for k, v in frozen.items() if not isinstance(v, (dict, list))),
                                     METHODOLOGY_FREEZE_REL + " enhanced (scalar fields; no tolerance field is frozen)")),
        ("gate_semantics", ev("the serial baseline self-test and the fast-math stability probe decide per spec: "
                              "baseline_incompatible (oracle crash/hang/self-fail or non-finite reference) and "
                              "numerically_unstable (perturbed oracle diverges) are oracle properties, never "
                              "counted against a model", ENHANCED_RUNNER_REL + " (module docstring, gate)")),
    ])
    sources = [source(ctx.root, ENHANCED_POLICY_REL), source(ctx.root, METHODOLOGY_FREEZE_REL),
               source(ctx.root, ENHANCED_RUNNER_REL), composite_source(ctx.root, document)]
    return _item("numerical_tolerance", COMPUTED, sources, evidence)


def item_launch(ctx, inputs):
    config_rel = _config_rel(ctx)
    stages = ctx.config.get("stages") or {}
    enhanced = stages.get("enhanced_tests") or {}
    correctness = stages.get("correctness_tests") or {}
    dynamic = (stages.get("dynamic_analysis") or {}).get("tools") or {}
    freeze = inputs["freeze"]
    frozen_enhanced = freeze.get("enhanced") or {}
    frozen_correctness = freeze.get("correctness") or {}
    frozen_dynamic = (freeze.get("dynamic") or {}).get("toolset") or {}
    config_launch = OrderedDict([("enhanced_launch", enhanced.get("enhanced_launch")),
                                 ("run_timeout_seconds", enhanced.get("run_timeout_seconds")),
                                 ("jobs", enhanced.get("jobs")), ("execution_models", enhanced.get("execution_models"))])
    frozen_launch = OrderedDict([("enhanced_launch", frozen_enhanced.get("enhanced_launch")),
                                 ("run_timeout_seconds", frozen_enhanced.get("run_timeout_seconds")),
                                 ("jobs", frozen_enhanced.get("effective_jobs_from_config")),
                                 ("execution_models", frozen_enhanced.get("execution_models")),
                                 ("build_timeout_seconds_constant", frozen_enhanced.get("build_timeout_seconds_constant"))])
    dynamic_config = OrderedDict((tool, OrderedDict([("enabled", entry.get("enabled")),
                                                     ("execution_models", entry.get("execution_models"))]))
                                 for tool, entry in dynamic.items() if isinstance(entry, dict))
    dynamic_frozen = OrderedDict((tool, OrderedDict([("enabled", entry.get("enabled")),
                                                     ("execution_models", entry.get("execution_models"))]))
                                 for tool, entry in frozen_dynamic.items() if isinstance(entry, dict))
    evidence = OrderedDict([
        ("enhanced_launch", ev(config_launch, config_rel + " stages.enhanced_tests")),
        ("frozen_enhanced_launch", ev(frozen_launch, METHODOLOGY_FREEZE_REL + " enhanced")),
        ("enhanced_launch_equals_freeze", ev(_same(config_launch, OrderedDict((k, frozen_launch[k]) for k in config_launch)),
                                             "comparison config stages.enhanced_tests vs freeze enhanced")),
        ("correctness_launch", ev(OrderedDict([("niter", correctness.get("niter")),
                                               ("run_timeout_seconds", correctness.get("run_timeout_seconds"))]),
                                  config_rel + " stages.correctness_tests")),
        ("frozen_correctness_launch", ev(OrderedDict((k, frozen_correctness.get(k)) for k in
                                                     ("niter", "build_timeout_seconds", "run_timeout_seconds",
                                                      "launch_defaults", "launch_overrides")),
                                         METHODOLOGY_FREEZE_REL + " correctness")),
        ("dynamic_toolset", ev(dynamic_config, config_rel + " stages.dynamic_analysis.tools")),
        ("dynamic_toolset_equals_freeze", ev(_same(dynamic_config, dynamic_frozen),
                                             "comparison config stages.dynamic_analysis.tools vs freeze dynamic.toolset")),
        ("contract_timeouts", ev(OrderedDict([
            (run, OrderedDict([("run_timeout_seconds", contract.get("run_timeout_seconds")),
                               ("enhanced_run_timeout_seconds", contract.get("enhanced_run_timeout_seconds"))]))
            for run, contract in ((core.PILOT, inputs["pilot_contract"]), (core.PARENT, inputs["parent_contract"]))]),
            "frozen contracts of pilot_002 / full_ext_001")),
    ])
    sources = [source(ctx.root, config_rel), source(ctx.root, METHODOLOGY_FREEZE_REL),
               source(ctx.root, core.RUN_REGISTRY[core.PILOT]["contract"]),
               source(ctx.root, core.RUN_REGISTRY[core.PARENT]["contract"])]
    return _item("frozen_thread_rank_configuration", ARTIFACT_BOUND, sources, evidence)


def item_infer(ctx, inputs):
    scan = _need(inputs, "infer_scan")
    top_files = OrderedDict()
    for entry in scan["top"]:
        top_files[entry["relative"]] = True
    evidence = OrderedDict([
        ("duration_key", ev(scan["duration_key"], "static records: tools.infer / supplement entry (keys seen: %s)"
                            % json.dumps(scan["duration_keys_seen"]))),
        ("wall_seconds_entries", count(scan["wall_seconds_entries"], "infer scan: entries carrying wall_seconds")),
        ("files_scanned", count(scan["files"], "infer scan: static_analysis.jsonl + static.*.jsonl supplement ledgers")),
        ("records_scanned", count(scan["records"], "infer scan")),
        ("infer_entries", count(scan["infer_entries"], "infer scan: entries with tool infer")),
        ("infer_entries_ran", count(scan["infer_entries_ran"], "infer scan: entries with ran = true")),
        ("non_numeric_durations", count(scan["non_numeric_durations"], "infer scan")),
        ("threshold_seconds", number(scan["threshold_seconds"], "thesis/study_closure/disclosures.py OUTLIER_SECONDS "
                                                                 "(reporting convention)")),
        ("max_seconds", number(scan["max_seconds"], "infer scan: max duration_seconds")),
        ("top_entries", ev(scan["top"], "infer scan: the %d longest Infer entries" % TOP_ENTRIES)),
        ("longest_entry_recorded_date", ev(scan["top"][0].get("recorded_date") if scan["top"] else None,
                                           "infer scan: created_at_utc (date part) of the longest Infer entry")),
        ("above_threshold", count(scan["above_threshold"], "infer scan: entries with duration_seconds > threshold")),
        ("above_threshold_entries", ev(scan["above_threshold_entries"], "infer scan (<= %d examples)" % EXAMPLES)),
        ("runs_scanned", ev(scan["runs_scanned"], "study_run_dirs(root)")),
        ("supplement_owners_scanned", ev(scan["supplement_owners_scanned"], "targets.SUPPLEMENT_OWNERS + phase 2")),
    ])
    narrative = ("operator note (thesis text, not a measurement): the longest Infer run coincided with a laptop "
                 "standby on the day its static record carries as recorded_date (created_at_utc, see "
                 "longest_entry_recorded_date); the recorded duration is wall-clock time including the standby "
                 "and the tool completed - the numbers and the date come from the scan, the standby from the "
                 "run log")
    return _item("infer_runtime_outlier", COMPUTED, [source(ctx.root, rel) for rel in top_files], evidence, narrative)


def item_one_generation(ctx, inputs):
    document = _need(inputs, "composite_document")
    pilot = inputs["pilot_contract"]
    parent = inputs["parent_contract"]
    pilot_rel = core.RUN_REGISTRY[core.PILOT]["contract"]
    parent_rel = core.RUN_REGISTRY[core.PARENT]["contract"]
    freeze_population = inputs["freeze"].get("population") or {}
    samples = OrderedDict([(core.PILOT, (pilot.get("population") or {}).get("num_samples_per_prompt")),
                           (core.PARENT, (parent.get("population") or {}).get("num_samples_per_prompt"))])
    frozen_samples = freeze_population.get("samples_per_prompt")
    # the requirement text states exactly one generation per prompt: a
    # contract or freeze that records anything else contradicts the item
    for name, value in list(samples.items()) + [(METHODOLOGY_FREEZE_REL, frozen_samples)]:
        if isinstance(value, bool) or value != 1:
            raise core.ClosureRefused("%s records %r samples per prompt; the disclosure states exactly one "
                                      "generation per base cell" % (name, value))
    base = (document.get("cells") or {}).get("base_per_block") or {}
    expected_base = OrderedDict([(pc.PILOT_BLOCK, pc.EXPECTED_POPULATION.get(core.PILOT)),
                                 (pc.FULL_BLOCK, pc.EXPECTED_POPULATION.get(core.PARENT))])
    evidence = OrderedDict([
        ("num_samples_per_prompt", count(samples, pilot_rel + " / " + parent_rel + " population.num_samples_per_prompt")),
        ("prompt_count", count(OrderedDict([(core.PILOT, (pilot.get("population") or {}).get("prompt_count")),
                                            (core.PARENT, (parent.get("population") or {}).get("prompt_count"))]),
                               pilot_rel + " / " + parent_rel + " population.prompt_count")),
        ("frozen_samples_per_prompt", count(freeze_population.get("samples_per_prompt"),
                                            METHODOLOGY_FREEZE_REL + " population.samples_per_prompt")),
        ("frozen_total_base_cells", count(freeze_population.get("total_base_cells"),
                                          METHODOLOGY_FREEZE_REL + " population.total_base_cells")),
        ("composite_base_per_block", count(OrderedDict((b, base.get(b)) for b in pc.BLOCKS),
                                           "composite cells.base_per_block")),
        ("expected_population", count(OrderedDict(pc.EXPECTED_POPULATION),
                                      "thesis/recovery_successor_005/composite.py EXPECTED_POPULATION")),
        ("composite_base_equals_expected_population",
         ev(OrderedDict((b, base.get(b) == expected_base[b]) for b in pc.BLOCKS),
            "comparison composite cells.base_per_block vs composite.py EXPECTED_POPULATION "
            "(the population section fails the closure on a mismatch)")),
        ("composite_population", count(OrderedDict([("base_cells", (document.get("population") or {}).get("base_cells")),
                                                    ("per_run", OrderedDict((document.get("population") or {}).get("per_run") or {}))]),
                                       "composite population")),
        ("reuse_policies", ev(OrderedDict([(core.PILOT, (pilot.get("reuse_policy") or {}).get("policy")),
                                           (core.PARENT, (parent.get("reuse_policy") or {}).get("policy"))]),
                              pilot_rel + " / " + parent_rel + " reuse_policy.policy")),
    ])
    sources = [source(ctx.root, pilot_rel), source(ctx.root, parent_rel), source(ctx.root, METHODOLOGY_FREEZE_REL),
               composite_source(ctx.root, document)]
    return _item("one_generation_per_base_cell", COMPUTED, sources, evidence)


def excluded_answers(root, run):
    """Generation rows and model files under raw/<run> (the excluded run)."""
    base = Path(root).resolve() / core.RAW_REL / run
    files = sorted(base.glob("*/generations.jsonl")) if base.is_dir() else []
    rows = 0
    relatives = []
    for path in files:
        relative = path.relative_to(Path(root).resolve()).as_posix()
        relatives.append(relative)
        rows += sum(1 for _ in _stream(path))
    return OrderedDict([("raw_dir_exists", base.is_dir()), ("model_files", len(files)), ("answers", rows),
                        ("files", relatives)])


def item_excluded(ctx, inputs):
    table = ctx.table
    source_runs = Counter(target.source_run for target in table.targets)
    entries = OrderedDict()
    sources = []
    for run in core.EXCLUDED_RUNS:
        answers = excluded_answers(ctx.root, run)
        if source_runs.get(run):
            raise core.ClosureRefused("excluded run %s is a phase-2 target source" % run)
        entries[run] = OrderedDict([
            ("raw_dir_exists", answers["raw_dir_exists"]),
            ("intermediate_dir_exists", (ctx.root / core.INTERMEDIATE_REL / run).is_dir()),
            ("model_files", answers["model_files"]), ("answers", answers["answers"]),
            ("phase2_targets_with_this_source_run", int(source_runs.get(run, 0))),
            ("in_study_run_dirs", run in study_run_dirs(ctx.root)),
        ])
        sources.extend(source(ctx.root, rel) for rel in answers["files"])
    evidence = OrderedDict([
        ("excluded_runs", ev(list(core.EXCLUDED_RUNS), LINEAGE_MODULE_REL + " EXCLUDED_HISTORICAL_RUNS")),
        ("per_run", ev(entries, "raw/<run>/*/generations.jsonl rows; frozen target table source_run; "
                                "results tree directories")),
        ("answers_per_run", count(OrderedDict((run, e["answers"]) for run, e in entries.items()),
                                  "raw/<run>/*/generations.jsonl rows")),
        ("phase2_targets_with_excluded_source", count(OrderedDict((run, e["phase2_targets_with_this_source_run"])
                                                                  for run, e in entries.items()),
                                                      "frozen target table source_run")),
        ("answers_total", count(sum(e["answers"] for e in entries.values()), "raw/<run>/*/generations.jsonl rows")),
        ("targets_sha256", ev(table.sha256, "frozen phase-2 target table")),
        ("statement", ev("the excluded run is never a phase-2 target source and never a study results directory",
                         "frozen target table + study_run_dirs(root)")),
    ])
    return _item("excluded_aborted_parent_repair", COMPUTED, sources, evidence)


def item_incidents(ctx, inputs):
    reports = _need(inputs, "phase2_reports")
    incidents = phase2_incidents(reports)
    history = stage_history(ctx.root)
    per_stage = OrderedDict((stage, OrderedDict((k, v) for k, v in entry.items() if k != "last_open_items"))
                            for stage, entry in history["stages"].items())
    open_items = OrderedDict((stage, entry["last_open_items"]) for stage, entry in history["stages"].items())
    sources = [source(ctx.root, STAGE_HISTORY_REL)] + \
              [source(ctx.root, core.PHASE2_VERIFICATION_REL + "/%s.phase2_verification.json" % model)
               for model in reports]
    evidence = OrderedDict([
        ("incident_totals", count(incidents["totals"], "phase-2 reports: %s detail + *%s repeated_build_groups"
                                  % (PHASE2_LEDGER_CHECK, PHASE2_PROVENANCE_SUFFIX))),
        ("incidents_per_model", ev(incidents["per_model"], "phase-2 reports per model")),
        ("stage_invocations", count(OrderedDict((s, OrderedDict((k, v) for k, v in e.items() if isinstance(v, int)))
                                                for s, e in per_stage.items()), STAGE_HISTORY_REL)),
        ("stage_last_status", ev(OrderedDict((s, e["last_status"]) for s, e in per_stage.items()), STAGE_HISTORY_REL)),
        ("stage_last_open_items", ev(open_items, STAGE_HISTORY_REL)),
        ("interrupted_invocations", count(history["interrupted_invocations"], STAGE_HISTORY_REL + ": invoked without completed")),
        ("history_rows", count(history["rows"], STAGE_HISTORY_REL)),
        ("models_reported", count(len(reports), "ctx.cache phase2_reports")),
    ])
    return _item("phase2_operational_incidents", COMPUTED, sources, evidence)


def item_scopes(ctx, inputs):
    scopes = verification_scopes(ctx.root, inputs.get("successor_reverification"))
    sources = [source(ctx.root, relative) for e in scopes["entries"] for relative in e["artifacts"]
               if not relative.startswith(core.ARTIFACT_DIR_REL)]
    evidence = OrderedDict([
        ("scopes", ev(scopes["entries"], "one persisted report per kind + closure constants")),
        ("scopes_distinct", ev(scopes["distinct"], "verification_scopes")),
        ("retrospective_reverification", ev(scopes["retrospective"] or "not available (coverage section not run)",
                                            "ctx.cache successor_reverification")),
    ])
    return _item("verification_scopes", ARTIFACT_BOUND, sources, evidence)


ITEM_BUILDERS = OrderedDict([
    ("policy_mandatory_sources", item_policy_sources),
    ("pilot_label", item_pilot_label),
    ("max_two_repair_iterations", item_max_iterations),
    ("reasoning_policy_differences", item_reasoning),
    ("cleaning_and_pipeline_interventions", item_cleaning),
    ("baseline_incompatibilities", item_baseline),
    ("static_analysis_gaps", item_static_gaps),
    ("dynamic_analysis_gaps", item_dynamic_gaps),
    ("tool_timeouts_and_errors", item_timeouts),
    ("single_tool_finding_validity", item_single_tool),
    ("numerical_tolerance", item_numerical),
    ("frozen_thread_rank_configuration", item_launch),
    ("infer_runtime_outlier", item_infer),
    ("one_generation_per_base_cell", item_one_generation),
    ("excluded_aborted_parent_repair", item_excluded),
    ("phase2_operational_incidents", item_incidents),
    ("verification_scopes", item_scopes),
])


# -- the register ------------------------------------------------------------------------------------

def disclosure_register(ctx, inputs=None):
    """The register document: every item built from the inputs; an item
    whose producer is missing is INPUT_UNAVAILABLE, a failing builder is
    BUILD_FAILED (both reported, both fail the section). Self-hashed,
    deterministic (no timestamps)."""
    inputs = inputs if inputs is not None else gather_inputs(ctx)
    items = []
    for item_id, builder in ITEM_BUILDERS.items():
        try:
            items.append(builder(ctx, inputs))
        except Unavailable as error:
            items.append(_placeholder(item_id, INPUT_UNAVAILABLE, str(error)))
        except Exception as error:  # noqa: BLE001 - every failure is reported in the item
            items.append(_placeholder(item_id, BUILD_FAILED, "%s: %s" % (type(error).__name__, error)))
    register = OrderedDict([
        ("schema_version", core.DISCLOSURES_SCHEMA),
        ("closure_id", core.CLOSURE_ID),
        ("run_ids", list(core.RUNS)),
        ("status_definitions", OrderedDict([
            (ARTIFACT_BOUND, "an existing artifact carries the disclosure text"),
            (COMPUTED, "the numbers are computed from the artifacts by the closure"),
            (AUTHOR_TEXT_REQUIRED, "the thesis text must state it; the closure provides the facts"),
            (INPUT_UNAVAILABLE, "a producer section did not deliver its input (section FAIL)"),
            (BUILD_FAILED, "the item builder failed (section FAIL)")])),
        ("items", items),
    ])
    register = core.json_stable(register)
    register["register_sha256"] = core.self_hash(register, "register_sha256")
    return register


# -- checks (ok, detail) -------------------------------------------------------------------------------

def _int_leaves(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, dict):
        return all(_int_leaves(v) for v in value.values())
    if isinstance(value, list):
        return all(_int_leaves(v) for v in value)
    return False


def _number_leaves(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, dict):
        return all(_number_leaves(v) for v in value.values())
    if isinstance(value, list):
        return all(_number_leaves(v) for v in value)
    return False


def source_problems(root, item, write_mode=False):
    """Every source exists with its recorded raw sha256; the only exception
    is the not-yet-persisted composite in dry-run mode (identified by its
    composite_sha256)."""
    problems = []
    root = Path(root).resolve()
    for entry in item.get("sources") or []:
        relative = entry.get("relative")
        if not relative:
            problems.append("source without path")
            continue
        if entry.get("raw_sha256") is None:
            if entry.get("persisted") is False and entry.get("composite_sha256") and not write_mode:
                continue
            problems.append("%s: no raw sha256" % relative)
            continue
        path = root / relative
        if not path.is_file():
            problems.append("%s: missing" % relative)
            continue
        if core.raw_sha256(root, relative) != entry["raw_sha256"]:
            problems.append("%s: changed since the register was built" % relative)
    return problems


def register_check(root, register, write_mode=False):
    """Ids in order, every item in a final status, every source valid,
    every count an int (no None where a count is expected)."""
    problems = []
    items = register.get("items") or []
    ids = [item.get("id") for item in items]
    if ids != list(ITEM_IDS):
        problems.append("item ids differ from the fixed register order")
    for item in items:
        if item.get("status") not in FINAL_STATUSES:
            problems.append("%s: status %s (%s)" % (item.get("id"), item.get("status"),
                                                    ((item.get("evidence") or {}).get("problem") or {}).get("value")))
        if not item.get("sources"):
            problems.append("%s: no sources" % item.get("id"))
        problems.extend("%s: %s" % (item.get("id"), p) for p in source_problems(root, item, write_mode))
        for name, entry in (item.get("evidence") or {}).items():
            if not isinstance(entry, dict):
                continue
            if entry.get("kind") == "count" and not _int_leaves(entry.get("value")):
                problems.append("%s.%s: count with a non-integer or None leaf" % (item.get("id"), name))
            if entry.get("kind") == "number" and not _number_leaves(entry.get("value")):
                problems.append("%s.%s: number with a non-numeric or None leaf" % (item.get("id"), name))
    statuses = pc.counts(Counter(str(item.get("status")) for item in items))
    detail = OrderedDict([("items", len(items)), ("statuses", statuses),
                          ("register_sha256", register.get("register_sha256")),
                          ("problems", problems[:EXAMPLES * 3]), ("problem_count", len(problems))])
    return not problems, detail


def evidence_problems(register):
    """Every evidence entry names its source (no numbers from memory)."""
    problems = []
    for item in register.get("items") or []:
        evidence = item.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            problems.append("%s: no evidence" % item.get("id"))
            continue
        for name, entry in evidence.items():
            if not isinstance(entry, dict) or "value" not in entry:
                problems.append("%s.%s: not an evidence entry" % (item.get("id"), name))
                continue
            if not isinstance(entry.get("source"), str) or not entry["source"].strip():
                problems.append("%s.%s: no source" % (item.get("id"), name))
            if entry.get("kind") not in KINDS:
                problems.append("%s.%s: unknown kind %r" % (item.get("id"), name, entry.get("kind")))
    return problems


def evidence_check(register):
    problems = evidence_problems(register)
    entries = sum(len(item.get("evidence") or {}) for item in register.get("items") or [])
    return not problems, OrderedDict([("evidence_entries", entries), ("problems", problems[:EXAMPLES * 3]),
                                      ("problem_count", len(problems))])


def _find_item(register, item_id):
    for item in register.get("items") or []:
        if item.get("id") == item_id:
            return item
    raise core.ClosureRefused("register lacks item " + item_id)


def policy_sources_check(register):
    item = _find_item(register, "policy_mandatory_sources")
    if item.get("status") != ARTIFACT_BOUND:
        return False, OrderedDict([("status", item.get("status"))])
    entries = item["evidence"]["entries"]["value"]
    unsatisfied = [e.get("id") for e in entries if not e.get("satisfied")]
    return bool(entries) and not unsatisfied, OrderedDict([("sources", len(entries)), ("unsatisfied", unsatisfied)])


def infer_outlier_check(register):
    """The scan must find the study's known outlier: at least one entry
    above the threshold (a scan that finds none is broken)."""
    item = _find_item(register, "infer_runtime_outlier")
    if item.get("status") != COMPUTED:
        return False, OrderedDict([("status", item.get("status"))])
    evidence = item["evidence"]
    above = evidence["above_threshold"]["value"]
    maximum = evidence["max_seconds"]["value"]
    threshold = evidence["threshold_seconds"]["value"]
    ok = isinstance(above, int) and above >= 1 and isinstance(maximum, (int, float)) and maximum > threshold
    return ok, OrderedDict([("above_threshold", above), ("max_seconds", maximum), ("threshold_seconds", threshold),
                            ("top", evidence["top_entries"]["value"][:1]), ("infer_entries", evidence["infer_entries"]["value"])])


# -- section ------------------------------------------------------------------------------------------------

def collect(ctx):
    section = core.Section(SECTION)
    missing = [key for key in CACHE_KEYS if ctx.cache.get(key) is None]
    section.add("inputs_available", not missing,
                OrderedDict([("missing", missing), ("note", "input unavailable" if missing else None)]))
    try:
        register = ctx.timed("disclosures.register", disclosure_register, ctx)
    except Exception as error:  # noqa: BLE001 - fail-closed
        section.add("register_built", False, "%s: %s" % (type(error).__name__, error))
        return section
    ctx.cache["disclosure_register"] = register
    section.guard("register_built", register_check, ctx.root, register, bool(ctx.options.get("write")))
    section.guard("policy_sources_ok", policy_sources_check, register)
    section.guard("infer_outlier_found", infer_outlier_check, register)
    section.guard("no_numbers_from_memory", evidence_check, register)
    statuses = pc.counts(Counter(str(item.get("status")) for item in register["items"]))
    scan = ctx.cache.get("infer_scan") or OrderedDict()
    section.data["register"] = OrderedDict([("items", len(register["items"])), ("statuses", statuses),
                                            ("register_sha256", register["register_sha256"])])
    section.data["infer_scan"] = OrderedDict([("files", scan.get("files")), ("infer_entries", scan.get("infer_entries")),
                                              ("max_seconds", scan.get("max_seconds")),
                                              ("above_threshold", scan.get("above_threshold")),
                                              ("top", list(scan.get("top") or [])[:1])])
    section.data["markdown_bytes"] = len(render_markdown(register).encode("utf-8"))
    return section


# -- markdown ---------------------------------------------------------------------------------------------

def _cell_text(value, limit=600):
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    text = text.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    if len(text) > limit:
        text = text[:limit] + " ..."
    return text


def render_markdown(register):
    """One table per item (sources, evidence); English like the code."""
    items = register.get("items") or []
    lines = ["# Disclosure register - %s" % register.get("closure_id"), "",
             "schema `%s`; register_sha256 `%s`; runs: %s" % (register.get("schema_version"),
                                                              register.get("register_sha256"),
                                                              ", ".join(register.get("run_ids") or [])), "",
             "| # | id | title | applies to | status |", "|---|---|---|---|---|"]
    for n, item in enumerate(items, 1):
        lines.append("| %d | `%s` | %s | %s | %s |" % (n, item.get("id"), _cell_text(item.get("title")),
                                                       item.get("applies_to"), item.get("status")))
    lines.append("")
    for n, item in enumerate(items, 1):
        lines.extend(["## %d. %s" % (n, item.get("title")), "",
                      "- id: `%s`" % item.get("id"),
                      "- requirement: %s" % _cell_text(item.get("requirement")),
                      "- applies to: %s" % item.get("applies_to"),
                      "- status: %s" % item.get("status")])
        if item.get("narrative"):
            lines.append("- narrative: %s" % _cell_text(item["narrative"]))
        lines.extend(["", "| source | raw sha256 |", "|---|---|"])
        for entry in item.get("sources") or []:
            sha = entry.get("raw_sha256") or ("in memory, composite_sha256 %s" % entry.get("composite_sha256"))
            lines.append("| `%s` | %s |" % (entry.get("relative"), sha))
        lines.extend(["", "| evidence | value | source |", "|---|---|---|"])
        for name, entry in (item.get("evidence") or {}).items():
            value = entry.get("value") if isinstance(entry, dict) else entry
            src = entry.get("source") if isinstance(entry, dict) else ""
            lines.append("| %s | %s | %s |" % (name, _cell_text(value), _cell_text(src)))
        lines.append("")
    return "\n".join(lines) + "\n"


# -- CLI ------------------------------------------------------------------------------------------------------

def _load_shared(ctx, compute_composite):
    """What run.py's study section would have cached: the census and the
    persisted phase-2 reports (cheap), the composite only on request."""
    from thesis.recovery_successor_004 import census
    from thesis.recovery_successor_005 import plan as pp

    if ctx.cache.get("census") is None:
        ctx.cache["census"] = census.census(ctx.root, list(core.MODELS))
        ctx.cache["census_summary"] = census.summary(ctx.cache["census"])
    if ctx.cache.get("phase2_reports") is None:
        reports = OrderedDict()
        for model in core.MODELS:
            reports[model] = core.read_json(ctx.root, core.PHASE2_VERIFICATION_REL + "/%s.phase2_verification.json" % model)
        ctx.cache["phase2_reports"] = reports
    if compute_composite and ctx.cache.get("composite_cells") is None:
        ctx.log("reconstructing the composite cells (minutes)")
        plan_summary = pp.summary(pp.plan(ctx.root, ctx.config, ctx.table, strict=True))
        cells = list(pc.iter_cells(ctx.root, ctx.config, ctx.table))
        ctx.cache["composite_cells"] = cells
        ctx.cache["composite_document"] = pc.composite_document(ctx.root, ctx.config, ctx.table, ctx.lineage.sha256,
                                                                plan_summary["totals"], cells=cells)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="study disclosure register (read-only)")
    parser.add_argument("--print", action="store_true", help="print the register JSON (default)")
    parser.add_argument("--markdown", action="store_true", help="print the markdown rendering instead")
    parser.add_argument("--compute-composite", action="store_true",
                        help="reconstruct the composite cells first (minutes); otherwise the composite-derived "
                             "items are INPUT_UNAVAILABLE")
    parser.add_argument("--root", default=str(core.REPO_ROOT))
    args = parser.parse_args(argv)
    pl.isolate_providers()
    ctx = core.load_context(Path(args.root).resolve(), log=lambda message: sys.stderr.write(message + "\n"))
    _load_shared(ctx, args.compute_composite)
    register = disclosure_register(ctx)
    if args.markdown:
        sys.stdout.write(render_markdown(register))
    else:
        sys.stdout.write(json.dumps(register, indent=1, default=str) + "\n")
    return 0 if register_check(ctx.root, register)[0] else 1


if __name__ == "__main__":
    raise SystemExit(main())
