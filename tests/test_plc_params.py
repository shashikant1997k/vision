from vis.integrations.plc_params import (
    PlcParameter,
    SimulatedRegisterClient,
    read_all,
    upload,
)


def test_parameter_roundtrips_through_dict():
    p = PlcParameter(name="conveyor_speed", address=40, kind="holding")
    assert PlcParameter.from_dict(p.to_dict()) == p


def test_read_all_returns_current_values():
    client = SimulatedRegisterClient({("holding", 40): 120, ("coil", 5): 1})
    params = [
        PlcParameter("conveyor_speed", 40, "holding"),
        PlcParameter("reject_enable", 5, "coil"),
        PlcParameter("unset", 99, "holding"),
    ]
    values = read_all(client, params)
    assert values == {"conveyor_speed": 120, "reject_enable": 1, "unset": 0}


def test_upload_writes_new_values_back():
    client = SimulatedRegisterClient()
    params = [PlcParameter("conveyor_speed", 40), PlcParameter("reject_enable", 5, "coil")]
    written = upload(client, params, {"conveyor_speed": 150, "reject_enable": 1})
    assert sorted(written) == ["conveyor_speed", "reject_enable"]
    assert client.read(40) == 150 and client.read(5, "coil") == 1


def test_upload_ignores_unknown_or_none():
    client = SimulatedRegisterClient()
    params = [PlcParameter("a", 1)]
    written = upload(client, params, {"a": None, "ghost": 7})
    assert written == [] and client.read(1) == 0
