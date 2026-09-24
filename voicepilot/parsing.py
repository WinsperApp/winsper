from __future__ import annotations


def parse_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except ValueError:
        return fallback


def parse_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except ValueError:
        return fallback


def parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
