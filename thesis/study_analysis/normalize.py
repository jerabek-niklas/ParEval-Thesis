"""Normalization of the verified study into the seven analysis tables
(core.SCHEMAS) - the ONLY module of the package that reads result files.

Every stage record is read through the authorized phase-2 readers, with the
presence and ownership semantics the composite (phase2_composite.v1) and the
phase-2 verifier used:

  pilot     pc.pilot_targets (pilot_002 and its iteration runs, read in
            place), pt.historical_records, pc.enhanced_by_sample; every stage
            is owned by pilot_002 (as the composite labels it)
  full_ext  the frozen phase-2 target table: pg.merged_static with
            pc.static_owners, pg.present_records (correctness, dynamic) and
            pg.phase2_enhanced (owner full_ext_phase2_001)
  loops     the census (cs.census) and each loop's own state ledger
            (state.jsonl; a continued loop: recovery_001's rows followed by
            the owner's rows), wave_state.json and request_rounds.json
  raw       raw/<source_run>/<model>/generations.jsonl

Why fail closed everywhere: these tables are the population of every metric.
Missing, duplicate, foreign or contradictory evidence would silently move a
numerator or a denominator, so it raises core.AnalysisRefused instead of
being skipped or defaulted (reader refusals are re-raised as such).

Conservative readings of the methodology (documented decisions):
  * tool state = framework.effective_tool_state(record, tool)[0]: a
    front-end rejection that the compiler's build failure subsumes is
    NOT_ANALYZED instead of the stored TOOL_ERROR/PARTIAL. Both are analysis
    gaps, so no three-state verdict changes; the composite's static summary
    keeps the stored state - the differences are counted in
    provenance["effective_state_overrides"].
  * the frozen tool scope (pg.static_settings / pg.dynamic_settings) decides
    applicability; a recorded entry that contradicts it (an applicable tool
    recorded NOT_APPLICABLE, an inapplicable tool recorded with any other
    state) or a tool outside the frozen tool set refuses.
  * a reported blocking finding of an applicable analysis tool makes the
    stage DIRTY whatever the tool's state (finding_rules: "from any applicable
    tool"); low-confidence findings never do. Recorded decision: this keeps
    the frozen literal rule although framework.tool_verdict gives
    DEFECT_FOUND only for COMPLETED / PARTIAL entries and tool_state_rules
    call TIMEOUT / TOOL_ERROR / NOT_ANALYZED gaps "never confirmed program
    defects". Why literal: the methodology was frozen before aggregation and
    metrics.py / validate.py recompute the same literal rule from
    tool_entries; narrowing it after the counts are known would be a
    post-hoc definition change. The real data has such cases (clang_tidy
    entries the compiler's build failure relabels NOT_ANALYZED that carry
    bugprone-* findings printed before the front-end error), so they are
    disclosed instead: provenance["dirty_only_from_gap_state_entries"]
    counts the artifacts (per stage/block/population) that are DIRTY only
    through entries in a TIMEOUT / TOOL_ERROR / NOT_ANALYZED state, and the
    contributing entries per tool/state; three_state(rows, tools,
    VERDICT_STATES) gives the framework.tool_verdict reading for a
    sensitivity analysis (such an artifact becomes NO_FINDING_INCOMPLETE).
  * a stage without any applicable tool refuses (an empty all() would make
    "no analysis at all" CLEAN_COMPLETE and analysis-complete).
  * an assembly row that is not assembled refuses: the readers drop such rows
    and the methodology has no population rule for them (none exist).
  * exactly one generation row per artifact, and every row of a generation
    file belongs to an artifact (a stray row would be a generated answer
    outside the population).
  * request_rounds.json must record exactly the iterations 1..final of a
    sample (continued loops: iteration 1 in recovery_001's file, iteration 2
    in the owner's) with positive integer counts; a candidate without a
    recorded request, or a request without a candidate, refuses.
  * every artifact carries exactly its expected enhanced pair set
    (pg.expected_enhanced over the frozen specs, the verifier's rule).
  * an ABSENT_INAPPLICABLE slot has ran false, no duration, zero counts and
    the static record owner as its owner.
  * the target table's census_digest must equal the digest of the census
    the trajectories are read from.
  * source binding of the stage records: a static record must carry
    sample_source_sha256 equal to the target's source (every real static
    record does); a phase-2 correctness / dynamic record carries
    candidate_source_sha256 (checked by the reader and again here); the
    historical correctness / dynamic records carry no source hash and are
    bound only by (run_id, model_id, sample_id, execution_model) plus the
    assembly binding of the run (one source per sample and run).
  * usage_normalized must carry input_tokens, output_tokens and
    reasoning_tokens; only reasoning_tokens may be null (C02: "provider
    reports no field"), a null input / output count refuses.
  * the frozen spec artifact (pg.frozen_specs_path) and the input shapes
    the spec validator reads (thesis.enhanced_tests.specs.SHAPES_PATH)
    decide the expected pair set, so both are required inputs: a missing
    file refuses (the readers would silently fall back to built-in specs /
    a 1-D default shape) and both are hashed into files_read (the shapes
    file is the specs module's own: outside a synthetic root its hash is
    kept in provenance["enhanced_inputs"] instead).

Deterministic: rows follow the target order (pilot: MODELS order and
pc.pilot_targets order, then the frozen table order) and each target's
sample order; pairs follow the expected spec order; no timestamps.
Python 3.8 compatible syntax; stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.study_analysis import core
from thesis.evaluation import framework
from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path
from thesis.recovery_successor_004 import census as cs
from thesis.recovery_successor_005 import composite as pc
from thesis.recovery_successor_005 import ledger as pg
from thesis.recovery_successor_005 import lineage as pl
from thesis.recovery_successor_005 import targets as pt

READERS = (
    "thesis.recovery_successor_005.composite", "thesis.recovery_successor_005.ledger",
    "thesis.recovery_successor_005.targets", "thesis.recovery_successor_004.census",
    "thesis.evaluation.successor_supplement", "thesis.evaluation.framework",
    "thesis.evaluation.finding_classes", "thesis.enhanced_tests.specs",
)
PILOT_BLOCK, FULL_BLOCK = core.BLOCKS
VALID_STATUSES = tuple(s for s in core.ENHANCED_STATUSES if s not in core.ENHANCED_GATED)
CLEAN_FIELDS = OrderedDict([
    # flag -> (cleaning key, expected type, rule)
    ("used_fence", ("used_fence", bool, lambda v: v)),
    ("dropped_leading_lines", ("dropped_leading_lines", int, lambda v: v > 0)),
    ("dropped_trailing_lines", ("dropped_trailing_lines", int, lambda v: v > 0)),
    ("dropped_duplicated_prompt_lines", ("dropped_duplicated_prompt_lines", int, lambda v: v > 0)),
    ("relocated_includes", ("relocated_includes", list, lambda v: len(v) > 0)),
    ("auto_closed", ("auto_closed", bool, lambda v: v)),
    ("signature_suspect", ("signature_suspect", bool, lambda v: v)),
    ("braces_unbalanced", ("braces_balanced", bool, lambda v: not v)),
])
TIMING_MODES = ("direct", "batch")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens")
NULLABLE_TOKEN_FIELDS = ("reasoning_tokens",)
# the states in which framework.tool_verdict turns a blocking finding into
# DEFECT_FOUND (COMPLETED, PARTIAL), and the gap states in which it never does
VERDICT_STATES = tuple(s for s in core.TOOL_STATES if s in framework.ANALYSIS_STATES
                       and framework.tool_verdict(s, 1) == framework.VERDICT_DEFECT_FOUND)
VERDICTLESS_GAP_STATES = tuple(s for s in core.GAP_STATES if s not in VERDICT_STATES)
# reader caught errors that are refusals of the evidence (AttributeError: a
# parsed value of the wrong JSON type reached a .get())
READER_ERRORS = (RecoveryRefused, KeyError, TypeError, ValueError, AttributeError, OSError)


def _refuse(message, *args):
    raise core.AnalysisRefused(message % args if args else message)


def _relative(root, path, what):
    """Root-relative POSIX path of a reader's input file (must lie under root)."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        _refuse("%s %s lies outside the analysed root %s", what, path, root)


