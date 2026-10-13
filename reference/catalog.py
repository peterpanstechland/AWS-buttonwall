"""Load the frozen content files. Numbers that affect play live in config, not in callers."""

from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def _load(name: str):
    with (CONFIG / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def load_services():
    rows = _load("services.json")["services"]
    by_id = {row["id"]: row for row in rows}
    by_key = {row["key"]: row for row in rows}
    return rows, by_id, by_key


def load_hardware():
    return _load("hardware.json")


def load_game_config():
    return _load("game_config.json")


def load_missions():
    return _load("solutions.json")["missions"]


def load_ui_strings():
    return _load("i18n/ui.json")


def mission_map(missions=None):
    missions = load_missions() if missions is None else missions
    return {mission["id"]: mission for mission in missions}


def canonical_mapping(hardware=None) -> bytes:
    hardware = load_hardware() if hardware is None else hardware
    buttons = [
        {"id": button["id"], "key": button["key"], "slot": button["slot"], "gpio": button["gpio"]}
        for button in hardware["buttons"]
    ]
    lanes = [
        {"lane": lane["lane"], "gpio": lane["gpio"], "slots": list(lane["slots"])}
        for lane in hardware["led"]["lanes"]
    ]
    body = {
        "buttons": buttons,
        "lanes": lanes,
        "pixels_per_panel": hardware["led"]["pixels_per_panel"],
        "revision": hardware["revision"],
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def mapping_crc32(hardware=None) -> str:
    return f"{zlib.crc32(canonical_mapping(hardware)) & 0xFFFFFFFF:08X}"


def pack_document(config=None, missions=None) -> dict:
    config = load_game_config() if config is None else config
    missions = load_missions() if missions is None else missions
    by_id = mission_map(missions)
    packed = []
    for mission_id in config["pack"]["mission_ids"]:
        mission = by_id[mission_id]
        packed.append(
            {
                "id": mission["id"],
                "nodes": [
                    {
                        "node_id": node["node_id"],
                        "service": node["service"],
                        "required": node["required"],
                        "depends_on": list(node["depends_on"]),
                    }
                    for node in mission["nodes"]
                ],
            }
        )
    return {
        "pack_id": config["pack"]["pack_id"],
        "mission_ids": list(config["pack"]["mission_ids"]),
        "missions": packed,
        "scoring_version": config["scoring_version"],
        "ruleset_version": config["ruleset_version"],
        "participant_class": config["participant_class"],
        "rush_duration_ms": config["rush_duration_ms"],
        "collapse": config.get("collapse", {}),
    }


def pack_hash(config=None, missions=None) -> str:
    raw = json.dumps(pack_document(config, missions), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_content():
    errors = []
    services, by_id, by_key = load_services()
    hardware = load_hardware()
    config = load_game_config()
    missions = load_missions()
    if [row["id"] for row in services] != list(range(17)):
        errors.append("service ids must be 0..16")
    if services[0]["key"] != "KIRO_START":
        errors.append("id 0 must be KIRO_START")
    hw_buttons = hardware["buttons"]
    if [button["id"] for button in hw_buttons] != list(range(17)):
        errors.append("hardware button ids must be 0..16")
    for service, button in zip(services, hw_buttons):
        if service["key"] != button["key"] or service["slot"] != button["slot"]:
            errors.append(f"hardware/service mismatch at id {service['id']}")
    if hardware["led"]["lanes"][0]["gpio"] == 0:
        errors.append("lane gpio looks unset")
    seen_gpio = [button["gpio"] for button in hw_buttons]
    if len(seen_gpio) != len(set(seen_gpio)):
        errors.append("duplicate button gpio")
    ranked_ids = []
    for mission in missions:
        node_ids = [node["node_id"] for node in mission["nodes"]]
        if len(node_ids) != len(set(node_ids)):
            errors.append(f"{mission['id']} duplicate node_id")
        required = [node for node in mission["nodes"] if node["required"]]
        if not required:
            errors.append(f"{mission['id']} has no required node")
        for node in mission["nodes"]:
            if node["service"] not in by_key or node["service"] == "KIRO_START":
                errors.append(f"{mission['id']} bad service {node['service']}")
            for role in ("zh", "en"):
                if not node["role"].get(role):
                    errors.append(f"{mission['id']} {node['node_id']} missing {role} role")
            for dep in node["depends_on"]:
                if dep not in node_ids:
                    errors.append(f"{mission['id']} missing dep {dep}")
        if _has_cycle(mission["nodes"]):
            errors.append(f"{mission['id']} cycle")
        if mission.get("ranked"):
            ranked_ids.append(mission["id"])
    pack_ids = config["pack"]["mission_ids"]
    if "M09_PROTECTED_WEB" in pack_ids:
        errors.append("M09 must stay out of the ranked pack")
    if pack_ids != [mission_id for mission_id in ranked_ids if mission_id != "M09_PROTECTED_WEB"] and set(pack_ids) != set(
        mid for mid in ranked_ids
    ):
        missing = [mid for mid in ranked_ids if mid not in pack_ids]
        if missing:
            errors.append(f"ranked missions missing from pack: {missing}")
    return errors


def _has_cycle(nodes) -> bool:
    deps = {node["node_id"]: list(node["depends_on"]) for node in nodes}
    visiting = set()
    done = set()

    def walk(node_id):
        if node_id in done:
            return False
        if node_id in visiting:
            return True
        visiting.add(node_id)
        for dep in deps.get(node_id, []):
            if walk(dep):
                return True
        visiting.remove(node_id)
        done.add(node_id)
        return False

    return any(walk(node_id) for node_id in deps)
