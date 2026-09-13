"""Positive writer attribution for stage records (repair_writer_attribution.v1).

WHO WROTE / INVOKED THIS STAGE? - not: IS THIS STAGE STILL MISSING?

The repair loop's `_run_analysis_stages(iteration)` runs the base evaluation
runners in-process. At ITERATION 0 it writes into the BASE run's own stage
files (LoopPaths.iter_run_id(0) == base_run_id), so once the records are
complete nothing in the records themselves says whether the base evaluation
or the repair loop produced them. The static runner has carried a durable
trace since the pre-run enforcement wave - the free-text invocation label
`repair <model>/<variant> iteration <n> (internal static)` appended to the
model's static_analysis_summary.json - and the post-run verifier uses it to
keep the repair_evaluation invocation REQUIRED for such a loop. Correctness
and dynamic had no equivalent (ITERATION_ZERO_COVERAGE_RESIDUAL =
CORRECTNESS_DYNAMIC_WRITER_NOT_ATTRIBUTABLE).

This module is the ONE definition of that attribution for all three
internal stages:

  * the repair loop builds `repair_attribution(...)` and hands it to the
    runner together with the label (same convention as static);
  * every runner persists it in its per-model invocation history
    (static_analysis_summary.json / dynamic_analysis_summary.json /
    correctness_summary.json `invocations[]`) - an ADDITIVE provenance
    entry, never a field of a result record; result semantics untouched;
  * the verifier parses it STRICTLY (fail-closed): a structured block and
    the label must agree, identities must match the loop, an iteration
    must be a bounded integer; anything malformed is a verdict, never
    silently "no repair attribution".

The attribution says INVOKED/WRITTEN BY REPAIR. It never claims that the
stage completed - record coverage decides completion, exactly as before.

Python 3.8 compatible (the LLOV container runs the static runner).
"""
from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

REPAIR_WRITER_ATTRIBUTION_VERSION = "repair_writer_attribution.v1"
WRITER_REPAIR = "repair"
WRITER_BASE = "base"

# the stages the repair loop runs in-process (orchestrator.missing_internal_stages)
INTERNAL_STAGES = ("static", "correctness", "dynamic")

# the per-model summary file that carries each stage's invocation history
SUMMARY_FILE_NAMES = OrderedDict([
    ("static", "static_analysis_summary.json"),
    ("correctness", "correctness_summary.json"),
    ("dynamic", "dynamic_analysis_summary.json"),
])

# free-text label, identical convention for every internal stage; the static
# form is byte-identical to the label the pre-run enforcement wave introduced
REPAIR_INVOCATION_LABEL = "repair %s/%s iteration %d (internal %s)"
_REPAIR_LABEL = re.compile(
    r"^repair (?P<model>.+)/(?P<variant>[^/]+) iteration (?P<iteration>\d+) "
    r"\(internal (?P<stage>static|correctness|dynamic)\)$")

# fields a repair attribution must carry (all of them, typed as checked below)
_REQUIRED_FIELDS = ("schema_version", "writer", "label", "base_run_id", "model_id",
                    "variant", "iteration", "internal_stage")


def repair_label(model_id: str, variant: str, iteration: int, internal_stage: str) -> str:
    return REPAIR_INVOCATION_LABEL % (model_id, variant, int(iteration), internal_stage)


def repair_attribution(base_run_id: str, model_id: str, variant: str, iteration: int,
                       internal_stage: str,
                       enforcement: "Optional[Dict[str, Any]]" = None
                       ) -> "OrderedDict[str, Any]":
    """The structured attribution the repair loop hands to a runner.

    `enforcement` is the result of stage_runtime.enforce_stage(...,
    'repair_evaluation', ...): when the run is contracted it binds the
    attribution to the contract, the run authorization, the repair_evaluation
    invocation fragment and the stage runtime stamp - the same provenance the
    fragment architecture already carries, not a second source of truth."""
    if internal_stage not in INTERNAL_STAGES:
        raise ValueError("unknown internal stage %r (expected one of %s)"
                         % (internal_stage, ", ".join(INTERNAL_STAGES)))
    if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
        raise ValueError("iteration must be a non-negative integer, got %r" % (iteration,))
    enforcement = enforcement or {}
    return OrderedDict([
        ("schema_version", REPAIR_WRITER_ATTRIBUTION_VERSION),
        ("writer", WRITER_REPAIR),
        ("label", repair_label(model_id, variant, iteration, internal_stage)),
        ("base_run_id", base_run_id),
        ("model_id", model_id),
        ("variant", variant),
        ("iteration", int(iteration)),
        ("internal_stage", internal_stage),
        ("contract_sha256", enforcement.get("contract_sha256")),
        ("authorization_sha256", enforcement.get("authorization_sha256")),
        ("repair_evaluation_invocation_sha256", enforcement.get("invocation_sha256")),
        ("repair_evaluation_stage_runtime_sha256", enforcement.get("stage_runtime_sha256")),
        ("pre_run_enforced", bool(enforcement.get("enforced"))),
    ])


