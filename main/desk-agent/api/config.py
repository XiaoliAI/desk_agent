import os
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "data" / ".config.yaml"


def load_api_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    return config if isinstance(config, dict) else {}


def get_remote_api_config() -> dict:
    config = (
        load_api_config()
        .get("plugins", {})
        .get("remote_api", {})
    )
    return config if isinstance(config, dict) else {}


def get_feishu_config() -> dict:
    config = (
        load_api_config()
        .get("plugins", {})
        .get("feishu", {})
    )
    return config if isinstance(config, dict) else {}


def get_config_value(
    config: dict,
    key: str,
    environment_name: str,
    default: str = "",
) -> str:
    environment_value = os.getenv(environment_name, "").strip()
    if environment_value:
        return environment_value
    return str(config.get(key, default) or "").strip()
