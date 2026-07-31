"""Re-validate the spec set against the CURRENT validator (both directions).

RECOVER (--apply): specs in specs_discarded.jsonl that the repaired
validator accepts are moved back into specs.jsonl.

PRUNE (--prune): specs in specs.jsonl that the repaired validator now
REJECTS are moved out into specs_discarded.jsonl. This is the necessary
counterpart — the old 1-D check accepted explicit_values specs on
benchmarks where the pattern has no effect at all (no ENHANCED_FILL site)
or would be applied to several containers at once, and matrix specs with
n instead of n*n values (cyclically filled, so the spec's own rationale
described something the test never ran).

Rationale: the explicit_values check used to demand len(values) == size,
a 1-D assumption. For n x n matrix benchmarks the generator correctly
proposed n*n values and was rejected (63 of 67 discards). With the
shape-aware validator those specs are valid — and they were already paid
for, so recover them from specs_discarded.jsonl instead of regenerating
(no API calls).

Recovered specs keep their original provenance (source "llm", the
spec_model that produced them); only rows that pass validation AND are
not already present (spec_key dedupe) are appended.

Usage:
    python thesis/enhanced_tests/recover_discarded.py --config <cfg> [--apply]

Python 3.8 compatible.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.enhanced_tests.specs import (  # noqa: E402
    spec_key,
    stage_settings,
    validate_spec,
)

CACHE_DIR = REPO_ROOT / "thesis" / "results" / "cache" / "enhanced"


def load_jsonl(path: Path) -> "list":
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover discarded specs.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--specs", default=str(CACHE_DIR / "specs.jsonl"))
    parser.add_argument("--discarded", default=str(CACHE_DIR / "specs_discarded.jsonl"))
    parser.add_argument("--apply", action="store_true",
                        help="Write the recovered specs (default: report only).")
    parser.add_argument("--prune", action="store_true",
                        help="Also move now-invalid accepted specs out of "
                             "specs.jsonl into the discarded log.")
    args = parser.parse_args()

    config = load_config(Path(args.config).resolve())
    settings = stage_settings(config)

    specs_path = Path(args.specs)
    discarded_path = Path(args.discarded)

    specs = load_jsonl(specs_path)
    discarded = load_jsonl(discarded_path)

    known = {s["benchmark"] for s in specs} | {d["benchmark"] for d in discarded}
    existing_keys = {spec_key(s) for s in specs}

    recovered = []
    still_invalid = []

    for row in discarded:
        spec = row.get("spec")
        if not isinstance(spec, dict):
            still_invalid.append((row.get("reason", "?"), "no spec payload"))
            continue

        ok, reason = validate_spec(
            spec,
            known,
            max_size=int(settings["max_spec_size"]),
            allowed_patterns=list(settings["offered_patterns"]),
            explicit_values_max_size=int(settings["explicit_values_max_size"]),
        )

        if not ok:
            still_invalid.append((row.get("reason", "?"), reason))
            continue

        key = spec_key(spec)
        if key in existing_keys:
            still_invalid.append((row.get("reason", "?"), "duplicate of an accepted spec"))
            continue

        existing_keys.add(key)
        recovered.append(spec)

    print("discarded rows:      %d" % len(discarded))
    print("recovered (now valid): %d" % len(recovered))
    print("still invalid:       %d" % len(still_invalid))

    if recovered:
        print("\nrecovered per benchmark:")
        for benchmark, count in sorted(Counter(s["benchmark"] for s in recovered).items()):
            print("  %-56s %d" % (benchmark, count))

    if still_invalid:
        print("\nstill-invalid reasons (new validator):")
        for reason, count in Counter(r[1][:70] for r in still_invalid).most_common():
            print("  %3d  %s" % (count, reason))

    # ---- prune: accepted specs the repaired validator rejects -------------

    keep = []
    pruned = []

    if args.prune:
        for spec in specs:
            ok, reason = validate_spec(
                spec,
                known,
                max_size=int(settings["max_spec_size"]),
                allowed_patterns=list(settings["offered_patterns"]),
                explicit_values_max_size=int(settings["explicit_values_max_size"]),
            )
            (keep if ok else pruned).append((spec, reason if not ok else ""))

        print("\naccepted specs re-checked: %d" % len(specs))
        print("now invalid (to prune):     %d" % len(pruned))

        if pruned:
            print("\nprune reasons:")
            for reason, count in Counter(r[:70] for _, r in pruned).most_common(10):
                print("  %3d  %s" % (count, reason))

    if not args.apply:
        print("\n(report only — pass --apply to write)")
        return

    if args.prune:
        with specs_path.open("w", encoding="utf-8") as handle:
            for spec, _ in keep:
                handle.write(json.dumps(spec) + "\n")
        with specs_path.open("a", encoding="utf-8") as handle:
            for spec in recovered:
                handle.write(json.dumps(spec) + "\n")
    else:
        with specs_path.open("a", encoding="utf-8") as handle:
            for spec in recovered:
                handle.write(json.dumps(spec) + "\n")

    # the discarded log keeps everything that is (still) invalid
    with discarded_path.open("w", encoding="utf-8") as handle:
        for row in discarded:
            spec = row.get("spec")
            if isinstance(spec, dict) and spec in recovered:
                continue
            handle.write(json.dumps(row) + "\n")
        for spec, reason in pruned:
            handle.write(
                json.dumps(
                    {
                        "benchmark": spec.get("benchmark"),
                        "reason": "pruned on revalidation: " + reason,
                        "spec": spec,
                    }
                )
                + "\n"
            )

    print("\nrecovered %d, pruned %d -> %s" % (len(recovered), len(pruned), specs_path))


if __name__ == "__main__":
    main()
