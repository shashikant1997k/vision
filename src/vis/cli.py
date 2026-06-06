from __future__ import annotations

import argparse

from .common.events import EventBus
from .common.types import ROI
from .domain.entities import Recipe, Region, ToolSpec
from .engine.camera import FakeCamera
from .engine.pipeline import InspectionPipeline
from .engine.pool import ProcessPool, SyncPool


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
    args = parser.parse_args()

    recipe = build_demo_recipe()
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

    pipeline = InspectionPipeline(recipe, pool, bus)
    camera = FakeCamera("cam1", recipe, num_frames=args.frames, defect_rate=args.defect_rate)

    total = passed = 0
    for frame in camera.frames():
        for r in pipeline.process_frame(frame):
            total += 1
            passed += int(r.passed)
            status = "PASS" if r.passed else f"REJECT -> {r.reject_output}"
            print(f"frame {frame.frame_id:>3}  {r.region_id}: {status}")
    pool.close()
    if transport is not None:
        transport.close()

    pool_kind = f"ProcessPool({args.workers})" if args.workers > 0 else "SyncPool"
    print(f"\n[{pool_kind}] {passed}/{total} regions passed; {len(rejects)} rejects routed")


if __name__ == "__main__":
    main()
