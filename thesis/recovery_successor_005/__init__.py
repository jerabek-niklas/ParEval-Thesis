"""Phase-2 successor run full_ext_phase2_001 (profile recovery_successor_005).

Completes the remaining experimental measurements of the full extension
WITHOUT any provider request and without touching a historical byte:
phase-2 backfill (correctness + dynamic for static_feedback candidates, the
missing static tools for test_feedback candidates) and the held-out enhanced
tests for every full-extension candidate (the 1,584 iteration-0 base cells
and all 2,933 repair candidates of full_ext_recovery_001..004). Every new
measurement is written under the new result identity full_ext_phase2_001 and
bound to its candidate by source hash; the native measurement functions are
reused unchanged. pilot_002 is complete and only verified read-only.
"""
