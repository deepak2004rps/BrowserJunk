"""
browsers.py – Browser registry, detection, and populator dispatch.

Keeps Windows path knowledge and the chrome/edge/brave/firefox dispatch table
in one place so main.py stays thin.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from core.helpers import get_logger

logger = get_logger("browsers")


class DataCategory:
    HISTORY = "history"
    BOOKMARKS = "bookmarks"
    PASSWORDS = "passwords"
    COOKIES = "cookies"
    AUTOFILL = "autofill"
    ALL = {HISTORY, BOOKMARKS, PASSWORDS, COOKIES, AUTOFILL}


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))


def _roaming_appdata() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))


BROWSER_REGISTRY = {
    "chrome": {
        "name": "Google Chrome",
        "family": "chromium",
        "user_data_dir": lambda: _local_appdata() / "Google" / "Chrome" / "User Data",
    },
    "edge": {
        "name": "Microsoft Edge",
        "family": "chromium",
        "user_data_dir": lambda: _local_appdata() / "Microsoft" / "Edge" / "User Data",
    },
    "brave": {
        "name": "Brave",
        "family": "chromium",
        "user_data_dir": lambda: _local_appdata() / "BraveSoftware" / "Brave-Browser" / "User Data",
    },
    "firefox": {
        "name": "Mozilla Firefox",
        "family": "firefox",
        "user_data_dir": lambda: _roaming_appdata() / "Mozilla" / "Firefox",
    },
}


def detect_installed_browsers() -> set[str]:
    """Return the set of registry keys whose User Data root exists on disk."""
    found = set()
    for key, meta in BROWSER_REGISTRY.items():
        try:
            if meta["user_data_dir"]().exists():
                found.add(key)
        except Exception:
            continue
    return found


def find_demo_profiles(browser_keys: list[str], base_name: str) -> dict[str, list[Path]]:
    """For each browser, list existing demo profile directories (folders whose
    name starts with base_name, e.g. 'BVaultDemo'). Returns {key: [paths]}."""
    result: dict[str, list[Path]] = {}
    for key in browser_keys:
        meta = BROWSER_REGISTRY.get(key)
        if not meta:
            continue
        if meta["family"] == "firefox":
            root = meta["user_data_dir"]() / "Profiles"
        else:
            root = meta["user_data_dir"]()
        matches: list[Path] = []
        try:
            if root.exists():
                for child in root.iterdir():
                    if child.is_dir() and child.name.startswith(base_name):
                        matches.append(child)
        except OSError:
            pass
        if matches:
            result[key] = matches
    return result


def purge_demo_profiles(browser_keys: list[str], base_name: str) -> int:
    """Delete existing demo profile folders and, for Chromium browsers, remove
    their registration from Local State so they no longer appear in the profile
    picker as ghost entries. Returns the number of profile folders removed."""
    removed = 0
    found = find_demo_profiles(browser_keys, base_name)
    for key, paths in found.items():
        meta = BROWSER_REGISTRY[key]
        for path in paths:
            try:
                shutil.rmtree(path)
                removed += 1
            except OSError as exc:
                logger.warning(f"could not delete {path}: {exc}")

        if meta["family"] == "chromium":
            _purge_picker_entries(meta["user_data_dir"]() / "Local State", base_name)
    return removed


def _purge_picker_entries(local_state_path: Path, base_name: str) -> None:
    """Remove demo profiles from Local State's info_cache and profiles_order so
    the browser stops listing folders we just deleted."""
    if not local_state_path.exists():
        return
    try:
        state = json.loads(local_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    profile_block = state.get("profile")
    if not isinstance(profile_block, dict):
        return
    info_cache = profile_block.get("info_cache")
    if isinstance(info_cache, dict):
        for name in [n for n in info_cache if n.startswith(base_name)]:
            info_cache.pop(name, None)
    order = profile_block.get("profiles_order")
    if isinstance(order, list):
        profile_block["profiles_order"] = [n for n in order if not n.startswith(base_name)]
    try:
        local_state_path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"could not rewrite {local_state_path}: {exc}")


def build_populators(
    browser_keys: Optional[list[str]],
    personas: list,
    categories: Optional[set[str]],
    dry_run: bool,
    demo_profile: str,
    force_create: bool,
) -> list:
    """Resolve requested browsers into ready-to-run populator instances."""
    from core.chromium import ChromiumPopulator
    from core.firefox import FirefoxPopulator

    if browser_keys:
        keys = [k.lower() for k in browser_keys]
    elif force_create:
        keys = list(BROWSER_REGISTRY)
    else:
        keys = list(detect_installed_browsers())
    cats = categories or set(DataCategory.ALL)

    invalid = [k for k in keys if k not in BROWSER_REGISTRY]
    if invalid:
        raise ValueError(f"Unknown browser(s): {', '.join(invalid)}")

    detected = detect_installed_browsers()
    populators = []
    for key in keys:
        meta = BROWSER_REGISTRY[key]
        if key not in detected and not force_create:
            logger.warning(f"{meta['name']} not detected, skipping (use --force-create to override).")
            continue

        user_data_dir = meta["user_data_dir"]()
        if meta["family"] == "chromium":
            populators.append(ChromiumPopulator(
                key=key, name=meta["name"], user_data_dir=user_data_dir,
                personas=personas, categories=cats, dry_run=dry_run,
                demo_profile=demo_profile,
            ))
        else:
            populators.append(FirefoxPopulator(
                key=key, name=meta["name"], root_dir=user_data_dir,
                personas=personas, categories=cats, dry_run=dry_run,
                demo_profile=demo_profile,
            ))
    return populators