def invocation_entry(label: "Optional[str]", writer_attribution: "Optional[Dict[str, Any]]",
                     **fields: Any) -> "OrderedDict[str, Any]":
    """One entry of a runner's per-model invocation history: the label, the
    writer (repair or base) and the runner's own facts (samples, tools_run,
    verdicts, ...). `created_at_utc` is added by the caller."""
    entry = OrderedDict([("label", label)])
    entry["writer"] = (writer_attribution or {}).get("writer") or WRITER_BASE
    entry["repair_writer"] = (OrderedDict(writer_attribution)
                              if writer_attribution else None)
    for key, value in fields.items():
        entry[key] = value
    return entry


# ---------------------------------------------------------------------------
# strict, fail-closed parsing (verifier side)
# ---------------------------------------------------------------------------

def parse_label(label: Any) -> "Optional[Dict[str, Any]]":
    """The (model, variant, iteration, stage) a repair label encodes, or None
    for any other label (base runner labels, free text)."""
    if not isinstance(label, str):
        return None
    match = _REPAIR_LABEL.match(label)
    if not match:
        return None
    return OrderedDict([("model_id", match.group("model")),
                        ("variant", match.group("variant")),
                        ("iteration", int(match.group("iteration"))),
                        ("internal_stage", match.group("stage"))])


def parse_entry(entry: Any) -> "Tuple[Optional[Dict[str, Any]], Optional[str]]":
    """(attribution, problem) for one invocation-history entry.

    attribution is None for a base/other writer (no repair label, no repair
    block). A problem is ANY malformed or self-contradicting repair
    attribution: a block without its fields, a mistyped iteration, a label
    that does not match the block, a block whose writer is not 'repair'.
    Such an entry is never 'no attribution' - it is a verdict for the loop.
    """
    if not isinstance(entry, dict):
        return None, "invocation entry is not an object (%s)" % type(entry).__name__
    writer = entry.get("writer")
    if writer not in (None, WRITER_BASE, WRITER_REPAIR):
        return None, "entry.writer %r is unknown" % (writer,)
    block = entry.get("repair_writer")
    labelled = parse_label(entry.get("label"))
    if block is None:
        if labelled is None:
            if writer == WRITER_REPAIR:
                return None, "entry claims writer=repair without a repair attribution"
            return None, None
        if writer not in (None, WRITER_REPAIR):
            return None, ("entry label %r is a repair label but entry.writer is %r"
                          % (entry.get("label"), writer))
        if labelled["internal_stage"] != "static":
            # only the static runner ever wrote label-only entries (pre-run
            # enforcement wave); correctness and dynamic histories were born
            # with the structured block
            return None, ("a %s repair label without the structured attribution block"
                          % labelled["internal_stage"])
        # label-only attribution (the static format of the pre-run enforcement
        # wave): the strict regex is the whole contract
        return OrderedDict([("schema_version", None), ("writer", WRITER_REPAIR),
                            ("label", entry.get("label")), ("base_run_id", None),
                            ("model_id", labelled["model_id"]),
                            ("variant", labelled["variant"]),
                            ("iteration", labelled["iteration"]),
                            ("internal_stage", labelled["internal_stage"]),
                            ("source", "label")]), None
    if not isinstance(block, dict):
        return None, "repair_writer is not an object"
    missing = [f for f in _REQUIRED_FIELDS if f not in block]
    if missing:
        return None, "repair_writer lacks %s" % ", ".join(missing)
    if block.get("writer") != WRITER_REPAIR:
        return None, "repair_writer.writer is %r, not %r" % (block.get("writer"), WRITER_REPAIR)
    if block.get("schema_version") != REPAIR_WRITER_ATTRIBUTION_VERSION:
        return None, "repair_writer.schema_version %r is not %s" % (
            block.get("schema_version"), REPAIR_WRITER_ATTRIBUTION_VERSION)
    iteration = block.get("iteration")
    if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
        return None, "repair_writer.iteration %r is not a non-negative integer" % (iteration,)
    if block.get("internal_stage") not in INTERNAL_STAGES:
        return None, "repair_writer.internal_stage %r is unknown" % (block.get("internal_stage"),)
    for field in ("base_run_id", "model_id", "variant", "label"):
        if not isinstance(block.get(field), str) or not block.get(field):
            return None, "repair_writer.%s is not a non-empty string" % field
    expected_label = repair_label(block["model_id"], block["variant"], iteration,
                                  block["internal_stage"])
    if block["label"] != expected_label:
        return None, ("repair_writer.label %r contradicts its own fields (expected %r)"
                      % (block["label"], expected_label))
    if entry.get("label") is not None and entry.get("label") != expected_label:
        return None, ("the entry label %r contradicts the repair_writer block (%r)"
                      % (entry.get("label"), expected_label))
    if entry.get("writer") not in (None, WRITER_REPAIR):
        return None, "entry.writer %r contradicts the repair_writer block" % (entry.get("writer"),)
    attribution = OrderedDict(block)
    attribution["source"] = "structured"
    return attribution, None


