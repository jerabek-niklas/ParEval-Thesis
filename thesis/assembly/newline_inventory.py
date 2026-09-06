"""Read-only inventory of every locally present generated-code.hpp.

Classifies each assembled source by its RAW bytes (LF / CRLF / MIXED /
OTHER, trailing newline yes/no), per run (base run and repair iteration
runs) and per model, and writes a JSON inventory. Nothing under the output
tree is modified.

    python thesis/assembly/newline_inventory.py --config thesis/config/config.yaml \
        --run-prefix pilot_001 --out thesis/evaluation/pilot001_newline_inventory.json
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import condition_hashing as ch  # noqa: E402

SOURCE_FILE_NAME = "generated-code.hpp"


def inventory(intermediate_dir: Path, run_prefix: str) -> "OrderedDict":
    runs = OrderedDict()
    total = Counter()
    trailing = Counter()
    files = 0
    for run_dir in sorted(Path(intermediate_dir).iterdir()):
        if not run_dir.is_dir() or not run_dir.name.startswith(run_prefix):
            continue
        models = OrderedDict()
        for model_dir in sorted(run_dir.iterdir()):
            sources = model_dir / "sources"
            if not sources.is_dir():
                continue
            counts = Counter()
            no_trailing = 0
            n = 0
            for sample_dir in sorted(sources.iterdir()):
                source = sample_dir / SOURCE_FILE_NAME
                if not source.is_file():
                    continue
                data = source.read_bytes()
                convention = ch.newline_convention(data)
                counts[convention] += 1
                total[convention] += 1
                n += 1
                files += 1
                if not ch.has_trailing_newline(data):
                    no_trailing += 1
                    trailing["without_trailing_newline"] += 1
            models[model_dir.name] = OrderedDict([
                ("files", n),
                ("LF", counts["LF"]), ("CRLF", counts["CRLF"]),
                ("MIXED", counts["MIXED"]), ("OTHER", counts["OTHER"]),
                ("without_trailing_newline", no_trailing),
            ])
        kind = "base" if run_dir.name == run_prefix else (
            "repair_iteration" if "__iter" in run_dir.name else "other")
        runs[run_dir.name] = OrderedDict([("kind", kind), ("models", models)])
    return OrderedDict([
        ("schema_version", "newline_inventory.v1"),
        ("run_prefix", run_prefix),
        ("host_platform", sys.platform),
        ("files", files),
        ("LF", total["LF"]), ("CRLF", total["CRLF"]),
        ("MIXED", total["MIXED"]), ("OTHER", total["OTHER"]),
        ("without_trailing_newline", trailing["without_trailing_newline"]),
        ("runs", runs),
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-prefix", default="pilot_001")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    config = load_config(Path(args.config).resolve())
    result = inventory(Path(config["outputs"]["intermediate_dir"]), args.run_prefix)
    print("NEWLINE_INVENTORY files=%d LF=%d CRLF=%d MIXED=%d OTHER=%d without_trailing_newline=%d"
          % (result["files"], result["LF"], result["CRLF"], result["MIXED"],
             result["OTHER"], result["without_trailing_newline"]))
    for run_id, run in result["runs"].items():
        for model_id, m in run["models"].items():
            print("  %-45s %-28s files=%3d LF=%3d CRLF=%3d MIXED=%d OTHER=%d"
                  % (run_id, model_id, m["files"], m["LF"], m["CRLF"], m["MIXED"], m["OTHER"]))
    if args.out:
        atomic_io.atomic_write_json(Path(args.out), result)
        print("written:", args.out)


if __name__ == "__main__":
    main()
