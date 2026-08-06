"""Image archiving — keep the evidence, and say why it was rejected.

Every inspected frame can be written to disk according to a retention policy, so
a plant can go back and look at what the line actually saw. Two things make an
archive genuinely useful rather than a pile of PNGs:

- **Passes and rejects are kept apart** (``…/pass`` and ``…/reject``), so
  "show me yesterday's rejects" is a folder, not a database query;
- **Each reject is written with its analysis** — a JSON sidecar naming the
  inspection that failed, what it read, what was expected, and the confidence.
  A month later that is the difference between evidence and a picture.

Policies:
  ``none``   record the FrameCapture row, store no image
  ``fails``  store rejects only (default — the usual GMP retention)
  ``all``    store every frame (validation runs, troubleshooting a new product)

Images go to the filesystem and only a path is stored in the database (D-013).
Archiving must never break the line, so failures here are logged, not raised.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from ..db.models import FrameCapture

log = logging.getLogger(__name__)

POLICIES = ("none", "fails", "all")


def reject_analysis(frame, results) -> dict:
    """Why this frame was rejected, in a form that survives without the app.

    Structured per region -> per failed tool, with measured vs expected values
    so the record answers "what did it read, and what should it have read?".
    """
    regions = []
    for region in results:
        failures = [
            {
                "tool": getattr(tool, "tool_id", ""),
                "read": getattr(tool, "measured_value", None),
                "expected": getattr(tool, "expected_value", None),
                "confidence": getattr(tool, "confidence", None),
                "model": getattr(tool, "model_version", None),
            }
            for tool in (getattr(region, "tool_results", None) or [])
            if not getattr(tool, "passed", True)
        ]
        regions.append(
            {
                "region": getattr(region, "region_id", ""),
                "passed": bool(getattr(region, "passed", True)),
                "reject_output": getattr(region, "reject_output", ""),
                "failures": failures,
            }
        )
    failed = [r for r in regions if not r["passed"]]
    summary = "; ".join(
        (
            f"{f['tool']}: read {f['read']!r}, expected {f['expected']!r}"
            if f["read"] is not None and f["expected"] is not None
            else (f["tool"] or "inspection")
        )
        for region in failed
        for f in region["failures"]
    )
    return {
        "camera_id": frame.camera_id,
        "frame_id": frame.frame_id,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": not failed,
        "summary": summary or ("failed" if failed else "passed"),
        "regions": regions,
    }


class FrameArchiver:
    """``on_frame`` hook that archives frames per an image-retention policy.

    ``directory`` is the archive root; when ``separate_folders`` is set (the
    default) images land in ``<root>/pass`` and ``<root>/reject``. Set
    ``write_analysis`` to drop a ``.json`` sidecar next to each rejected image.
    """

    def __init__(
        self, session_factory, directory: str, *, batch_id: int | None = None,
        policy: str = "fails", uploader=None, separate_folders: bool = True,
        write_analysis: bool = True,
    ) -> None:
        self._sf = session_factory
        self.directory = directory
        self.batch_id = batch_id
        self.policy = policy if policy in POLICIES else "fails"
        self.uploader = uploader  # optional callable(local_path) -> remote ref
        self.separate_folders = separate_folders
        self.write_analysis = write_analysis
        self.saved = 0
        self.errors = 0
        os.makedirs(directory, exist_ok=True)

    def _target_dir(self, passed: bool) -> str:
        if not self.separate_folders:
            return self.directory
        target = os.path.join(self.directory, "pass" if passed else "reject")
        os.makedirs(target, exist_ok=True)
        return target

    def _should_save(self, any_fail: bool) -> bool:
        if self.policy == "all":
            return True
        if self.policy == "none":
            return False
        return any_fail

    def on_frame(self, frame, results) -> None:
        any_fail = any(not r.passed for r in results)
        image_ref = None
        if self._should_save(any_fail):
            try:
                image_ref = self._write(frame, results, passed=not any_fail)
            except Exception:
                # archiving must never stop the line
                self.errors += 1
                log.exception("could not archive frame %s", frame.frame_id)
        try:
            with self._sf() as s:
                s.add(
                    FrameCapture(
                        batch_id=self.batch_id,
                        camera_id=frame.camera_id,
                        frame_id=frame.frame_id,
                        image_ref=image_ref,
                        passed=not any_fail,
                    )
                )
                s.commit()
        except Exception:
            self.errors += 1
            log.exception("could not record FrameCapture for frame %s", frame.frame_id)

    def _write(self, frame, results, *, passed: bool) -> str:
        from PIL import Image

        # store the product-region crop (the centred product), not the whole
        # frame — the rest is conveyor. Falls back to the full frame.
        try:
            from ..engine.content_crop import crop_to_content

            out = crop_to_content(frame.image)
        except Exception:
            out = frame.image
        stem = f"{frame.camera_id}_f{frame.frame_id:05d}"
        image_ref = os.path.join(self._target_dir(passed), f"{stem}.png")
        Image.fromarray(out).save(image_ref)
        self.saved += 1

        if self.write_analysis and not passed:
            analysis = reject_analysis(frame, results)
            analysis["image"] = os.path.basename(image_ref)
            analysis["batch_id"] = self.batch_id
            try:
                with open(os.path.splitext(image_ref)[0] + ".json", "w", encoding="utf-8") as f:
                    json.dump(analysis, f, indent=2, default=str)
            except Exception:
                self.errors += 1
                log.exception("could not write the analysis for frame %s", frame.frame_id)

        if self.uploader is not None:  # push to FTP / network archive
            try:
                image_ref = self.uploader(image_ref) or image_ref
            except Exception:
                log.exception("archive upload failed for %s", image_ref)
        return image_ref
