"""Run freshness + record identity (NO_PILOT001_MEASUREMENT_REUSE enforcement).

Two provenance-only mechanisms - no verdict, finding or record semantics
change:

  inspect_run_freshness(config, run_id)
      Is the run FRESH, i.e. does it carry NO result-bearing file yet
      (generations, batch bookkeeping, assembly + sources, correctness /
      static / dynamic / enhanced records, repair state, manifest fragments,
      authorization, iteration-run directories)? A first start of a
      contracted run (run_authorization.authorize_start) refuses a run that
      is not fresh: copied historical records can never become the run's
      own inputs "at start". Only the frozen contract (run_contract.json) is
      admitted pre-run.

  record_identity_problems(config, run_id, model_ids)
      Every result record (generation, assembly, correctness, static,
      dynamic, enhanced, repair state) must claim THIS run: a record whose
      run_id names another run, a pre-contract legacy schema (assembly.v1,
      static_analysis.v2 - the historical pilot_001 shapes) or an assembly
      entry whose source_path / logical_source_path lives under another run
      is a foreign / historical record. The post-run verifier turns any
      such record into FAIL (record_run_identity:<model>).

Python 3.8 compatible.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FRESH = "FRESH"
NOT_FRESH = "NOT_FRESH"
UNRESOLVED = "UNRESOLVED"

# result-bearing files of the RAW tree (per model directory)
RAW_RESULT_FILES = ("generations.jsonl", "generation_summary.json", "generation_batch.json",
                    "generation_batch.done.json")
# result-bearing files of the INTERMEDIATE tree (per model directory)
INTERMEDIATE_RESULT_FILES = ("assembly.jsonl", "assembly_summary.json", "compilation.jsonl",
                             "correctness.jsonl", "correctness_summary.json",
                             "static_analysis.jsonl", "static_analysis_summary.json",
                             "dynamic_analysis.jsonl", "dynamic_analysis_summary.json",
                             "enhanced_tests.jsonl", "enhanced_tests_summary.json")
INTERMEDIATE_RESULT_DIRS = ("sources", "repair")
# run-level state that means "this run already started": every fragment of
# the run manifest EXCEPT the global config fragment. generate.py freezes the
# run manifest (global.json, the run_manifest.json snapshot, the toolchain
# record) in the parent BEFORE the provider child performs the first start,
# so those three are legitimate pre-start state; a contract / runtime
# evidence / authorization / invocation / stage / assembly / enhanced /
# condition fragment or a history entry means the run already ran.
RUN_LEVEL_STATE = ("run_manifest.fragments",)
ALLOWED_PRE_START_RUN_FILES = ("run_manifest.json", "toolchain-versions.txt")
# fragment kinds ensure_run_manifest writes at first contact: the frozen
# config (global) and its additive enrichments (prompt_selection,
# enhanced_policy); a drift fragment is NOT pre-start state (the config
# changed between two pre-start touches - use a fresh run id)
ALLOWED_PRE_START_FRAGMENT_KINDS = ("global", "enrichment")
# the only file a NOT yet started contracted run may carry besides those
ALLOWED_PRE_RUN_FILES = ("run_contract.json",)

# pre-contract record schemas: the historical pilot_001 shapes
LEGACY_SCHEMAS = {
    "assembly.jsonl": ("assembly.v1",),
    "static_analysis.jsonl": ("static_analysis.v1", "static_analysis.v2"),
}
RECORD_FILES = ("generations.jsonl", "assembly.jsonl", "correctness.jsonl", "static_analysis.jsonl",
                "dynamic_analysis.jsonl", "enhanced_tests.jsonl")


def _outputs(config: Dict[str, Any]) -> "Dict[str, Path]":
    outputs = config.get("outputs") or {}
    return {"raw": Path(outputs.get("raw_dir") or "thesis/results/raw"),
            "intermediate": Path(outputs.get("intermediate_dir") or "thesis/results/intermediate")}


def _iteration_dirs(parent: Path, run_id: str) -> "List[str]":
    if not parent.is_dir():
        return []
    prefix = (run_id + "__").lower()
    try:
        return sorted(p.name for p in parent.iterdir()
                      if p.is_dir() and p.name.lower().startswith(prefix))
    except OSError:
        return []


def _pre_start_fragment(name: str) -> bool:
    """`global.json`, `enrichment.<field>.json` and their history entries
    (`global.<stamp>.<pid>.json`, `enrichment.<field>.<stamp>.<pid>.json`)."""
    kind = name.split(".", 1)[0]
    return name.endswith(".json") and kind in ALLOWED_PRE_START_FRAGMENT_KINDS


def inspect_run_freshness(config: Dict[str, Any], run_id: str) -> "OrderedDict[str, Any]":
    """FRESH / NOT_FRESH / UNRESOLVED with the offending paths (repo-relative
    where possible). Never deletes, never writes."""
    findings: "List[str]" = []
    problems: "List[str]" = []
    trees = _outputs(config)
    raw_run = trees["raw"] / run_id
    inter_run = trees["intermediate"] / run_id
    try:
        if raw_run.exists():
            for entry in sorted(raw_run.iterdir()):
                if entry.is_dir():
                    for name in RAW_RESULT_FILES:
                        if (entry / name).exists():
                            findings.append(str(entry / name))
                    if any(entry.iterdir()) and not any((entry / n).exists() for n in RAW_RESULT_FILES):
                        findings.append("%s (non-empty model directory)" % entry)
                else:
                    findings.append(str(entry))
        if inter_run.exists():
            for entry in sorted(inter_run.iterdir()):
                if entry.name in ALLOWED_PRE_RUN_FILES or entry.name in ALLOWED_PRE_START_RUN_FILES:
                    continue
                if entry.name in RUN_LEVEL_STATE:
                    # the fragments directory: only the global config fragment
                    # may exist before the first start
                    if entry.is_dir():
                        for fragment in sorted(entry.iterdir()):
                            if _pre_start_fragment(fragment.name):
                                continue
                            if fragment.name == "history" and fragment.is_dir():
                                # the append-only history of those fragments is
                                # pre-start state too; any other history entry
                                # names a fragment that means "started"
                                for item in sorted(fragment.iterdir()):
                                    if not _pre_start_fragment(item.name):
                                        findings.append("%s (run manifest history before the first "
                                                        "start)" % item)
                                continue
                            findings.append("%s (run manifest fragment before the first start)"
                                            % fragment)
                    else:
                        findings.append(str(entry))
                    continue
                if entry.is_dir():
                    hit = False
                    for name in INTERMEDIATE_RESULT_FILES:
                        if (entry / name).exists():
                            findings.append(str(entry / name))
                            hit = True
                    for name in INTERMEDIATE_RESULT_DIRS:
                        if (entry / name).exists():
                            findings.append(str(entry / name))
                            hit = True
                    if not hit:
                        findings.append("%s (unexpected pre-run directory)" % entry)
                else:
                    findings.append("%s (unexpected pre-run file)" % entry)
        for parent in (trees["raw"], trees["intermediate"]):
            for name in _iteration_dirs(parent, run_id):
                findings.append("%s (repair-iteration run of this base run already exists)"
                                % (parent / name))
    except OSError as exc:
        problems.append("%s: %s" % (type(exc).__name__, exc))
    status = UNRESOLVED if problems else (NOT_FRESH if findings else FRESH)
    return OrderedDict([
        ("run_id", run_id),
        ("status", status),
        ("raw_run_dir", str(raw_run)),
        ("intermediate_run_dir", str(inter_run)),
        ("result_bearing_paths", findings),
        ("allowed_pre_run_files", list(ALLOWED_PRE_RUN_FILES) + list(ALLOWED_PRE_START_RUN_FILES)),
        ("allowed_pre_start_fragment_kinds", list(ALLOWED_PRE_START_FRAGMENT_KINDS)),
        ("problems", problems),
    ])


def _iter_records(path: Path) -> "List[Any]":
    records: "List[Any]" = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    records.append(None)
    except OSError:
        return [None]
    return records


def parse_utc(value: Any) -> "Optional[datetime]":
    """ISO-8601 UTC timestamp -> aware datetime; None when absent / not a
    string / unparseable (the caller treats that as a problem, never as
    'postdates')."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iteration_run_ids(config: Dict[str, Any], run_id: str) -> "List[str]":
    """The repair-iteration runs of a base run present on disk
    (`<run_id>__<variant>__iterN`, raw or intermediate tree)."""
    trees = _outputs(config)
    found = set()
    for parent in (trees["raw"], trees["intermediate"]):
        found.update(_iteration_dirs(parent, run_id))
    return sorted(found)


