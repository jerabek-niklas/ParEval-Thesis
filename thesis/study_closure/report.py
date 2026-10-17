"""Assembly and rendering of the closure document (study_global_verification.v1).

The document is deterministic apart from its `volatile` block (timestamps,
durations, interpreter); its self-hash `closure_sha256` follows the sha_rule
of the pilot artifacts (canonical sha256 without `volatile` and the hash
field). The markdown rendering is derived from the document only, so the
two artifacts can never disagree.

Nothing here reads the repository; run.py passes the sections and context.
"""
from __future__ import annotations

import json
import platform
from collections import OrderedDict

from thesis.study_closure import core

SECTION_ORDER = ("identity", "runs", "tree", "history", "population", "phase2", "coverage",
                 "acceptance", "disclosures")
STATUS_FLAGS = ("MEASUREMENTS_COMPLETE", "COMPOSITE_VERIFICATION_COMPLETE",
                "FORMAL_GLOBAL_VERIFICATION_COMPLETE", "PILOT_ACCEPTANCE_COMPLETE",
                "PUBLICATION_READY", "READY_FOR_SCIENTIFIC_ANALYSIS")


def _get(mapping, *keys, default=None):
    node = mapping
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def section_map(sections):
    return OrderedDict((section.name, section) for section in sections)


def _status_of(sections, *names):
    """PASS iff every named section exists and passed."""
    by_name = section_map(sections)
    return all(name in by_name and by_name[name].status == core.PASS for name in names)


def flags(sections, ctx, formal):
    """The six closure flags. Technical flags follow the sections; the
    acceptance/publication flags follow the author's decision (never set by
    the closure itself)."""
    by_name = section_map(sections)
    gate = ctx.cache.get("publication_gate") or {}
    measurements = _status_of(sections, "population", "phase2") and _status_of(sections, "runs")
    composite = (_status_of(sections, "population")
                 and bool(_get(by_name.get("population").data if "population" in by_name else {},
                               "composite", "persisted")))
    global_ok = all(s.status == core.PASS for s in sections) and bool(sections)
    acceptance_status = gate.get("result_acceptance_status")
    accepted = acceptance_status == "ACCEPTED" and bool(gate.get("publication_allowed"))
    return OrderedDict([
        ("MEASUREMENTS_COMPLETE", "YES" if measurements else "NO"),
        ("COMPOSITE_VERIFICATION_COMPLETE", "YES" if composite else "NO"),
        ("FORMAL_GLOBAL_VERIFICATION_COMPLETE", "YES" if (global_ok and formal) else "NO"),
        ("PILOT_ACCEPTANCE_COMPLETE", "YES" if accepted else "NO"),
        ("PUBLICATION_READY", "YES" if (accepted and global_ok and formal) else "NO"),
        ("READY_FOR_SCIENTIFIC_ANALYSIS", "YES" if (measurements and composite and global_ok) else "NO"),
    ])


def summary(sections, ctx):
    """The compact facts an analysis cites (all computed by the sections)."""
    by_name = section_map(sections)
    bindings = ctx.cache.get("run_bindings") or OrderedDict()
    composite = ctx.cache.get("composite_document") or {}
    census = ctx.cache.get("census_summary") or {}
    evidence = _get(by_name["coverage"].data, "runs_evidence", default={}) if "coverage" in by_name else {}
    runs = OrderedDict()
    for run in core.RUNS:
        binding = bindings.get(run) or {}
        runs[run] = OrderedDict([
            ("role", core.RUN_REGISTRY[run]["role"]),
            ("block", core.RUN_REGISTRY[run]["block"]),
            ("contract_sha256", binding.get("contract_sha256")),
            ("authorization_sha256", binding.get("authorization_sha256")),
            ("manifest_complete", binding.get("manifest_complete")),
            ("git_commit", binding.get("git_commit")),
            ("models", len(binding.get("model_ids") or [])),
            ("verification_evidence", evidence.get(run)),
            ("closure_checks", OrderedDict([
                ("runs", [c["status"] for c in (by_name["runs"].checks if "runs" in by_name else [])
                          if c["check"].startswith("runs:%s:" % run)]),
            ])),
        ])
    verify = ctx.cache.get("phase2_verify") or {}
    pairs = OrderedDict([("pilot", 0), ("full_ext", 0)])
    for result in verify.values():
        for block in pairs:
            pairs[block] += _get(result, "counts", block, "enhanced", "expected_pairs", default=0) or 0
    pairs["total"] = pairs["pilot"] + pairs["full_ext"]
    gate = ctx.cache.get("publication_gate") or {}
    return OrderedDict([
        ("runs", runs),
        ("population", _get(composite, "population", default=None)),
        ("cells", _get(composite, "cells", default=None)),
        ("repair_loops", census.get("total_repair_loops_done")),
        ("repair_loop_owners", OrderedDict((block, _get(census, "blocks", block, "owners"))
                                           for block in ("pilot", "full_ext"))),
        ("enhanced_pairs", pairs),
        ("composite", _get(by_name["population"].data, "composite") if "population" in by_name else None),
        ("phase2_incidents", _get(by_name["phase2"].data, "incidents") if "phase2" in by_name else None),
        ("pilot_publication_gate", OrderedDict([
            ("publication_allowed", gate.get("publication_allowed")),
            ("result_acceptance_status", gate.get("result_acceptance_status")),
            ("reasons", gate.get("reasons")),
            ("label_required", gate.get("label_required")),
        ])),
        ("verification_scopes", _get(by_name["coverage"].data, "scopes") if "coverage" in by_name else None),
    ])


