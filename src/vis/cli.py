from __future__ import annotations

import argparse

from .common.events import EventBus
from .common.types import ROI
from .domain.entities import Recipe, Region, ToolSpec
from .engine.camera import FakeCamera
from .engine.pipeline import InspectionPipeline
from .engine.pool import ProcessPool, SyncPool
from .tools.gs1 import GS


def build_demo_recipe() -> Recipe:
    """Demo: two products in one camera FOV (multi-product, D-010), each with
    lot / expiry / MRP fields to verify."""

    def product_region(idx: int, x0: int) -> Region:
        roi = ROI(x=x0, y=0, w=600, h=480)
        tools = [
            ToolSpec(f"r{idx}_lot", "ocv_stub", ROI(10, 10, 50, 20), {"expected": 42}),
            ToolSpec(f"r{idx}_expiry", "ocv_stub", ROI(10, 40, 50, 20), {"expected": 99}),
            ToolSpec(f"r{idx}_mrp", "ocv_stub", ROI(10, 70, 50, 20), {"expected": 7}),
        ]
        return Region(f"region{idx}", f"Product {idx}", roi, f"lane{idx}", tools)

    return Recipe(
        recipe_id="demo",
        product="Demo Tablets 500mg",
        version=1,
        regions=[product_region(1, 0), product_region(2, 640)],
    )


def _gs1(serial: str) -> str:
    """A GS1 element string: 01 GTIN | 17 expiry | 10 batch <GS> 21 serial."""
    return "01" + "09506000134352" + "17" + "261231" + "10" + "LOT42" + GS + "21" + serial


def build_code_demo_recipe() -> Recipe:
    """Demo for the `sim` source: two products in one FOV, each with a real GS1
    code (code_verify) plus an OCV text field (ocv_stub)."""

    def product_region(idx: int, x0: int, serial: str) -> Region:
        roi = ROI(x=x0, y=0, w=360, h=480)
        tools = [
            ToolSpec(
                f"r{idx}_code",
                "code_verify",
                ROI(30, 30, 300, 300),
                {"gs1": True, "expected_data": _gs1(serial)},
            ),
            ToolSpec(f"r{idx}_lot", "ocv_stub", ROI(30, 360, 60, 20), {"expected": 42}),
        ]
        return Region(f"region{idx}", f"Product {idx}", roi, f"lane{idx}", tools)

    return Recipe(
        recipe_id="code-demo",
        product="Demo Tablets 500mg (GS1)",
        version=1,
        regions=[product_region(1, 0, "SN0001"), product_region(2, 400, "SN0002")],
    )


def build_ocr_demo_recipe() -> Recipe:
    """Demo for the `ocr` source: each product has a real GS1 code (code_verify)
    plus a printed lot text field verified by OCR (ocv_text)."""

    def product_region(idx: int, x0: int, serial: str) -> Region:
        roi = ROI(x=x0, y=0, w=360, h=440)
        tools = [
            ToolSpec(
                f"r{idx}_code",
                "code_verify",
                ROI(30, 30, 300, 300),
                {"gs1": True, "expected_data": _gs1(serial)},
            ),
            ToolSpec(
                f"r{idx}_lot",
                "ocv_text",
                ROI(0, 340, 360, 90),
                {"expected": "LOT42", "uppercase": True},
            ),
        ]
        return Region(f"region{idx}", f"Product {idx}", roi, f"lane{idx}", tools)

    return Recipe(
        recipe_id="ocr-demo",
        product="Demo Tablets 500mg (GS1 + OCR)",
        version=1,
        regions=[product_region(1, 0, "SN0001"), product_region(2, 400, "SN0002")],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Walking-skeleton inspection demo")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument(
        "--workers", type=int, default=0, help="0 = in-process SyncPool; >0 = ProcessPool"
    )
    parser.add_argument("--defect-rate", type=float, default=0.2)
    parser.add_argument(
        "--tcp-server",
        type=int,
        default=0,
        help="if >0, publish results to third-party apps over TCP on this port",
    )
    parser.add_argument("--tcp-format", choices=("json", "csv"), default="json")
    parser.add_argument(
        "--source",
        choices=("sim", "ocr", "fake"),
        default="sim",
        help="sim = GS1 codes (needs qrcode); ocr = GS1 + real OCR text (needs ocr extra); "
        "fake = pixel-stub OCV only",
    )
    parser.add_argument(
        "--db",
        default="",
        help="if set (e.g. sqlite:///run.db), persist inspection results to this DB",
    )
    parser.add_argument("--cameras", type=int, default=1, help="number of cameras to run")
    args = parser.parse_args()

    if args.source == "ocr":
        recipe = build_ocr_demo_recipe()
    elif args.source == "sim":
        recipe = build_code_demo_recipe()
    else:
        recipe = build_demo_recipe()

    def make_camera(index: int):
        cam_id = f"cam{index + 1}"
        if args.source in ("sim", "ocr"):
            from .engine.sim import SimulatedCodeCamera

            return SimulatedCodeCamera(
                cam_id, recipe, num_frames=args.frames, defect_rate=args.defect_rate, seed=index
            )
        return FakeCamera(
            cam_id, recipe, num_frames=args.frames, defect_rate=args.defect_rate, seed=index
        )

    cameras = [make_camera(i) for i in range(args.cameras)]
    pool = ProcessPool(args.workers) if args.workers > 0 else SyncPool()
    bus = EventBus()
    rejects: list = []
    bus.subscribe("inspection.reject", rejects.append)

    transport = None
    if args.tcp_server > 0:
        from .integrations.format import format_delimited, format_json
        from .integrations.publisher import ResultPublisher
        from .integrations.tcp import TcpResultServer

        transport = TcpResultServer(host="0.0.0.0", port=args.tcp_server)
        fmt = format_json if args.tcp_format == "json" else format_delimited
        bus.subscribe("inspection.result", ResultPublisher(transport, fmt).on_result)
        print(f"[tcp] publishing results on 0.0.0.0:{transport.port} ({args.tcp_format})")

    if args.db:
        from .db.base import init_db, make_engine, make_session_factory
        from .db.store import ResultStore

        engine = make_engine(args.db)
        init_db(engine)
        bus.subscribe("inspection.result", ResultStore(make_session_factory(engine)).on_result)
        print(f"[db] persisting results to {args.db}")

    from .runtime import InspectionRunner, RecordingRejectHandler

    def _print_result(r):
        status = "PASS" if r.passed else f"REJECT -> {r.reject_output}"
        codes = [tr for tr in r.tool_results if tr.detail.get("grade")]
        extra = f"  [grade {codes[0].detail['grade']['overall']}]" if codes else ""
        print(f"{r.camera_id} f{r.frame_id:>3}  {r.region_id}: {status}{extra}")

    bus.subscribe("inspection.result", _print_result)

    reject_handler = RecordingRejectHandler()
    runner = InspectionRunner(
        [(c, recipe) for c in cameras], pool, bus=bus, reject_handler=reject_handler
    )
    print(f"running {len(cameras)} camera(s), source={args.source}...")
    stats = runner.run()
    pool.close()
    if transport is not None:
        transport.close()

    totals = stats.totals()
    pool_kind = f"ProcessPool({args.workers})" if args.workers > 0 else "SyncPool"
    print(f"\n[{pool_kind}] per-camera: {stats.snapshot()}")
    print(
        f"[totals] {totals['passed']}/{totals['total']} regions passed; "
        f"{reject_handler.count()} rejects routed"
    )


if __name__ == "__main__":
    main()
