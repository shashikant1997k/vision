"""Simulation acquisition source for demos and tests.

Renders REAL codes (QR) and pixel-encoded OCV values into each region's tool
ROIs, so the full decode/verify/grade pipeline runs with no camera hardware
(e.g. on macOS). Injects per-region defects at `defect_rate`. This is a
dev/demo source only — production uses GenICam/Harvester (D-011).

Requires qrcode + Pillow (the project's dev extra).
"""

from __future__ import annotations

import random
from collections.abc import Iterator

import numpy as np

from ..domain.entities import Recipe
from .camera import Camera
from .frame import Frame


def _render_qr(text: str, w: int, h: int) -> np.ndarray:
    import qrcode
    from PIL import Image

    qr = qrcode.QRCode(border=4, box_size=5)
    qr.add_data(text)
    qr.make(fit=True)
    code = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    canvas = Image.new("RGB", (w, h), "white")
    cw, ch = code.size
    if cw <= w and ch <= h:
        canvas.paste(code, ((w - cw) // 2, (h - ch) // 2))  # crisp: no interpolation
    else:
        canvas = code.resize((w, h), Image.NEAREST)
    return np.array(canvas, dtype=np.uint8)


class SimulatedCodeCamera(Camera):
    """Generates frames containing real, decodable codes per the recipe."""

    def __init__(
        self,
        camera_id: str,
        recipe: Recipe,
        num_frames: int = 6,
        width: int = 800,
        height: int = 480,
        defect_rate: float = 0.25,
        seed: int = 0,
    ) -> None:
        super().__init__(camera_id)
        self.recipe = recipe
        self.num_frames = num_frames
        self.width = width
        self.height = height
        self.defect_rate = defect_rate
        self._rng = random.Random(seed)

    def frames(self) -> Iterator[Frame]:
        for i in range(self.num_frames):
            img = np.full((self.height, self.width, 3), 255, dtype=np.uint8)  # white bg
            for region in self.recipe.regions:
                defective = self._rng.random() < self.defect_rate
                for tool in region.tools:
                    self._render_tool(img, region, tool, defective)
            yield Frame(self.camera_id, i, img, timestamp=float(i))

    def _render_tool(self, img, region, tool, defective: bool) -> None:
        roi = tool.roi
        y0 = region.roi.y + roi.y
        x0 = region.roi.x + roi.x
        if tool.tool_type == "code_verify":
            data = str(tool.config.get("expected_data", ""))
            if defective:
                data = data.replace("LOT42", "LOT99")  # simulate a misprint
            img[y0 : y0 + roi.h, x0 : x0 + roi.w] = _render_qr(data, roi.w, roi.h)
        elif tool.tool_type == "ocv_stub":
            expected = int(tool.config.get("expected", 0))
            value = (expected + 1) % 256 if defective else expected
            img[y0, x0, 0] = value