def repair_iterations(invocations: Any, *, internal_stage: str, base_run_id: str,
                      model_id: str, contracted_variants: "Optional[List[str]]",
                      variant: str, max_iterations: "Optional[int]",
                      history_iteration: "Optional[int]" = None,
                      contract_sha256: "Optional[str]" = None,
                      authorization_sha256: "Optional[str]" = None,
                      repair_evaluation_invocation_sha256s: "Optional[Dict[str, List[str]]]" = None
                      ) -> "OrderedDict[str, Any]":
    """Iterations of loop (model_id, variant) that a summary's invocation
    history attributes to the repair loop for `internal_stage`, plus every
    problem the history carries for THIS model.

    Rules (all fail-closed):
      * an entry of another contracted variant belongs to that loop - it is
        neither this loop's evidence nor a problem;
      * an entry naming another model, another base run, a stage it must not
        appear under, an uncontracted variant, an iteration beyond the
        contract's max_iterations or an iteration this history cannot carry
        (`history_iteration`: the base run's history holds iteration 0 only -
        the runner writes iteration N >= 1 into that iteration's own run
        directory) is a contradiction -> problem;
      * a KNOWN binding (contract, authorization, repair_evaluation
        invocation fingerprint) that differs from the run's own provenance
        is a contradiction -> problem (an unrecorded binding is neutral);
      * a malformed entry is a problem;
      * problems are attributed to the variant of the entry that carries them
        (`variant` None: the model's whole history - malformed entries and
        identity contradictions), so another loop's over-max entry never
        fails this loop;
      * identical entries (resume / rerun) are one consistent observation:
        counted in `duplicates`, never a problem;
      * two entries with the same label but different bound provenance
        (contract / authorization / invocation sha) contradict each other.
    """
    iterations: "List[int]" = []
    problems: "List[OrderedDict[str, Any]]" = []
    seen: "Dict[str, Dict[str, Any]]" = {}
    duplicates = 0
    entries = 0

    def problem(text: str, owner_variant: "Optional[str]" = None) -> None:
        problems.append(OrderedDict([("variant", owner_variant), ("problem", text)]))

    if invocations is None:
        invocations = []
    if not isinstance(invocations, list):
        problem("invocations is not a list")
        return OrderedDict([("iterations", []), ("entries", 0), ("duplicates", 0),
                            ("problems", problems)])
    for entry in invocations:
        entries += 1
        attribution, malformed = parse_entry(entry)
        if malformed:
            problem(malformed)
            continue
        if attribution is None:
            continue  # base / other writer
        own = attribution["variant"] if (contracted_variants is None
                                         or attribution["variant"] in contracted_variants) else None
        if attribution["internal_stage"] != internal_stage:
            problem("a repair attribution for stage %r is recorded in the %s history"
                    % (attribution["internal_stage"], internal_stage))
            continue
        if attribution["model_id"] != model_id:
            problem("repair attribution names model %r inside %s's history"
                    % (attribution["model_id"], model_id))
            continue
        if attribution.get("base_run_id") not in (None, base_run_id):
            problem("repair attribution names base run %r, not %r"
                    % (attribution.get("base_run_id"), base_run_id))
            continue
        if contracted_variants is not None and attribution["variant"] not in contracted_variants:
            problem("repair attribution names variant %r, which the contract does not plan"
                    % attribution["variant"])
            continue
        if isinstance(max_iterations, int) and not isinstance(max_iterations, bool) \
                and attribution["iteration"] > max_iterations:
            problem("repair attribution claims iteration %d beyond the contracted max_iterations "
                    "%d" % (attribution["iteration"], max_iterations), own)
            continue
        if isinstance(history_iteration, int) and not isinstance(history_iteration, bool) \
                and attribution["iteration"] != history_iteration:
            problem("repair attribution claims iteration %d inside the history of iteration %d "
                    "(the runner writes iteration N >= 1 into that iteration's own run directory)"
                    % (attribution["iteration"], history_iteration), own)
            continue
        # bindings: a KNOWN value that differs from the run's own provenance
        # is a contradiction; label-only / unrecorded bindings are neutral
        bound_contract = attribution.get("contract_sha256")
        if contract_sha256 and bound_contract and bound_contract != contract_sha256:
            problem("repair attribution is bound to contract %s..., not the run's %s..."
                    % (str(bound_contract)[:12], contract_sha256[:12]), own)
            continue
        bound_auth = attribution.get("authorization_sha256")
        if authorization_sha256 and bound_auth and bound_auth != authorization_sha256:
            problem("repair attribution is bound to authorization %s..., not the run's %s..."
                    % (str(bound_auth)[:12], authorization_sha256[:12]), own)
            continue
        bound_invocation = attribution.get("repair_evaluation_invocation_sha256")
        known = (repair_evaluation_invocation_sha256s or {}).get(attribution["variant"])
        if bound_invocation and known and bound_invocation not in known:
            problem("repair attribution is bound to a repair_evaluation invocation %s... the run "
                    "does not carry for this loop" % str(bound_invocation)[:12], own)
            continue
        label = attribution["label"]
        binding = OrderedDict((k, attribution.get(k)) for k in (
            "contract_sha256", "authorization_sha256", "repair_evaluation_invocation_sha256"))
        previous = seen.get(label)
        if previous is not None:
            # a KNOWN value on both sides that differs is a contradiction; an
            # unknown (None, label-only) side cannot contradict a known one
            conflicting = [k for k in binding
                           if previous.get(k) is not None and binding.get(k) is not None
                           and previous.get(k) != binding.get(k)]
            if conflicting:
                problem("two attributions %r bind different provenance (%s)"
                        % (label, ", ".join(conflicting)), own)
                continue
            duplicates += 1
            for k, v in binding.items():
                if previous.get(k) is None and v is not None:
                    previous[k] = v
        else:
            seen[label] = binding
        if attribution["variant"] == variant:
            iterations.append(attribution["iteration"])
    return OrderedDict([("iterations", sorted(set(iterations))), ("entries", entries),
                        ("duplicates", duplicates), ("problems", problems)])


