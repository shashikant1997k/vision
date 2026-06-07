import numpy as np

from vis.camera.focus import FocusAssist, focus_score


def test_sharp_image_scores_higher_than_blurred():
    from PIL import Image, ImageFilter

    rng = np.random.default_rng(0)
    sharp = (rng.integers(0, 2, (120, 120)) * 255).astype(np.uint8)
    sharp_rgb = np.stack([sharp] * 3, axis=2)
    blurred = np.array(Image.fromarray(sharp_rgb).filter(ImageFilter.GaussianBlur(3)))

    assert focus_score(sharp_rgb) > focus_score(blurred)


def test_focus_assist_tracks_best_as_percent():
    striped = np.zeros((60, 60, 3), dtype=np.uint8)
    striped[::2] = 255
    fa = FocusAssist()
    score, percent = fa.update(striped)
    assert score > 0 and percent == 100.0

    flat = np.full((60, 60, 3), 128, dtype=np.uint8)
    _, percent2 = fa.update(flat)
    assert percent2 < 100.0  # less sharp than the best seen


def test_focus_score_on_roi():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[::2] = 255
    assert focus_score(img, roi=(10, 10, 40, 40)) > 0
