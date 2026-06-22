"""Render inspection results onto a frame for the live HMI view.

Draws each region's box (green=pass, red=reject) and each tool's ROI with its
read value and grade, so the operator sees exactly what was inspected and why a
product was rejected. Pure function: image + recipe + results -> annotated image.
"""

from __future__ import annotations

import numpy as np

GREEN = (0, 170, 0)
RED = (220, 30, 30)
BLUE = (40, 120, 255)

_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
]


def _font(size: int):
    from PIL import ImageFont

    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _disp(value) -> str:
    return "" if value is None else str(value).replace("\x1d", "<GS>")


def _label(draw, xy, text, color, font):
    """Draw text with a dark backing box so it's readable over any image."""
    x, y = xy
    try:
        left, top, right, bottom = draw.textbbox((x, y), text, font=font)
        draw.rectangle([left - 2, top - 1, right + 2, bottom + 1], fill=(0, 0, 0))
    except Exception:
        pass
    draw.text((x, y), text, fill=color, font=font)


_FRIENDLY = {
    "code_verify": "Read Code",
    "ocv_text": "Read Text",
    "ocv_stub": "Read Text",
    "ocv_font": "Read Text",
    "presence": "Presence",
    "measure": "Measure",
    "color_check": "Colour",
    "template_match": "Template",
}
YELLOW = (255, 200, 0)
CYAN = (0, 200, 220)
SEARCH = (90, 130, 255)


def _box_style(arr, box, color):
    """Adapt a box's stroke to the LOCAL background so it is visible on any
    colour: sample the luminance under the box, choose a contrasting halo
    (black on light, white on dark) and brighten the accent on dark areas."""
    x0, y0, x1, y1 = (int(v) for v in box)
    h, w = arr.shape[:2]
    x0c, x1c = max(0, min(w - 1, x0)), max(1, min(w, x1))
    y0c, y1c = max(0, min(h - 1, y0)), max(1, min(h, y1))
    patch = arr[y0c:y1c, x0c:x1c]
    if patch.size == 0:
        lum = 128.0
    else:
        lum = float(patch[..., :3].mean()) if patch.ndim == 3 else float(patch.mean())
    halo = (0, 0, 0) if lum >= 110 else (255, 255, 255)
    accent = color
    if lum < 90:  # brighten the accent on dark backgrounds
        accent = tuple(int(c + (255 - c) * 0.45) for c in color)
    return halo, accent


def _visible_rect(draw, arr, box, color, width=3):
    """Rectangle with a contrasting halo — readable on every background."""
    halo, accent = _box_style(arr, box, color)
    x0, y0, x1, y1 = box
    draw.rectangle([x0 - 1, y0 - 1, x1 + 1, y1 + 1], outline=halo, width=width + 2)
    draw.rectangle([x0, y0, x1, y1], outline=accent, width=width)


def _visible_dashed(draw, arr, box, color, width=2):
    halo, accent = _box_style(arr, box, color)
    _dashed_rect(draw, box, halo, width=width + 2)
    _dashed_rect(draw, box, accent, width=width)


def _margins(tool) -> tuple[int, int]:
    cfg = tool.config or {}
    legacy = int(cfg.get("search_margin", 0) or 0)
    return int(cfg.get("search_x", legacy) or 0), int(cfg.get("search_y", legacy) or 0)


def _dashed_rect(draw, box, color, width=2, dash=7, gap=5):
    """Dashed rectangle — the standard look for a SEARCH region, visually
    distinct from the solid inner read box."""
    x0, y0, x1, y1 = box
    x = x0
    while x < x1:
        end = min(x + dash, x1)
        draw.line([(x, y0), (end, y0)], fill=color, width=width)
        draw.line([(x, y1), (end, y1)], fill=color, width=width)
        x += dash + gap
    y = y0
    while y < y1:
        end = min(y + dash, y1)
        draw.line([(x0, y), (x0, end)], fill=color, width=width)
        draw.line([(x1, y), (x1, end)], fill=color, width=width)
        y += dash + gap


