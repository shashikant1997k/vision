"""GS1 Application Identifier (AI) parser + validator for pharma coding.

Handles the AIs on pharma cartons: 01 (GTIN), 17 (expiry), 10 (batch/lot),
21 (serial), 00 (SSCC) plus other common fixed-length AIs. Fixed-length AIs are
read by their defined data length; variable-length AIs are terminated by the GS
separator (ASCII 29) or end of string.

Beyond parsing, `validate_gs1` enforces what an auditor checks and what many
legacy parsers skip: GTIN/SSCC MOD-10 check digits, real YYMMDD dates (incl. the
GS1 "DD=00 means last day of month" rule), and GS1 CSET-82 charset on
batch/serial. Rules per GS1 General Specifications §3.

Limitation: assumes 2-digit AI prefixes (true for the pharma core set); 3-/4-
digit AIs (31x weights etc.) are not pharma-carton traffic and are parsed only
if added to the tables below.
"""

from __future__ import annotations

GS = "\x1d"  # FNC1 / group separator
SYMBOLOGY_ID = "]d2"  # AIM identifier some scanners prepend to GS1 DataMatrix

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

DATE_AIS = {"11", "12", "13", "15", "16", "17"}

# GS1 CSET 82 — the invariant subset allowed in alphanumeric AIs (batch/serial).
CSET_82 = set(
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    '!"%&\'()*+,-./_:;<=>?'
)


def parse_gs1(data: str) -> dict[str, str]:
    """Parse a GS1 element string into {AI: value}.

    Tolerates a leading symbology id (`]d2`) and a leading FNC1, which some
    scanners surface on a GS1 DataMatrix read.
    """
    if data.startswith(SYMBOLOGY_ID):
        data = data[len(SYMBOLOGY_ID) :]
    data = data.lstrip(GS)
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


# ---- validation ----------------------------------------------------------
def mod10_check(digits: str) -> bool:
    """GS1 MOD-10 check digit (used by GTIN-14 and SSCC-18). The rightmost digit
    is the check digit; remaining digits are weighted 3,1,3,1,... from the right."""
    if not digits.isdigit() or len(digits) < 2:
        return False
    body, check = digits[:-1], int(digits[-1])
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10 == check


def valid_date_yymmdd(value: str) -> bool:
    """A GS1 YYMMDD date. DD may be '00' (GS1: last day of the month)."""
    import calendar

    if len(value) != 6 or not value.isdigit():
        return False
    yy, mm, dd = int(value[:2]), int(value[2:4]), int(value[4:6])
    if not 1 <= mm <= 12:
        return False
    year = 2000 + yy
    last_day = calendar.monthrange(year, mm)[1]
    return dd == 0 or 1 <= dd <= last_day


def valid_cset82(value: str) -> bool:
    return len(value) >= 1 and all(ch in CSET_82 for ch in value)


def validate_gs1(parsed: dict[str, str]) -> dict[str, str]:
    """Validate parsed AIs. Returns {ai: error_message} for every AI that fails
    a structural rule; an empty dict means structurally valid. Friendly-named
    keys are accepted too (gtin/expiry/batch/serial)."""
    name_to_ai = {v: k for k, v in AI_NAMES.items()}
    errors: dict[str, str] = {}
    for key, value in parsed.items():
        ai = name_to_ai.get(key, key)
        if ai in ("01", "02") and not mod10_check(value):
            errors[key] = "GTIN check digit invalid"
        elif ai == "00" and not mod10_check(value):
            errors[key] = "SSCC check digit invalid"
        elif ai in DATE_AIS and not valid_date_yymmdd(value):
            errors[key] = "not a valid YYMMDD date"
        elif ai in ("10", "21") and not valid_cset82(value):
            errors[key] = "contains characters outside GS1 CSET 82"
    return errors


def canonical_date(value: str) -> str:
    """Canonical YYMMDD for comparison (normalises DD=00 to the month's last
    day), so an expiry compares equal regardless of the last-day convention."""
    import calendar

    if not valid_date_yymmdd(value):
        return value
    yy, mm, dd = int(value[:2]), int(value[2:4]), int(value[4:6])
    if dd == 0:
        dd = calendar.monthrange(2000 + yy, mm)[1]
    return f"{yy:02d}{mm:02d}{dd:02d}"
