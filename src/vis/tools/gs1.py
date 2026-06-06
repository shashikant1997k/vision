"""Minimal GS1 Application Identifier (AI) parser.

Handles the AIs used in pharma coding: 01 (GTIN), 17 (expiry), 10 (batch/lot),
21 (serial), plus other common fixed-length AIs. Fixed-length AIs are read by
their defined data length; everything else is treated as variable-length,
terminated by the GS separator (ASCII 29) or end of string.

Limitation: assumes 2-digit AI prefixes (true for the pharma core set). Full
3-/4-digit AI support is a later refinement.
"""

from __future__ import annotations

GS = "\x1d"  # FNC1 / group separator

# AI -> length of the data that follows it (fixed-length AIs only).
FIXED_LENGTH: dict[str, int] = {
    "00": 18,
    "01": 14,
    "02": 14,
    "11": 6,  # production date (YYMMDD)
    "12": 6,
    "13": 6,
    "15": 6,  # best-before
    "16": 6,
    "17": 6,  # expiry (YYMMDD)
    "20": 2,
}

AI_NAMES: dict[str, str] = {
    "00": "sscc",
    "01": "gtin",
    "10": "batch",
    "11": "production_date",
    "15": "best_before",
    "17": "expiry",
    "21": "serial",
}


def parse_gs1(data: str) -> dict[str, str]:
    """Parse a GS1 element string into {AI: value}."""
    out: dict[str, str] = {}
    i, n = 0, len(data)
    while i < n:
        if data[i] == GS:
            i += 1
            continue
        ai = data[i : i + 2]
        i += 2
        if not ai:
            break
        if ai in FIXED_LENGTH:
            length = FIXED_LENGTH[ai]
            out[ai] = data[i : i + length]
            i += length
        else:
            end = data.find(GS, i)
            if end == -1:
                end = n
            out[ai] = data[i:end]
            i = end
    return out


def named(parsed: dict[str, str]) -> dict[str, str]:
    """Map AI numbers to friendly names (gtin/batch/expiry/serial/...)."""
    return {AI_NAMES.get(ai, ai): value for ai, value in parsed.items()}
