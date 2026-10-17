"""Section `acceptance`: the pilot_002 publication gate as it stands today,
the PENDING result-acceptance template and the validator CLI.

The pilot publication policy (POST_RUN_ACCEPTED_RESULTS_ONLY) makes any
publication of pilot_002 results depend on an author decision recorded in
thesis/evaluation/pilot_002_result_acceptance.json. The closure never takes
that decision. It proves that every VERIFIABLE field of a future acceptance
(the post-run report digest, the run id, the frozen contract) is correct by
feeding a PENDING template through the native gate
(pilot_freeze.publication_decision) and showing that the only remaining
reasons are the pending decision itself. No function of this module ever
returns a document with status ACCEPTED unless it was given one.

    python3 -B -m thesis.study_closure.acceptance --template     (print the PENDING template)
    python3 -B -m thesis.study_closure.acceptance --check PATH   (validate a candidate acceptance)
    python3 -B -m thesis.study_closure.acceptance --readiness    (print the readiness document)

Read-only: nothing is written, no provider is reached.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import pilot_freeze as pf  # noqa: E402
from thesis.evaluation.recovery_lineage import checked_path  # noqa: E402
from thesis.recovery_successor_005 import lineage as pl  # noqa: E402
from thesis.study_closure import core  # noqa: E402

SECTION = "acceptance"
# the schema the pilot verifier writes (verify_pilot_run.py); the report is
# read, never rebuilt here
POST_RUN_SCHEMA = "post_run_verification.v1"
STATUSES = ("ACCEPTED", "REJECTED", "PENDING")
PENDING = "PENDING"
READINESS_STATUS = "AUTHOR_DECISION_REQUIRED"
# the readiness status once a valid decision record (ACCEPTED or REJECTED)
# exists; the recorded status then appears under `recorded_status`, never
# as a `status` field of a closure document
DECISION_RECORDED = "DECISION_RECORDED"
DECIDED = ("ACCEPTED", "REJECTED")
UNDECIDED = (None, PENDING)
VALIDATE_COMMAND = "python3 -B -m thesis.study_closure.acceptance --check <path>"
PREPARED_BY = core.CLOSURE_ID + " (template, no decision)"
CHECK_IDS = ("pilot_post_run_report", "publication_policy_fresh", "mandatory_disclosure_sources",
             "publication_gate_now", "template_valid", "readiness_document")
# the only gate reasons that speak about the (missing) author decision and
# nothing else: a reason about a wrong digest / run / contract / status
# field is a defective acceptance file, never "pending"
PENDING_REASONS = (
    re.compile(r"^result acceptance pending \(no .* artifact\)$"),
    re.compile(r"^result acceptance status is (PENDING|REJECTED|None), not ACCEPTED$"),
)
# the empty decision fields are "pending" only while the record itself is
# undecided (absent or PENDING): a record whose status claims a decision
# (ACCEPTED, REJECTED) without decider or date is defective, never pending
DECISION_FIELDS_REASON = re.compile(
    r"^result acceptance lacks required field\(s\): (decided_by|decided_on|decided_by, decided_on)$")
ACCEPTANCE_REASONS = PENDING_REASONS + (DECISION_FIELDS_REASON,)
TEMPLATE_REASONS = (
    re.compile(r"^result acceptance status is PENDING, not ACCEPTED$"),
    re.compile(r"^result acceptance lacks required field\(s\): decided_by, decided_on$"),
)
DATE_FORMAT = "%Y-%m-%d"


# -- inputs ------------------------------------------------------------------------------

def _filled(value):
    """A required acceptance field must carry content (mirror of the gate's
    presence rule): None, False, '', {} and [] are empty."""
    if value is None or value is False:
        return False
    if isinstance(value, (str, dict, list)) and not value:
        return False
    return True


def load_inputs(root, contract=None):
    """The gate inputs: policy, post-run report, the frozen pilot contract
    (self-hash verified) and the result acceptance (None when absent), each
    with its raw sha256."""
    root = Path(root).resolve()
    contract_rel = core.RUN_REGISTRY[core.PILOT]["contract"]
    if contract is None:
        from thesis.evaluation import pilot_run_contract as prc

        contract = prc.load_frozen(checked_path(root, contract_rel))
    acceptance_path = checked_path(root, core.RESULT_ACCEPTANCE_REL)
    exists = acceptance_path.is_file()
    shas = OrderedDict([(core.PUBLICATION_POLICY_REL, core.raw_sha256(root, core.PUBLICATION_POLICY_REL)),
                        (core.PILOT_POST_RUN_REL, core.raw_sha256(root, core.PILOT_POST_RUN_REL)),
                        (contract_rel, core.raw_sha256(root, contract_rel)),
                        (core.RESULT_ACCEPTANCE_REL,
                         core.raw_sha256(root, core.RESULT_ACCEPTANCE_REL) if exists else None)])
    return OrderedDict([
        ("policy", core.read_json(root, core.PUBLICATION_POLICY_REL)),
        ("report", core.read_json(root, core.PILOT_POST_RUN_REL)),
        ("contract", contract),
        ("acceptance", core.read_json(root, core.RESULT_ACCEPTANCE_REL) if exists else None),
        ("acceptance_exists", exists),
        ("raw_sha256", shas),
    ])


# -- pure checks (ok, detail) --------------------------------------------------------------

def report_check(report, contract, raw_sha256=None):
    """The persisted post-run verification of the pilot: schema, run, PASS
    without FAIL/UNRESOLVED, bound to the pilot contract, and its own
    publication block names the digest the gate recomputes."""
    problems = []
    if report.get("schema_version") != POST_RUN_SCHEMA:
        problems.append("schema_version %r is not %s" % (report.get("schema_version"), POST_RUN_SCHEMA))
    if report.get("run_id") != core.PILOT:
        problems.append("run_id %r is not %s" % (report.get("run_id"), core.PILOT))
    if report.get("status") != core.PASS:
        problems.append("status %r is not PASS" % report.get("status"))
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else OrderedDict()
    for key in ("FAIL", "UNRESOLVED"):
        if counts.get(key) != 0:
            problems.append("counts.%s is %r, not 0" % (key, counts.get(key)))
    if report.get("contract_sha256") != contract.get("contract_sha256"):
        problems.append("report contract %s differs from the frozen pilot contract %s"
                        % (report.get("contract_sha256"), contract.get("contract_sha256")))
    digest = pf.post_run_report_digest(report)
    recorded = (report.get("publication") or {}).get("post_run_verification_sha256") \
        if isinstance(report.get("publication"), dict) else None
    if digest is None or digest != recorded:
        problems.append("recomputed digest %s differs from publication.post_run_verification_sha256 %s"
                        % (digest, recorded))
    detail = OrderedDict([("verifier_version", report.get("verifier_version")),
                          ("schema_version", report.get("schema_version")), ("counts", counts),
                          ("digest", digest), ("recorded_digest", recorded),
                          ("contract_sha256", report.get("contract_sha256")),
                          ("raw_sha256", raw_sha256), ("problems", problems)])
    return not problems, detail


def policy_check(policy, contract):
    """The publication policy is FRESH (code-canonical, self-hash reproduced),
    governs the pilot and is the one the frozen contract bound."""
    state = pf.verify_publication_policy(policy)
    problems = list(state.get("problems") or [])
    if state.get("status") != pf.FRESH:
        problems.insert(0, "policy status %s" % state.get("status"))
    if policy.get("run_id") != core.PILOT:
        problems.append("policy run_id %r is not %s" % (policy.get("run_id"), core.PILOT))
    bound = (contract.get("publication_policy") or {}).get("sha256")
    if bound is None or bound != policy.get("publication_policy_sha256"):
        problems.append("contract binds publication policy %s, the repository holds %s"
                        % (bound, policy.get("publication_policy_sha256")))
    detail = OrderedDict([("status", state.get("status")), ("run_id", policy.get("run_id")),
                          ("publication_policy_sha256", policy.get("publication_policy_sha256")),
                          ("contract_bound_sha256", bound), ("policy", policy.get("policy")),
                          ("problems", problems)])
    return not problems, detail


def sources_check(policy, root):
    """Every mandatory disclosure source of the policy is readable, carries
    its field and satisfies the machine-readable requirement."""
    states = pf.disclosure_sources_state(policy, Path(root))
    problems = []
    entries = []
    for state in states:
        satisfied = bool(state.get("artifact_readable")) and bool(state.get("field_present")) \
            and not state.get("problems")
        if not satisfied:
            problems.append("%s: readable=%s field_present=%s problems=%s"
                            % (state.get("id"), state.get("artifact_readable"),
                               state.get("field_present"), state.get("problems")))
        entries.append(OrderedDict([("id", state.get("id")), ("artifact", state.get("artifact")),
                                    ("field_present", state.get("field_present")),
                                    ("problems", state.get("problems"))]))
    if not states:
        problems.append("the policy declares no mandatory disclosure source")
    detail = OrderedDict([("sources", len(states)), ("satisfied", len(states) - len(problems)),
                          ("entries", entries), ("problems", problems)])
    return not problems, detail


def acceptance_related(reason, status=None):
    """True for a gate reason that speaks about the missing author decision
    only. `status` is the gate's result_acceptance_status (None: no
    record): the empty decided_by/decided_on are pending while the record
    is absent or PENDING; under ACCEPTED or REJECTED they are a defect."""
    if any(pattern.match(reason) for pattern in PENDING_REASONS):
        return True
    if DECISION_FIELDS_REASON.match(reason):
        return status in UNDECIDED
    return False


def gate_problems(gate):
    """Reasons of the live gate that are NOT the pending author decision; a
    decision record (ACCEPTED/REJECTED) lacking decided_by or decided_on is
    named as defective (a contradictory record never passes the gate check)."""
    status = gate.get("result_acceptance_status")
    problems = []
    for reason in (gate.get("reasons") or []):
        if acceptance_related(reason, status):
            continue
        if DECISION_FIELDS_REASON.match(reason):
            problems.append("defective acceptance record (status %s claims a decision): %s" % (status, reason))
        else:
            problems.append(reason)
    return problems


def decision_state(gate, acceptance_exists):
    """The readiness state the live gate implies: a decision is recorded
    only when the acceptance artifact exists, its status is ACCEPTED or
    REJECTED and the gate raises nothing beyond the decision itself;
    otherwise (absent, PENDING, defective) the author's decision is still
    required."""
    status = gate.get("result_acceptance_status")
    recorded = bool(acceptance_exists) and status in DECIDED and not gate_problems(gate)
    return OrderedDict([("status", DECISION_RECORDED if recorded else READINESS_STATUS),
                        ("recorded_status", status if recorded else None),
                        ("author_decision_required", not recorded)])


def gate_check(gate, acceptance_exists):
    """Technical PASS: the gate refuses publication ONLY because the author
    decision is pending (or not ACCEPTED); any other reason is a defect."""
    problems = gate_problems(gate)
    detail = OrderedDict([("publication_allowed", gate.get("publication_allowed")),
                          ("result_acceptance_status", gate.get("result_acceptance_status")),
                          ("acceptance_file_present", acceptance_exists),
                          ("reasons", list(gate.get("reasons") or [])),
                          ("label_required", gate.get("label_required")),
                          ("post_run_verification_sha256", gate.get("post_run_verification_sha256")),
                          ("problems", problems)])
    return not problems, detail


def template_problems(reasons):
    """The gate reasons for the PENDING template must be exactly the two the
    template causes by construction (status PENDING, empty decided_by and
    decided_on); anything else means a verifiable field is wrong."""
    reasons = list(reasons or [])
    problems = []
    for pattern in TEMPLATE_REASONS:
        if not any(pattern.match(reason) for reason in reasons):
            problems.append("expected reason missing: %s" % pattern.pattern)
    for reason in reasons:
        if not any(pattern.match(reason) for pattern in TEMPLATE_REASONS):
            problems.append("unexpected reason: %s" % reason)
    if len(reasons) != len(TEMPLATE_REASONS):
        problems.append("%d reasons, expected %d" % (len(reasons), len(TEMPLATE_REASONS)))
    return problems


# -- the template, the validator, the readiness document --------------------------------------

def acceptance_template(report, contract, policy):
    """The PENDING acceptance: every verifiable field filled from the
    current artifacts, the decision fields empty, instructions for the
    author. Status PENDING by construction."""
    template = OrderedDict([
        ("schema_version", pf.RESULT_ACCEPTANCE_SCHEMA),
        ("status", PENDING),
        ("run_id", core.PILOT),
        ("post_run_verification_status", report.get("status")),
        ("post_run_verification_sha256", pf.post_run_report_digest(report)),
        ("frozen_contract_sha256", contract.get("contract_sha256")),
        ("decided_by", None),
        ("decided_on", None),
        ("publication_policy_sha256", policy.get("publication_policy_sha256")),
        ("pilot_label", policy.get("pilot_label")),
        ("author_instructions", OrderedDict([
            ("decision", "set status to ACCEPTED or REJECTED, decided_by to your name and decided_on "
                         "to the ISO date (YYYY-MM-DD) of the decision; change nothing else"),
            ("ACCEPTED", "publication of pilot_002 results becomes allowed ONLY under the pilot label "
                         "(pilot_label) and with every mandatory disclosure of the policy; the gate "
                         "stays closed while any verifiable field differs from the current artifacts"),
            ("REJECTED", "publication stays refused; the measurements remain in the repository as "
                         "verified but unaccepted results"),
            ("PENDING", "no decision yet; publication_allowed stays false"),
            ("never_edit", ["post_run_verification_sha256", "frozen_contract_sha256", "run_id",
                            "post_run_verification_status", "schema_version"]),
            ("artifact", core.RESULT_ACCEPTANCE_REL),
            ("validate", VALIDATE_COMMAND),
            ("gate", policy.get("gate_function")),
        ])),
        ("prepared_by", PREPARED_BY),
        ("note", "template prepared by the study closure; it is not a decision and carries status "
                 "PENDING by construction - the closure never accepts"),
    ])
    if template["status"] != PENDING:  # invariant, never reachable
        raise core.ClosureRefused("the closure template must be PENDING")
    return template


def validate_acceptance(root, acceptance, inputs=None):
    """The gate result for a candidate acceptance plus the strict field
    validation an author needs before relying on the gate: every required
    field present and filled, a known status, decided_on an ISO date,
    decided_by non-empty, and the verifiable fields equal to the current
    artifacts. Never writes."""
    root = Path(root).resolve()
    inputs = inputs if inputs is not None else load_inputs(root)
    policy, report, contract = inputs["policy"], inputs["report"], inputs["contract"]
    if not isinstance(acceptance, dict):
        return OrderedDict([("status", None), ("valid_for_gate", False), ("publication_allowed", False),
                            ("reasons", ["result acceptance artifact malformed (not an object)"]),
                            ("problems", ["the candidate is not a JSON object"]),
                            ("label_required", policy.get("pilot_label"))])
    gate = pf.publication_decision(policy, report, acceptance, root, contract)
    problems = []
    if acceptance.get("schema_version") != pf.RESULT_ACCEPTANCE_SCHEMA:
        problems.append("schema_version %r is not %s" % (acceptance.get("schema_version"),
                                                         pf.RESULT_ACCEPTANCE_SCHEMA))
    missing = [f for f in pf.ACCEPTANCE_REQUIRED_FIELDS if f not in acceptance]
    if missing:
        problems.append("required field(s) absent: %s" % ", ".join(missing))
    empty = [f for f in pf.ACCEPTANCE_REQUIRED_FIELDS if f in acceptance and not _filled(acceptance.get(f))]
    if empty:
        problems.append("required field(s) empty: %s" % ", ".join(empty))
    status = acceptance.get("status")
    if status not in STATUSES:
        problems.append("status %r is not one of %s" % (status, ", ".join(STATUSES)))
    decided_by = acceptance.get("decided_by")
    if not isinstance(decided_by, str) or not decided_by.strip():
        problems.append("decided_by must be a non-empty string")
    decided_on = acceptance.get("decided_on")
    if not isinstance(decided_on, str):
        problems.append("decided_on must be an ISO date string (YYYY-MM-DD)")
    else:
        try:
            datetime.datetime.strptime(decided_on, DATE_FORMAT)
        except ValueError:
            problems.append("decided_on %r is not an ISO date (YYYY-MM-DD)" % decided_on)
    expected = OrderedDict([("run_id", core.PILOT),
                            ("post_run_verification_status", report.get("status")),
                            ("post_run_verification_sha256", pf.post_run_report_digest(report)),
                            ("frozen_contract_sha256", contract.get("contract_sha256"))])
    for field, value in expected.items():
        if acceptance.get(field) != value:
            problems.append("%s is %r, the current artifacts give %r" % (field, acceptance.get(field), value))
    return OrderedDict([("status", status), ("valid_for_gate", not problems),
                        ("publication_allowed", bool(gate.get("publication_allowed"))),
                        ("reasons", list(gate.get("reasons") or [])), ("problems", problems),
                        ("label_required", gate.get("label_required")),
                        ("expected_values", expected)])


def readiness_document(ctx, gate, template, inputs=None):
    """What the author must decide, the exact values the decision must
    carry, the consequences of each status and how to validate - status
    AUTHOR_DECISION_REQUIRED while no valid decision record exists,
    DECISION_RECORDED (with `recorded_status`) once one does; self-hashed.
    Carries no ACCEPTED `status` field. Refuses without the live gate."""
    if not isinstance(gate, dict):
        raise core.ClosureRefused("publication gate unavailable: the readiness document needs the live "
                                  "gate result (pilot_freeze.publication_decision)")
    if not isinstance(template, dict) or template.get("status") != PENDING:
        raise core.ClosureRefused("acceptance template unavailable or not PENDING")
    root = ctx.root
    inputs = inputs if inputs is not None else load_inputs(root, ctx.frozen_contract(core.PILOT))
    state = decision_state(gate, inputs["acceptance_exists"])
    template_gate = pf.publication_decision(inputs["policy"], inputs["report"], template, root,
                                            inputs["contract"])
    disclosures = [OrderedDict([("id", d.get("id")), ("artifact", d.get("artifact")),
                                ("satisfied", bool(d.get("artifact_readable")) and bool(d.get("field_present"))
                                 and not d.get("problems"))])
                   for d in (gate.get("mandatory_disclosures") or [])]
    document = OrderedDict([
        ("schema_version", core.ACCEPTANCE_READINESS_SCHEMA),
        ("closure_id", core.CLOSURE_ID),
        ("run_id", core.PILOT),
        ("status", state["status"]),
        ("recorded_status", state["recorded_status"]),
        ("author_decision_required", state["author_decision_required"]),
        ("decision", OrderedDict([
            ("who", "the thesis author; the closure prepares the decision and never takes it"),
            ("what", "status ACCEPTED | REJECTED | PENDING, decided_by (name), decided_on (YYYY-MM-DD)"),
            ("artifact", core.RESULT_ACCEPTANCE_REL),
            ("artifact_exists", bool(inputs["acceptance_exists"])),
            ("template", core.ARTIFACT_DIR_REL + "/" + core.ACCEPTANCE_TEMPLATE),
            ("validate_command", VALIDATE_COMMAND),
            ("gate_function", inputs["policy"].get("gate_function")),
        ])),
        ("exact_values", OrderedDict([
            ("run_id", template["run_id"]),
            ("post_run_verification_status", template["post_run_verification_status"]),
            ("post_run_verification_sha256", template["post_run_verification_sha256"]),
            ("frozen_contract_sha256", template["frozen_contract_sha256"]),
            ("publication_policy_sha256", template["publication_policy_sha256"]),
            ("pilot_label", gate.get("label_required")),
        ])),
        ("consequences", OrderedDict([
            ("ACCEPTED", "publication_allowed becomes true only with the pilot label and every "
                         "mandatory disclosure; results may then be used as pilot results, never as "
                         "a full 60-benchmark study"),
            ("REJECTED", "publication stays refused; the verified measurements stay in the "
                         "repository as unaccepted results"),
            ("PENDING", "nothing changes; publication_allowed stays false"),
        ])),
        ("gate_now", OrderedDict([
            ("publication_allowed", bool(gate.get("publication_allowed"))),
            ("result_acceptance_status", gate.get("result_acceptance_status")),
            ("reasons", list(gate.get("reasons") or [])),
            ("label_required", gate.get("label_required")),
            ("mandatory_disclosures", disclosures),
        ])),
        ("template_gate", OrderedDict([
            ("publication_allowed", bool(template_gate.get("publication_allowed"))),
            ("reasons", list(template_gate.get("reasons") or [])),
            ("only_pending_reasons", not template_problems(template_gate.get("reasons"))),
        ])),
        ("inputs_raw_sha256", inputs["raw_sha256"]),
    ])
    document = core.json_stable(document)
    document["readiness_sha256"] = core.self_hash(document, "readiness_sha256")
    return document


# -- section --------------------------------------------------------------------------------------

def collect(ctx):
    section = core.Section(SECTION)
    try:
        inputs = load_inputs(ctx.root, ctx.frozen_contract(core.PILOT))
    except Exception as error:  # noqa: BLE001 - every input failure is a FAIL of every check
        for check_id in CHECK_IDS:
            section.add(check_id, False, "input unavailable: %s: %s" % (type(error).__name__, error))
        return section
    policy, report, contract = inputs["policy"], inputs["report"], inputs["contract"]
    section.data["inputs"] = OrderedDict([("raw_sha256", inputs["raw_sha256"]),
                                          ("acceptance_file", core.RESULT_ACCEPTANCE_REL),
                                          ("acceptance_exists", inputs["acceptance_exists"])])
    section.guard("pilot_post_run_report", report_check, report, contract,
                  inputs["raw_sha256"][core.PILOT_POST_RUN_REL])
    section.guard("publication_policy_fresh", policy_check, policy, contract)
    section.guard("mandatory_disclosure_sources", sources_check, policy, ctx.root)

    def _gate():
        gate = pf.publication_decision(policy, report, inputs["acceptance"], ctx.root, contract)
        ctx.cache["publication_gate"] = gate
        return gate_check(gate, inputs["acceptance_exists"])

    section.guard("publication_gate_now", _gate)

    def _template():
        template = acceptance_template(report, contract, policy)
        ctx.cache["acceptance_template"] = template
        reasons = pf.publication_decision(policy, report, template, ctx.root, contract).get("reasons")
        problems = template_problems(reasons)
        return not problems, OrderedDict([("status", template["status"]), ("reasons", list(reasons or [])),
                                          ("problems", problems),
                                          ("post_run_verification_sha256",
                                           template["post_run_verification_sha256"]),
                                          ("frozen_contract_sha256", template["frozen_contract_sha256"])])

    section.guard("template_valid", _template)

    def _readiness():
        gate = ctx.cache.get("publication_gate")
        template = ctx.cache.get("acceptance_template")
        if gate is None or template is None:
            raise core.ClosureRefused("gate or template unavailable")
        document = readiness_document(ctx, gate, template, inputs)
        ctx.cache["acceptance_readiness"] = document
        section.data["readiness"] = document
        section.data["template"] = template
        return True, OrderedDict([("status", document["status"]),
                                  ("readiness_sha256", document["readiness_sha256"])])

    section.guard("readiness_document", _readiness)
    gate = ctx.cache.get("publication_gate") or OrderedDict()
    state = decision_state(gate, inputs["acceptance_exists"])
    section.data["summary"] = OrderedDict([
        ("acceptance_file", core.RESULT_ACCEPTANCE_REL),
        ("acceptance_exists", inputs["acceptance_exists"]),
        ("publication_allowed", bool(gate.get("publication_allowed"))),
        ("result_acceptance_status", gate.get("result_acceptance_status")),
        ("post_run_verification_sha256", gate.get("post_run_verification_sha256")),
        ("frozen_contract_sha256", contract.get("contract_sha256")),
        ("label_required", gate.get("label_required")),
        ("reasons", list(gate.get("reasons") or [])),
        ("readiness_status", state["status"]),
        ("recorded_status", state["recorded_status"]),
        ("author_decision_required", state["author_decision_required"]),
    ])
    return section


# -- CLI -----------------------------------------------------------------------------------------

def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="pilot_002 result acceptance: template, validator, "
                                                 "readiness (read-only, never ACCEPTED)")
    parser.add_argument("--template", action="store_true", help="print the PENDING template")
    parser.add_argument("--check", metavar="PATH", help="validate a candidate acceptance file; "
                                                        "exit 0 iff it is structurally valid")
    parser.add_argument("--readiness", action="store_true", help="print the readiness document")
    parser.add_argument("--root", default=str(core.REPO_ROOT))
    args = parser.parse_args(argv)
    pl.isolate_providers()
    root = Path(args.root).resolve()
    if args.check:
        path = Path(args.check)
        candidate = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
        result = validate_acceptance(root, candidate)
        sys.stdout.write(json.dumps(result, indent=1, default=str) + "\n")
        return 0 if result["valid_for_gate"] else 1
    if args.template:
        inputs = load_inputs(root)
        template = acceptance_template(inputs["report"], inputs["contract"], inputs["policy"])
        sys.stdout.write(json.dumps(template, indent=1, default=str) + "\n")
        return 0
    if args.readiness:
        ctx = core.load_context(root)
        inputs = load_inputs(root, ctx.frozen_contract(core.PILOT))
        gate = pf.publication_decision(inputs["policy"], inputs["report"], inputs["acceptance"], root,
                                       inputs["contract"])
        template = acceptance_template(inputs["report"], inputs["contract"], inputs["policy"])
        document = readiness_document(ctx, gate, template, inputs)
        sys.stdout.write(json.dumps(document, indent=1, default=str) + "\n")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
