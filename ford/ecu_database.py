from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from fnmatch import fnmatchcase


class EcuDatabaseError(RuntimeError):
    pass


def _database_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "ecus.json"


def _parse_security_entry(entry: dict[str, Any]) -> dict[str, Any]:
    item = dict(entry)
    if "magic" in item:
        item["magic"] = int(str(item["magic"]), 0)
    if "secret" in item:
        raw = str(item["secret"]).replace(" ", "")
        item["secret"] = raw.upper().removeprefix("0X")
        if len(item["secret"]) != 10:
            raise EcuDatabaseError(f"Nieprawidłowy 5-byte secret: {item['secret']!r}")
    return item


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
        parsed = dict(entry)
        parsed["response_id"] = int(str(entry.get("response_id", hex(ecu_id + 8))), 0)

        security: dict[int, dict[str, Any]] = {}
        for level_key, security_entry in entry.get("security", {}).items():
            security[int(level_key, 0)] = _parse_security_entry(security_entry)
        parsed["security"] = security

        profiles = []
        for profile in entry.get("profiles", []):
            p = dict(profile)
            psec: dict[int, dict[str, Any]] = {}
            for level_key, security_entry in profile.get("security", {}).items():
                psec[int(level_key, 0)] = _parse_security_entry(security_entry)
            p["security"] = psec
            profiles.append(p)
        parsed["profiles"] = profiles

        rules = []
        for rule in entry.get("security_rules", []):
            r = _parse_security_entry(rule)
            raw_level = r.get("level")
            r["level"] = None if raw_level in (None, "", "any") else int(str(raw_level), 0)
            r["hw_prefix"] = str(r.get("hw_prefix", "")).upper()
            rules.append(r)
        parsed["security_rules"] = rules
        parsed["sbl_rules"] = [dict(r) for r in entry.get("sbl_rules", [])]
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
    return entry.get("security", {}).get(level) if entry else None


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


def get_security_definition_for_part(ecu_id: int, level: int, part_number: str | None) -> dict[str, Any] | None:
    profile = find_matching_profile(ecu_id, part_number)
    if profile:
        security = profile.get("security", {}).get(level)
        if security:
            return security
    return get_security_definition(ecu_id, level)


def get_security_definition_for_hw(ecu_id: int, level: int, hardware: str | None) -> dict[str, Any] | None:
    """Pick the longest NON-EMPTY F111 prefix match.

    Empty ``hw_prefix`` entries are generic wildcard rules imported from other
    databases.  They must not override a verified ECU-wide legacy secret.
    """
    entry = get_ecu_definition(ecu_id)
    if not entry:
        return None
    hw = (hardware or "").strip().upper()
    if not hw:
        return None
    rules = entry.get("security_rules", [])
    for want_level in (level, None):
        candidates = []
        for r in rules:
            prefix = str(r.get("hw_prefix", "")).strip().upper()
            if not prefix:
                continue
            if r.get("level") == want_level and hw.startswith(prefix):
                candidates.append(r)
        if candidates:
            return max(candidates, key=lambda r: len(str(r.get("hw_prefix", ""))))
    return None


def get_security_wildcard(ecu_id: int, level: int) -> dict[str, Any] | None:
    """Return a generic imported wildcard rule, if present.

    Wildcards are intentionally last-resort only.
    """
    entry = get_ecu_definition(ecu_id)
    if not entry:
        return None
    rules = entry.get("security_rules", [])
    for want_level in (level, None):
        for r in rules:
            prefix = str(r.get("hw_prefix", "")).strip()
            if not prefix and r.get("level") == want_level:
                return r
    return None


def select_security_definition(
    ecu_id: int,
    level: int,
    *,
    hardware: str | None = None,
    part_numbers: Iterable[str] = (),
) -> tuple[dict[str, Any] | None, str | None]:
    """Select SecurityAccess data in verified-first order.

    Priority:
      1. Project/VBF-specific profile
      2. Specific NON-EMPTY F111 hardware rule
      3. Verified ECU-wide legacy fallback
      4. Generic wildcard rule (last resort only)

    This prevents imported ``*`` rules from overriding known working values
    such as IPC 0x720 / level 0x01 = 0x4A7722 and
    ACM 0x727 / level 0x01 = 0x123BF9.
    """
    for part_number in part_numbers:
        profile = find_matching_profile(ecu_id, part_number)
        if profile:
            sec = profile.get("security", {}).get(level)
            if sec:
                name = str(profile.get("name") or profile.get("id") or part_number)
                return sec, f"VBF profile: {name}"

    sec = get_security_definition_for_hw(ecu_id, level, hardware)
    if sec:
        prefix = str(sec.get("hw_prefix", "")).strip()
        return sec, f"F111 rule: {prefix}"

    sec = get_security_definition(ecu_id, level)
    if sec:
        return sec, "legacy ECU fallback (verified)"

    sec = get_security_wildcard(ecu_id, level)
    if sec:
        return sec, "generic wildcard fallback"

    return None, None


def get_sbl_recommendation(ecu_id: int, hardware: str | None) -> str | None:
    entry = get_ecu_definition(ecu_id)
    if not entry:
        return None
    hw = (hardware or "").strip().upper()
    candidates = []
    for rule in entry.get("sbl_rules", []):
        prefix = str(rule.get("hw_prefix", "")).upper()
        if prefix and hw.startswith(prefix):
            candidates.append(rule)
    if candidates:
        return str(max(candidates, key=lambda r: len(str(r.get("hw_prefix", ""))))["filename"])
    for rule in entry.get("sbl_rules", []):
        if not str(rule.get("hw_prefix", "")):
            return str(rule["filename"])
    default = entry.get("default_sbl")
    return str(default) if default else None


def get_programming_flags(ecu_id: int) -> dict[str, bool]:
    entry = get_ecu_definition(ecu_id) or {}
    return {
        "finalize": bool(entry.get("finalize", False)),
        "sbl_call_halfword": bool(entry.get("sbl_call_halfword", False)),
    }


def build_fixedbytes() -> dict[int, dict[int, int]]:
    """Compatibility map for older code paths using ECU-wide legacy entries."""
    result: dict[int, dict[int, int]] = {}
    for ecu_id, entry in load_ecu_database().items():
        levels: dict[int, int] = {}
        for level, security in entry.get("security", {}).items():
            if security.get("algorithm") == "ford_3byte":
                if "secret" in security:
                    levels[level] = int(security["secret"], 16)
                elif "magic" in security:
                    levels[level] = int(security["magic"])
        if levels:
            result[ecu_id] = levels
    return result
