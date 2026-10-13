"""Mission frontier and Free Build matching. One graph walker for Guided, Rush, and Free."""

from __future__ import annotations

from collections import Counter


def frontier(mission: dict, done: set[str]) -> list[dict]:
    ready = []
    for node in mission["nodes"]:
        if node["node_id"] in done:
            continue
        if all(dep in done for dep in node["depends_on"]):
            ready.append(node)
    return ready


def required_done(mission: dict, done: set[str]) -> bool:
    return all(node["node_id"] in done for node in mission["nodes"] if node["required"])


def take_role(mission: dict, done: set[str], service: str) -> dict | None:
    for node in frontier(mission, done):
        if node["service"] == service:
            return node
    return None


def _required_need(mission: dict) -> Counter:
    need = Counter()
    for node in mission["nodes"]:
        if node["required"]:
            need[node["service"]] += 1
    return need


def analyze_selection(missions: list[dict], selected: Counter, limit: int = 3) -> dict:
    candidates = []
    for mission in missions:
        need = _required_need(mission)
        total = sum(need.values())
        matched = sum(min(selected[service], count) for service, count in need.items())
        if matched < 2 and not (total and matched / total >= 0.5 and matched >= 1):
            continue
        missing = []
        for service, count in need.items():
            short = count - selected[service]
            if short > 0:
                missing.extend([service] * short)
        status = "VALID_COMPLETE" if matched == total else "VALID_PARTIAL"
        candidates.append(
            {
                "mission_id": mission["id"],
                "title": mission["title"],
                "status": status,
                "matched_required": matched,
                "total_required": total,
                "missing": missing,
                "present_nodes": [
                    node["node_id"]
                    for node in mission["nodes"]
                    if node["required"] and selected[node["service"]] > 0
                ],
                "explanation": mission["teaching_points"],
            }
        )
    candidates.sort(key=lambda row: (-row["matched_required"] / row["total_required"], len(row["missing"]), row["mission_id"]))
    chosen = candidates[:limit]
    if not chosen:
        return {
            "status": "UNSUPPORTED",
            "candidates": [],
            "explanation": {
                "zh": "本地规则库还没有能解释这组服务的架构。这不是在说 AWS 做不到。",
                "en": "The local ruleset has no architecture for this set. That is not a claim that AWS cannot do it.",
            },
        }
    return {"status": "CANDIDATES", "candidates": chosen}
