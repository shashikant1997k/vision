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
    for region in recipe.regions:
        rx, ry, rw, rh = region.roi.x, region.roi.y, region.roi.w, region.roi.h
        draw.rectangle([rx, ry, rx + rw - 1, ry + rh - 1], outline=BLUE, width=2)
        _label(draw, (rx + 4, ry + 4), region.name, BLUE, font)
        _draw_locator(draw, region, font)
        for tool in region.tools:
            ax, ay = rx + tool.roi.x, ry + tool.roi.y
            mx, my = _margins(tool)
            if mx or my:  # outer search window (print-drift tolerance) — dashed
                _dashed_rect(
                    draw,
                    (ax - mx, ay - my, ax + tool.roi.w - 1 + mx, ay + tool.roi.h - 1 + my),
                    SEARCH,
                )
            draw.rectangle([ax, ay, ax + tool.roi.w - 1, ay + tool.roi.h - 1], outline=BLUE, width=2)
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


def draw_overlay(image: np.ndarray, recipe, results) -> np.ndarray:
    """Return a copy of `image` annotated with results: each region boxed and
    bannered green (PASS) / red (REJECT), each inspection boxed with a ✓/✗ tag
    showing the value it read."""
    from PIL import Image, ImageDraw

    img = Image.fromarray(np.ascontiguousarray(image)).convert("RGB")
    draw = ImageDraw.Draw(img)
    height = img.height
    big = _font(max(18, height // 22))  # region status — readable at a glance
    font = _font(max(14, height // 32))  # inspection value tags

    by_region = {r.region_id: r for r in results}
    for region in recipe.regions:
        region_result = by_region.get(region.region_id)
        passed = region_result.passed if region_result else True
        color = GREEN if passed else RED
        rx, ry, rw, rh = region.roi.x, region.roi.y, region.roi.w, region.roi.h
        draw.rectangle([rx, ry, rx + rw - 1, ry + rh - 1], outline=color, width=4)

        status = "PASS"
        if region_result and not region_result.passed:
            status = f"REJECT -> {region_result.reject_output or '?'}"
        # banner INSIDE the region's top edge so it can never clip off-image
        banner_text = f"{region.name} — {status}"
        banner_y = max(2, ry + 4)
        _banner(draw, (rx + 8, banner_y), banner_text, color, big)
        _, btop, _, bbottom = draw.textbbox((rx + 8, banner_y), banner_text, font=big)
        banner_bottom = bbottom + 6

        tool_results = {t.tool_id: t for t in (region_result.tool_results if region_result else [])}
        for tool in region.tools:
            tr = tool_results.get(tool.tool_id)
            tcolor = GREEN if (tr and tr.passed) else RED
            ax, ay = rx + tool.roi.x, ry + tool.roi.y
            mx, my = _margins(tool)
            if mx or my:
                _dashed_rect(
                    draw,
                    (ax - mx, ay - my, ax + tool.roi.w - 1 + mx, ay + tool.roi.h - 1 + my),
                    tcolor, width=1,
                )
            draw.rectangle([ax, ay, ax + tool.roi.w - 1, ay + tool.roi.h - 1], outline=tcolor, width=3)
            if tr is None:
                continue
            value = _disp(tr.measured_value) or "(no read)"
            if len(value) > 28:
                value = value[:27] + "…"
            grade = (tr.detail or {}).get("grade", {}).get("overall")
            if grade:
                value = f"{value} [{grade}]"
            mark = "OK" if tr.passed else "NG"
            text = f"{mark}  {tool.tool_id}: {value}"
            # place the tag above the box; flip inside at the image top, and keep
            # it below the region's status banner so they never overlap
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            tag_h = bottom - top + 8
            ty = ay - tag_h if ay - tag_h >= 0 else ay + 2
            if ty < banner_bottom:
                ty = banner_bottom + 2
            _label(draw, (ax + 4, ty + 4), text, tcolor, font)

    return np.array(img, dtype=np.uint8)