# ---------------------------------------------------------------------------
# invocation history writer (runner side): INVOKED before the first record,
# COMPLETED after the last one
# ---------------------------------------------------------------------------
#
# An entry is written BEFORE a runner produces its first record and closed
# after its last one, so a runner that dies half-way leaves partial records
# that are still attributed to the writer that invoked it (status
# "invoked", never "completed") - the provenance never looks as if the base
# evaluation had written them. The status separates INVOKED/WRITTEN BY from
# STAGE RESULT COMPLETE; record coverage keeps deciding completion.

STATUS_INVOKED = "invoked"
STATUS_COMPLETED = "completed"


def load_history(summary_path: Any) -> "Tuple[Dict[str, Any], Optional[str]]":
    """(document, unreadable): the existing summary document, or {} with the
    unreadable bytes reported so the writer never silently drops history."""
    import json

    path = summary_path
    if not path.exists():
        return {}, None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        document = json.loads(text)
    except Exception:  # noqa: BLE001 - OSError, ValueError, RecursionError, ...
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            text = "<unreadable: %s>" % exc
        return {}, text[:2000]
    if not isinstance(document, dict):
        return {}, text[:2000]
    invocations = document.get("invocations")
    if invocations is not None and (not isinstance(invocations, list)
                                    or not all(isinstance(e, dict) for e in invocations)):
        # a history of the wrong shape: keep its bytes, start a fresh list
        document = OrderedDict(document)
        document["invocations"] = []
        return document, text[:2000]
    return document, None


