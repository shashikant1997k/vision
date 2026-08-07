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


def test_read_all_reports_registers_it_could_not_read():
    """A short read must not look like a successful one: "the register reads 0"
    and "the register could not be read" are different facts."""
    class _Flaky:
        def read(self, address, kind="holding"):
            if address == 99:
                raise OSError("no response from slave")
            return 7

        def write(self, address, value, kind="holding"):
            pass

        def close(self):
            pass

    params = [PlcParameter("good", 1), PlcParameter("dead", 99)]
    errors: list = []
    values = read_all(_Flaky(), params, errors)

    assert values == {"good": 7}          # the dead one is NOT reported as 0
    assert len(errors) == 1
    name, why = errors[0]
    assert name == "dead" and "no response" in why


def test_plc_screen_warns_when_there_is_no_plc(tmp_path):
    """Reading a simulator that answers 0 to everything, while the screen says
    "Read 3 parameter(s)", is how a zero gets mistaken for the real machine."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.hmi.plc_params_window import PlcParametersWindow

    QApplication.instance() or QApplication([])
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)

    unconfigured = PlcParametersWindow(sf, target_provider=lambda: None)
    assert "NO PLC CONFIGURED" in unconfigured._target.text()
    unconfigured._add_row(PlcParameter("speed", 40, "holding"))
    unconfigured._read()
    assert "SIMULATOR" in unconfigured._status.text()

    real = PlcParametersWindow(sf, target_provider=lambda: "192.168.0.10:502")
    assert "192.168.0.10:502" in real._target.text()
    assert "NO PLC" not in real._target.text()
    real._add_row(PlcParameter("speed", 40, "holding"))
    real._read()
    assert "192.168.0.10:502" in real._status.text()


def test_plc_test_connection_reports_success_and_failure(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.hmi.plc_params_window import PlcParametersWindow

    QApplication.instance() or QApplication([])
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)

    def refuses():
        raise RuntimeError("cannot connect to PLC at 10.0.0.9:502")

    win = PlcParametersWindow(sf, client_factory=refuses,
                              target_provider=lambda: "10.0.0.9:502")
    win._test()
    assert "FAILED" in win._status.text() and "10.0.0.9:502" in win._status.text()

    ok = PlcParametersWindow(sf, client_factory=SimulatedRegisterClient,
                             target_provider=lambda: "10.0.0.9:502")
    ok._test()
    assert "successfully" in ok._status.text()

    none = PlcParametersWindow(sf, target_provider=lambda: None)
    none._test()
    assert "No PLC configured" in none._status.text()


def test_upload_ignores_unknown_or_none():
    client = SimulatedRegisterClient()
    params = [PlcParameter("a", 1)]
    written = upload(client, params, {"a": None, "ghost": 7})
    assert written == [] and client.read(1) == 0
