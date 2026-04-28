from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default_config.yaml"
WEB_SAVED_CONFIG_PATH = PROJECT_ROOT / "config" / "saved_web_config.yaml"
WEB_RUNTIME_PATH_DEFAULTS = {
    "output_dir": Path("output"),
    "log_dir": Path("logs"),
    "temp_dir": Path("output/.tmp"),
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_sources_with_defaults(
    base_sources: list[dict[str, Any]],
    override_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_sources: list[dict[str, Any]] = []
    used_indexes: set[int] = set()

    for override in override_sources:
        match_index = next(
            (
                index
                for index, source in enumerate(base_sources)
                if index not in used_indexes
                and (
                    source.get("name") == override.get("name")
                    or source.get("url") == override.get("url")
                )
            ),
            None,
        )
        if match_index is None:
            merged_sources.append(deepcopy(override))
            continue
        used_indexes.add(match_index)
        merged_sources.append(_deep_merge(base_sources[match_index], override))

    for index, source in enumerate(base_sources):
        if index in used_indexes:
            continue
        merged_sources.append(deepcopy(source))

    return merged_sources


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    config_file = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    with config_file.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    config["_config_path"] = str(config_file.resolve())
    config["_project_root"] = str(PROJECT_ROOT)
    _normalize_config_paths(config)
    return config


def merge_overrides(config: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    if not override:
        return config
    merged = _deep_merge(config, override)
    _normalize_config_paths(merged)
    return merged


def load_web_config() -> dict[str, Any]:
    base_config = load_config(DEFAULT_CONFIG_PATH)
    if WEB_SAVED_CONFIG_PATH.exists():
        with WEB_SAVED_CONFIG_PATH.open("r", encoding="utf-8") as handle:
            saved = yaml.safe_load(handle) or {}
        if saved.get("sources"):
            saved = deepcopy(saved)
            saved["sources"] = _merge_sources_with_defaults(base_config.get("sources", []), saved["sources"])
        base_config = merge_overrides(base_config, saved)
    normalize_web_runtime_paths(base_config)
    return base_config


def save_web_config(config: dict[str, Any]) -> Path:
    config_to_save = deepcopy(config)
    normalize_web_runtime_paths(config_to_save)
    _relativize_web_runtime_paths(config_to_save)
    config_to_save.pop("_config_path", None)
    config_to_save.pop("_project_root", None)
    with WEB_SAVED_CONFIG_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config_to_save, handle, allow_unicode=True, sort_keys=False)
    return WEB_SAVED_CONFIG_PATH


def normalize_web_runtime_paths(config: dict[str, Any]) -> None:
    """Keep Web UI generated files in this project's downloadable folders."""
    project_root = Path(config.get("_project_root", PROJECT_ROOT)).resolve()
    runtime = config.setdefault("runtime", {})
    for key, relative_path in WEB_RUNTIME_PATH_DEFAULTS.items():
        runtime[key] = str((project_root / relative_path).resolve())


def _relativize_web_runtime_paths(config: dict[str, Any]) -> None:
    runtime = config.setdefault("runtime", {})
    project_root = PROJECT_ROOT.resolve()
    for key in WEB_RUNTIME_PATH_DEFAULTS:
        value = runtime.get(key)
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            continue
        try:
            runtime[key] = path.resolve().relative_to(project_root).as_posix()
        except ValueError:
            continue


def _normalize_config_paths(config: dict[str, Any]) -> None:
    project_root = Path(config.get("_project_root", PROJECT_ROOT))
    runtime = config.setdefault("runtime", {})
    for source in config.setdefault("sources", []):
        source.setdefault("inherit_runtime_limit", True)

    output_dir = Path(runtime.get("output_dir", project_root / "output"))
    log_dir = Path(runtime.get("log_dir", project_root / "logs"))
    temp_dir = Path(runtime.get("temp_dir", output_dir / ".tmp"))

    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    if not log_dir.is_absolute():
        log_dir = project_root / log_dir
    if not temp_dir.is_absolute():
        temp_dir = project_root / temp_dir

    runtime["output_dir"] = str(output_dir.resolve())
    runtime["log_dir"] = str(log_dir.resolve())
    runtime["temp_dir"] = str(temp_dir.resolve())


def ensure_runtime_dirs(config: dict[str, Any]) -> None:
    runtime = config["runtime"]
    for key in ("output_dir", "log_dir", "temp_dir"):
        Path(runtime[key]).mkdir(parents=True, exist_ok=True)
