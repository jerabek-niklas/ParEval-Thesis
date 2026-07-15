# Python 3.8 compatibility (LLOV container): keep annotations lazy so
# `str | Path` unions do not evaluate at import time.
from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import yaml

# Optional: dotenv only feeds API keys to the generation stage. 
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    def load_dotenv() -> None:
        pass


def load_config(config_path: str | Path, validate_keys: bool = False) -> dict[str, Any]:
    load_dotenv()

    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Hard schema validation for the per-tool stage config (unknown tool
    # names / execution models fail loudly at load time, not mid-run) and
    # for the repair stop-mode enum. Imported lazily to keep this module
    # dependency-light for scripts that only read prompts/models.
    from thesis.evaluation.tool_config import (
        validate_repair_config,
        validate_stage_tools,
    )

    validate_stage_tools(config, "static_analysis")
    validate_stage_tools(config, "dynamic_analysis")
    validate_repair_config(config)

    # Off by default: validating every model's key would make it impossible
    # to run a single model or validate result files without all keys set.
    # The provider scripts check their own key via common.get_api_key.
    if validate_keys:
        validate_api_key_envs(config)

    return config


def validate_api_key_envs(config: dict[str, Any]) -> None:
    models = config.get("models", [])

    for model in models:
        env_name = model.get("api_key_env")

        if env_name and not os.environ.get(env_name):
            raise EnvironmentError(
                f"Missing API key environment variable '{env_name}' "
                f"for model '{model.get('id')}'."
            )