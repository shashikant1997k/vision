from __future__ import annotations

import os

from ..db.models import FrameCapture


class FrameArchiver:
    """`on_frame` hook that archives frames per an image-retention policy.

    policy:
      "none"  — record FrameCapture rows but store no image
      "fails" — store an image only when the frame had a reject (default)
      "all"   — store every image

    Images go to the filesystem (path stored in FrameCapture.image_ref), never
    as DB blobs (D-013).
    """

    def __init__(
        self, session_factory, directory: str, *, batch_id: int | None = None,
        policy: str = "fails", uploader=None,
    ) -> None:
        self._sf = session_factory
        self.directory = directory
        self.batch_id = batch_id
        self.policy = policy
        self.uploader = uploader  # optional callable(local_path) -> remote ref (FTP/network)
        os.makedirs(directory, exist_ok=True)

    def on_frame(self, frame, results) -> None:
        any_fail = any(not r.passed for r in results)
        if self.policy == "all":
            save_image = True
        elif self.policy == "none":
            save_image = False
        else:  # "fails"
            save_image = any_fail

        image_ref = None
        if save_image:
            from PIL import Image

            image_ref = os.path.join(
                self.directory, f"{frame.camera_id}_f{frame.frame_id:05d}.png"
            )
            Image.fromarray(frame.image).save(image_ref)
            if self.uploader is not None:  # push to FTP / network archive
                try:
                    image_ref = self.uploader(image_ref) or image_ref
                except Exception:
                    pass  # never let archiving break the line

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
