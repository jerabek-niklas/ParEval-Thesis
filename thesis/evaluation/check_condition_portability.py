"""Checkout portability of the NEW (LF-normalized) condition fingerprints.

The repository is checked out with core.autocrlf=true on Windows and with LF
in a Linux clone, so RAW-byte hashes over implementation files differ per
checkout. Every condition introduced by the pilot_002 pre-run wave is
therefore computed over LF-NORMALIZED bytes; this script prints those
fingerprints so the SAME values can be shown on both checkouts:

    # Windows host
    .venv/Scripts/python.exe thesis/evaluation/check_condition_portability.py --out host.json
    # fresh Linux clone inside the container
    git clone /workspace /tmp/clone && cd /tmp/clone
    python3 thesis/evaluation/check_condition_portability.py --out clone.json
    # compare
    python3 thesis/evaluation/check_condition_portability.py --compare host.json clone.json

Only METHOD hashes appear here. Artifact hashes (generated-code.hpp) stay
RAW bytes by design and are NOT expected to be checkout-independent.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import condition_hashing as ch  # noqa: E402

TRACKED_IMPLEMENTATION_FILES = [
    "thesis/assembly/cleaning.py",
    "thesis/assembly/assemble_sources.py",
    "thesis/assembly/assembly_provenance.py",
    "thesis/evaluation/condition_hashing.py",
    "thesis/evaluation/atomic_io.py",
    "thesis/evaluation/manifest_fragments.py",
    "thesis/evaluation/timing_semantics.py",
    "thesis/evaluation/check_timing_semantics.py",
    "thesis/evaluation/pilot_run_contract.py",
    "thesis/evaluation/verify_pilot_run.py",
    "thesis/analysis_overview/report_contracts.py",
    "thesis/analysis_overview/build_overview.py",
    "thesis/evaluation/semantic_decisions_pilot002.json",
]


def fingerprints(config_path: Path) -> "OrderedDict[str, object]":
    from thesis.analysis_overview import report_contracts
    from thesis.assembly import assembly_provenance as ap
    from thesis.config.load_config import load_config
    from thesis.evaluation import timing_semantics

    config = load_config(Path(config_path).resolve())
    result = OrderedDict()
    result["schema_version"] = "condition_portability.v1"
    result["environment"] = OrderedDict([
        ("platform", sys.platform),
        ("os_linesep", repr(os.linesep)),
        ("python_version", platform.python_version()),
        ("repo_root", str(REPO_ROOT)),
    ])
    result["conditions"] = OrderedDict([
        ("assembly_condition_version", ap.ASSEMBLY_CONDITION_VERSION),
        ("assembly_condition_sha256",
         ap.assembly_condition_sha256(ap.assembly_condition(config))),
        ("generation_cleaning_condition_sha256",
         ap.generation_cleaning_condition_sha256(ap.generation_cleaning_condition())),
        ("timing_contract_sha256", timing_semantics.timing_contract_sha256()),
        ("report_condition_sha256", report_contracts.report_condition_sha256()),
    ])
    files = OrderedDict()
    for relative in TRACKED_IMPLEMENTATION_FILES:
        path = REPO_ROOT / relative
        files[relative] = OrderedDict([
            ("lf_normalized_sha256", ch.lf_normalized_sha256(path)),
            ("raw_sha256", ch.raw_sha256(path)),
            ("cr_bytes", (path.read_bytes().count(b"\r") if path.is_file() else None)),
        ])
    result["files"] = files
    return result


def compare(a_path: Path, b_path: Path) -> int:
    a = json.loads(Path(a_path).read_text(encoding="utf-8"))
    b = json.loads(Path(b_path).read_text(encoding="utf-8"))
    print("A: %s (%s, linesep %s)" % (a_path, a["environment"]["platform"],
                                      a["environment"]["os_linesep"]))
    print("B: %s (%s, linesep %s)" % (b_path, b["environment"]["platform"],
                                      b["environment"]["os_linesep"]))
    problems = []
    for key, value in a["conditions"].items():
        other = b["conditions"].get(key)
        same = value == other
        print("  %-45s %s" % (key, "EQUAL" if same else "DIFFERENT (%s vs %s)"
                              % (str(value)[:12], str(other)[:12])))
        if not same:
            problems.append(key)
    lf_diff = [f for f in a["files"]
               if a["files"][f]["lf_normalized_sha256"] != (b["files"].get(f) or {}).get("lf_normalized_sha256")]
    raw_diff = [f for f in a["files"]
                if a["files"][f]["raw_sha256"] != (b["files"].get(f) or {}).get("raw_sha256")]
    print("  files with a different LF-normalized hash: %d" % len(lf_diff))
    for f in lf_diff:
        print("    %s" % f)
    print("  files with a different RAW hash (expected on a CRLF checkout): %d of %d"
          % (len(raw_diff), len(a["files"])))
    problems.extend(lf_diff)
    print("CONDITION_FINGERPRINTS_CHECKOUT_INDEPENDENT = %s"
          % ("true" if not problems else "false"))
    return 0 if not problems else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="thesis/config/config.yaml")
    parser.add_argument("--out", default=None)
    parser.add_argument("--compare", nargs=2, default=None, metavar=("A", "B"))
    args = parser.parse_args()

    if args.compare:
        return compare(Path(args.compare[0]), Path(args.compare[1]))

    result = fingerprints(Path(args.config))
    print("PLATFORM = %s (os.linesep %s, python %s)"
          % (result["environment"]["platform"], result["environment"]["os_linesep"],
             result["environment"]["python_version"]))
    for key, value in result["conditions"].items():
        print("%s = %s" % (key.upper(), value))
    crlf_files = [f for f, v in result["files"].items() if (v["cr_bytes"] or 0) > 0]
    print("FILES_WITH_CR_BYTES = %d of %d" % (len(crlf_files), len(result["files"])))
    if args.out:
        from thesis.evaluation import atomic_io

        atomic_io.atomic_write_json(Path(args.out), result)
        print("written:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