def _path_run_segment(value: Any, run_id: str) -> "Optional[str]":
    """The run directory a stored source path lives under, if it names one
    (…/<run>/<model>/sources/<sample>/…)."""
    if not isinstance(value, str):
        return None
    parts = [p for p in value.replace("\\", "/").split("/") if p]
    for i, part in enumerate(parts):
        if part == "sources" and i >= 2:
            return parts[i - 2]
    return None


def _expected_model_identity(config: Dict[str, Any]) -> "Dict[str, Tuple[Any, Any]]":
    return {str(m.get("id")): (m.get("provider"), m.get("model_name"))
            for m in (config.get("models") or []) if isinstance(m, dict) and m.get("enabled", False)}


def record_identity_problems(config: Dict[str, Any], run_id: str,
                             model_ids: "List[str]",
                             authorized_at: "Optional[str]" = None) -> "OrderedDict[str, List[str]]":
    """Per model: every record that does not claim THIS run, carries a
    pre-contract legacy schema, points at another run's sources, analysed
    other bytes than this run's assembled source (static
    sample_source_sha256 vs the assembly entry) or - with the start
    authorization time given - predates the run's start."""
    trees = _outputs(config)
    started = parse_utc(authorized_at)
    expected_identity = _expected_model_identity(config)
    problems: "OrderedDict[str, List[str]]" = OrderedDict()
    for model in model_ids:
        model_problems: "List[str]" = []
        candidates = [trees["raw"] / run_id / model / "generations.jsonl"]
        candidates += [trees["intermediate"] / run_id / model / name
                       for name in RECORD_FILES if name != "generations.jsonl"]
        assembled_sources: "Dict[str, Any]" = {}
        assembly_path = trees["intermediate"] / run_id / model / "assembly.jsonl"
        if assembly_path.is_file():
            for entry in _iter_records(assembly_path):
                if isinstance(entry, dict) and entry.get("sample_id"):
                    assembled_sources[str(entry["sample_id"])] = entry.get("source_sha256")
        for path in candidates:
            if not path.is_file():
                continue
            foreign: "OrderedDict[str, int]" = OrderedDict()
            legacy: "OrderedDict[str, int]" = OrderedDict()
            unreadable = 0
            foreign_sources = 0
            early = 0
            untimed = 0
            other_bytes = 0
            other_model = 0
            for record in _iter_records(path):
                if not isinstance(record, dict):
                    unreadable += 1
                    continue
                if path.name == "generations.jsonl" and model in expected_identity:
                    block = record.get("model") if isinstance(record.get("model"), dict) else {}
                    if (block.get("id") != model
                            or (block.get("provider"), block.get("model_name")) != expected_identity[model]):
                        other_model += 1
                claimed = record.get("run_id")
                if claimed != run_id:
                    foreign[str(claimed)] = foreign.get(str(claimed), 0) + 1
                schema = str(record.get("schema_version"))
                if schema in LEGACY_SCHEMAS.get(path.name, ()):
                    legacy[schema] = legacy.get(schema, 0) + 1
                if path.name == "assembly.jsonl":
                    for field in ("source_path", "logical_source_path"):
                        segment = _path_run_segment(record.get(field), run_id)
                        if segment is not None and segment != run_id:
                            foreign_sources += 1
                            break
                if path.name == "static_analysis.jsonl" and record.get("sample_source_sha256") is not None:
                    expected = assembled_sources.get(str(record.get("sample_id")))
                    if expected is not None and record.get("sample_source_sha256") != expected:
                        other_bytes += 1
                if started is not None and path.name != "generations.jsonl":
                    created = parse_utc(record.get("created_at_utc"))
                    if created is None:
                        untimed += 1
                    elif created < started:
                        early += 1
            if foreign:
                model_problems.append("%s: %d record(s) claim another run (%s)" % (
                    path.name, sum(foreign.values()),
                    ", ".join("%s x%d" % (k, v) for k, v in foreign.items())))
            if legacy:
                model_problems.append("%s: %d record(s) carry a pre-contract legacy schema (%s) - the "
                                      "historical pilot_001 shape" % (
                                          path.name, sum(legacy.values()),
                                          ", ".join("%s x%d" % (k, v) for k, v in legacy.items())))
            if foreign_sources:
                model_problems.append("%s: %d assembly entr%s point at another run's sources"
                                      % (path.name, foreign_sources, "y" if foreign_sources == 1 else "ies"))
            if other_bytes:
                model_problems.append("%s: %d record(s) analysed other bytes than this run's assembled "
                                      "source (sample_source_sha256 != assembly source_sha256)"
                                      % (path.name, other_bytes))
            if other_model:
                model_problems.append("%s: %d record(s) name another model identity than the contracted "
                                      "%s (%s / %s)" % (path.name, other_model, model,
                                                        expected_identity[model][0], expected_identity[model][1]))
            if early:
                model_problems.append("%s: %d record(s) predate the run's start authorization"
                                      % (path.name, early))
            if untimed:
                model_problems.append("%s: %d record(s) without a parseable created_at_utc"
                                      % (path.name, untimed))
            if unreadable:
                model_problems.append("%s: %d unreadable record(s)" % (path.name, unreadable))
        # repair state of the base run (state.jsonl / wave_state.json)
        repair_root = trees["intermediate"] / run_id / model / "repair"
        if repair_root.is_dir():
            for state in sorted(repair_root.glob("*/state.jsonl")):
                claimed = {str(r.get("run_id")) for r in _iter_records(state) if isinstance(r, dict)}
                other = sorted(c for c in claimed if c != run_id)
                if other:
                    model_problems.append("repair/%s/state.jsonl claims run(s) %s"
                                          % (state.parent.name, ", ".join(other)))
            for wave in sorted(repair_root.glob("*/wave_state.json")):
                try:
                    document = json.loads(wave.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    model_problems.append("repair/%s/wave_state.json unreadable" % wave.parent.name)
                    continue
                if isinstance(document, dict) and document.get("run_id") not in (None, run_id):
                    model_problems.append("repair/%s/wave_state.json claims run %r"
                                          % (wave.parent.name, document.get("run_id")))
        if model_problems:
            problems[model] = model_problems
    return problems


def generation_binding_problems(config: Dict[str, Any], run_id: str, model_ids: "List[str]",
                                authorization: "Optional[Dict[str, Any]]") -> "OrderedDict[str, Any]":
    """Generation records must postdate the run's start authorization and the
    per-model generation summary must carry the run's authorization sha:
    a generation that predates T0 (or names another authorization) was not
    produced by this authorized run."""
    trees = _outputs(config)
    authorized_at = (authorization or {}).get("authorized_at_utc")
    started = parse_utc(authorized_at)
    authorization_sha = (authorization or {}).get("authorization_sha256")
    per_model: "OrderedDict[str, Any]" = OrderedDict()
    for model in model_ids:
        problems: "List[str]" = []
        unresolved: "List[str]" = []
        path = trees["raw"] / run_id / model / "generations.jsonl"
        has_records = False
        if path.is_file():
            if started is None:
                unresolved.append("no parseable start authorization time to compare the generation "
                                  "records with")
            else:
                early = 0
                untimed = 0
                for record in _iter_records(path):
                    if not isinstance(record, dict):
                        continue
                    has_records = True
                    created = parse_utc(record.get("created_at_utc"))
                    if created is None:
                        untimed += 1
                    elif created < started:
                        early += 1
                if early:
                    problems.append("%d generation record(s) predate the start authorization (%s)"
                                    % (early, authorized_at))
                if untimed:
                    problems.append("%d generation record(s) carry no parseable created_at_utc - "
                                    "they cannot be shown to postdate the start" % untimed)
        summary_path = trees["raw"] / run_id / model / "generation_summary.json"
        if has_records and not summary_path.is_file():
            unresolved.append("no generation_summary.json - the runner's authorization binding for "
                              "this model is missing (a copied generations.jsonl has none)")
        if summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                summary = None
            if not isinstance(summary, dict):
                problems.append("generation_summary.json unreadable")
            else:
                if summary.get("run_id") not in (None, run_id):
                    problems.append("generation_summary.json claims run %r" % summary.get("run_id"))
                bound = (summary.get("run_authorization") or {}).get("authorization_sha256")
                if authorization_sha is None:
                    unresolved.append("no persisted start authorization to compare the summary with")
                elif bound != authorization_sha:
                    problems.append("generation_summary.json is bound to authorization %s..., the run's "
                                    "is %s..." % (str(bound)[:12], str(authorization_sha)[:12]))
                skipped = (summary.get("counts") or {}).get("skipped_existing")
                if isinstance(skipped, int) and skipped > 0:
                    unresolved.append("generation_summary.json reports %d sample(s) skipped as already "
                                      "existing - a resume; the provenance of those records must be "
                                      "shown by their own authorization binding" % skipped)
        if problems or unresolved:
            per_model[model] = OrderedDict([("problems", problems), ("unresolved", unresolved)])
    return per_model
