"""Exact registered old -> new pairs, never a generic hash-drift exception.

Certificates are pinned by the composite contract. Creating/reviewing a
certificate is deliberately separate from verifying it. This module never
creates certificates or upgrades unknown fingerprints automatically.
"""
from __future__ import annotations
from pathlib import Path
from thesis.evaluation import condition_hashing as ch

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_CONDITIONS = frozenset({"enhanced_runner_sources_sha256"})
CLASSIFICATION = "BACKFILL_AUTHORITY_TARGET_MISSING_ONLY_PROVENANCE"
INVARIANTS = (
    "generation_provider_parameters", "prompts_and_text", "assembly_cleaning",
    "compiler_static_semantics", "correctness_semantics_launch",
    "dynamic_semantics", "enhanced_specs_policy_launch_verdict",
    "repair_feedback_stop_variants_iterations", "models_reasoning", "tools_scope",
)

class Refuse(ValueError):
    pass

def fingerprint(document):
    return ch.canonical_sha256({k:v for k,v in document.items() if k != "certificate_sha256"})

def validate_certificate(certificate, expected_sha, root=ROOT):
    if (certificate.get("schema_version") != "method_equivalence.v1" or
            certificate.get("status") != "PROVEN" or not expected_sha or
            certificate.get("certificate_sha256") != expected_sha or
            fingerprint(certificate) != expected_sha):
        raise Refuse("missing/unproven/tampered equivalence certificate")
    if set(certificate.get("unchanged_fields", {})) != set(INVARIANTS):
        raise Refuse("incomplete methodological invariants")
    for field, values in certificate["unchanged_fields"].items():
        if not values.get("old") or values.get("old") != values.get("new"):
            raise Refuse("methodological field changed: " + field)
    tests = certificate.get("tests", [])
    if not tests or any(t.get("status") != "PASS" or not t.get("evidence_sha256") for t in tests):
        raise Refuse("equivalence tests not proven")
    pairs = certificate.get("pairs", [])
    seen = set()
    for pair in pairs:
        name = pair.get("condition")
        if name not in ALLOWED_CONDITIONS or name in seen:
            raise Refuse("unknown/duplicate condition exemption")
        seen.add(name)
        if (pair.get("classification") != CLASSIFICATION or not pair.get("exact_diff") or
                not pair.get("old_fingerprint") or not pair.get("new_fingerprint")):
            raise Refuse("incomplete equivalence pair")
    if not pairs or not certificate.get("source_pins"):
        raise Refuse("empty equivalence proof")
    for relative, expected in certificate["source_pins"].items():
        path = (Path(root) / relative).resolve()
        if Path(root).resolve() not in path.parents or ch.lf_normalized_sha256(path) != expected:
            raise Refuse("certificate source drift: " + relative)

def compare_conditions(old, new, certificate=None, expected_sha=None, root=ROOT):
    if set(old) != set(new):
        raise Refuse("condition key set differs")
    differences = [k for k in old if old[k] != new[k]]
    if not differences:
        return
    validate_certificate(certificate or {}, expected_sha, root)
    pairs = {p["condition"]:(p["old_fingerprint"],p["new_fingerprint"]) for p in certificate["pairs"]}
    for key in differences:
        if pairs.get(key) != (old[key],new[key]):
            raise Refuse("unregistered condition fingerprint pair: " + key)
