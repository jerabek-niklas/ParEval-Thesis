"""Repair-loop CLI (thesis/repair/orchestrator.py).

Drives the per-(model, variant) wave state machines. The orchestrator
never waits: it advances every loop until it is done or blocked (pending
batch job, pending external-container tools, or API transport failures)
and then exits; re-running continues from the persisted state.

Usage (inside the pareval-thesis container — the analyze phase needs the
toolchain; API keys come from .env via load_config):

    python3 thesis/repair/run_repair.py --config thesis/config/config.yaml \
        --profile smoke
    # filters / bounded run:
    python3 thesis/repair/run_repair.py ... --model-id deepseek_v4_pro \
        --variant static_feedback --max-wave 1
    # batch bookkeeping only (no analysis, no submits):
    python3 thesis/repair/run_repair.py ... --poll
    # overview table:
    python3 thesis/repair/run_repair.py ... --status
    # build requests in memory, count and estimate tokens, send nothing:
    python3 thesis/repair/run_repair.py ... --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.repair import orchestrator  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the repair loop.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model-id", default=None, help="Single model; default all enabled.")
    parser.add_argument(
        "--variant",
        default=None,
        choices=list(orchestrator.VARIANTS),
        help="Single loop variant; default stages.repair.variants.",
    )
    parser.add_argument(
        "--max-wave",
        type=int,
        default=None,
        help="Stop each loop after N completed waves (decide transitions).",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Only check/merge pending batch jobs, then exit.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the per-(model, variant) loop overview and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the next wave's requests in memory, print counts and a "
        "token estimate, send nothing.",
    )
    parser.add_argument("--primary-compiler", default="g++", choices=["g++", "clang++"])
    return parser.parse_args()


def build_loops(args: argparse.Namespace):
    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    settings = orchestrator.repair_settings(config)

    variants = [args.variant] if args.variant else settings["variants"]

    models = [
        model
        for model in config.get("models", [])
        if model.get("enabled", False)
        and (args.model_id is None or model.get("id") == args.model_id)
    ]

    if not models:
        raise ValueError("No enabled models matched the selection.")

    loops = []
    for model_config in models:
        for variant in variants:
            loops.append(
                orchestrator.RepairLoop(
                    config=config,
                    config_path=str(Path(args.config)),
                    profile_name=args.profile,
                    profile=profile,
                    model_config=model_config,
                    variant=variant,
                    primary_compiler=args.primary_compiler,
                )
            )

    return loops


def print_status(loops) -> None:
    columns = [
        ("model", 22),
        ("variant", 18),
        ("iter", 4),
        ("phase", 26),
        ("active", 6),
        ("clean", 5),
        ("tests", 5),
        ("budget", 6),
        ("unusable", 8),
        ("ext", 4),
        ("batch", 20),
    ]

    header = "  ".join(name.ljust(width) for name, width in columns)
    print(header)
    print("-" * len(header))

    for loop in loops:
        row = loop.status_row()
        values = [
            row["model_id"],
            row["variant"],
            str(row["iteration"]),
            row["phase"],
            str(row["active"]),
            str(row["stopped_clean"]),
            str(row["stopped_tests_pass"]),
            str(row["stopped_budget"]),
            str(row["repair_unusable"]),
            str(row["pending_external"]),
            str(row["batch_id"] or "-"),
        ]
        print(
            "  ".join(
                value.ljust(width) for value, (_, width) in zip(values, columns)
            )
        )


def dry_run_aggregate(loops, summaries) -> None:
    """Wave totals in both history modes plus a rough cost estimate.

    Input cost uses the estimated request tokens; output cost is an UPPER
    BOUND from generation_defaults.max_output_tokens (the real completion
    length is unknown before the call). Prices are the list prices in
    config.yaml (source: thesis/docs/model-set.md).
    """
    if not summaries:
        print()
        print("dry-run: no wave would send requests.")
        return

    by_model = {loop.model_id: loop.model_config for loop in loops}
    generation_defaults = loops[0].config.get("generation_defaults", {})

    totals = {"full": 0, "compressed": 0}
    cost = {"full": 0.0, "compressed": 0.0}
    requests = 0
    priced = 0
    unpriced = set()

    for summary in summaries:
        model_config = by_model.get(summary["model_id"], {})
        price_in = model_config.get("price_per_mtok_in")
        price_out = model_config.get("price_per_mtok_out")
        max_output = int(
            common.get_param(
                model_config, generation_defaults, "max_output_tokens", 4096
            )
        )

        requests += summary["requests"]

        for mode in ("full", "compressed"):
            totals[mode] += summary["chars"][mode]

            if price_in is None or price_out is None:
                continue

            input_tokens = orchestrator.estimated_tokens(summary["chars"][mode])
            cost[mode] += (
                input_tokens * price_in
                + summary["requests"] * max_output * price_out
            ) / 1_000_000.0

        if price_in is None or price_out is None:
            unpriced.add(summary["model_id"])
        else:
            priced += 1

    print()
    print("=" * 78)
    print(
        "Wave total over %d loop(s), %d request(s)" % (len(summaries), requests)
    )
    for mode in ("full", "compressed"):
        print(
            "  history_mode=%-11s %13s chars  ~%9s tokens  ~$%8.2f"
            % (
                mode + ":",
                "{:,}".format(totals[mode]),
                "{:,}".format(orchestrator.estimated_tokens(totals[mode])),
                cost[mode],
            )
        )

    delta = totals["full"] - totals["compressed"]
    percent = (delta / totals["compressed"] * 100.0) if totals["compressed"] else 0.0
    print(
        "  %-24s %+13s chars  (%+.0f %%)  %+.2f USD"
        % ("difference:", "{:,}".format(delta), percent, cost["full"] - cost["compressed"])
    )
    print()
    print(
        "  Token estimate = chars / %d — crude in absolute terms, but the "
        "full/compressed RATIO is exact (same divisor on both sides). Cost "
        "adds an UPPER-BOUND output part (max_output_tokens per request at "
        "list prices); real output is shorter."
        % orchestrator.CHARS_PER_TOKEN_ESTIMATE
    )

    if unpriced:
        print(
            "  No price in config for: %s — excluded from the cost sum."
            % ", ".join(sorted(unpriced))
        )


def main() -> None:
    args = parse_args()
    loops = build_loops(args)

    if args.status:
        print_status(loops)
        return

    if args.dry_run:
        summaries = [s for s in (loop.dry_run() for loop in loops) if s]
        dry_run_aggregate(loops, summaries)
        return

    if args.poll:
        for loop in loops:
            wave = loop.load_wave_state()
            if wave["phase"] == "submitted":
                loop.step()
            else:
                loop.log("no pending batch (phase %s)" % wave["phase"])
        return

    outcomes = {}
    for loop in loops:
        outcomes[(loop.model_id, loop.variant)] = loop.run(max_waves=args.max_wave)

    print()
    print("Repair loop outcomes:")
    for (model_id, variant), outcome in outcomes.items():
        print("  %s/%s: %s" % (model_id, variant, outcome))


if __name__ == "__main__":
    main()
