"""Ranked score and sort key. Display score never goes below the configured floor."""

from __future__ import annotations


def combo_bonus(streak: int, step: int, cap: int) -> int:
    if streak < 2:
        return 0
    return min((streak - 1) * step, cap)


def display_score(raw_score: int, floor: int) -> int:
    return raw_score if raw_score > floor else floor


def rank_key(row: dict) -> tuple:
    last = row["last_completed_t_ms"]
    if last is None:
        last = 2**62
    return (
        -row["solutions_completed"],
        -row["score"],
        row["invalid_hits"],
        last,
    )
