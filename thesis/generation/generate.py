"""
General generation orchestrator for the thesis pipeline.

This script reads thesis/config/config.yaml, selects the active profile and enabled
models, and calls the provider-specific generation scripts.

Example:
    python thesis/generation/generate.py --profile smoke

    python thesis/generation/generate.py --profile full --model-id openai_gpt55

Expected model-specific script interface:
    python thesis/generation/generate-openai.py --config thesis/config/config.yaml --profile smoke --model-id openai_gpt55

The provider-specific scripts should read the same config file and generate outputs
according to the model and generation parameters defined there.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402


DEFAULT_CONFIG_PATH = REPO_ROOT / "thesis" / "config" / "config.yaml"


PROVIDER_SCRIPT_MAP = {
    "openai": "generate-openai.py",
    "gemini": "generate-gemini.py",
    "anthropic": "generate-anthropic.py",
    "openai_compatible": "generate-openai-compatible.py",
    "qwen": "generate-openai-compatible.py",
    "deepseek": "generate-openai-compatible.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run generation for all enabled models from the thesis config."
    )

    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to config YAML. Default: {DEFAULT_CONFIG_PATH}",
    )

    parser.add_argument(
        "--profile",
        default="smoke",
        help="Experiment profile to run, e.g. smoke, pilot, full. Default: smoke.",
    )

    parser.add_argument(
        "--model-id",
        default=None,
        help="Optional single model id to run. If omitted, all enabled models are run.",
    )

    parser.add_argument(
        "--provider",
        default=None,
        help="Optional provider filter, e.g. openai, gemini, anthropic.",
    )

    parser.add_argument(
        "--restart",
        action="store_true",
        help="Forward --restart to provider-specific generation scripts.",
    )

    parser.add_argument(
        "--poll",
        action="store_true",
        help="Forward --poll (batch mode: collect finished jobs, submit nothing).",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them.",
    )

    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with remaining models if one provider script fails.",
    )

    return parser.parse_args()


def get_enabled_models(
    config: dict[str, Any],
    model_id: str | None,
    provider: str | None,
) -> list[dict[str, Any]]:
    models = config.get("models", [])

    selected = []

    for model in models:
        if not model.get("enabled", False):
            continue

        if model_id is not None and model.get("id") != model_id:
            continue

        if provider is not None and model.get("provider") != provider:
            continue

        selected.append(model)

    return selected


def get_provider_script(provider: str) -> Path:
    script_name = PROVIDER_SCRIPT_MAP.get(provider)

    if script_name is None:
        known = ", ".join(sorted(PROVIDER_SCRIPT_MAP.keys()))
        raise ValueError(
            f"No generation script configured for provider '{provider}'. "
            f"Known providers: {known}"
        )

    script_path = Path(__file__).resolve().parent / script_name

    if not script_path.exists():
        raise FileNotFoundError(
            f"Provider script for provider '{provider}' does not exist: {script_path}"
        )

    return script_path


def build_command(
    script_path: Path,
    config_path: Path,
    profile: str,
    model_id: str,
    restart: bool,
    poll: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        str(script_path),
        "--config",
        str(config_path),
        "--profile",
        profile,
        "--model-id",
        model_id,
    ]

    if restart:
        command.append("--restart")

    if poll:
        command.append("--poll")

    return command


def print_run_overview(
    config_path: Path,
    profile: str,
    models: list[dict[str, Any]],
) -> None:
    print("Generation run")
    print("==============")
    print(f"Config:  {config_path}")
    print(f"Profile: {profile}")
    print(f"Models:  {len(models)}")

    for model in models:
        print(
            f"  - {model.get('id')} "
            f"({model.get('provider')} / {model.get('model_name')})"
        )

    print()


def run_command(command: list[str], dry_run: bool) -> int:
    printable = " ".join(command)
    print(f"Running:\n  {printable}\n")

    if dry_run:
        return 0

    completed = subprocess.run(command, cwd=REPO_ROOT)
    return completed.returncode


def main() -> None:
    args = parse_args()

    config_path = Path(args.config).resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Config file does not exist: {config_path}")

    config = load_config(config_path)

    if "profiles" not in config:
        raise KeyError("Config must contain a top-level 'profiles' section.")

    if args.profile not in config["profiles"]:
        available = ", ".join(config["profiles"].keys())
        raise KeyError(
            f"Profile '{args.profile}' not found in config. "
            f"Available profiles: {available}"
        )

    models = get_enabled_models(
        config=config,
        model_id=args.model_id,
        provider=args.provider,
    )

    if not models:
        raise ValueError(
            "No enabled models selected. Check 'enabled: true' in config.yaml "
            "or your --model-id / --provider filters."
        )

    # freeze the run configuration at the run's true start (or record
    # config drift on continuation runs) — see run_manifest.py
    from thesis.evaluation.run_manifest import ensure_run_manifest

    ensure_run_manifest(
        config,
        config["profiles"][args.profile]["run_id"],
        stage="generation",
        profile=args.profile,
    )

    print_run_overview(
        config_path=config_path,
        profile=args.profile,
        models=models,
    )

    failures = []

    for model in models:
        provider = model["provider"]
        model_id = model["id"]

        try:
            script_path = get_provider_script(provider)

            command = build_command(
                script_path=script_path,
                config_path=config_path,
                profile=args.profile,
                model_id=model_id,
                restart=args.restart,
                poll=args.poll,
            )

            return_code = run_command(command, dry_run=args.dry_run)

            if return_code != 0:
                failures.append((model_id, return_code))

                if not args.continue_on_error:
                    raise RuntimeError(
                        f"Generation failed for model '{model_id}' "
                        f"with return code {return_code}."
                    )

        except Exception as error:
            failures.append((model_id, repr(error)))

            if not args.continue_on_error:
                raise

            print(f"Error for model '{model_id}': {error}")
            print("Continuing because --continue-on-error is set.\n")

    print("Generation orchestration finished.")

    if failures:
        print("\nFailures:")
        for model_id, error in failures:
            print(f"  - {model_id}: {error}")
        sys.exit(1)

    print("All selected models completed successfully.")


if __name__ == "__main__":
    main()