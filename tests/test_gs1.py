from vis.tools.gs1 import GS, named, parse_gs1


def test_parse_fixed_and_variable_ais():
    # 01 GTIN(14) | 17 expiry(6) | 10 batch(var) <GS> 21 serial(var)
    data = "01" + "09506000134352" + "17" + "260101" + "10" + "ABC123" + GS + "21" + "SER001"
    parsed = parse_gs1(data)
    assert parsed["01"] == "09506000134352"
    assert parsed["17"] == "260101"
    assert parsed["10"] == "ABC123"
    assert parsed["21"] == "SER001"


def test_named_mapping():
    data = "01" + "09506000134352" + "10" + "LOT42" + GS + "21" + "S9"
    n = named(parse_gs1(data))
    assert n["gtin"] == "09506000134352"
    assert n["batch"] == "LOT42"
    assert n["serial"] == "S9"


def test_variable_ai_runs_to_end_without_trailing_gs():
    data = "10" + "FINAL"
    assert parse_gs1(data)["10"] == "FINAL"