def build_document(sections, ctx, formal):
    """The closure document (sections in SECTION_ORDER first, unknown ones
    appended), self-hashed."""
    ordered = sorted(sections, key=lambda s: (SECTION_ORDER.index(s.name) if s.name in SECTION_ORDER
                                              else len(SECTION_ORDER), s.name))
    tree = section_map(ordered).get("tree")
    inventory = _get(tree.data, "phase2_inventory") if tree is not None else None
    document = OrderedDict([
        ("schema_version", core.SCHEMA),
        ("closure_id", core.CLOSURE_ID),
        ("scope", core.SCOPE),
        ("retrospective_scope", core.RETROSPECTIVE_SCOPE),
        ("formal", bool(formal)),
        ("mode_note", "formal closure (worktree clean, artifacts persisted)" if formal
         else "dry run (nothing persisted; not a formal closure)"),
        ("run_ids", list(core.RUNS)),
        ("model_ids", list(core.MODELS)),
        ("git", core.git_state(ctx.root)),
        ("source_pins", core.closure_source_pins(ctx.root)),
        ("options", OrderedDict((k, v) for k, v in ctx.options.items() if k != "persist_composite")),
        ("status", core.PASS if ordered and all(s.status == core.PASS for s in ordered) else core.FAIL),
        ("flags", flags(ordered, ctx, formal)),
        ("summary", summary(ordered, ctx)),
        ("sections", [s.document() for s in ordered]),
        ("closure_protected", OrderedDict([
            (core.PHASE2, OrderedDict([
                ("inventory_sha256", _get(inventory, "inventory_sha256") if isinstance(inventory, dict) else None),
                ("file_count", _get(inventory, "file_count") if isinstance(inventory, dict) else None),
                ("total_bytes", _get(inventory, "total_bytes") if isinstance(inventory, dict) else None),
                ("files", _get(inventory, "files") if isinstance(inventory, dict) else None),
            ])),
        ])),
        ("sha_rule", "condition_hashing.canonical_sha256 of the document without `volatile` and "
                     "`closure_sha256`"),
        ("volatile", OrderedDict([
            ("started_at_utc", ctx.started_utc), ("generated_at_utc", core.utc_now()),
            ("timings_seconds", ctx.timings), ("python", platform.python_version()),
            ("platform", platform.platform()),
        ])),
    ])
    document = core.json_stable(document)
    document["closure_sha256"] = core.self_hash(document, "closure_sha256")
    return document


def verify_document(document):
    if document.get("schema_version") != core.SCHEMA:
        raise core.ClosureRefused("not a %s document" % core.SCHEMA)
    if core.self_hash(document, "closure_sha256") != document.get("closure_sha256"):
        raise core.ClosureRefused("closure document does not reproduce its hash")
    return True


# -- markdown --------------------------------------------------------------------------

def _row(*cells):
    return "| " + " | ".join(str(c) if c is not None else "-" for c in cells) + " |"


