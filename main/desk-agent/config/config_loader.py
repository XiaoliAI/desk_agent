import os
import shutil
from collections.abc import Mapping

import yaml


def get_project_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/"


def read_config(config_path):
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


async def load_config():
    from core.utils.cache.manager import CacheType, cache_manager

    cached_config = cache_manager.get(CacheType.CONFIG, "main_config")
    if cached_config is not None:
        return cached_config

    project_dir = get_project_dir()
    default_config = read_config(os.path.join(project_dir, "config.yaml"))
    custom_config_path = os.path.join(project_dir, "data", ".config.yaml")

    os.makedirs(os.path.dirname(custom_config_path), exist_ok=True)
    if not os.path.exists(custom_config_path):
        example_config_path = os.path.join(project_dir, "config.example.yaml")
        if os.path.exists(example_config_path):
            shutil.copyfile(example_config_path, custom_config_path)
            print(
                "已根据 config.example.yaml 创建 data/.config.yaml，"
                "请填写其中的密钥和本机路径。"
            )
        else:
            with open(custom_config_path, "w", encoding="utf-8") as file:
                file.write("{}\n")

    custom_config = read_config(custom_config_path)
    config = merge_configs(default_config, custom_config)
    config["read_config_from_api"] = False
    ensure_directories(config)

    cache_manager.set(CacheType.CONFIG, "main_config", config)
    return config


async def reload_local_config(config):
    """Return local configuration; Desk Agent has no manager service."""
    config["read_config_from_api"] = False
    return config


def ensure_directories(config):
    dirs_to_create = set()
    project_dir = get_project_dir()

    log_dir = config.get("log", {}).get("log_dir", "tmp")
    dirs_to_create.add(os.path.join(project_dir, log_dir))

    for module in ["ASR", "TTS"]:
        for provider in (config.get(module) or {}).values():
            output_dir = provider.get("output_dir", "")
            if output_dir:
                dirs_to_create.add(output_dir)

    selected_modules = config.get("selected_module", {})
    for module_type in ["ASR", "LLM", "TTS"]:
        selected_provider = selected_modules.get(module_type)
        provider_config = (config.get(module_type) or {}).get(selected_provider, {})
        output_dir = provider_config.get("output_dir")
        if output_dir:
            dirs_to_create.add(os.path.join(project_dir, output_dir))

    for dir_path in dirs_to_create:
        os.makedirs(dir_path, exist_ok=True)


def merge_configs(default_config, custom_config):
    if not isinstance(default_config, Mapping):
        return custom_config if isinstance(custom_config, Mapping) else {}
    if not isinstance(custom_config, Mapping):
        return dict(default_config)

    merged = dict(default_config)
    for key, value in custom_config.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value
    return merged