def _template_size(fixture):
    try:
        import cv2

        arr = np.frombuffer(fixture.template, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        return img.shape[1], img.shape[0]
    except Exception:
        return 40, 40


def _draw_locator(draw, region, font):
    fixture = getattr(region, "fixture", None)
    if fixture is None:
        return
    tw, th = _template_size(fixture)
    x, y = fixture.anchor_x, fixture.anchor_y
    draw.rectangle([x, y, x + tw - 1, y + th - 1], outline=CYAN, width=2)
    label_y = y - 18 if y >= 18 else y + th + 2
    _label(draw, (x + 2, label_y), "⌖ Locator", CYAN, font)


def draw_layout(image: np.ndarray, recipe, highlight=None) -> np.ndarray:
    """Draw region/tool ROIs (no results) for the teach preview. `highlight` is
    an absolute (x, y, w, h) box drawn thick yellow to mark the selected item."""
    from PIL import Image, ImageDraw

    img = Image.fromarray(np.ascontiguousarray(image)).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _font(16)
    arr = np.ascontiguousarray(image)
    for region in recipe.regions:
        rx, ry, rw, rh = region.roi.x, region.roi.y, region.roi.w, region.roi.h
        _visible_rect(draw, arr, (rx, ry, rx + rw - 1, ry + rh - 1), BLUE, width=2)
        _label(draw, (rx + 4, ry + 4), region.name, BLUE, font)
        _draw_locator(draw, region, font)
        for tool in region.tools:
            ax, ay = rx + tool.roi.x, ry + tool.roi.y
            mx, my = _margins(tool)
            if mx or my:  # outer search window (print-drift tolerance) — dashed
                _visible_dashed(
                    draw, arr,
                    (ax - mx, ay - my, ax + tool.roi.w - 1 + mx, ay + tool.roi.h - 1 + my),
                    SEARCH,
                )
            _visible_rect(draw, arr, (ax, ay, ax + tool.roi.w - 1, ay + tool.roi.h - 1), BLUE, width=3)
            ty = ay - 18 if ay >= 18 else ay + 2
            friendly = _FRIENDLY.get(tool.tool_type, tool.tool_type)
            _label(draw, (ax + 2, ty), f"{tool.tool_id} · {friendly}", BLUE, font)
    if highlight is not None:
        hx, hy, hw, hh = highlight
        draw.rectangle([hx - 1, hy - 1, hx + hw, hy + hh], outline=YELLOW, width=3)
    return np.array(img, dtype=np.uint8)


def _banner(draw, xy, text, bg, font):
    """Solid status banner (white text on the pass/fail colour) — readable from
    across the line, never clipped."""
    x, y = xy
    left, top, right, bottom = draw.textbbox((x, y), text, font=font)
    draw.rectangle([left - 6, top - 4, right + 6, bottom + 4], fill=bg)
    draw.text((x, y), text, fill=(255, 255, 255), font=font)


def _rects_overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _place_tag(draw, box, text, color, font, occupied, W, H):
    """Draw a per-ROI read tag so tags never overlap each other: prefer just to
    the RIGHT of the box; if that collides with an already-placed tag, slide it
    down until it's clear. Coloured text on a solid dark backing = readable on
    any background (green = pass, red = fail)."""
    x0, y0, x1, y1 = box
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    tw, th = (right - left) + 8, (bottom - top) + 6
    for cx, cy in ((x1 + 5, y0), (x0, y1 + 3), (max(2, x0 - tw - 5), y0)):
        cx = max(2, min(cx, W - tw - 2))
        cy = max(2, min(cy, H - th - 2))
        rect = [cx, cy, cx + tw, cy + th]
        for _ in range(60):
            if not any(_rects_overlap(rect, o) for o in occupied):
                break
            cy += th + 2
            if cy > H - th - 2:
                break
            rect = [cx, cy, cx + tw, cy + th]
        if not any(_rects_overlap(rect, o) for o in occupied):
            occupied.append(rect)
            draw.rectangle([rect[0], rect[1], rect[2], rect[3]], fill=(0, 0, 0))
            draw.text((rect[0] + 4, rect[1] + 3), text, fill=color, font=font)
            return
    # everything collided — draw at the right edge anyway (rare)
    _label(draw, (min(x1 + 5, W - tw), y0), text, color, font)


def draw_overlay(image: np.ndarray, recipe, results, offset=(0, 0)) -> np.ndarray:
    """Return a copy of `image` annotated with results: a big PASS/FAIL banner,
    thin green(pass)/red(reject) ROI boxes, and each inspection's read value as a
    non-overlapping colour-coded tag beside its box.

    `offset` (ox, oy) is subtracted from every recipe coordinate so the overlay
    lines up when `image` is a crop of the full frame (zoom-to-content view)."""
    from PIL import Image, ImageDraw

    ox, oy = offset
    arr = np.ascontiguousarray(image)
    img = Image.fromarray(arr).convert("RGB")
    draw = ImageDraw.Draw(img)
    W, H = img.width, img.height
    big = _font(max(22, H // 18))      # the headline PASS / FAIL
    font = _font(max(13, H // 40))     # per-ROI read tags (compact)

    by_region = {r.region_id: r for r in results}
    occupied: list = []  # placed tag rects, so read values never overlap

    for region in recipe.regions:
        region_result = by_region.get(region.region_id)
        passed = region_result.passed if region_result else True
        color = GREEN if passed else RED
        rx, ry, rw, rh = region.roi.x - ox, region.roi.y - oy, region.roi.w, region.roi.h
        _visible_rect(draw, arr, (rx, ry, rx + rw - 1, ry + rh - 1), color, width=2)  # thin

        tool_results = {t.tool_id: t for t in (region_result.tool_results if region_result else [])}
        for tool in region.tools:
            tr = tool_results.get(tool.tool_id)
            tcolor = GREEN if (tr and tr.passed) else RED
            ax, ay = rx + tool.roi.x, ry + tool.roi.y
            box = (ax, ay, ax + tool.roi.w - 1, ay + tool.roi.h - 1)
            mx, my = _margins(tool)
            if mx or my:
                _visible_dashed(
                    draw, arr,
                    (ax - mx, ay - my, ax + tool.roi.w - 1 + mx, ay + tool.roi.h - 1 + my),
                    tcolor, width=1,
                )
            _visible_rect(draw, arr, box, tcolor, width=2)  # thin so text stays visible
            if tr is None:
                continue
            value = _disp(tr.measured_value) or "(no read)"
            if len(value) > 24:
                value = value[:23] + "…"
            grade = (tr.detail or {}).get("grade", {}).get("overall")
            if grade:
                value = f"{value} [{grade}]"
            mark = "✓" if tr.passed else "✗"
            _place_tag(draw, box, f"{mark} {tool.tool_id}: {value}", tcolor, font, occupied, W, H)

    # one big, unambiguous PASS / FAIL headline for the whole product
    overall = all(r.passed for r in results) if results else True
    _banner(draw, (12, 10), "PASS" if overall else "FAIL", GREEN if overall else RED, big)
    return np.array(img, dtype=np.uint8)
