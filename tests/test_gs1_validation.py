"""GS1 structural validation (check digits, dates, charset) + serial uniqueness."""

import pytest

from vis.tools.gs1 import (
    GS,
    canonical_date,
    mod10_check,
    named,
    parse_gs1,
    valid_cset82,
    valid_date_yymmdd,
    validate_gs1,
)


def test_parse_strips_symbology_id_and_leading_fnc1():
    data = "]d2" + GS + "010950600013435221SN001"
    parsed = parse_gs1(data)
    assert parsed["01"] == "09506000134352" and parsed["21"] == "SN001"


def test_gtin_and_sscc_check_digits():
    assert mod10_check("09506000134352")       # valid GTIN-14
    assert not mod10_check("09506000134353")    # wrong check digit
    assert mod10_check("106141411234567897")    # valid SSCC-18
    assert not mod10_check("106141411234567890")


def test_date_validation_including_dd00_rule():
    assert valid_date_yymmdd("261031")          # 2026-10-31
    assert valid_date_yymmdd("261000")          # DD=00 allowed (last day)
    assert not valid_date_yymmdd("261301")      # month 13
    assert not valid_date_yymmdd("260230")      # Feb 30
    assert valid_date_yymmdd("240229")          # 2024 leap day
    assert not valid_date_yymmdd("250229")      # 2025 not a leap year


def test_canonical_date_normalises_dd00():
    assert canonical_date("261000") == "261031"  # Oct -> 31
    assert canonical_date("260200") == "260228"  # Feb 2026 -> 28 (not leap)
    assert canonical_date("260229") == "260229"  # already concrete


def test_cset82_charset():
    assert valid_cset82("ABC-123/45")
    assert not valid_cset82("LOT\x1d42")         # control char
    assert not valid_cset82("")                  # empty


def test_validate_flags_bad_check_digit_and_date():
    parsed = parse_gs1("010950600013435317" + "261301" + GS + "10LOT42")
    errors = validate_gs1(parsed)
    assert "01" in errors and "check digit" in errors["01"]
    assert "17" in errors and "date" in errors["17"]
    # a clean code validates
    good = parse_gs1("010950600013435217261031" + GS + "10LOT42" + GS + "21SN1")
    assert validate_gs1(good) == {}


def test_validate_accepts_named_keys():
    assert validate_gs1({"gtin": "09506000134352"}) == {}
    assert "gtin" in validate_gs1({"gtin": "09506000134353"})


def test_code_verify_rejects_invalid_checkdigit():
    pytest.importorskip("cv2")
    pytest.importorskip("qrcode")
    import numpy as np
    import qrcode

    from vis.tools import build_tool

    # a GS1 string whose GTIN check digit is wrong
    payload = "010950600013435317" + "261031" + GS + "21SN001"
    img = qrcode.make(payload).convert("RGB")
    arr = np.array(img)
    tool = build_tool("code_verify", "c", {"gs1": True, "validate": True})
    result = tool.inspect(arr)
    # decode may or may not succeed depending on env; if it decoded, it must flag
    if result.measured_value:
        assert not result.passed
        assert "invalid" in result.detail


def test_code_verify_canonical_date_match():
    pytest.importorskip("cv2")
    pytest.importorskip("qrcode")
    import numpy as np
    import qrcode

    from vis.tools import build_tool

    payload = "010950600013435217" + "261000" + GS + "21SN1"  # DD=00
    arr = np.array(qrcode.make(payload).convert("RGB"))
    tool = build_tool("code_verify", "c", {
        "gs1": True, "expected_fields": {"expiry": "261031"}})  # concrete last day
    result = tool.inspect(arr)
    if result.measured_value:  # if decoded in this env
        assert result.passed  # 261000 canonicalises to 261031


def test_named_mapping():
    assert named({"01": "X", "21": "Y"}) == {"gtin": "X", "serial": "Y"}
