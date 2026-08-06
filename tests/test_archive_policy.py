"""Image archiving: retention policy, pass/reject folders, and reject analysis."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from vis.db.base import init_db, make_engine, make_session_factory
from vis.engine.aggregator import RegionResult
from vis.engine.frame import Frame
from vis.runtime.archive import FrameArchiver, reject_analysis
from vis.tools.base import ToolResult


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    return make_session_factory(engine)


def _frame(frame_id=1):
    return Frame("cam1", frame_id, (np.random.rand(40, 60, 3) * 255).astype("uint8"), timestamp=1.0)


def _region(passed, tools=()):
    return RegionResult(
        frame_id=1, camera_id="cam1", region_id="region1",
        reject_output="lane1", passed=passed, tool_results=list(tools),
    )


def _pass():
    return [_region(True, [ToolResult("ocr", True, "LOT42", "LOT42")])]


def _fail():
    return [_region(False, [ToolResult("ocr", False, "LOT99", "LOT42", confidence=0.4)])]


# ---- retention policy ----------------------------------------------------
def test_policy_fails_stores_only_rejects(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="fails")
    a.on_frame(_frame(1), _pass())
    a.on_frame(_frame(2), _fail())
    assert not list((tmp_path / "img" / "pass").glob("*.png"))
    assert len(list((tmp_path / "img" / "reject").glob("*.png"))) == 1


def test_policy_all_stores_both(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="all")
    a.on_frame(_frame(1), _pass())
    a.on_frame(_frame(2), _fail())
    assert len(list((tmp_path / "img" / "pass").glob("*.png"))) == 1
    assert len(list((tmp_path / "img" / "reject").glob("*.png"))) == 1


def test_policy_none_stores_nothing_but_still_records(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="none")
    a.on_frame(_frame(1), _fail())
    assert not list(Path(tmp_path / "img").rglob("*.png"))
    from vis.db.models import FrameCapture

    with session_factory() as s:
        rows = s.query(FrameCapture).all()
        assert len(rows) == 1 and rows[0].image_ref is None


def test_unknown_policy_falls_back_to_fails(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="nonsense")
    assert a.policy == "fails"


def test_separate_folders_can_be_switched_off(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="all",
                      separate_folders=False)
    a.on_frame(_frame(1), _pass())
    assert len(list((tmp_path / "img").glob("*.png"))) == 1


# ---- the analysis --------------------------------------------------------
def test_reject_gets_an_analysis_sidecar(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="fails")
    a.on_frame(_frame(3), _fail())
    files = list((tmp_path / "img" / "reject").glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["passed"] is False
    assert "LOT99" in data["summary"] and "LOT42" in data["summary"]
    failure = data["regions"][0]["failures"][0]
    assert failure["tool"] == "ocr"
    assert failure["read"] == "LOT99" and failure["expected"] == "LOT42"
    assert failure["confidence"] == pytest.approx(0.4)
    assert data["image"].endswith(".png")


def test_passes_get_no_analysis_file(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="all")
    a.on_frame(_frame(4), _pass())
    assert not list((tmp_path / "img" / "pass").glob("*.json"))


def test_analysis_can_be_disabled(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="fails",
                      write_analysis=False)
    a.on_frame(_frame(5), _fail())
    assert not list((tmp_path / "img" / "reject").glob("*.json"))


def test_analysis_only_reports_failed_tools():
    results = [_region(False, [
        ToolResult("good", True, "a", "a"), ToolResult("bad", False, "x", "y"),
    ])]
    data = reject_analysis(_frame(), results)
    tools = [f["tool"] for f in data["regions"][0]["failures"]]
    assert tools == ["bad"]


def test_analysis_of_a_pass_says_so():
    data = reject_analysis(_frame(), _pass())
    assert data["passed"] is True and data["summary"] == "passed"


# ---- robustness ----------------------------------------------------------
def test_archiving_failure_never_breaks_the_line(session_factory, tmp_path, monkeypatch):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="all")
    monkeypatch.setattr(a, "_write", lambda *args, **kw: (_ for _ in ()).throw(OSError("disk full")))
    a.on_frame(_frame(6), _fail())      # must not raise
    assert a.errors == 1
    from vis.db.models import FrameCapture

    with session_factory() as s:
        assert s.query(FrameCapture).count() == 1   # the record is still made


def test_frame_capture_records_the_verdict(session_factory, tmp_path):
    a = FrameArchiver(session_factory, str(tmp_path / "img"), policy="all", batch_id=7)
    a.on_frame(_frame(1), _pass())
    a.on_frame(_frame(2), _fail())
    from vis.db.models import FrameCapture

    with session_factory() as s:
        rows = s.query(FrameCapture).order_by(FrameCapture.frame_id).all()
        assert [r.passed for r in rows] == [True, False]
        assert all(r.batch_id == 7 for r in rows)
