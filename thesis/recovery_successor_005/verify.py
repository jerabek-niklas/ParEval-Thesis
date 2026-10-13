"""Per-model verification of the WHOLE experiment's measurement completeness
after phase 2 (full_ext_phase2_001), for all 11 models.

A PASS proves, for one model:

  pilot     every pilot_002 base cell and every pilot repair candidate
            (pilot_002__<variant>__iter<N>) carries a static record with every
            APPLICABLE enabled static tool, a correctness record, a dynamic
            record with every applicable enabled dynamic tool, and exactly the
            expected enhanced (sample, spec_key) set (read-only reference);
  full_ext  for every target of the frozen table: the missing-only plan has no
            open item and no integrity finding; the merged static view carries
            every enabled tool; every phase-2 static entry validates against
            its settings and candidate source; correctness and dynamic exist
            (historical or phase 2) with every applicable dynamic tool; the
            enhanced pairs equal the expected set exactly (no missing, extra or
            duplicate pair); the enhanced registration exists and its model
            execution fingerprint reproduces over the CURRENT candidate sources
            (drift); every phase-2 row carries the candidate provenance and the
            run's contract/authorization binding; no phase-2 ledger lies
            outside a table target;
  global    protected bytes/definitions unchanged (lineage.verify, computed
            once per verification run) and the 1,980-cell base population.

Documented gap states (TIMEOUT / TOOL_ERROR / PARTIAL / NOT_ANALYZED static
entries, build_failed / timeout correctness verdicts, gated enhanced rows) are
measurements: they are COUNTED, never treated as missing. model_complete is
True only if every check passes (nothing open).

Read-only except write_report (phase-2 verification dir only). Main container.

    python3 -B -m thesis.recovery_successor_005.verify [--model M ...] [--write]
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path  # noqa: E402
from thesis.recovery_successor_005 import composite as pc  # noqa: E402
from thesis.recovery_successor_005 import ledger as pg  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.recovery_successor_005 import plan as pp  # noqa: E402
from thesis.recovery_successor_005 import targets as pt  # noqa: E402

SCHEMA = "phase2_model_verification.v1"
SCOPE = "PHASE2_MEASUREMENT_COMPLETENESS_PILOT_AND_FULL_EXT"
PASS = "PASS"
FAIL = "FAIL"
VERIFICATION_REL = pl.RESULTS_REL + "/verification"
BINDING_FIELDS = ("contract_sha256", "authorization_sha256", "stage_runtime_sha256", "invocation_sha256")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
# keys under which a registration sidecar may carry the per-model execution
# provenance (the native summary key first); any single dict carrying a
# model_execution_fingerprint_sha256 is accepted as well
MODEL_PROVENANCE_KEYS = ("enhanced_model_execution_provenance", "model_execution_provenance",
                         "model_execution_fingerprint")
# native stage files that would make the phase-2 tree a base-population owner
NATIVE_STAGE_FILES = ("generations.jsonl", "assembly.jsonl", pt.STATIC_FILE, pt.CORRECTNESS_FILE,
                      pt.DYNAMIC_FILE, pt.ENHANCED_FILE)
EXAMPLES = 10


class Report:
    def __init__(self, model):
        self.model = model
        self.checks = []

    def add(self, name, ok, detail=None):
        self.checks.append(OrderedDict([("check", name), ("status", PASS if ok else FAIL),
                                        ("detail", detail)]))
        return ok

    def guard(self, name, function, *args):
        """Run a check returning (ok, detail); an exception is a FAIL with
        its message (an unreadable/torn/foreign ledger never passes)."""
        try:
            ok, detail = function(*args)
        except Exception as error:  # noqa: BLE001 - every failure is reported
            return self.add(name, False, "%s: %s" % (type(error).__name__, error))
        return self.add(name, ok, detail)

    def failing(self):
        return [c["check"] for c in self.checks if c["status"] != PASS]

    @property
    def status(self):
        return PASS if self.checks and not self.failing() else FAIL


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _block_counts():
    return OrderedDict([
        ("targets", 0), ("samples", 0),
        ("static", OrderedDict([("records", 0), ("entries_by_source", Counter()), ("states", OrderedDict())])),
        ("correctness", OrderedDict([("historical", 0), ("phase2", 0), ("verdicts", Counter())])),
        ("dynamic", OrderedDict([("historical", 0), ("phase2", 0), ("states", OrderedDict())])),
        ("enhanced", OrderedDict([("rows", 0), ("expected_samples", 0), ("expected_pairs", 0),
                                  ("specs_per_sample", Counter()), ("statuses", Counter()),
                                  ("registrations", 0), ("summaries", 0)])),
    ])


def _plain(value):
    """Counters -> key-sorted OrderedDicts (recursively), for stable JSON."""
    if isinstance(value, Counter):
        return pc.counts(value)
    if isinstance(value, dict):
        return OrderedDict((key, _plain(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _state_counts(bucket, tool, state):
    bucket.setdefault(tool, Counter())[state] += 1


# -- shared deep checks (computed ONCE per verification run) ---------------------

def immutability(lineage):
    """lineage.verify(): every protected byte, membership and frozen
    definition unchanged (minutes - computed once by verify_all)."""
    if lineage is None:
        return OrderedDict([("status", FAIL), ("detail", "no phase-2 lineage supplied")])
    try:
        counts = lineage.verify()
    except Exception as error:  # noqa: BLE001 - reported as FAIL
        return OrderedDict([("status", FAIL), ("detail", "%s: %s" % (type(error).__name__, error))])
    return OrderedDict([("status", PASS), ("detail", OrderedDict([
        ("lineage_sha256", lineage.sha256), ("protected_file_counts", counts)]))])


def population(root):
    """1,980 base cells via composite_study.read_base_cells, and the phase-2
    tree owns none (no raw tree, no native stage file at model level)."""
    root = Path(root).resolve()
    try:
        counts = pc.check_population(pc.population_counts(root))
        owned = []
        if (root / pt.RAW_REL / pl.SUCCESSOR).exists():
            owned.append(pt.RAW_REL + "/" + pl.SUCCESSOR)
        base = root / pl.RESULTS_REL
        if base.is_dir():
            for name in NATIVE_STAGE_FILES:
                owned.extend(p.relative_to(root).as_posix() for p in sorted(base.glob("*/" + name)))
        if owned:
            raise RecoveryRefused("the phase-2 run carries base-population files: %s" % owned[:5])
    except Exception as error:  # noqa: BLE001 - reported as FAIL
        return OrderedDict([("status", FAIL), ("detail", "%s: %s" % (type(error).__name__, error))])
    return OrderedDict([("status", PASS), ("detail", OrderedDict(list(counts.items())
                                                                  + [("phase2_base_cells", 0)]))])


def recorded_binding(root):
    """The run's binding as recorded in its manifest fragments: contract and
    authorization sha256 (merged manifest) and, per stage, every registered
    stage runtime / effective invocation sha256 (current fragments plus their
    non-refused history). None when the run has no manifest yet."""
    from thesis.evaluation import manifest_fragments as mf

    intermediate = Path(root).resolve() / pt.INTERMEDIATE_REL
    directory = mf.fragments_dir(intermediate, pl.SUCCESSOR)
    if not directory.is_dir():
        return None
    manifest = mf.merge_fragments(intermediate, pl.SUCCESSOR)
    runtime, invocation = OrderedDict(), OrderedDict()
    paths = sorted(directory.glob("*.json")) + sorted((directory / mf.HISTORY_DIR_NAME).glob("*.json"))
    for path in paths:
        if ".tmp-" in path.name or not (path.name.startswith("runtime.") or path.name.startswith("invocation.")):
            continue
        fragment = json.loads(path.read_text(encoding="utf-8"))
        if fragment.get("outcome") == "REFUSED":
            continue
        content = fragment.get("content") or {}
        stage = content.get("stage")
        if path.name.startswith("runtime.") and content.get("stage_runtime_sha256"):
            runtime.setdefault(stage, set()).add(content["stage_runtime_sha256"])
        if path.name.startswith("invocation.") and content.get("invocation_sha256"):
            invocation.setdefault(stage, set()).add(content["invocation_sha256"])
    return OrderedDict([
        ("contract_sha256", manifest.get("contract_sha256")),
        ("authorization_sha256", (manifest.get("authorization") or {}).get("authorization_sha256")),
        ("stage_runtime_sha256", OrderedDict((s, sorted(v)) for s, v in sorted(runtime.items(), key=str))),
        ("invocation_sha256", OrderedDict((s, sorted(v)) for s, v in sorted(invocation.items(), key=str))),
    ])


def candidate_fingerprint(root, target):
    """execution_provenance.candidate_source_fingerprint over the CURRENT
    candidate sources of one target (the productive discovery path)."""
    from thesis.enhanced_tests import execution_provenance as ep

    root = Path(root).resolve()
    return ep.candidate_source_fingerprint(root / pt.INTERMEDIATE_REL, target.source_run, target.model_id, root)


def prepare_deep_checks(root, lineage, deep_checks=None):
    """Fill every shared input that was not injected: immutability,
    population, the recorded run binding, the candidate fingerprint function,
    the frozen LLM specs and one shared spec cache."""
    deep = OrderedDict(deep_checks or {})
    if "immutability" not in deep:
        deep["immutability"] = immutability(lineage)
    if "population" not in deep:
        deep["population"] = population(root)
    if "binding" not in deep:
        try:
            deep["binding"] = recorded_binding(root)
        except Exception as error:  # noqa: BLE001 - surfaces in the binding check
            deep["binding"] = OrderedDict([("error", "%s: %s" % (type(error).__name__, error))])
    deep.setdefault("candidate_fingerprint", candidate_fingerprint)
    if "llm_specs" not in deep:
        deep["llm_specs"] = pg.load_frozen_specs(root)
    deep.setdefault("spec_cache", {})
    return deep


# -- generic coverage checks (both blocks) ------------------------------------------

def static_coverage(target, records, tools, applicable_only, counts):
    """Every sample has a record and the required tools (applicable enabled
    tools for the pilot, every enabled tool for the merged full_ext view). Any
    stored state is present; gap states are counted."""
    from thesis.evaluation import framework

    missing_records, missing_entries = [], []
    for sample_id, facts in target.samples.items():
        record = records.get(sample_id)
        if record is None:
            missing_records.append(sample_id)
            continue
        counts["records"] += 1
        entries = record.get("tools") or {}
        for tool, settings in tools.items():
            if applicable_only and not settings.applies_to(facts["execution_model"]):
                continue
            if tool not in entries:
                missing_entries.append("%s/%s" % (sample_id, tool))
                continue
            state = framework.effective_tool_state(record, tool)[0]
            _state_counts(counts["states"], tool, state)
    ok = not missing_records and not missing_entries
    return ok, OrderedDict([("samples", len(target.samples)), ("missing_records", len(missing_records)),
                            ("missing_entries", len(missing_entries)),
                            ("examples", (missing_records + missing_entries)[:EXAMPLES])])


def record_coverage(target, present, counts, kind):
    """correctness: every sample has a record (any verdict)."""
    missing = [sid for sid in target.samples if sid not in present]
    for sample_id, (owner, record) in present.items():
        counts["phase2" if owner == pl.SUCCESSOR else "historical"] += 1
        if kind == "correctness":
            counts["verdicts"][record.get("verdict")] += 1
    return not missing, OrderedDict([("samples", len(target.samples)), ("missing_records", len(missing)),
                                     ("examples", missing[:EXAMPLES])])


def dynamic_coverage(config, target, present, counts):
    """Every sample to which an enabled dynamic tool applies has a record
    carrying every such tool (any state)."""
    tools = pg.dynamic_settings(config)
    missing_records, missing_entries = [], []
    for sample_id, facts in target.samples.items():
        required = [t for t, s in tools.items() if s.applies_to(facts["execution_model"])]
        if not required:
            continue
        if sample_id not in present:
            missing_records.append(sample_id)
            continue
        owner, record = present[sample_id]
        counts["phase2" if owner == pl.SUCCESSOR else "historical"] += 1
        entries = record.get("tools") or {}
        for tool in required:
            if tool not in entries:
                missing_entries.append("%s/%s" % (sample_id, tool))
            else:
                _state_counts(counts["states"], tool, (entries[tool] or {}).get("analysis_state"))
    ok = not missing_records and not missing_entries
    return ok, OrderedDict([("samples", len(target.samples)), ("missing_records", len(missing_records)),
                            ("missing_entries", len(missing_entries)),
                            ("examples", (missing_records + missing_entries)[:EXAMPLES])])


def enhanced_pairs(target, rows, expected, counts):
    """Observed (sample_id, spec_key) pairs == expected pairs exactly: no
    missing, unexpected, duplicate, foreign or unkeyable row."""
    from thesis.enhanced_tests.specs import spec_key

    observed = Counter()
    foreign, unkeyable = [], 0
    for row in rows:
        sample_id = row.get("sample_id")
        if (sample_id not in target.samples or row.get("model_id") != target.model_id
                or row.get("run_id") != target.source_run):
            foreign.append(str(sample_id))
            continue
        try:
            key = pg.key_text(spec_key(row["spec"]))
        except (KeyError, TypeError, ValueError):
            unkeyable += 1
            continue
        observed[(sample_id, key)] += 1
        counts["statuses"][row.get("status")] += 1
    counts["rows"] += len(rows)
    counts["expected_samples"] += len(expected)
    counts["expected_pairs"] += sum(len(specs) for specs in expected.values())
    counts["specs_per_sample"].update(Counter(len(specs) for specs in expected.values()))
    wanted = set((sid, key) for sid, specs in expected.items() for key in specs)
    missing = sorted(wanted - set(observed))
    unexpected = sorted(set(observed) - wanted)
    duplicates = sorted(pair for pair, n in observed.items() if n > 1)
    ok = not (missing or unexpected or duplicates or foreign or unkeyable)
    return ok, OrderedDict([
        ("expected_pairs", len(wanted)), ("observed_pairs", len(observed)), ("rows", len(rows)),
        ("missing", len(missing)), ("unexpected", len(unexpected)), ("duplicates", len(duplicates)),
        ("foreign_rows", len(foreign)), ("unkeyable_rows", unkeyable),
        ("examples", ["missing %s|%s" % p for p in missing[:EXAMPLES]]
         + ["unexpected %s|%s" % p for p in unexpected[:EXAMPLES]]
         + ["duplicate %s|%s" % p for p in duplicates[:EXAMPLES]]
         + ["foreign %s" % s for s in foreign[:EXAMPLES]])])


# -- pilot block -----------------------------------------------------------------------

def verify_pilot(root, config, model, report, counts, deep):
    """pilot_002 base cells + every pilot repair-candidate assembly (read-only)."""
    tools = pg.static_settings(config)
    for run, variant, iteration in pc.pilot_runs(root, model):
        label = "pilot:%s" % run
        holder = {}

        def assembly(run=run, variant=variant, iteration=iteration, holder=holder):
            holder["target"] = pc.pilot_target(root, model, run, variant, iteration)
            return True, OrderedDict([("samples", holder["target"].document["sample_count"]),
                                      ("assembly", holder["target"].document["assembly"])])

        if not report.guard(label + ":assembly", assembly):
            continue
        target = holder["target"]
        counts["targets"] += 1
        counts["samples"] += len(target.samples)

        def static(target=target):
            records = pt.historical_records(root, target, pt.STATIC_FILE)
            counts["static"]["entries_by_source"]["historical_record"] += sum(
                len(r.get("tools") or {}) for r in records.values())
            return static_coverage(target, records, tools, True, counts["static"])

        report.guard(label + ":static_coverage", static)
        report.guard(label + ":correctness_coverage", lambda: record_coverage(
            target, OrderedDict((sid, (pl.PILOT, r)) for sid, r in
                                pt.historical_records(root, target, pt.CORRECTNESS_FILE).items()),
            counts["correctness"], "correctness"))
        report.guard(label + ":dynamic_coverage", lambda: dynamic_coverage(
            config, target, OrderedDict((sid, (pl.PILOT, r)) for sid, r in
                                        pt.historical_records(root, target, pt.DYNAMIC_FILE).items()),
            counts["dynamic"]))
        report.guard(label + ":enhanced_pairs", lambda: enhanced_pairs(
            target, pc.pilot_enhanced_rows(root, target),
            pg.expected_enhanced(root, config, target, deep["llm_specs"], deep["spec_cache"]),
            counts["enhanced"]))


# -- full_ext block -------------------------------------------------------------------------

def plan_complete(root, config, target, deep):
    stages, findings = pp.target_plan(root, config, target, deep["llm_specs"], deep["spec_cache"])
    open_items = OrderedDict((stage, entry["items"]) for stage, entry in stages.items() if entry["items"])
    return not open_items and not findings, OrderedDict([("open_items", open_items),
                                                         ("integrity_findings", findings)])


def static_entries(root, config, target):
    """Every phase-2 supplement row (validated ledger) carries an entry that
    validates against the tool settings and the candidate source sha256."""
    from thesis.evaluation import successor_supplement as ss

    problems = []
    rows = 0
    for tool, settings in pg.static_settings(config).items():
        for sample_id, row in pg.phase2_static(root, target, tool).items():
            rows += 1
            facts = target.samples[sample_id]
            try:
                ss.validate_entry(row.get("entry"), tool, facts["execution_model"], settings,
                                  facts["source_sha256"])
            except Exception as error:  # noqa: BLE001 - counted
                problems.append("%s/%s: %s" % (sample_id, tool, error))
    return not problems, OrderedDict([("phase2_rows", rows), ("invalid", len(problems)),
                                      ("examples", problems[:EXAMPLES])])


def registered_model_provenance(document):
    if not isinstance(document, dict):
        return None
    if "model_execution_fingerprint_sha256" in document:
        return document
    for key in MODEL_PROVENANCE_KEYS:
        value = document.get(key)
        if isinstance(value, dict) and "model_execution_fingerprint_sha256" in value:
            return value
    found = [v for v in document.values() if isinstance(v, dict) and "model_execution_fingerprint_sha256" in v]
    return found[0] if len(found) == 1 else None


def enhanced_registration(root, target, deep, counts, globals_seen):
    """The registration sidecar of a target with enhanced rows exists, is
    bound to the target, and its model execution fingerprint reproduces from
    the STORED global fingerprint plus the CURRENT candidate sources (a
    difference means the candidate code changed after registration)."""
    from thesis.enhanced_tests import execution_provenance as ep

    rows = pg.ledger_rows(root, target.model_id, target.source_run, pt.ENHANCED_FILE)
    path = checked_path(root, pt.ledger_relative(target.model_id, target.source_run,
                                                 pt.ENHANCED_REGISTRATION_FILE))
    if checked_path(root, pt.ledger_relative(target.model_id, target.source_run,
                                             pt.ENHANCED_SUMMARY_FILE)).is_file():
        counts["summaries"] += 1
    if not path.is_file():
        return not rows, ("no enhanced rows, nothing registered" if not rows
                          else "%d enhanced row(s) without a registration sidecar" % len(rows))
    counts["registrations"] += 1
    document = json.loads(path.read_text(encoding="utf-8"))
    recorded = registered_model_provenance(document)
    if recorded is None:
        return False, "the registration carries no model execution fingerprint"
    identity = OrderedDict([("target_id", target.target_id), ("model_id", target.model_id),
                            ("candidate_source_run", target.source_run), ("variant", target.variant),
                            ("iteration", target.iteration)])
    foreign = [f for f, v in identity.items() if f in document and document[f] != v]
    sources = recorded.get("candidate_sources") or {}
    if (foreign or recorded.get("model_id") != target.model_id
            or sources.get("run_id") not in (None, target.source_run)):
        return False, "the registration is bound to another target (%s; model %s, run %s)" % (
            ",".join(foreign), recorded.get("model_id"), sources.get("run_id"))
    global_sha = recorded.get("global_execution_fingerprint_sha256")
    stored_global = (document.get("enhanced_execution_provenance") or {}).get(
        "enhanced_execution_fingerprint_sha256", global_sha)
    if stored_global != global_sha:
        return False, "the registered global fingerprint %s differs from the one in the model fingerprint %s" % (
            str(stored_global)[:16], str(global_sha)[:16])
    globals_seen.add(global_sha)
    candidate = deep["candidate_fingerprint"](root, target)
    current = ep.model_execution_fingerprint(
        OrderedDict([("enhanced_execution_fingerprint_sha256", global_sha)]), candidate)
    registered_sha = ep.model_fingerprint_sha(recorded)
    current_sha = ep.model_fingerprint_sha(current)
    detail = OrderedDict([("registered", registered_sha), ("recomputed", current_sha),
                          ("global_execution_fingerprint_sha256", global_sha),
                          ("candidate_samples", (candidate or {}).get("sample_count"))])
    if registered_sha != current_sha:
        before = OrderedDict((s.get("sample_id"), s.get("source_sha256")) for s in sources.get("samples") or [])
        now = OrderedDict((s.get("sample_id"), s.get("source_sha256")) for s in (candidate or {}).get("samples") or [])
        detail["drifted_samples"] = sorted(sid for sid in set(before) | set(now)
                                           if before.get(sid) != now.get(sid))[:EXAMPLES]
    return registered_sha is not None and registered_sha == current_sha, detail


def _phase2_rows(root, config, target):
    """[(stage, ledger, row)] of every phase-2 measurement ledger of a target."""
    result = []
    for tool in pg.static_settings(config):
        for row in pg.ledger_rows(root, target.model_id, target.source_run, "static.%s.jsonl" % tool):
            result.append((pp.static_stage_of(tool), "static.%s" % tool, row))
    for stage, name in (("correctness", pt.CORRECTNESS_FILE), ("dynamic", pt.DYNAMIC_FILE),
                        ("enhanced", pt.ENHANCED_FILE)):
        for row in pg.ledger_rows(root, target.model_id, target.source_run, name):
            result.append((stage, name, row))
    return result


def provenance(root, config, target):
    """Every phase-2 row is bound to its candidate: static rows by the
    supplement identity, the other ledgers (incl. enhanced build groups) by
    the flat provenance fields of ledger.PROVENANCE_FIELDS."""
    problems = []
    checked = 0
    for stage, name, row in _phase2_rows(root, config, target):
        checked += 1
        sample_id = row.get("sample_id")
        if sample_id not in target.samples:
            problems.append("%s: foreign sample %s" % (name, sample_id))
            continue
        if name.startswith("static."):
            facts = target.samples[sample_id]
            expected = OrderedDict([("run_id", pl.SUCCESSOR), ("authority_run_id", pl.SUCCESSOR),
                                    ("candidate_source_run", target.source_run), ("model_id", target.model_id),
                                    ("variant", target.variant), ("iteration", target.iteration),
                                    ("execution_model", facts["execution_model"]),
                                    ("candidate_source_sha256", facts["source_sha256"])])
            wrong = [f for f, v in expected.items() if row.get(f) != v]
        else:
            wrong = [f for f, v in pt.provenance(target, sample_id).items() if row.get(f) != v]
            if row.get("run_id") != target.source_run or row.get("model_id") != target.model_id:
                wrong.append("run_id/model_id")
        if wrong:
            problems.append("%s %s: %s" % (name, sample_id, ",".join(wrong)))
    groups_seen = set()
    repeated_groups = 0
    for row in pg.ledger_rows(root, target.model_id, target.source_run, pt.ENHANCED_GROUPS_FILE):
        checked += 1
        sample_id = row.get("sample_id")
        if sample_id not in target.samples:
            problems.append("groups: foreign sample %s" % sample_id)
            continue
        wrong = [f for f, v in pt.provenance(target, sample_id).items() if row.get(f) != v]
        if wrong:
            problems.append("groups %s: %s" % (sample_id, ",".join(wrong)))
        # a build group compiled again after a hard kill between a sample's
        # group rows and its records (native append order): reported so a
        # compile-time analysis can account for it, never a coverage failure
        key = (sample_id, row.get("size"))
        repeated_groups += 1 if key in groups_seen else 0
        groups_seen.add(key)
    return not problems, OrderedDict([("rows", checked), ("unbound", len(problems)),
                                      ("repeated_build_groups", repeated_groups),
                                      ("examples", problems[:EXAMPLES])])


def binding_problem(stage, binding, expected):
    if not isinstance(binding, dict):
        return "no phase2_binding"
    if any(not isinstance(binding.get(f), str) or not SHA_RE.match(binding.get(f)) for f in BINDING_FIELDS):
        return "incomplete binding"
    if binding["contract_sha256"] != expected.get("contract_sha256"):
        return "foreign contract_sha256"
    if binding["authorization_sha256"] != expected.get("authorization_sha256"):
        return "foreign authorization_sha256"
    for field in ("stage_runtime_sha256", "invocation_sha256"):
        registered = expected.get(field)
        if registered is not None and binding[field] not in (registered.get(stage) or ()):
            return "unregistered %s for %s" % (field, stage)
    return None


def run_binding(root, config, target, expected):
    """Every phase-2 row carries the 4 binding shas (static rows flat, the
    other ledgers in phase2_binding); contract and authorization equal the
    run's, stage runtime / invocation were registered for the row's stage."""
    rows = _phase2_rows(root, config, target)
    if not rows:
        return True, "no phase-2 rows"
    if not expected or expected.get("error") or not expected.get("contract_sha256"):
        return False, "%d phase-2 row(s) but no recorded run binding (%s)" % (
            len(rows), (expected or {}).get("error") or "no run manifest")
    problems = Counter()
    examples = []
    for stage, name, row in rows:
        binding = (OrderedDict((f, row.get(f)) for f in BINDING_FIELDS) if name.startswith("static.")
                   else row.get("phase2_binding"))
        reason = binding_problem(stage, binding, expected)
        if reason:
            problems[name] += 1
            examples.append("%s %s: %s" % (name, row.get("sample_id"), reason))
    return not problems, OrderedDict([("rows", len(rows)), ("foreign", pc.counts(problems)),
                                      ("examples", examples[:EXAMPLES])])


def ledgers_bound(root, config, model, targets):
    """Every phase-2 ledger directory of the model belongs to a table target
    and holds only the known ledger names (torn-tail archives are reported)."""
    base = Path(root).resolve() / pl.RESULTS_REL / model / "supplements"
    if not base.is_dir():
        return True, "no phase-2 ledgers"
    runs = set(t.source_run for t in targets)
    known = set("static.%s.jsonl" % tool for tool in pg.static_settings(config)) | set([
        pt.CORRECTNESS_FILE, pt.DYNAMIC_FILE, pt.ENHANCED_FILE, pt.ENHANCED_GROUPS_FILE,
        pt.ENHANCED_REGISTRATION_FILE, pt.ENHANCED_SUMMARY_FILE])
    stray, torn, temporary = [], [], []
    for directory in sorted(base.iterdir()):
        if not directory.is_dir() or directory.name not in runs:
            stray.append(directory.name)
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.name.endswith(".torn") and path.name[:-5] in known:
                torn.append("%s/%s" % (directory.name, path.name))
            elif ".tmp-" in path.name:
                temporary.append("%s/%s" % (directory.name, path.name))
            elif not path.is_file() or path.name not in known:
                stray.append("%s/%s" % (directory.name, path.name))
    return not stray, OrderedDict([("stray", stray[:EXAMPLES]), ("archived_torn_tails", torn),
                                   ("temporary_files", temporary[:EXAMPLES])])


def verify_target(root, config, target, report, counts, deep, globals_seen):
    label = "full_ext:%s" % target.source_run
    counts["targets"] += 1
    counts["samples"] += len(target.samples)
    report.guard(label + ":plan_complete", plan_complete, root, config, target, deep)

    def static():
        merged = pg.merged_static(root, config, target)
        sources = counts["static"]["entries_by_source"]
        for tools in pc.static_owners(root, config, target).values():
            for owner in tools.values():
                sources["historical_record" if owner == target.source_run else
                        "phase2_supplement" if owner == pl.SUCCESSOR else "historical_supplement"] += 1
        return static_coverage(target, merged, pg.static_settings(config), False, counts["static"])

    report.guard(label + ":static_coverage", static)
    report.guard(label + ":static_supplement_entries", static_entries, root, config, target)
    report.guard(label + ":correctness_coverage", lambda: record_coverage(
        target, pg.present_records(root, target, pt.CORRECTNESS_FILE), counts["correctness"], "correctness"))
    report.guard(label + ":dynamic_coverage", lambda: dynamic_coverage(
        config, target, pg.present_records(root, target, pt.DYNAMIC_FILE), counts["dynamic"]))
    report.guard(label + ":enhanced_pairs", lambda: enhanced_pairs(
        target, pg.ledger_rows(root, target.model_id, target.source_run, pt.ENHANCED_FILE),
        pg.expected_enhanced(root, config, target, deep["llm_specs"], deep["spec_cache"]),
        counts["enhanced"]))
    report.guard(label + ":enhanced_registration", enhanced_registration, root, target, deep,
                 counts["enhanced"], globals_seen)
    report.guard(label + ":phase2_provenance", provenance, root, config, target)
    report.guard(label + ":phase2_binding", run_binding, root, config, target, deep["binding"])


def verify_full_ext(root, config, table, model, report, counts, deep):
    targets = table.select(model=model)
    base = [t for t in targets if t.is_base]
    report.add("full_ext:targets", len(base) == 1 and base[0].source_run == pl.PARENT,
               OrderedDict([("targets", len(targets)), ("base_targets", len(base)),
                            ("candidates", sum(len(t.samples) for t in targets if not t.is_base))]))
    globals_seen = set()
    for target in targets:
        verify_target(root, config, target, report, counts, deep, globals_seen)
    report.guard("full_ext:phase2_ledgers_bound_to_targets", ledgers_bound, root, config, model, targets)
    report.add("full_ext:enhanced_global_fingerprint_uniform", len(globals_seen) <= 1,
               OrderedDict([("global_execution_fingerprints", sorted(str(g) for g in globals_seen))]))


# -- model / run -----------------------------------------------------------------------------

def verify_model(root, config, table, model, lineage=None, deep_checks=None):
    """The verification report of one model (deterministic, read-only).
    deep_checks: the shared inputs of prepare_deep_checks (injectable)."""
    root = Path(root).resolve()
    if model not in pl.MODELS:
        raise RecoveryRefused("not a phase-2 model: %r" % model)
    deep = prepare_deep_checks(root, lineage, deep_checks)
    report = Report(model)
    counts = OrderedDict([("pilot", _block_counts()), ("full_ext", _block_counts())])
    for name in ("immutability", "population"):
        result = deep[name]
        report.add("global:%s" % name, result.get("status") == PASS, result.get("detail"))
    report.add("global:target_table_bound_to_lineage",
               lineage is not None and lineage.targets_sha256 == table.sha256,
               OrderedDict([("table_sha256", table.sha256),
                            ("lineage_targets_sha256", getattr(lineage, "targets_sha256", None))]))
    verify_pilot(root, config, model, report, counts["pilot"], deep)
    verify_full_ext(root, config, table, model, report, counts["full_ext"], deep)
    failing = report.failing()
    complete = report.status == PASS
    return OrderedDict([
        ("schema_version", SCHEMA), ("scope", SCOPE), ("run_id", pl.SUCCESSOR), ("model_id", model),
        ("status", report.status),
        ("model_complete", complete),
        ("model_complete_reason", "every pilot and full_ext measurement is present (gap states are "
                                  "documented measurements); nothing is open" if complete else
                                  "%d failing check(s): %s" % (len(failing), ", ".join(failing[:EXAMPLES]))),
        ("lineage_sha256", getattr(lineage, "sha256", None)),
        ("targets_sha256", table.sha256),
        ("run_binding", deep["binding"]),
        ("counts", _plain(counts)),
        ("checks", _plain(report.checks)),
    ])


def report_relative(model):
    if model not in pl.MODELS:
        raise RecoveryRefused("not a phase-2 model: %r" % model)
    return "%s/%s.phase2_verification.json" % (VERIFICATION_REL, model)


def write_report(root, result):
    """Persist one model verification atomically (phase-2 tree only; a later
    verification of the same model replaces it)."""
    from thesis.evaluation import atomic_io

    path = pl.require_writable(root, report_relative(result["model_id"]))
    document = OrderedDict(result)
    document["written_at_utc"] = _utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_io.atomic_write_json(path, document)
    return path


def summary(result):
    return OrderedDict([("status", result["status"]), ("model_complete", result["model_complete"]),
                        ("model_complete_reason", result["model_complete_reason"]),
                        ("failing_checks", [c["check"] for c in result["checks"] if c["status"] != PASS])])


def verify_all(root, config, table, lineage, models=None, write=True, deep_checks=None):
    """lineage.verify() and the population ONCE, then every model; reports
    written only with write=True."""
    root = Path(root).resolve()
    models = list(models) if models else list(pl.MODELS)
    unknown = [m for m in models if m not in pl.MODELS]
    if unknown:
        raise RecoveryRefused("not a phase-2 model: %s" % unknown)
    deep = prepare_deep_checks(root, lineage, deep_checks)
    results = OrderedDict()
    reports = OrderedDict()
    for model in models:
        result = verify_model(root, config, table, model, lineage, deep)
        if write:
            reports[model] = write_report(root, result).relative_to(root).as_posix()
        results[model] = summary(result)
    complete = all(r["model_complete"] for r in results.values())
    return OrderedDict([
        ("schema_version", SCHEMA + ".summary"), ("run_id", pl.SUCCESSOR),
        ("status", PASS if all(r["status"] == PASS for r in results.values()) else FAIL),
        ("models_complete", complete),
        ("immutability", deep["immutability"]), ("population", deep["population"]),
        ("models", results), ("reports", reports),
    ])


def main(argv=None):
    import argparse

    from thesis.config.load_config import load_config

    parser = argparse.ArgumentParser(description="phase-2 per-model verification (read-only unless --write)")
    parser.add_argument("--config", default=pl.CONFIG_REL)
    parser.add_argument("--model", action="append", choices=list(pl.MODELS))
    parser.add_argument("--write", action="store_true",
                        help="persist the per-model reports under %s" % VERIFICATION_REL)
    args = parser.parse_args(argv)
    pl.isolate_providers()
    config = load_config((REPO_ROOT / args.config).resolve())
    pl.scrub_provider_environment(config)
    lineage = pl.load(REPO_ROOT)
    table = pt.load_table(REPO_ROOT, lineage.targets_sha256)
    result = verify_all(REPO_ROOT, config, table, lineage, models=args.model, write=args.write)
    sys.stdout.write(json.dumps(result, indent=1, default=str) + "\n")
    return 0 if result["models_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
