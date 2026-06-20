"""Exercise the real app camera class (HarvesterCamera) end-to-end, the same
way the HMI does: construct -> open (applies default settings) -> grab."""
import numpy as np
from vis.camera.genicam import HarvesterCamera

cam = HarvesterCamera("gige1")  # cti_path from VIS_GENTL_CTI
cam.open()
print("opened; grabbing 3 frames via app path...")
for i in range(3):
    f = cam.grab()
    img = f.image
    print(f"  frame {f.frame_id}: {img.shape} dtype={img.dtype} "
          f"min={img.min()} max={img.max()} mean={img.mean():.1f}")
cam.close()
print("closed cleanly.")