def _write_document(summary_path: Any, document: "Dict[str, Any]") -> None:
    # atomic: a concurrent reader never sees a truncated history
    from thesis.evaluation import atomic_io

    atomic_io.atomic_write_json(summary_path, document)


def open_invocation(summary_path: Any, base_document: "Dict[str, Any]",
                    label: "Optional[str]", writer_attribution: "Optional[Dict[str, Any]]",
                    **facts: Any) -> int:
    """Append an INVOKED entry to the summary's history and return its index."""
    from thesis.generation import common

    document, unreadable = load_history(summary_path)
    invocations = list(document.get("invocations") or [])
    entry = invocation_entry(label, writer_attribution, status=STATUS_INVOKED,
                             started_at_utc=common.utc_now_iso(), **facts)
    invocations.append(entry)
    merged = OrderedDict(document)
    merged.update(base_document)
    merged["invocations"] = invocations
    if unreadable is not None:
        merged["unreadable_previous"] = unreadable
    _write_document(summary_path, merged)
    return len(invocations) - 1


def _same_identity(entry: "Dict[str, Any]", label: "Optional[str]",
                   writer_attribution: "Optional[Dict[str, Any]]") -> bool:
    block = entry.get("repair_writer")
    expected = OrderedDict(writer_attribution) if writer_attribution else None
    return entry.get("label") == label and (
        (block is None and expected is None)
        or (isinstance(block, dict) and expected is not None and dict(block) == dict(expected)))


def close_invocation(summary_path: Any, index: int, facts: "Dict[str, Any]",
                     document_updates: "Optional[Dict[str, Any]]" = None,
                     label: "Optional[str]" = None,
                     writer_attribution: "Optional[Dict[str, Any]]" = None) -> None:
    """Mark the entry opened by open_invocation COMPLETED and record the
    runner's facts (samples, verdicts, tools_run, ...); `document_updates`
    refreshes the summary's own top-level fields.

    The entry is closed only if it still carries the identity that opened it
    (label + attribution); otherwise - the shared file was rewritten by
    another writer meanwhile - the completion is appended as its own entry
    WITH that identity, never as an anonymous base entry."""
    from thesis.generation import common

    document, unreadable = load_history(summary_path)
    invocations = list(document.get("invocations") or [])
    if 0 <= index < len(invocations) and isinstance(invocations[index], dict) \
            and invocations[index].get("status") == STATUS_INVOKED \
            and _same_identity(invocations[index], label, writer_attribution):
        entry = OrderedDict(invocations[index])
    else:
        # the opened entry is gone or is another writer's: record the
        # completion with ITS OWN identity rather than losing the attribution
        entry = invocation_entry(label, writer_attribution, status=STATUS_INVOKED,
                                 opened_entry_lost=True)
        invocations.append(entry)
        index = len(invocations) - 1
    entry["status"] = STATUS_COMPLETED
    entry["created_at_utc"] = common.utc_now_iso()
    for key, value in facts.items():
        entry[key] = value
    invocations[index] = entry
    merged = OrderedDict(document)
    if document_updates:
        merged.update(document_updates)
    merged["invocations"] = invocations
    if unreadable is not None:
        merged["unreadable_previous"] = unreadable
    _write_document(summary_path, merged)
