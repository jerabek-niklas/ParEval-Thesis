"""Effective stage invocation provenance (effective_stage_invocation.v1).

A methodical CLI override is allowed - but only if it is DECLARED and
PINNED:

    METHODICAL OVERRIDES ARE ALLOWED ONLY IF DECLARED AND PINNED

    1. the frozen contract expects exactly this value
    2. the T0 rebuild sees the same value
    3. the stage registers the same value as its effective invocation
    4. the post-run verifier compares the same value

Config 120 + contract 120 + actual `--run-timeout 60` must therefore be
refused before the stage runs; contract 60 + actual 60 is allowed. A
verifier that only compares the manifest's frozen config against the
contract (120 == 120) would call that run PASS - the effective value is the
one this module persists.

Only values that a CLI can actually override are stored. Values that are
config-only (niter, launch grid, build timeout) already have an
authoritative owner in the evaluation condition and are NOT duplicated here
(`ONE METHODICAL VALUE -> ONE AUTHORITATIVE SOURCE + optional override
layer`); FORBIDDEN_DUPLICATE_FIELDS makes that testable.

Fragments: invocation.<stage>, one owner per stage, idempotent for an
identical methodical fingerprint and a HARD FAIL for a different one.

Python 3.8 compatible.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

EFFECTIVE_INVOCATION_VERSION = "effective_stage_invocation.v1"
OVERRIDE_POLICY = "ALLOWED_ONLY_IF_DECLARED_AND_PINNED"

SOURCE_CLI = "CLI"
SOURCE_CONFIG = "CONFIG"
SOURCE_DEFAULT = "DEFAULT"

# Config-only methodical values: they have exactly one authoritative owner
# (the evaluation condition / the frozen config) and must never appear as a
# second source of truth in an invocation fragment.
FORBIDDEN_DUPLICATE_FIELDS = (
    "niter", "launch_configs", "build_timeout_seconds", "max_validation_attempts",
    "auto_close_single_brace", "target_cases_per_benchmark", "static_base_sizes",
)

# Which contract field an effective value must equal (when the contract pins one).
CONTRACT_EXPECTATIONS = OrderedDict([
    ("effective_run_timeout_seconds", "run_timeout_seconds"),
    ("effective_enhanced_run_timeout_seconds", "enhanced_run_timeout_seconds"),
    ("primary_compiler", "primary_compiler"),
])

# ---------------------------------------------------------------------------
# machine-readable coupling to the CLI inventory
# ---------------------------------------------------------------------------
#
# An invocation fragment may only carry values that are METHODICAL CLI
# overrides of THAT stage. Anything else is misleading provenance: a reader
# would take it for a pinned methodical value although it changes nothing
# that is measured. `output_file_name` was exactly that case - the CLI
# inventory classifies it as NON_METHODICAL ("name of the stage's own output
# file - the measured content is unchanged"), yet the correctness stage
# registered it.

# invocation field -> the CLI dest whose effective value it is
INVOCATION_FIELD_TO_CLI_DEST = OrderedDict([
    ("effective_run_timeout_seconds", "run_timeout"),
    ("effective_enhanced_run_timeout_seconds", "run_timeout"),
    ("primary_compiler", "primary_compiler"),
    ("model_scope", "model_id"),
    ("tools", "tools"),
    ("specs", "specs"),
    ("jobs", "jobs"),
    ("variant", "variant"),
    ("replace_tool_entries", "replace_tool_entries"),
    ("replace_legacy_record", "replace_legacy_record"),
    ("rerun_gaps", "rerun_gaps"),
    ("skip_unavailable_tools", "skip_unavailable_tools"),
])

# measurement stage -> the runner stage of the CLI inventory
STAGE_TO_INVENTORY_STAGE = OrderedDict([
    ("correctness", "correctness"),
    ("dynamic", "dynamic"),
    ("enhanced", "enhanced"),
    ("static.main", "static"),
    ("static.parcoach", "static"),
    ("static.llov", "static"),
    ("repair_evaluation", "repair"),
])

_INVENTORY_CACHE = {}


def _inventory():
    if "inventory" not in _INVENTORY_CACHE:
        from thesis.evaluation import cli_override_inventory as coi

        _INVENTORY_CACHE["inventory"] = coi.build_inventory()
    return _INVENTORY_CACHE["inventory"]


def cli_dest_for(field: str) -> str:
    """The canonical CLI dest an invocation field is the effective value of."""
    return INVOCATION_FIELD_TO_CLI_DEST.get(field, field)


def field_classification(stage: str, field: str) -> "OrderedDict[str, Any]":
    """Is this invocation field a METHODICAL CLI override of `stage`?"""
    inventory_stage = STAGE_TO_INVENTORY_STAGE.get(stage)
    dest = cli_dest_for(field)
    if inventory_stage is None:
        # fail-closed: an unmapped stage cannot prove its field is methodical
        return OrderedDict([("field", field), ("cli_dest", dest), ("stage", stage),
                            ("methodical", False),
                            ("reason", "no CLI inventory stage is mapped for %r, so the "
                                       "field cannot be shown to be methodical" % stage)])
    inventory = _inventory()
    methodical = {e["dest"] for e in
                  inventory["METHODICAL_CLI_OVERRIDES_BY_STAGE"].get(inventory_stage, [])}
    non_methodical = {e["dest"]: e.get("reason") for e in
                      inventory["NON_METHODICAL_CLI_OPTIONS_BY_STAGE"].get(inventory_stage, [])}
    if dest in methodical:
        return OrderedDict([("field", field), ("cli_dest", dest), ("stage", inventory_stage),
                            ("methodical", True), ("reason", None)])
    if dest in non_methodical:
        return OrderedDict([("field", field), ("cli_dest", dest), ("stage", inventory_stage),
                            ("methodical", False), ("reason", non_methodical[dest])])
    from thesis.evaluation import cli_override_inventory as coi

    if dest in coi.NON_METHODICAL_REASONS:
        # the option exists in the pipeline and is classified NON_METHODICAL -
        # it is not a CLI option of THIS runner either way
        return OrderedDict([("field", field), ("cli_dest", dest), ("stage", inventory_stage),
                            ("methodical", False), ("reason", coi.NON_METHODICAL_REASONS[dest])])
    if field in CONTRACT_EXPECTATIONS:
        # A methodical value the FROZEN CONTRACT pins. It is declared and
        # pinned even where the runner exposes no CLI option for it (the
        # enhanced run timeout comes from the config, and the contract pins
        # enhanced_run_timeout_seconds), so persisting its EFFECTIVE value is
        # exactly what the override policy requires.
        return OrderedDict([("field", field), ("cli_dest", dest), ("stage", inventory_stage),
                            ("methodical", True),
                            ("reason", "contract-pinned methodical value (%s)"
                                       % CONTRACT_EXPECTATIONS[field])])
    return OrderedDict([("field", field), ("cli_dest", dest), ("stage", inventory_stage),
                        ("methodical", False),
                        ("reason", "neither a methodical CLI override of this stage "
                                   "(%s) nor a contract-pinned value (%s)"
                                   % (", ".join(sorted(methodical)),
                                      ", ".join(CONTRACT_EXPECTATIONS)))])


def non_methodical_fields(stage: str, effective_values: "Dict[str, Any]") -> "List[str]":
    """Registered fields that carry no methodical meaning for `stage`.

    Every invocation field must be either the effective value of an option in
    METHODICAL_CLI_OVERRIDES_BY_STAGE[stage] - under the option's own dest or
    under an explicitly declared canonical name (INVOCATION_FIELD_TO_CLI_DEST)
    - or a value the frozen contract pins (CONTRACT_EXPECTATIONS). Anything
    else is misleading provenance: it reads as a pinned methodical override
    although it changes nothing that is measured."""
    problems = []
    for field in sorted(effective_values or {}):
        verdict = field_classification(stage, field)
        if verdict["methodical"] is False:
            problems.append("%s (CLI dest %r is not a methodical override of stage %s: %s)"
                            % (field, verdict["cli_dest"], verdict["stage"],
                               verdict["reason"]))
    return problems


class InvocationRefused(RuntimeError):
    """The effective invocation contradicts the frozen contract - the stage
    must not produce records. Not a tool or model failure."""

    failure_class = "EFFECTIVE_INVOCATION_DRIFT"


def value(effective: Any, cli: Any, config_value: Any = None,
          default: Any = None) -> "OrderedDict[str, Any]":
    """One field: its effective value and where that value came from."""
    if cli is not None:
        source = SOURCE_CLI
    elif config_value is not None:
        source = SOURCE_CONFIG
    else:
        source = SOURCE_DEFAULT
    return OrderedDict([("value", effective), ("source", source)])


def invocation_fingerprint(invocation: "Dict[str, Any]") -> str:
    """Methodical fields only: schema, stage, run id, scope and the effective
    values with their source. Never a timestamp, pid or hostname."""
    from thesis.evaluation.condition_hashing import canonical_sha256

    body = OrderedDict([
        ("schema_version", invocation.get("schema_version")),
        ("stage", invocation.get("stage")),
        ("run_id", invocation.get("run_id")),
        ("profile", invocation.get("profile")),
        ("model_scope", invocation.get("model_scope")),
        ("override_policy", invocation.get("override_policy")),
        ("effective_values", OrderedDict(
            (name, OrderedDict([("value", entry.get("value")),
                                ("source", entry.get("source"))]))
            for name, entry in sorted((invocation.get("effective_values") or {}).items()))),
    ])
    return canonical_sha256(body)


def build_invocation(run_id: str, stage: str, profile: "Optional[str]",
                     effective_values: "Dict[str, Any]",
                     model_scope: "Optional[Any]" = None,
                     contract: "Optional[Dict[str, Any]]" = None
                     ) -> "OrderedDict[str, Any]":
    duplicates = sorted(set(effective_values) & set(FORBIDDEN_DUPLICATE_FIELDS))
    if duplicates:
        raise InvocationRefused(
            "the invocation fragment must not duplicate config-only methodical values "
            "(%s): they already have an authoritative owner in the evaluation condition"
            % ", ".join(duplicates))
    misleading = non_methodical_fields(stage, effective_values)
    if misleading:
        raise InvocationRefused(
            "the invocation fragment must not carry NON_METHODICAL values (%s): they read "
            "as pinned methodical overrides although they change nothing that is measured"
            % "; ".join(misleading))
    invocation = OrderedDict([
        ("schema_version", EFFECTIVE_INVOCATION_VERSION),
        ("run_id", run_id),
        ("stage", stage),
        ("profile", profile),
        ("model_scope", model_scope),
        ("override_policy", OVERRIDE_POLICY),
        ("effective_values", OrderedDict(sorted(effective_values.items()))),
    ])
    if contract:
        expectations = OrderedDict()
        for field, contract_field in CONTRACT_EXPECTATIONS.items():
            if field in invocation["effective_values"] and contract_field in contract:
                expectations[field] = contract.get(contract_field)
        if expectations:
            invocation["contract_expected_values"] = expectations
    invocation["invocation_sha256"] = invocation_fingerprint(invocation)
    return invocation


def check_against_contract(invocation: "Dict[str, Any]",
                           contract: "Optional[Dict[str, Any]]") -> "List[str]":
    """Every effective value the contract pins must match exactly."""
    if not contract:
        return []
    problems = []
    values = invocation.get("effective_values") or {}
    for field, contract_field in CONTRACT_EXPECTATIONS.items():
        if field not in values or contract_field not in contract:
            continue
        expected = contract.get(contract_field)
        actual = (values[field] or {}).get("value")
        if expected is None:
            continue
        if _normalize(expected) != _normalize(actual):
            problems.append(
                "%s: contract pins %r but the effective invocation uses %r (source %s) - "
                "a methodical override is allowed ONLY if the contract pins exactly that "
                "value" % (field, expected, actual, (values[field] or {}).get("source")))
    # the model scope must be declared in the contract's model set
    scope = invocation.get("model_scope")
    contracted_models = contract.get("model_ids")
    if scope and contracted_models:
        missing = [m for m in _as_list(scope) if m not in contracted_models]
        if missing:
            problems.append("model_scope %s is not part of the contracted model set"
                            % ", ".join(missing))
    return problems


def _normalize(value_: Any) -> Any:
    if isinstance(value_, bool):
        return value_
    if isinstance(value_, (int, float)):
        return float(value_)
    if isinstance(value_, (list, tuple)):
        return [str(v) for v in value_]
    return value_


def _as_list(value_: Any) -> "List[Any]":
    if value_ is None:
        return []
    if isinstance(value_, (list, tuple, set)):
        return list(value_)
    return [value_]


def register_effective_invocation(config: "Dict[str, Any]", run_id: str, stage: str,
                                  effective_values: "Dict[str, Any]", *,
                                  profile: "Optional[str]" = None,
                                  model_scope: "Optional[Any]" = None,
                                  writer: "Optional[str]" = None,
                                  require_contract: bool = True
                                  ) -> "OrderedDict[str, Any]":
    """Validate the effective invocation against the frozen contract and
    register it as invocation.<stage>. Raises InvocationRefused BEFORE the
    stage produces records."""
    from thesis.evaluation import manifest_fragments as mf
    from thesis.evaluation import run_manifest

    manifest = run_manifest.load_manifest(config, run_id) or {}
    contract = manifest.get("contract")
    if contract is None and require_contract:
        raise InvocationRefused(
            "EFFECTIVE_INVOCATION_DRIFT (%s): the run carries no frozen contract, so a "
            "methodical override cannot be declared and pinned. Authorize the run first."
            % stage)
    invocation = build_invocation(run_id, stage, profile, effective_values,
                                  model_scope=model_scope, contract=contract)
    problems = check_against_contract(invocation, contract)
    if problems:
        raise InvocationRefused("EFFECTIVE_INVOCATION_DRIFT (%s): %s"
                                % (stage, "; ".join(problems)))
    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    try:
        mf.register_fragment(intermediate_dir, run_id, "invocation",
                             invocation_owner(stage, model_scope, effective_values),
                             invocation,
                             fingerprint=invocation["invocation_sha256"],
                             writer=writer or stage)
    except mf.FragmentConflict as conflict:
        raise InvocationRefused(
            "EFFECTIVE_INVOCATION_DRIFT (%s): this run already registered a DIFFERENT "
            "effective invocation for the stage%s: %s"
            % (stage, "" if not model_scope else " and model scope %s"
               % ", ".join(_as_list(model_scope)), conflict))
    mf.write_snapshot(intermediate_dir, run_id)
    return invocation


# Effective values that say WHICH SUBSET OF THE WORK an invocation covers,
# rather than under which condition it runs. A stage may legitimately be
# invoked several times per run with different values here - the repair loop
# runs once per (model, variant), the static stage once per tool subset and
# container - so they belong in the fragment OWNER. Everything else (timeouts,
# compiler, flags) stays fingerprint-only, so a CONTRADICTING condition under
# the SAME scope is still a HARD FAIL.
INVOCATION_SCOPE_FIELDS = ("variant", "tools")


def invocation_owner(stage: str, model_scope: "Optional[Any]" = None,
                     effective_values: "Optional[Dict[str, Any]]" = None) -> str:
    """The invocation fragment's owner: stage + the invocation's SCOPE.

    A stage that is invoked per model and per variant - the PARCOACH/LLOV
    containers and the repair loop (11 models x 3 variants) - produces one
    genuinely different effective invocation per scope. Keying the fragment by
    the stage alone made the second model, and then the second variant, a HARD
    FAIL that stopped the run. Putting the scope in the owner keeps the
    per-writer fragment architecture intact: same stage + same scope stays
    idempotent, and a CHANGED invocation under the same scope is still
    refused."""
    parts = []
    scope = _as_list(model_scope)
    if scope:
        parts.append("+".join(sorted(str(item) for item in scope)))
    for field in INVOCATION_SCOPE_FIELDS:
        entry = (effective_values or {}).get(field)
        if entry is None:
            continue
        value = entry.get("value") if isinstance(entry, dict) else entry
        if value is None:
            continue
        rendered = ("+".join(sorted(str(item) for item in value))
                    if isinstance(value, (list, tuple, set)) else str(value))
        parts.append("%s-%s" % (field, rendered))
    if not parts:
        return stage
    return "%s@%s" % (stage, "@".join(parts))


def registered_invocations(manifest: "Optional[Dict[str, Any]]") -> "Dict[str, Any]":
    return (manifest or {}).get("stage_invocations") or {}


def invocations_for_stage(manifest: "Optional[Dict[str, Any]]",
                          stage: str) -> "List[Dict[str, Any]]":
    """Every registered invocation of `stage`, across model scopes."""
    return [invocation for owner, invocation in sorted(registered_invocations(manifest).items())
            if (isinstance(invocation, dict) and invocation.get("stage") == stage)
            or str(owner) == stage or str(owner).startswith(stage + "@")]
