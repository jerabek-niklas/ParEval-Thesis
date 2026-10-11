"""Experiment-wide repair-loop census (read-only): how many of the 66 repair
loops (33 pilot + 33 full extension = 2 blocks x 11 models x 3 variants) are
terminal, and the 1,980-cell base population (pilot 396 + full_ext 1,584).

    python3 -B -m thesis.recovery_successor_004.census

Owner of a loop:
  pilot           pilot_002 (native)
  full extension  the UNIQUE successor (full_ext_recovery_002/003/004) with a
                  wave state for the loop, else full_ext_recovery_001 if it
                  has one, else NOT_STARTED; the aborted repair inside the
                  base run (full_ext_001/*/repair) is never an owner
                  (EXCLUDE_ALL_PARENT_REPAIR)
Sample states of a loop:
  native owners (pilot_002, recovery_001, a fresh 004)   the owner ledger
  continued owners (002/003: wave carries predecessor_run_id)
                  recovery_001's last-row view overlaid with the owner rows
A loop is TERMINAL iff its wave is 'done' (iteration 0..2, repair condition
recorded) and every base cell of the model is in a terminal status. A
terminal loop is NOT a successful answer or program: the status breakdown
(incl. non-model terminal statuses) is reported separately.

Pure JSON reads; writes nothing. Python 3.8 compatible.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VARIANTS = ("static_feedback", "test_feedback", "combined_feedback")
BLOCKS = OrderedDict([("pilot", "pilot_002"), ("full_ext", "full_ext_001")])
ORIGIN = "full_ext_recovery_001"
SUCCESSORS = ("full_ext_recovery_002", "full_ext_recovery_003", "full_ext_recovery_004")
POPULATION_FILES = OrderedDict([("pilot", "thesis/evaluation/pilot_002_population.json"),
                                ("full_ext", "thesis/evaluation/full_ext_001_population.json")])


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _jsonl(path):
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _latest(rows):
    states = OrderedDict()
    for row in rows:
        states[row["sample_id"]] = row
    return states


def _repair(root, run, model, variant):
    return Path(root) / "thesis/results/intermediate" / run / model / "repair" / variant


def models(root):
    """Model ids of both populations (they must agree)."""
    found = [_json(Path(root) / relative)["model_ids"] for relative in POPULATION_FILES.values()]
    if any(ids != found[0] for ids in found):
        raise ValueError("pilot and full-extension populations disagree on the model ids")
    return list(found[0])


def expected_cells(root, block, model):
    rows = _jsonl(Path(root) / "thesis/results/intermediate" / BLOCKS[block] / model / "assembly.jsonl")
    return sorted(set(row["sample_id"] for row in rows))


def owner(root, block, model, variant):
    if block == "pilot":
        return BLOCKS["pilot"] if (_repair(root, BLOCKS["pilot"], model, variant) / "wave_state.json").is_file() \
            else None
    claimed = [run for run in SUCCESSORS
               if (_repair(root, run, model, variant) / "wave_state.json").is_file()]
    if len(claimed) > 1:
        raise ValueError("loop %s/%s is claimed by %s" % (model, variant, claimed))
    if claimed:
        return claimed[0]
    if (_repair(root, ORIGIN, model, variant) / "wave_state.json").is_file():
        return ORIGIN
    return None


def loop_state(root, block, model, variant, terminal_statuses):
    run = owner(root, block, model, variant)
    expected = expected_cells(root, block, model)
    row = OrderedDict([("block", block), ("model", model), ("variant", variant), ("owner", run),
                       ("expected_cells", len(expected))])
    if run is None:
        row.update(state="NOT_STARTED", terminal=False, samples=0, status_counts={})
        return row
    directory = _repair(root, run, model, variant)
    wave = _json(directory / "wave_state.json")
    rows = _jsonl(directory / "state.jsonl")
    if wave.get("run_id") != run or wave.get("model_id") != model or wave.get("variant") != variant:
        raise ValueError("foreign wave state in %s" % directory)
    if any(r.get("run_id") != run or r.get("model_id") != model or r.get("variant") != variant
           for r in rows):
        raise ValueError("foreign state row in %s" % directory)
    if wave.get("predecessor_run_id") == ORIGIN:
        merged = _latest(_jsonl(_repair(root, ORIGIN, model, variant) / "state.jsonl"))
        for state in rows:
            if type(state.get("iteration")) is not int or state["iteration"] < 1:
                raise ValueError("continued owner %s wrote an iteration-0 row" % run)
            merged[state["sample_id"]] = state
        kind = "continued"
    else:
        merged = _latest(rows)
        kind = "native"
    counts = Counter(state.get("status") for state in merged.values())
    terminal = (wave.get("phase") == "done" and type(wave.get("iteration")) is int
                and 0 <= wave["iteration"] <= 2 and bool(wave.get("repair_condition_sha256"))
                and sorted(merged) == expected
                and all(state.get("status") in terminal_statuses for state in merged.values()))
    row.update(state="TERMINAL" if terminal else "OPEN", terminal=terminal, kind=kind,
               phase=wave.get("phase"), iteration=wave.get("iteration"),
               repair_condition_sha256=wave.get("repair_condition_sha256"),
               samples=len(merged), status_counts=OrderedDict(sorted(counts.items())))
    return row


def census(root=REPO_ROOT, model_ids=None):
    from thesis.repair import orchestrator

    root = Path(root)
    model_ids = list(model_ids or models(root))
    loops = []
    cells = OrderedDict()
    for block in BLOCKS:
        cells[block] = sum(len(expected_cells(root, block, model)) for model in model_ids)
        for model in model_ids:
            for variant in VARIANTS:
                loops.append(loop_state(root, block, model, variant, orchestrator.TERMINAL_STATUSES))
    return OrderedDict([("models", model_ids), ("base_cells", cells), ("loops", loops),
                        ("non_model_terminal_statuses", list(orchestrator.NON_MODEL_TERMINAL_STATUSES))])


def summary(result):
    loops = result["loops"]
    blocks = OrderedDict()
    for block in BLOCKS:
        mine = [loop for loop in loops if loop["block"] == block]
        blocks[block] = OrderedDict([
            ("terminal", sum(1 for loop in mine if loop["terminal"])), ("loops", len(mine)),
            ("open", ["%s/%s" % (l["model"], l["variant"]) for l in mine if l["state"] == "OPEN"]),
            ("not_started", ["%s/%s" % (l["model"], l["variant"]) for l in mine if l["state"] == "NOT_STARTED"]),
            ("owners", OrderedDict(sorted(Counter(str(l["owner"]) for l in mine).items()))),
            ("sample_states", OrderedDict(sorted(sum((Counter(l["status_counts"]) for l in mine),
                                                     Counter()).items())))])
    conditions = sorted(set(l.get("repair_condition_sha256") for l in loops if l.get("repair_condition_sha256")))
    return OrderedDict([
        ("total_repair_loops_done", "%d/%d" % (sum(b["terminal"] for b in blocks.values()), len(loops))),
        ("blocks", blocks),
        ("base_cells", OrderedDict(list(result["base_cells"].items())
                                   + [("total", sum(result["base_cells"].values()))])),
        ("repair_conditions", conditions)])


def main(argv=None):
    result = census(REPO_ROOT)
    print(json.dumps(OrderedDict([("summary", summary(result)), ("loops", result["loops"])]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
