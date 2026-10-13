"""The phase-2 target table: every full-extension candidate that phase 2
measures, with exactly one owner, bound by source hash.

A TARGET is one (model, source_run) pair:
  * iteration 0: source_run = full_ext_001 (the 144 base cells of the model);
  * iteration N in (1, 2) of a repair loop (model, variant): the iteration run
    that holds the loop's iteration-N candidates. The loop owner comes from the
    census (thesis.recovery_successor_004.census.owner):
      native owner O (recovery_001 test_feedback, all 004 loops)
          -> O__<variant>__iter<N>
      continued owner O (002/003; wave.predecessor_run_id == recovery_001)
          -> iteration 1 full_ext_recovery_001__<variant>__iter1,
             iteration 2 O__<variant>__iter2
    A (model, variant, N) without assembled candidates has no target.
The aborted repair inside the base run (full_ext_001__static_feedback__iter1,
full_ext_001/<model>/repair) is NEVER a target (EXCLUDE_ALL_PARENT_REPAIR).

Per sample the table binds sample_id, execution_model, benchmark,
source_sha256 (assembly row == sha256 of the source bytes, both checked),
source_path, and per target the assembly file's raw sha256. Every candidate
of an iteration must have been REQUESTED at that iteration by its loop (the
owner's requests.jsonl) - no stray assembly row is ever adopted.

Read-only. Python 3.8 compatible.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, OrderedDict
from pathlib import Path

from thesis.evaluation.condition_hashing import canonical_sha256
from thesis.evaluation.recovery_lineage import RecoveryRefused, checked_path
from thesis.recovery_successor_005 import lineage as pl

SCHEMA = "phase2_targets.v1"
INTERMEDIATE_REL = "thesis/results/intermediate"
RAW_REL = "thesis/results/raw"
STATIC_FILE = "static_analysis.jsonl"
CORRECTNESS_FILE = "correctness.jsonl"
DYNAMIC_FILE = "dynamic_analysis.jsonl"
ENHANCED_FILE = "enhanced_tests.jsonl"
ENHANCED_GROUPS_FILE = "enhanced_build_groups.jsonl"
ENHANCED_REGISTRATION_FILE = "enhanced_registration.json"
ENHANCED_SUMMARY_FILE = "enhanced_tests_summary.json"
# the 002/003 supplement ledgers that complete recovery_001 iteration-1 static records
SUPPLEMENT_OWNERS = ("full_ext_recovery_002", "full_ext_recovery_003")


def _jsonl_bytes(data, relative):
    rows = []
    text = data.decode("utf-8")
    if text and not text.endswith("\n"):
        raise RecoveryRefused("torn or unterminated JSONL: " + relative)
    for line in text.split("\n"):
        if line.strip():
            rows.append(json.loads(line, object_pairs_hook=OrderedDict))
    return rows


def read_jsonl(root, relative):
    path = checked_path(Path(root), relative)
    if not path.is_file():
        return []
    return _jsonl_bytes(path.read_bytes(), relative)


def run_dir(run, model, area="intermediate"):
    base = INTERMEDIATE_REL if area == "intermediate" else RAW_REL
    return "%s/%s/%s" % (base, run, model)


def iteration_run(owner, variant, iteration):
    if variant not in pl.VARIANTS or type(iteration) is not int or not 1 <= iteration <= pl.MAX_ITERATIONS:
        raise RecoveryRefused("iteration outside the repair design")
    return "%s__%s__iter%d" % (owner, variant, iteration)


def _wave(root, owner, model, variant):
    relative = "%s/%s/%s/repair/%s/wave_state.json" % (INTERMEDIATE_REL, owner, model, variant)
    return json.loads(checked_path(Path(root), relative).read_text(encoding="utf-8"),
                      object_pairs_hook=OrderedDict)


def _request_ids(root, owner, model, variant, iteration):
    relative = "%s/%s/%s/repair/%s/iter%d/requests.jsonl" % (INTERMEDIATE_REL, owner, model, variant, iteration)
    rows = read_jsonl(root, relative)
    ids = [row.get("sample_id") for row in rows]
    if len(ids) != len(set(ids)):
        raise RecoveryRefused("duplicate request rows in " + relative)
    return set(ids), relative


def candidate_runs(root, model, variant):
    """[(iteration, source_run, owner, request_owner)] of one repair loop
    whose iteration run holds an assembly for the model."""
    from thesis.recovery_successor_004 import census

    owner = census.owner(root, "full_ext", model, variant)
    if owner is None:
        raise RecoveryRefused("repair loop %s/%s has no owner" % (model, variant))
    wave = _wave(root, owner, model, variant)
    continued = wave.get("predecessor_run_id") == pl.ORIGIN
    result = []
    for iteration in range(1, pl.MAX_ITERATIONS + 1):
        if continued and iteration == 1:
            source, request_owner = iteration_run(pl.ORIGIN, variant, 1), pl.ORIGIN
        else:
            source, request_owner = iteration_run(owner, variant, iteration), owner
        if (Path(root) / run_dir(source, model) / "assembly.jsonl").is_file():
            result.append((iteration, source, owner, request_owner))
    return owner, ("continued" if continued else "native"), result


def _samples(root, source_run, model, request_ids=None):
    """Verified per-sample facts of one assembly (assembled rows only)."""
    relative = run_dir(source_run, model) + "/assembly.jsonl"
    data = checked_path(Path(root), relative).read_bytes()
    rows = _jsonl_bytes(data, relative)
    samples = OrderedDict()
    for row in rows:
        if row.get("run_id") != source_run or row.get("model_id") != model:
            raise RecoveryRefused("foreign assembly row in " + relative)
        if not row.get("assembled"):
            continue
        sample_id = row["sample_id"]
        if sample_id in samples:
            raise RecoveryRefused("duplicate assembled sample %s in %s" % (sample_id, relative))
        source_path = str(row["source_path"]).replace("\\", "/")
        source = checked_path(Path(root), source_path).read_bytes()
        source_sha = hashlib.sha256(source).hexdigest()
        if row.get("source_sha256") != source_sha:
            raise RecoveryRefused("assembly source hash disagrees with the source bytes: " + sample_id)
        parts = sample_id.split("__")
        execution_model = parts[-2] if len(parts) >= 2 else "serial"
        if row.get("execution_model") not in (None, execution_model):
            raise RecoveryRefused("execution model disagrees with the sample id: " + sample_id)
        benchmark = row.get("benchmark") or "%s/%s" % (parts[-4], parts[-3])
        samples[sample_id] = OrderedDict([
            ("sample_id", sample_id), ("execution_model", execution_model), ("benchmark", benchmark),
            ("source_sha256", source_sha), ("source_path", source_path)])
    if request_ids is not None and set(samples) != request_ids:
        raise RecoveryRefused("assembled candidates of %s/%s differ from the loop's requests "
                              "(%d assembled, %d requested)" % (source_run, model, len(samples), len(request_ids)))
    return samples, OrderedDict([("path", relative), ("raw_sha256", hashlib.sha256(data).hexdigest())])


def _target(model, variant, iteration, source_run, owner, kind, samples, assembly):
    return OrderedDict([
        ("target_id", "%s/%s" % (model, source_run)),
        ("model_id", model), ("block", "full_ext"), ("variant", variant), ("iteration", iteration),
        ("source_run", source_run), ("loop_owner", owner), ("loop_kind", kind),
        ("assembly", assembly), ("sample_count", len(samples)),
        ("samples", list(samples.values()))])


def build_table(root, census_result=None, models=None):
    """The deterministic target table of the real repository (models: the
    study's eleven; a subset only for synthetic tests)."""
    from thesis.recovery_successor_004 import census

    root = Path(root).resolve()
    models = list(models or pl.MODELS)
    if census_result is None:
        census_result = census.census(root, models)
    summary = census.summary(census_result)
    expected_loops = 2 * len(pl.VARIANTS) * len(models)
    if (len(census_result["loops"]) != expected_loops
            or summary["total_repair_loops_done"] != "%d/%d" % (expected_loops, expected_loops)):
        raise RecoveryRefused("held-out gate: only %s repair loops are terminal"
                              % summary["total_repair_loops_done"])
    targets = []
    for model in models:
        samples, assembly = _samples(root, pl.PARENT, model)
        targets.append(_target(model, None, 0, pl.PARENT, None, "base", samples, assembly))
        for variant in pl.VARIANTS:
            owner, kind, runs = candidate_runs(root, model, variant)
            for iteration, source, loop_owner, request_owner in runs:
                if source in pl.EXCLUDED_HISTORICAL_RUNS:
                    raise RecoveryRefused("excluded historical run resolved as a target: " + source)
                request_ids, _ = _request_ids(root, request_owner, model, variant, iteration)
                samples, assembly = _samples(root, source, model, request_ids)
                if samples:
                    targets.append(_target(model, variant, iteration, source, loop_owner, kind,
                                           samples, assembly))
    totals = Counter()
    for target in targets:
        key = "base" if target["iteration"] == 0 else target["variant"]
        totals[key] += target["sample_count"]
    document = OrderedDict([
        ("schema_version", SCHEMA),
        ("run_id", pl.SUCCESSOR),
        ("model_ids", models),
        ("excluded_historical_runs", list(pl.EXCLUDED_HISTORICAL_RUNS)),
        ("census_digest", canonical_sha256(summary)),
        ("census_summary", summary),
        ("target_count", len(targets)),
        ("sample_totals", OrderedDict(sorted(totals.items()))),
        ("targets", targets),
    ])
    document["table_sha256"] = canonical_sha256(document)
    return document


class Target:
    def __init__(self, document):
        self.document = document
        self.target_id = document["target_id"]
        self.model_id = document["model_id"]
        self.variant = document["variant"]
        self.iteration = document["iteration"]
        self.source_run = document["source_run"]
        self.loop_owner = document["loop_owner"]
        self.samples = OrderedDict((s["sample_id"], s) for s in document["samples"])

    @property
    def is_base(self):
        return self.iteration == 0

    def __repr__(self):
        return "Target(%s)" % self.target_id


class TargetTable:
    def __init__(self, root, document, expected_sha=None, models=None):
        self.root = Path(root).resolve()
        body = OrderedDict((k, v) for k, v in document.items() if k != "table_sha256")
        if (document.get("schema_version") != SCHEMA or document.get("run_id") != pl.SUCCESSOR
                or document.get("model_ids") != list(models or pl.MODELS)
                or canonical_sha256(body) != document.get("table_sha256")
                or (expected_sha is not None and document.get("table_sha256") != expected_sha)):
            raise RecoveryRefused("invalid phase-2 target table binding")
        self.document = document
        self.targets = [Target(t) for t in document["targets"]]
        ids = [t.target_id for t in self.targets]
        if len(ids) != len(set(ids)):
            raise RecoveryRefused("duplicate phase-2 target")
        if any(t.source_run in pl.EXCLUDED_HISTORICAL_RUNS for t in self.targets):
            raise RecoveryRefused("an excluded historical run is a phase-2 target")

    @property
    def sha256(self):
        return self.document["table_sha256"]

    def select(self, model=None, variant=None, base=None):
        result = []
        for target in self.targets:
            if model is not None and target.model_id != model:
                continue
            if variant is not None and target.variant != variant:
                continue
            if base is not None and target.is_base != base:
                continue
            result.append(target)
        return result

    def get(self, target_id):
        for target in self.targets:
            if target.target_id == target_id:
                return target
        raise RecoveryRefused("unknown phase-2 target " + target_id)


def table_path(root):
    return checked_path(Path(root), pl.DEFINITIONS_REL + "/targets.json")


def load_table(root, expected_sha=None):
    document = json.loads(table_path(root).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    return TargetTable(root, document, expected_sha)


# -- read-only historical evidence of a target ----------------------------------

def assembled_samples(root, target):
    """framework.AssembledSample objects of a target, every source re-hashed
    against the frozen table (a candidate that changed refuses)."""
    from thesis.evaluation import successor_supplement as ss

    root = Path(root).resolve()
    relative = target.document["assembly"]["path"]
    data = checked_path(root, relative).read_bytes()
    if hashlib.sha256(data).hexdigest() != target.document["assembly"]["raw_sha256"]:
        raise RecoveryRefused("assembly drifted since the target table was frozen: " + relative)
    rows = [row for row in _jsonl_bytes(data, relative) if row.get("assembled")]
    samples = ss.assembled_samples(root, rows, target.source_run, target.model_id)
    if [s.sample_id for s in samples] != list(target.samples):
        raise RecoveryRefused("assembled samples differ from the frozen target " + target.target_id)
    for sample in samples:
        facts = target.samples[sample.sample_id]
        if sample.execution_model != facts["execution_model"]:
            raise RecoveryRefused("execution model drifted for " + sample.sample_id)
        if hashlib.sha256(sample.source_path.read_bytes()).hexdigest() != facts["source_sha256"]:
            raise RecoveryRefused("candidate source drifted for " + sample.sample_id)
    return samples


def historical_records(root, target, file_name):
    """sample_id -> the target's own historical stage record (read-only)."""
    rows = read_jsonl(root, run_dir(target.source_run, target.model_id) + "/" + file_name)
    records = OrderedDict()
    for row in rows:
        sample_id = row.get("sample_id")
        if row.get("model_id") != target.model_id or sample_id not in target.samples:
            raise RecoveryRefused("foreign %s row in %s" % (file_name, target.target_id))
        if sample_id in records:
            raise RecoveryRefused("duplicate %s row for %s" % (file_name, sample_id))
        records[sample_id] = row
    return records


def historical_supplements(root, target):
    """{tool: {sample_id: entry}} from the 002/003 supplement ledgers of a
    recovery_001 iteration-1 target (empty for every other target)."""
    from thesis.evaluation import successor_supplement as ss

    expected = OrderedDict((sid, facts["execution_model"]) for sid, facts in target.samples.items())
    result = OrderedDict()
    for owner in SUPPLEMENT_OWNERS:
        for tool in pl.EXTERNAL_TOOLS:
            relative = ss.supplement_relative(owner, target.model_id, target.source_run, tool)
            rows = read_jsonl(root, relative)
            if not rows:
                continue
            indexed = ss.index_rows(rows, successor_run=owner, predecessor_target=target.source_run,
                                    model=target.model_id, tool=tool, expected=expected)
            entries = result.setdefault(tool, OrderedDict())
            for sample_id, row in indexed.items():
                if sample_id in entries:
                    raise RecoveryRefused("two historical supplements for %s/%s" % (tool, sample_id))
                if row.get("candidate_source_sha256") != target.samples[sample_id]["source_sha256"]:
                    raise RecoveryRefused("historical supplement bound to another source: " + sample_id)
                entries[sample_id] = row["entry"]
    return result


def historical_static(root, target):
    """The merged historical static view: target record + 002/003 supplements."""
    from thesis.evaluation import successor_supplement as ss

    records = historical_records(root, target, STATIC_FILE)
    return ss.merge_static_records(records, historical_supplements(root, target))


# -- phase-2 ledgers ------------------------------------------------------------------

def ledger_dir_relative(model, source_run):
    for value in (model, source_run):
        if not value or "/" in value or "\\" in value or value.startswith("."):
            raise RecoveryRefused("invalid phase-2 ledger identity")
    return "%s/%s/supplements/%s" % (pl.RESULTS_REL, model, source_run)


def ledger_relative(model, source_run, name):
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise RecoveryRefused("invalid phase-2 ledger name")
    return ledger_dir_relative(model, source_run) + "/" + name


def ledger_path(root, model, source_run, name):
    """A writable phase-2 ledger path (inside the phase-2 tree only)."""
    return pl.require_writable(root, ledger_relative(model, source_run, name))


def provenance(target, sample_id):
    """The flat candidate provenance carried by every phase-2 record."""
    facts = target.samples[sample_id]
    return OrderedDict([
        ("writer_run_id", pl.SUCCESSOR),
        ("authority_run_id", pl.SUCCESSOR),
        ("candidate_source_run", target.source_run),
        ("candidate_source_sha256", facts["source_sha256"]),
        ("candidate_source_path", facts["source_path"]),
        ("variant", target.variant),
        ("iteration", target.iteration),
    ])


def main(argv=None):
    """Print the target table summary of the real repository (read-only)."""
    import sys

    root = Path(__file__).resolve().parents[2]
    document = build_table(root)
    out = OrderedDict((k, v) for k, v in document.items() if k != "targets")
    per_model = OrderedDict()
    for target in document["targets"]:
        per_model.setdefault(target["model_id"], []).append(
            "%s:%d" % (target["source_run"], target["sample_count"]))
    out["per_model"] = per_model
    sys.stdout.write(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
