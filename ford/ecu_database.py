from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from fnmatch import fnmatchcase


class EcuDatabaseError(RuntimeError):
    pass


def _database_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "ecus.json"


@lru_cache(maxsize=1)
def load_ecu_database() -> dict[int, dict[str, Any]]:
    path = _database_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EcuDatabaseError(f"Nie można wczytać bazy ECU: {path}: {exc}") from exc

    result: dict[int, dict[str, Any]] = {}
    for ecu_key, entry in raw.items():
        ecu_id = int(ecu_key, 0)
        security: dict[int, dict[str, Any]] = {}
        for level_key, security_entry in entry.get("security", {}).items():
            item = dict(security_entry)
            if "magic" in item:
                item["magic"] = int(str(item["magic"]), 0)
            security[int(level_key, 0)] = item
        parsed = dict(entry)
        parsed["response_id"] = int(str(entry.get("response_id", hex(ecu_id + 8))), 0)
        parsed["security"] = security
        parsed_profiles = []
        for profile in entry.get("profiles", []):
            parsed_profile = dict(profile)
            profile_security: dict[int, dict[str, Any]] = {}
            for level_key, security_entry in profile.get("security", {}).items():
                item = dict(security_entry)
                if "magic" in item:
                    item["magic"] = int(str(item["magic"]), 0)
                profile_security[int(level_key, 0)] = item
            parsed_profile["security"] = profile_security
            parsed_profiles.append(parsed_profile)
        parsed["profiles"] = parsed_profiles
        result[ecu_id] = parsed
    return result


def reload_ecu_database() -> dict[int, dict[str, Any]]:
    load_ecu_database.cache_clear()
    return load_ecu_database()


def get_ecu_definition(ecu_id: int) -> dict[str, Any] | None:
    return load_ecu_database().get(ecu_id)


def get_ecu_name(ecu_id: int) -> str:
    entry = get_ecu_definition(ecu_id)
    return str(entry.get("name")) if entry else f"ECU 0x{ecu_id:03X}"


def get_security_definition(ecu_id: int, level: int) -> dict[str, Any] | None:
    entry = get_ecu_definition(ecu_id)
    if not entry:
        return None
    return entry.get("security", {}).get(level)



def get_security_definition_for_part(ecu_id: int, level: int, part_number: str | None) -> dict[str, Any] | None:
    entry = get_ecu_definition(ecu_id)
    if not entry:
        return None
    normalized = (part_number or "").strip().upper()
    if normalized:
        for profile in entry.get("profiles", []):
            patterns = profile.get("match_part_number", [])
            if isinstance(patterns, str):
                patterns = [patterns]
            if any(fnmatchcase(normalized, str(pattern).upper()) for pattern in patterns):
                security = profile.get("security", {}).get(level)
                if security:
                    return security
    return entry.get("security", {}).get(level)


def find_matching_profile(ecu_id: int, part_number: str | None) -> dict[str, Any] | None:
    entry = get_ecu_definition(ecu_id)
    if not entry or not part_number:
        return None
    normalized = part_number.strip().upper()
    for profile in entry.get("profiles", []):
        patterns = profile.get("match_part_number", [])
        if isinstance(patterns, str):
            patterns = [patterns]
        if any(fnmatchcase(normalized, str(pattern).upper()) for pattern in patterns):
            return profile
    return None

def build_fixedbytes() -> dict[int, dict[int, int]]:
    result: dict[int, dict[int, int]] = {}
    for ecu_id, entry in load_ecu_database().items():
        levels: dict[int, int] = {}
        for level, security in entry.get("security", {}).items():
            if security.get("algorithm") == "ford_3byte" and "magic" in security:
                levels[level] = int(security["magic"])
        if levels:
            result[ecu_id] = levels
    return result
