import numpy as np
import pytest

pytest.importorskip("cv2")

import cv2  # noqa: E402

from vis.engine.content_crop import content_bbox, crop_to_content


def _frame_with_centered_product():
    """Uniform 'conveyor' background with a printed product block in the centre."""
    img = np.full((480, 640, 3), 200, np.uint8)  # flat grey background
    cv2.rectangle(img, (250, 200), (390, 280), (255, 255, 255), -1)  # product face
    cv2.putText(img, "LOT123", (260, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    return img


def test_bbox_finds_centered_product_not_full_frame():
    img = _frame_with_centered_product()
    x, y, w, h = content_bbox(img)
    # the crop is well inside the full 640x480 frame and surrounds the centre
    assert w < 640 and h < 480
    assert x > 50 and y > 50
    assert x < 320 < x + w and y < 240 < y + h  # contains the product centre


def test_crop_to_content_is_smaller_but_keeps_the_text():
    img = _frame_with_centered_product()
    crop = crop_to_content(img)
    assert crop.size < img.size  # actually cropped
    assert crop.shape[0] >= 60 and crop.shape[1] >= 100  # product region preserved


def test_blank_frame_falls_back_to_full():
    blank = np.full((200, 300, 3), 180, np.uint8)
    assert content_bbox(blank) == (0, 0, 300, 200)  # nothing to crop → full frame
