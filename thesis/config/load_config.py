from pathlib import Path
from typing import Any
import os
import yaml
from dotenv import load_dotenv


def load_config(config_path: str | Path) -> dict[str, Any]:
    load_dotenv()

    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

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