def _short(value):
    return core.short(value, 16) if value else "-"


def _fmt(value):
    if isinstance(value, (dict, list)):
        text = json.dumps(value, default=str, sort_keys=False)
        return text if len(text) <= 160 else text[:157] + "..."
    return str(value)


def render_markdown(document):
    lines = []
    out = lines.append
    out("# %s - global verification of the study (%s)" % (document["closure_id"], document["status"]))
    out("")
    out("Scope `%s`; schema `%s`; closure sha256 `%s`." % (document["scope"], document["schema_version"],
                                                           document["closure_sha256"]))
    out("Mode: %s. Git HEAD `%s` (%s, %s)." % (document["mode_note"], document["git"]["head"],
                                               document["git"].get("branch"),
                                               "clean" if document["git"]["clean"] else
                                               "%d uncommitted path(s)" % document["git"]["uncommitted_count"]))
    out("")
    out("## Flags")
    out("")
    for flag, value in document["flags"].items():
        out("- `%s = %s`" % (flag, value))
    out("")
    out("## Sections")
    out("")
    out(_row("section", "status", "checks", "failing"))
    out(_row("---", "---", "---", "---"))
    for section in document["sections"]:
        out(_row(section["section"], section["status"], section["checks"],
                 ", ".join(section["failing"]) if section["failing"] else "-"))
    out("")
    s = document["summary"]
    out("## The seven runs")
    out("")
    out(_row("run", "block", "models", "contract", "authorization", "manifest", "verification evidence"))
    out(_row("---", "---", "---", "---", "---", "---", "---"))
    for run, entry in s["runs"].items():
        out(_row(run, entry["block"], entry["models"], _short(entry["contract_sha256"]),
                 _short(entry["authorization_sha256"]), "complete" if entry["manifest_complete"] else "INCOMPLETE",
                 _fmt(entry["verification_evidence"])))
    out("")
    out("## Population and candidates")
    out("")
    out("- base population: %s" % _fmt(s["population"]))
    out("- composite cells: %s" % _fmt(s["cells"]))
    out("- repair loops terminal: %s (owners %s)" % (s["repair_loops"], _fmt(s["repair_loop_owners"])))
    out("- enhanced (sample, spec) pairs: %s" % _fmt(s["enhanced_pairs"]))
    out("- composite artifact: %s" % _fmt(s["composite"]))
    out("- phase-2 incidents: %s" % _fmt(s["phase2_incidents"]))
    out("")
    out("## Pilot publication gate")
    out("")
    gate = s["pilot_publication_gate"]
    out("- publication_allowed: %s; result acceptance: %s" % (gate["publication_allowed"],
                                                               gate["result_acceptance_status"]))
    for reason in gate.get("reasons") or []:
        out("- reason: %s" % reason)
    out("- label required: %s" % gate.get("label_required"))
    out("")
    if s.get("verification_scopes"):
        out("## Verification scopes")
        out("")
        scopes = s["verification_scopes"]
        if isinstance(scopes, dict):
            for key, value in scopes.items():
                out("- `%s`: %s" % (key, _fmt(value)))
        else:
            for value in scopes:
                out("- %s" % _fmt(value))
        out("")
    out("## Checks")
    out("")
    for section in document["sections"]:
        out("### %s (%s)" % (section["section"], section["status"]))
        out("")
        out(_row("check", "status", "detail"))
        out(_row("---", "---", "---"))
        for check in section["check_list"]:
            out(_row(check["check"], check["status"], _fmt(check["detail"]).replace("|", "\\|")))
        out("")
    out("## Closure-protected bytes")
    out("")
    for run, entry in document["closure_protected"].items():
        out("- `%s`: %s files, %s bytes, inventory sha256 `%s`" % (
            run, entry.get("file_count"), entry.get("total_bytes"), entry.get("inventory_sha256")))
    out("")
    out("## Source pins")
    out("")
    for group, pins in document["source_pins"].items():
        out("- %s:" % group)
        for path, sha in pins.items():
            out("  - `%s` `%s`" % (path, sha))
    out("")
    out("Generated %s (started %s)." % (document["volatile"]["generated_at_utc"],
                                        document["volatile"]["started_at_utc"]))
    return "\n".join(lines) + "\n"