# the frozen spec artifact of the code checkout (build_dataset derives it per root)
FROZEN_SPECS_REL = _relative(core.REPO_ROOT, pg.frozen_specs_path(core.REPO_ROOT), "the frozen spec artifact")


# -- typed accessors (a wrong type is contradictory evidence) --------------------

def _bool(value, what):
    if type(value) is not bool:
        _refuse("%s is not a boolean (%r)", what, value)
    return value


def _int(value, what, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        _refuse("%s is not an integer%s (%r)", what, "" if minimum is None else " >= %d" % minimum, value)
    return value


def _opt_int(value, what):
    return None if value is None else _int(value, what)


def _opt_float(value, what):
    if value is None:
        return None
    if type(value) not in (int, float):
        _refuse("%s is not a number (%r)", what, value)
    return float(value)


def _str(value, what):
    if not isinstance(value, str):
        _refuse("%s is not a string (%r)", what, value)
    return value


def _dict(value, what):
    if not isinstance(value, dict):
        _refuse("%s is not an object (%r)", what, type(value).__name__)
    return value


# -- files read (relative -> raw sha256, every file hashed once) -----------------

class FilesRead:
    """The input files of the dataset. Own reads go through read(); files a
    reader opened are recorded by rule with note() (hashed once, if they
    exist) or note_hash() (the reader verified the bytes against a hash)."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.sha = OrderedDict()

    def _record(self, relative, digest):
        prior = self.sha.get(relative)
        if prior is not None and prior != digest:
            _refuse("input file changed during the normalization: %s", relative)
        self.sha[relative] = digest

    def read(self, relative):
        data = checked_path(self.root, relative).read_bytes()
        self._record(relative, hashlib.sha256(data).hexdigest())
        return data

    def exists(self, relative):
        return checked_path(self.root, relative).is_file()

    def note(self, relative):
        if relative not in self.sha and self.exists(relative):
            self.read(relative)

    def note_hash(self, relative, digest):
        self._record(relative, digest)

    def sorted(self):
        return OrderedDict(sorted(self.sha.items()))


def _jsonl_rows(data, relative):
    """Strict JSONL (a torn tail refuses) whose every line is an object."""
    try:
        rows = pt._jsonl_bytes(data, relative)
    except (RecoveryRefused, ValueError, UnicodeDecodeError) as error:
        _refuse("unreadable JSONL %s: %s", relative, error)
    for number, row in enumerate(rows, 1):
        _dict(row, "%s row %d" % (relative, number))
    return rows


def _jsonl(files, relative):
    """Strict JSONL of an own read."""
    return _jsonl_rows(files.read(relative), relative)


def _json(files, relative):
    try:
        return json.loads(files.read(relative).decode("utf-8"), object_pairs_hook=OrderedDict)
    except (ValueError, UnicodeDecodeError) as error:
        _refuse("unreadable JSON %s: %s", relative, error)


def _repair_rel(run, model, variant, name):
    return "%s/%s/%s/repair/%s/%s" % (pt.INTERMEDIATE_REL, run, model, variant, name)


# -- settings, census ----------------------------------------------------------

def _models(models):
    models = list(models) if models else list(core.MODELS)
    if not models or len(models) != len(set(models)) or [m for m in models if m not in core.MODELS] \
            or models != [m for m in core.MODELS if m in models]:
        _refuse("not a MODELS-ordered subset of the study models: %s", models)
    return models


def tool_settings(config):
    """(static, dynamic) ToolSettings in core tool order; the enabled tool
    sets of the phase-2 config must be exactly the methodology's tools."""
    static, dynamic = pg.static_settings(config), pg.dynamic_settings(config)
    if set(static) != set(core.STATIC_TOOLS) or set(dynamic) != set(core.DYNAMIC_TOOLS):
        _refuse("enabled tools %s / %s are not the methodology tools", list(static), list(dynamic))
    return (OrderedDict((t, static[t]) for t in core.STATIC_TOOLS),
            OrderedDict((t, dynamic[t]) for t in core.DYNAMIC_TOOLS))


def census_binding(census_result, models, table=None):
    """The census covers every (block, model, variant) loop once, every loop
    is TERMINAL, and (given a table) it is the census the table was built on."""
    if list(census_result.get("models") or []) != list(models):
        _refuse("the census covers %s, not %s", census_result.get("models"), models)
    loops = census_result.get("loops") or []
    keys = [(l.get("block"), l.get("model"), l.get("variant")) for l in loops]
    expected = [(b, m, v) for b in core.BLOCKS for m in models for v in core.VARIANTS]
    if len(keys) != len(set(keys)) or sorted(keys) != sorted(expected):
        _refuse("the census loops are not exactly blocks x models x variants")
    open_loops = ["%s/%s/%s" % k for k, l in zip(keys, loops) if l.get("terminal") is not True
                  or l.get("state") != "TERMINAL"]
    if open_loops:
        _refuse("repair loops not terminal: %s", open_loops[:5])
    summary = cs.summary(census_result)
    if summary["total_repair_loops_done"] != "%d/%d" % (len(expected), len(expected)):
        _refuse("census: %s repair loops terminal", summary["total_repair_loops_done"])
    digest = canonical_sha256(summary)
    if table is not None and table.document.get("census_digest") != digest:
        _refuse("the target table was frozen on another census (%s != %s)",
                table.document.get("census_digest"), digest)
    return summary, digest


# -- targets -------------------------------------------------------------------------

def iter_study_targets(root, table, models=None):
    """(block, target) in the deterministic study order: the pilot targets
    (MODELS order, pc.pilot_targets order: base run first), then the frozen
    table targets in table order."""
    root = Path(root).resolve()
    models = _models(models)
    for model in models:
        for target in pc.pilot_targets(root, model):
            yield PILOT_BLOCK, target
    for target in table.targets:
        if target.model_id in models:
            yield FULL_BLOCK, target


def _check_target(block, target):
    run, variant, iteration = target.source_run, target.variant, target.iteration
    if run in core.EXCLUDED_RUNS:
        _refuse("excluded run %s is a study target", run)
    if target.document.get("block") != block:
        _refuse("target %s is not a %s target", target.target_id, block)
    if iteration == 0:
        if variant is not None or run != core.BLOCK_BASE_RUN[block]:
            _refuse("base target %s is not the %s base run", target.target_id, block)
        return
    if variant not in core.VARIANTS or type(iteration) is not int or not 1 <= iteration <= core.MAX_ITERATIONS:
        _refuse("target %s is outside the repair design", target.target_id)
    if block == PILOT_BLOCK:
        if run != pt.iteration_run(core.PILOT, variant, iteration) or target.loop_owner != core.PILOT:
            _refuse("pilot candidate target %s is not a pilot_002 iteration run", target.target_id)
    elif (target.loop_owner not in core.OWNERS or not run.startswith("full_ext_")
            or not any(run == pt.iteration_run(owner, variant, iteration) for owner in core.OWNERS)):
        _refuse("full_ext candidate target %s is not an owner iteration run", target.target_id)


def _assembly(files, target):
    """sample_id -> assembly row of the target (the bytes the table / the
    pilot reader bound; every row assembled, every row a target sample)."""
    relative = target.document["assembly"]["path"]
    data = files.read(relative)
    if hashlib.sha256(data).hexdigest() != target.document["assembly"]["raw_sha256"]:
        _refuse("assembly drifted since it was bound: %s", relative)
    rows = OrderedDict()
    for row in _jsonl_rows(data, relative):
        sample_id = row.get("sample_id")
        if row.get("run_id") != target.source_run or row.get("model_id") != target.model_id or sample_id in rows:
            _refuse("foreign or duplicate assembly row %s in %s", sample_id, relative)
        if row.get("assembled") is not True:
            _refuse("non-assembled answer %s in %s (no population rule)", sample_id, relative)
        rows[sample_id] = row
    if list(rows) != list(target.samples):
        _refuse("assembly rows of %s differ from the target samples", target.target_id)
    for sample_id, row in rows.items():
        facts = target.samples[sample_id]
        if (row.get("source_sha256") != facts["source_sha256"] or row.get("benchmark") != facts["benchmark"]
                or row.get("execution_model") != facts["execution_model"]):
            _refuse("assembly facts of %s contradict the target", sample_id)
    return rows


def _assembly_columns(row, what):
    cleaning = row.get("cleaning")
    if not isinstance(cleaning, dict):
        _refuse("%s has no cleaning block", what)
    flags = OrderedDict()
    for flag, (key, kind, rule) in CLEAN_FIELDS.items():
        value = cleaning.get(key)
        if (type(value) is not kind) if kind is not list else not isinstance(value, list):
            _refuse("%s cleaning.%s is not %s (%r)", what, key, kind.__name__, value)
        flags["clean_" + flag] = bool(rule(value))
    columns = OrderedDict([("assembled", _bool(row.get("assembled"), what + " assembled")),
                           ("generation_truncated", _bool(row.get("generation_truncated"),
                                                          what + " generation_truncated"))])
    columns.update(flags)
    columns["clean_any"] = any(v for k, v in flags.items() if k != "clean_used_fence")
    columns["clean_any_including_fence"] = any(flags.values())
    return columns


def _generations(files, target):
    """sample_id -> the raw generation row of the target's run (one per sample)."""
    relative = "%s/%s/%s/generations.jsonl" % (pt.RAW_REL, target.source_run, target.model_id)
    if not files.exists(relative):
        _refuse("missing generation records %s", relative)
    rows = OrderedDict()
    for row in _jsonl(files, relative):
        sample_id = row.get("sample_id")
        if (row.get("run_id") != target.source_run or (row.get("model") or {}).get("id") != target.model_id
                or sample_id in rows):
            _refuse("foreign or duplicate generation row %s in %s", sample_id, relative)
        rows[sample_id] = row
    stray = [sid for sid in rows if sid not in target.samples]
    if stray:
        _refuse("generation rows without an artifact in %s: %s", relative, stray[:3])
    return rows


def _generation_row(artifact_id, row, target, what):
    if row is None:
        _refuse("no generation record for %s", what)
    status = _dict(row.get("status"), what + " status")
    repair = row.get("repair")
    if target.iteration == 0:
        if repair is not None:
            _refuse("base generation %s carries a repair block", what)
        kind, request_chars = "base", None
    else:
        repair = _dict(repair, what + " repair")
        if repair.get("iteration") != target.iteration or repair.get("variant") != target.variant:
            _refuse("repair generation %s belongs to another iteration/variant", what)
        kind, request_chars = "repair", _opt_int(repair.get("request_chars"), what + " request_chars")
    timing = status.get("timing_mode")
    if timing not in TIMING_MODES:
        _refuse("%s timing_mode %r", what, timing)
    usage = _dict((row.get("api_response") or {}).get("usage_normalized"), what + " usage_normalized")
    tokens = OrderedDict()
    for field in TOKEN_FIELDS:
        # an absent key is schema drift, not "provider reports no field"
        if field not in usage:
            _refuse("%s usage_normalized lacks %s", what, field)
        if usage[field] is None and field not in NULLABLE_TOKEN_FIELDS:
            _refuse("%s usage_normalized.%s is null", what, field)
        tokens[field] = _opt_int(usage[field], "%s %s" % (what, field))
    finish = (row.get("output") or {}).get("finish_reason")
    return OrderedDict([
        ("artifact_id", artifact_id), ("kind", kind),
        ("provider", _str((row.get("model") or {}).get("provider"), what + " provider")),
        ("success", _bool(status.get("success"), what + " status.success")), ("timing_mode", timing),
        # batch spans are queue time, never a latency (C03)
        ("duration_seconds", _opt_float(status.get("duration_seconds"), what + " duration")
         if timing == "direct" else None),
        ("input_tokens", tokens["input_tokens"]), ("output_tokens", tokens["output_tokens"]),
        ("reasoning_tokens", tokens["reasoning_tokens"]),
        ("request_chars", request_chars),
        ("finish_reason", "" if finish is None else _str(finish, what + " finish_reason")),
    ])


def _check_record(record, target, facts, stage):
    if record is None:
        _refuse("no %s record for %s/%s", stage, target.target_id, facts["sample_id"])
    if (record.get("run_id") != target.source_run or record.get("model_id") != target.model_id
            or record.get("sample_id") != facts["sample_id"]
            or record.get("execution_model") != facts["execution_model"]):
        _refuse("%s record of %s/%s carries a foreign identity", stage, target.target_id, facts["sample_id"])
    # static records always carry their source binding; the phase-2
    # correctness / dynamic records carry the candidate binding, the
    # historical ones none (module docstring)
    if stage == "static" and "sample_source_sha256" not in record:
        _refuse("static record of %s/%s carries no sample_source_sha256", target.target_id, facts["sample_id"])
    for field in ("sample_source_sha256", "candidate_source_sha256"):
        if field in record and record[field] != facts["source_sha256"]:
            _refuse("%s record of %s is bound to another source (%s)", stage, facts["sample_id"], field)
    return record


# -- tool entries, findings, three-state -------------------------------------------

def _stage_rows(artifact_id, stage, record, settings, execution_model, owner_of, record_owner, overrides):
    """(tool rows, finding rows) of one stage record over the frozen tools."""
    from thesis.evaluation.finding_classes import classify_finding

    tools = record.get("tools")
    if not isinstance(tools, dict):
        _refuse("%s record of %s has no tools", stage, artifact_id)
    foreign = sorted(set(tools) - set(settings))
    if foreign:
        _refuse("%s record of %s carries tools outside the frozen tool set: %s", stage, artifact_id, foreign)
    tool_rows, finding_rows = [], []
    for tool, settings_of in settings.items():
        what = "%s %s/%s" % (artifact_id, stage, tool)
        applicable = settings_of.applies_to(execution_model)
        entry = tools.get(tool)
        counts = Counter()
        if entry is None:
            if applicable:
                _refuse("no entry for the applicable tool %s", what)
            state, ran, duration, owner = "ABSENT_INAPPLICABLE", False, None, record_owner
        else:
            _dict(entry, what)
            state = framework.effective_tool_state(record, tool)[0]
            stored = framework.analysis_state_of(entry)
            if state != stored:
                overrides["%s/%s/%s->%s" % (stage, tool, stored, state)] += 1
            if state not in core.TOOL_STATES or state == "ABSENT_INAPPLICABLE":
                _refuse("state %r of %s", state, what)
            if applicable == (state == "NOT_APPLICABLE"):
                _refuse("state %s of %s contradicts the frozen scope (applicable=%s)", state, what, applicable)
            ran = _bool(entry.get("ran"), what + " ran")
            duration = _opt_float(entry.get("duration_seconds"), what + " duration")
            owner = owner_of(tool)
            findings = entry.get("findings")
            if not isinstance(findings, list):
                _refuse("%s has no findings list", what)
            if entry.get("num_findings") is not None and entry.get("num_findings") != len(findings):
                _refuse("%s num_findings contradicts its findings", what)
            for finding in findings:
                _dict(finding, what + " finding")
                blocking = _bool(finding.get("blocking"), what + " finding.blocking")
                low = _bool(finding.get("low_confidence"), what + " finding.low_confidence")
                kind = "low_confidence" if low else ("reported_blocking" if blocking else "non_blocking")
                counts[kind] += 1
                check_id = _str(finding.get("check_id"), what + " check_id")
                finding_rows.append(OrderedDict([
                    ("artifact_id", artifact_id), ("stage", stage), ("tool", tool), ("check_id", check_id),
                    ("family", classify_finding(tool, check_id, finding.get("message") or "")),
                    ("severity", _str(finding.get("severity"), what + " severity")), ("kind", kind),
                    ("line", _opt_int(finding.get("line"), what + " line"))]))
            counts["all"] = len(findings)
        tool_rows.append(OrderedDict([
            ("artifact_id", artifact_id), ("stage", stage), ("tool", tool), ("applicable", applicable),
            ("state", state), ("ran", ran), ("duration_seconds", duration), ("num_findings", counts["all"]),
            ("num_reported_blocking", counts["reported_blocking"]),
            ("num_low_confidence", counts["low_confidence"]), ("num_non_blocking", counts["non_blocking"]),
            ("owner", owner)]))
    return tool_rows, finding_rows


def _applicable(tool_rows, tools):
    """The applicable rows of `tools`; a stage without any refuses (no
    analysis at all is neither clean nor complete)."""
    rows = [r for r in tool_rows if r["tool"] in tools and r["applicable"]]
    if not rows:
        _refuse("no applicable tool of %s for %s", list(tools), tool_rows[0]["artifact_id"] if tool_rows else "?")
    return rows


def three_state(tool_rows, tools, finding_states=None):
    """finding_rules.analysis_verdict_three_state over the APPLICABLE tools
    of `tools`: DIRTY (>= 1 reported blocking finding), else CLEAN_COMPLETE
    (all COMPLETED), else NO_FINDING_INCOMPLETE (>= 1 analysis gap).

    finding_states None is the frozen rule (a finding of an applicable tool
    in any state); VERDICT_STATES counts only findings of COMPLETED /
    PARTIAL entries (framework.tool_verdict) - a sensitivity reading only."""
    rows = _applicable(tool_rows, tools)
    if any(r["num_reported_blocking"] for r in rows if finding_states is None or r["state"] in finding_states):
        return "DIRTY"
    if all(r["state"] == "COMPLETED" for r in rows):
        return "CLEAN_COMPLETE"
    if any(r["state"] in core.GAP_STATES for r in rows):
        return "NO_FINDING_INCOMPLETE"
    _refuse("no three-state verdict for %s", rows[0]["artifact_id"])


def analysis_complete(tool_rows, tools):
    """Every applicable tool of `tools` COMPLETED (>= 1 applicable tool)."""
    return all(r["state"] == "COMPLETED" for r in _applicable(tool_rows, tools))


def gap_state_dirty_entries(tool_rows, tools):
    """The applicable rows with reported blocking findings when the stage is
    DIRTY ONLY through entries in a TIMEOUT / TOOL_ERROR / NOT_ANALYZED
    state (no COMPLETED / PARTIAL entry carries one), else []."""
    rows = _applicable(tool_rows, tools)
    if any(r["num_reported_blocking"] for r in rows if r["state"] in VERDICT_STATES):
        return []
    return [r for r in rows if r["num_reported_blocking"]]


# -- enhanced pairs ---------------------------------------------------------------------

def _pairs(artifact_id, bucket, expected, what):
    """Pair rows in expected-spec order; the observed key set must be exactly
    the expected one."""
    bucket = bucket or OrderedDict()
    expected = expected or OrderedDict()
    if set(bucket) != set(expected):
        _refuse("enhanced pairs of %s: %d missing, %d unexpected", what, len(set(expected) - set(bucket)),
                len(set(bucket) - set(expected)))
    rows = []
    for key in expected:
        row = bucket[key]
        spec = _dict(row.get("spec"), what + " spec")
        status = row.get("status")
        if status not in core.ENHANCED_STATUSES:
            _refuse("enhanced status %r of %s", status, what)
        rows.append(OrderedDict([
            ("artifact_id", artifact_id), ("spec_key", key), ("size", _opt_int(spec.get("size"), what + " size")),
            ("pattern", _str(spec.get("pattern"), what + " pattern")),
            ("spec_source", _str(spec.get("source"), what + " spec source")), ("status", status),
            ("gated", status in core.ENHANCED_GATED),
            ("duration_seconds", _opt_float(row.get("duration_seconds"), what + " pair duration"))]))
    return rows


def _enhanced_columns(pairs):
    statuses = Counter(p["status"] for p in pairs)
    valid = sum(1 for p in pairs if not p["gated"])
    columns = OrderedDict([("enh_pairs", len(pairs)), ("enh_valid", valid), ("enh_gated", len(pairs) - valid)])
    for status in VALID_STATUSES:
        columns["enh_" + status] = statuses.get(status, 0)
    columns["enh_all_pass"] = None if valid == 0 else (1 if columns["enh_pass"] == valid else 0)
    return columns


# -- one target --------------------------------------------------------------------------

def _evidence(root, config, files, block, target):
    """The stage evidence of one target through the authorized readers, and
    the files those readers opened (recorded by rule)."""
    run, model = target.source_run, target.model_id
    stage_files = [pt.run_dir(run, model) + "/" + name
                   for name in (pt.STATIC_FILE, pt.CORRECTNESS_FILE, pt.DYNAMIC_FILE)]
    if block == PILOT_BLOCK:
        static = pt.historical_records(root, target, pt.STATIC_FILE)
        owners = OrderedDict((sid, OrderedDict((tool, core.PILOT) for tool in (record.get("tools") or {})))
                             for sid, record in static.items())
        correctness = OrderedDict((sid, (core.PILOT, r)) for sid, r in
                                  pt.historical_records(root, target, pt.CORRECTNESS_FILE).items())
        dynamic = OrderedDict((sid, (core.PILOT, r)) for sid, r in
                              pt.historical_records(root, target, pt.DYNAMIC_FILE).items())
        enhanced = pc.enhanced_by_sample(target, pc.pilot_enhanced_rows(root, target))
        record_owner, enhanced_owner = core.PILOT, core.PILOT
        stage_files.append(pt.run_dir(run, model) + "/" + pt.ENHANCED_FILE)
    else:
        from thesis.evaluation import successor_supplement as ss

        static = pg.merged_static(root, config, target)
        owners = pc.static_owners(root, config, target)
        correctness = pg.present_records(root, target, pt.CORRECTNESS_FILE)
        dynamic = pg.present_records(root, target, pt.DYNAMIC_FILE)
        enhanced = pg.phase2_enhanced(root, target)
        record_owner, enhanced_owner = run, core.PHASE2
        stage_files.extend(ss.supplement_relative(owner, model, run, tool)
                           for owner in pt.SUPPLEMENT_OWNERS for tool in pl.EXTERNAL_TOOLS)
        stage_files.extend(pt.ledger_relative(model, run, "static.%s.jsonl" % tool) for tool in core.STATIC_TOOLS)
        stage_files.extend(pt.ledger_relative(model, run, name)
                           for name in (pt.CORRECTNESS_FILE, pt.DYNAMIC_FILE, pt.ENHANCED_FILE))
    for relative in stage_files:
        files.note(relative)
    return static, owners, correctness, dynamic, enhanced, record_owner, enhanced_owner


def _normalize_target(root, config, files, block, target, settings, specs, out):
    static_settings, dynamic_settings = settings
    _check_target(block, target)
    model, run = target.model_id, target.source_run
    assembly = _assembly(files, target)
    generations = _generations(files, target)
    if block == PILOT_BLOCK:
        # the pilot reader re-hashed every source against its assembly row
        for facts in target.samples.values():
            files.note_hash(facts["source_path"], facts["source_sha256"])
    static, owners, correctness, dynamic, enhanced, record_owner, enhanced_owner = \
        _evidence(root, config, files, block, target)
    expected = pg.expected_enhanced(root, config, target, specs["llm"], specs["cache"])
    for benchmark in sorted(set(f["benchmark"] for f in target.samples.values())):
        files.note("drivers/cpp/benchmarks/%s/cpu.cc" % benchmark)
    for sample_id, facts in target.samples.items():
        what = "%s/%s" % (target.target_id, sample_id)
        artifact_id = core.artifact_id(block, model, run, sample_id)
        if artifact_id in out["artifact_ids"]:
            _refuse("duplicate artifact %s", artifact_id)
        out["artifact_ids"].add(artifact_id)
        execution_model = facts["execution_model"]
        if execution_model not in core.EXECUTION_MODELS:
            _refuse("execution model %r of %s", execution_model, what)
        # static (merged view; per-tool owners)
        record = _check_record(static.get(sample_id), target, facts, "static")
        tool_owner = owners.get(sample_id) or OrderedDict()
        if set(tool_owner) != set(record.get("tools") or {}):
            _refuse("static owners of %s do not match its merged record", what)
        static_rows, static_findings = _stage_rows(
            artifact_id, "static", record, static_settings, execution_model, lambda tool: tool_owner[tool],
            record_owner, out["overrides"])
        supplemented = OrderedDict((tool, by) for tool, by in tool_owner.items() if by != record_owner)
        # dynamic / correctness: (owner, record)
        d_owner, d_record = dynamic.get(sample_id) or (None, None)
        _check_record(d_record, target, facts, "dynamic")
        dynamic_rows, dynamic_findings = _stage_rows(
            artifact_id, "dynamic", d_record, dynamic_settings, execution_model, lambda tool: d_owner,
            d_owner, out["overrides"])
        c_owner, c_record = correctness.get(sample_id) or (None, None)
        _check_record(c_record, target, facts, "correctness")
        verdict = c_record.get("verdict")
        if verdict not in core.CORRECTNESS_VERDICTS:
            _refuse("correctness verdict %r of %s", verdict, what)
        build_ok = _bool(_dict(c_record.get("compile"), what + " compile").get("ok"), what + " compile.ok")
        pairs = _pairs(artifact_id, enhanced.get(sample_id), expected.get(sample_id), what)
        for pair in pairs:
            group = (block, facts["benchmark"], pair["spec_key"], execution_model)
            out["gates"].setdefault(group, set()).add(pair["gated"])
        generation = _generation_row(artifact_id, generations.get(sample_id), target, what)
        tool_rows = static_rows + dynamic_rows
        compiler = [r for r in static_rows if r["tool"] == "compiler"][0]
        verdicts = OrderedDict()
        population = "BASE" if target.iteration == 0 else "REPAIR_CANDIDATES"
        for stage, rows, tools in (("static", static_rows, core.STATIC_ANALYSIS_TOOLS),
                                   ("dynamic", dynamic_rows, core.DYNAMIC_TOOLS)):
            verdicts[stage] = (three_state(rows, tools), analysis_complete(rows, tools))
            gap_dirty = gap_state_dirty_entries(rows, tools)
            if gap_dirty:  # DIRTY by the frozen rule only (module docstring)
                out["gap_dirty"]["artifacts"]["%s/%s/%s" % (stage, block, population)] += 1
                for entry in gap_dirty:
                    out["gap_dirty"]["entries"]["%s/%s/%s/%s/%s" % (
                        stage, block, population, entry["tool"], entry["state"])] += 1
        row = OrderedDict([
            ("artifact_id", artifact_id), ("cell_id", core.cell_id(block, model, sample_id)), ("block", block),
            ("model_id", model), ("benchmark", facts["benchmark"]), ("family", core.family_of(facts["benchmark"])),
            ("execution_model", execution_model), ("sample_id", sample_id), ("variant", target.variant or ""),
            ("iteration", target.iteration), ("source_run", run),
            ("loop_owner", "" if target.iteration == 0 else target.loop_owner),
            ("source_sha256", facts["source_sha256"]), ("generation_success", generation["success"])])
        row.update(_assembly_columns(assembly[sample_id], what))
        row.update([
            ("build_ok", build_ok), ("correctness_verdict", verdict), ("correctness_owner", c_owner),
            ("static_owner", record_owner), ("static_supplemented_by", supplemented), ("dynamic_owner", d_owner),
            ("enhanced_owner", enhanced_owner),
            ("static_three_state", verdicts["static"][0]), ("dynamic_three_state", verdicts["dynamic"][0]),
            ("compile_error", compiler["num_reported_blocking"] > 0),
            ("low_confidence_any", any(r["num_low_confidence"] > 0 for r in tool_rows)),
            ("static_analysis_complete", verdicts["static"][1]),
            ("dynamic_analysis_complete", verdicts["dynamic"][1]),
        ])
        row.update(_enhanced_columns(pairs))
        out["artifacts"].append(row)
        out["tool_entries"].extend(tool_rows)
        out["findings"].extend(static_findings + dynamic_findings)
        out["enhanced_pairs"].extend(pairs)
        out["generations"].append(generation)
    return len(target.samples)


# -- trajectories ----------------------------------------------------------------------

def _candidate_run(block, owner, continued, variant, iteration):
    """The iteration run that holds a loop's iteration-k candidates (the rule
    pt.candidate_runs froze into the table)."""
    if block == PILOT_BLOCK:
        return pt.iteration_run(core.PILOT, variant, iteration)
    if continued and iteration == 1:
        return pt.iteration_run(cs.ORIGIN, variant, 1)
    return pt.iteration_run(owner, variant, iteration)


def _state_rows(files, run, model, variant):
    rows = _jsonl(files, _repair_rel(run, model, variant, "state.jsonl"))
    for row in rows:
        if row.get("run_id") != run or row.get("model_id") != model or row.get("variant") != variant:
            _refuse("foreign state row in %s", _repair_rel(run, model, variant, "state.jsonl"))
        _int(row.get("iteration"), "state row iteration", 0)
    return rows


def _request_rounds(files, run, model, variant):
    """sample_id -> {iteration: rounds} of one request_rounds.json ({} if absent)."""
    relative = _repair_rel(run, model, variant, "request_rounds.json")
    if not files.exists(relative):
        return OrderedDict()
    document = _dict(_json(files, relative), relative)
    rounds = OrderedDict()
    for sample_id, per in document.items():
        per = _dict(per, relative + " " + sample_id)
        parsed = OrderedDict()
        for key, value in per.items():
            if not str(key).isdigit():
                _refuse("request_rounds key %r in %s", key, relative)
            parsed[int(key)] = _int(value, "request rounds of %s" % sample_id, 1)
        rounds[sample_id] = parsed
    return rounds


def trajectories(root, census_result, artifact_index, files=None):
    """One row per (base cell, variant) from the loops' own state ledgers.

    artifact_index: artifact_id -> artifacts row. FINAL/STEP selection rests
    on these rows only (no held-out evidence takes part)."""
    root = Path(root).resolve()
    files = files if files is not None else FilesRead(root)
    terminal = set(core.TERMINAL_STATUSES)
    by_key, bases = {}, OrderedDict()
    for row in artifact_index.values():
        key = (row["block"], row["model_id"], row["variant"], row["iteration"], row["sample_id"])
        if key in by_key:
            _refuse("two artifacts for %s", key)
        by_key[key] = row
        if row["iteration"] == 0:
            bases.setdefault((row["block"], row["model_id"]), []).append(row)
    result, referenced = [], set()
    status_by_block = OrderedDict((block, Counter()) for block in core.BLOCKS)
    for loop in census_result["loops"]:
        block, model, variant, owner = loop["block"], loop["model"], loop["variant"], loop["owner"]
        label = "%s/%s/%s" % (block, model, variant)
        if (block == PILOT_BLOCK and owner != core.PILOT) or (block == FULL_BLOCK and owner not in core.OWNERS):
            _refuse("loop %s has the foreign owner %s", label, owner)
        wave = _dict(_json(files, _repair_rel(owner, model, variant, "wave_state.json")), label + " wave")
        if wave.get("run_id") != owner or wave.get("model_id") != model or wave.get("variant") != variant:
            _refuse("foreign wave state of loop %s", label)
        predecessor = wave.get("predecessor_run_id")
        if predecessor not in (None, cs.ORIGIN) or (predecessor == cs.ORIGIN and (block != FULL_BLOCK or owner == cs.ORIGIN)):
            _refuse("loop %s continues the unknown predecessor %r", label, predecessor)
        continued = predecessor == cs.ORIGIN
        if loop.get("kind") != ("continued" if continued else "native"):
            _refuse("census kind of loop %s contradicts its wave state", label)
        history = OrderedDict()
        if continued:
            # recovery_001's rows followed by the owner's rows (cs.loop_state's overlay)
            for row in _state_rows(files, cs.ORIGIN, model, variant):
                history.setdefault(row["sample_id"], []).append(row)
        for row in _state_rows(files, owner, model, variant):
            if continued and row["iteration"] < 1:
                _refuse("continued owner %s wrote an iteration-0 row (%s)", owner, label)
            history.setdefault(row["sample_id"], []).append(row)
        own_rounds = _request_rounds(files, owner, model, variant)
        origin_rounds = _request_rounds(files, cs.ORIGIN, model, variant) if continued else OrderedDict()
        cells = bases.get((block, model)) or []
        if sorted(history) != sorted(r["sample_id"] for r in cells):
            _refuse("state ledger of loop %s does not cover exactly the base cells", label)
        stray = sorted((set(own_rounds) | set(origin_rounds)) - set(history))
        if stray:
            _refuse("request rounds of loop %s for unknown samples: %s", label, stray[:3])
        statuses = Counter()
        for base in cells:
            sample_id = base["sample_id"]
            rows = history[sample_id]
            iterations = [r["iteration"] for r in rows]
            final = iterations[-1]
            if iterations != list(range(final + 1)) or final > core.MAX_ITERATIONS:
                _refuse("loop %s sample %s has the iteration history %s", label, sample_id, iterations)
            if any(r.get("status") != "active" for r in rows[:-1]):
                _refuse("loop %s sample %s has a non-active row before its final row", label, sample_id)
            status = rows[-1].get("status")
            if status not in terminal:
                _refuse("loop %s sample %s ends in the non-terminal status %r", label, sample_id, status)
            statuses[status] += 1
            artifacts = [base["artifact_id"]]
            for k in range(1, core.MAX_ITERATIONS + 1):
                candidate = by_key.get((block, model, variant, k, sample_id))
                if k <= final:
                    if candidate is None:
                        _refuse("loop %s sample %s: missing iteration-%d artifact", label, sample_id, k)
                    if (candidate["source_run"] != _candidate_run(block, owner, continued, variant, k)
                            or candidate["loop_owner"] != owner):
                        _refuse("loop %s sample %s: iteration-%d artifact of another run/owner", label, sample_id, k)
                    artifacts.append(candidate["artifact_id"])
                    referenced.add(candidate["artifact_id"])
                elif candidate is not None:
                    _refuse("loop %s sample %s: candidate at iteration %d beyond the final iteration %d",
                            label, sample_id, k, final)
            # the requests behind iterations 1..final (continued: 1 by recovery_001, 2 by the owner)
            own = own_rounds.get(sample_id) or OrderedDict()
            origin = origin_rounds.get(sample_id) or OrderedDict()
            if continued:
                consistent = sorted(origin) == list(range(1, min(final, 1) + 1)) and \
                    sorted(own) == list(range(2, final + 1))
            else:
                consistent = sorted(own) == list(range(1, final + 1))
            if not consistent:
                _refuse("loop %s sample %s: request rounds recorded for iterations %s/%s, final iteration %d",
                        label, sample_id, sorted(origin), sorted(own), final)
            last = rows[-1]
            verdict = last.get("test_verdict")
            padded = [r.get("status") for r in rows] + [""] * (core.MAX_ITERATIONS + 1 - len(rows))
            artifacts += [""] * (core.MAX_ITERATIONS + 1 - len(artifacts))
            result.append(OrderedDict([
                ("trajectory_id", core.trajectory_id(base["cell_id"], variant)), ("cell_id", base["cell_id"]),
                ("block", block), ("model_id", model), ("variant", variant), ("loop_owner", owner),
                ("loop_kind", "continued" if continued else "native"), ("final_iteration", final),
                ("terminal_status", status), ("stop_reason", last.get("stop_reason") or ""),
                ("status_iter0", padded[0]), ("status_iter1", padded[1]), ("status_iter2", padded[2]),
                ("test_verdict_final", "" if verdict is None else _str(verdict, label + " test_verdict")),
                ("artifact_iter0", artifacts[0]), ("artifact_iter1", artifacts[1]), ("artifact_iter2", artifacts[2]),
                ("final_artifact", artifacts[final]), ("request_rounds", sum(own.values()) + sum(origin.values())),
            ]))
        if OrderedDict(sorted(statuses.items())) != OrderedDict(sorted((loop.get("status_counts") or {}).items())):
            _refuse("terminal statuses of loop %s differ from the census", label)
        status_by_block[block].update(statuses)
    candidates = set(r["artifact_id"] for r in artifact_index.values() if r["iteration"] >= 1)
    if referenced != candidates:
        _refuse("trajectories reference %d candidates, the population holds %d (%d unreferenced, %d unknown)",
                len(referenced), len(candidates), len(candidates - referenced), len(referenced - candidates))
    summary = cs.summary(census_result)
    for block in core.BLOCKS:
        if dict(status_by_block[block]) != dict(summary["blocks"][block]["sample_states"]):
            _refuse("terminal statuses of the %s block differ from the census summary", block)
    return result


# -- dataset ----------------------------------------------------------------------------------

def _integrity(artifacts, gates, census_result, table):
    """Population-level integrity (section 2.3)."""
    base = OrderedDict()
    benchmarks = OrderedDict((block, set()) for block in core.BLOCKS)
    for row in artifacts:
        benchmarks[row["block"]].add(row["benchmark"])
        if row["iteration"] == 0:
            base[row["cell_id"]] = row
    for row in artifacts:
        if row["source_run"] in core.EXCLUDED_RUNS:
            _refuse("artifact %s comes from an excluded run", row["artifact_id"])
        run = row["source_run"]
        in_pilot = run == core.PILOT or run.startswith(core.PILOT + "__")
        if (row["block"] == PILOT_BLOCK) != in_pilot or (not in_pilot and not run.startswith("full_ext_")):
            _refuse("artifact %s mixes block %s with run %s", row["artifact_id"], row["block"], run)
        cell = base.get(row["cell_id"])
        if cell is None:
            _refuse("candidate %s has no base cell", row["artifact_id"])
        if (cell["benchmark"], cell["execution_model"]) != (row["benchmark"], row["execution_model"]):
            _refuse("candidate %s contradicts its base cell", row["artifact_id"])
    if benchmarks[PILOT_BLOCK] & benchmarks[FULL_BLOCK]:
        _refuse("the blocks share benchmarks: %s", sorted(benchmarks[PILOT_BLOCK] & benchmarks[FULL_BLOCK])[:3])
    mixed = sorted(group for group, gated in gates.items() if len(gated) > 1)
    if mixed:
        _refuse("%d (block, benchmark, spec, execution_model) group(s) mix gated and valid pairs: %s",
                len(mixed), mixed[:2])
    per_block = Counter(row["block"] for row in base.values())
    for block in core.BLOCKS:
        if per_block.get(block, 0) != census_result["base_cells"].get(block):
            _refuse("%s base cells: %d artifacts, census %s", block, per_block.get(block, 0),
                    census_result["base_cells"].get(block))
    # the table's loop identities are the census loops
    loops = OrderedDict(((l["model"], l["variant"]), l) for l in census_result["loops"] if l["block"] == FULL_BLOCK)
    for target in table.targets:
        if not target.iteration or target.model_id not in census_result["models"]:
            continue
        loop = loops.get((target.model_id, target.variant))
        if loop is None or target.loop_owner != loop["owner"] or target.document.get("loop_kind") != loop.get("kind"):
            _refuse("table target %s names another loop owner/kind than the census", target.target_id)
    return base


def _enhanced_inputs(root, files):
    """The frozen LLM specs and the input shapes of the spec validator: both
    decide pg.expected_enhanced (validate_spec checks explicit_values against
    the shapes), and both readers silently fall back to defaults on a missing
    file, so a missing file refuses here. The shapes come from the specs
    module's own checkout (specs.SHAPES_PATH, cached by load_shapes): under
    the analysed root they are a files_read entry, otherwise (a synthetic
    root) their hash is kept in the provenance; the cached shapes must be the
    bytes recorded."""
    from thesis.enhanced_tests import specs as es

    specs_rel = _relative(root, pg.frozen_specs_path(root), "the frozen spec artifact")
    if not files.exists(specs_rel):
        _refuse("missing frozen spec artifact %s (the reader would use built-in specs only)", specs_rel)
    files.read(specs_rel)
    llm_specs = pg.load_frozen_specs(root)
    shapes_path = Path(es.SHAPES_PATH).resolve()
    if not shapes_path.is_file():
        _refuse("missing input shapes %s (validate_spec would assume 1-D shapes)", shapes_path.name)
    try:
        shapes_rel = shapes_path.relative_to(root).as_posix()
    except ValueError:
        shapes_rel = None
    data = files.read(shapes_rel) if shapes_rel is not None else shapes_path.read_bytes()
    try:
        recorded = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        _refuse("unreadable input shapes %s: %s", shapes_path.name, error)
    if es.load_shapes() != recorded:
        _refuse("the spec validator's cached input shapes differ from %s", shapes_rel or shapes_path.name)
    identity = OrderedDict([("frozen_specs", specs_rel), ("shapes", shapes_rel),
                            ("shapes_raw_sha256", hashlib.sha256(data).hexdigest())])
    return llm_specs, identity


def build_dataset(root, config, table, census_result=None, log=None, models=None, lineage_sha256=None):
    """The normalized core.Dataset of the study (read-only).

    models: a MODELS-ordered subset for synthetic tests only (default: all).
    lineage_sha256: recorded in the provenance when the caller loaded the
    phase-2 lineage the table is bound to."""
    started = time.time()
    root = Path(root).resolve()
    log = log or (lambda message: None)
    models = _models(models)
    core.provider_isolation(config)
    files = FilesRead(root)
    settings = tool_settings(config)
    try:
        if census_result is None:
            census_result = cs.census(root, models)
        summary, census_digest = census_binding(census_result, models, table)
        llm_specs, enhanced_inputs = _enhanced_inputs(root, files)
        specs = OrderedDict([("llm", llm_specs), ("cache", {})])
        out = OrderedDict([("artifact_ids", set()), ("gates", OrderedDict()), ("overrides", Counter()),
                           ("gap_dirty", OrderedDict([("artifacts", Counter()), ("entries", Counter())])),
                           ("artifacts", []), ("tool_entries", []), ("findings", []), ("enhanced_pairs", []),
                           ("generations", [])])
        for block, target in iter_study_targets(root, table, models):
            try:
                count = _normalize_target(root, config, files, block, target, settings, specs, out)
            except core.AnalysisRefused:
                raise
            except READER_ERRORS as error:
                _refuse("target %s: %s: %s", target.target_id, type(error).__name__, error)
            log("normalized %s %s (%d artifacts, %.0f s)" % (block, target.target_id, count, time.time() - started))
        base = _integrity(out["artifacts"], out["gates"], census_result, table)
        index = OrderedDict((row["artifact_id"], row) for row in out["artifacts"])
        trajectory_rows = trajectories(root, census_result, index, files)
    except core.AnalysisRefused:
        raise
    except READER_ERRORS as error:
        _refuse("%s: %s", type(error).__name__, error)
    base_cells = [OrderedDict([
        ("cell_id", row["cell_id"]), ("block", row["block"]), ("model_id", row["model_id"]),
        ("benchmark", row["benchmark"]), ("family", row["family"]), ("execution_model", row["execution_model"]),
        ("sample_id", row["sample_id"]), ("base_run", row["source_run"]), ("source_sha256", row["source_sha256"]),
        ("bl01", row["benchmark"] == core.BL01_BENCHMARK)]) for row in base.values()]
    read = files.sorted()
    leaked = [p for p in read if any("/%s/" % run in p for run in core.EXCLUDED_RUNS)
              or p.startswith("%s/%s/" % (pt.INTERMEDIATE_REL, core.PARENT)) and "/repair/" in p]
    if leaked:
        _refuse("the normalizer read excluded evidence: %s", leaked[:3])
    provenance = OrderedDict([
        ("schema_version", core.DATASET_SCHEMA), ("targets_sha256", table.sha256)])
    if lineage_sha256 is not None:
        provenance["lineage_sha256"] = lineage_sha256
    provenance.update([
        ("census_digest", census_digest), ("models", models), ("readers", list(READERS)),
        ("tool_scope", OrderedDict((stage, OrderedDict((t, list(s.execution_models)) for t, s in group.items()))
                                   for stage, group in zip(("static", "dynamic"), settings))),
        ("effective_state_overrides", OrderedDict(sorted(out["overrides"].items()))),
        # DIRTY under the frozen rule only (module docstring): artifacts per
        # stage/block/population, contributing entries per .../tool/state
        ("dirty_only_from_gap_state_entries", OrderedDict([
            ("states", list(VERDICTLESS_GAP_STATES)),
            ("artifacts", OrderedDict(sorted(out["gap_dirty"]["artifacts"].items()))),
            ("entries", OrderedDict(sorted(out["gap_dirty"]["entries"].items())))])),
        ("gated_groups", sum(1 for gated in out["gates"].values() if gated == set([True]))),
        ("enhanced_inputs", enhanced_inputs),
        ("files_read", read),
    ])
    dataset = core.Dataset(OrderedDict([
        ("base_cells", base_cells), ("artifacts", out["artifacts"]), ("tool_entries", out["tool_entries"]),
        ("findings", out["findings"]), ("enhanced_pairs", out["enhanced_pairs"]),
        ("trajectories", trajectory_rows), ("generations", out["generations"])]), provenance)
    pairs = set((p["artifact_id"], p["spec_key"]) for p in out["enhanced_pairs"])
    if len(pairs) != len(out["enhanced_pairs"]):
        _refuse("duplicate (artifact, spec) pair")
    dataset.by("trajectories", "trajectory_id")
    log("dataset %s in %.0f s" % (dict(dataset.counts()), time.time() - started))
    return dataset
