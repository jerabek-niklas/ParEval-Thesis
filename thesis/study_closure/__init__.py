"""Formal closure of the whole study (study_closure_001): read-only global
verification over the seven experiment runs and the persisted final composite.

Runs (evidence lineage): pilot_002 (pilot block, base cells + its own repair
candidates), full_ext_001 (full-extension base cells), full_ext_recovery_001
..004 (the 33 full-extension repair loops and their candidates),
full_ext_phase2_001 (phase-2 backfill + held-out enhanced tests of every
full-extension candidate).

The closure NEVER measures, generates, repairs or contacts a provider, and
never changes a historical byte: it reads, re-derives, compares and writes
only its own artifacts (the composite under the phase-2 results tree through
the phase-2 writer, and the closure reports under thesis/evaluation/closure).
The author's result acceptance of the pilot is a separate decision that the
closure prepares but never takes.

    python3 -B -m thesis.study_closure.run --dry-run     (nothing written)
    python3 -B -m thesis.study_closure.run --write       (formal closure)
"""
