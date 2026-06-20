"""Collapse the configured station(s) to a single camera: keep the lowest-id
camera per station and remove the rest. For single-physical-camera setups that
accidentally ended up with extra camera rows (which force multi-camera UI)."""
import sqlite3
from pathlib import Path

db = Path.home() / ".vision-inspection" / "vis.db"
con = sqlite3.connect(str(db))
con.row_factory = sqlite3.Row

cams = con.execute("SELECT id, station_id, name FROM cameras ORDER BY station_id, id").fetchall()
print("before:", [dict(r) for r in cams])

keep, drop = {}, []
for r in cams:
    sid = r["station_id"]
    if sid not in keep:
        keep[sid] = r["id"]      # lowest id per station survives
    else:
        drop.append(r["id"])

for cid in drop:
    # remove any rows that reference the camera before deleting it
    for tbl in ("camera_assignments", "frame_captures"):
        try:
            con.execute(f"DELETE FROM {tbl} WHERE camera_id=?", (cid,))
        except sqlite3.OperationalError:
            pass
    con.execute("DELETE FROM cameras WHERE id=?", (cid,))
con.commit()

print("dropped camera ids:", drop)
print("after :", [dict(r) for r in
                  con.execute("SELECT id, station_id, name FROM cameras ORDER BY id").fetchall()])
con.close()
