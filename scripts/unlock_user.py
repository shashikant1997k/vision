"""Clear the lockout on a user account directly in the SQLite DB.
Usage: python scripts/unlock_user.py [username]   (default: admin)
"""
import os
import sqlite3
import sys
from pathlib import Path

user = sys.argv[1] if len(sys.argv) > 1 else "admin"
db = Path.home() / ".vision-inspection" / "vis.db"
if not db.exists():
    sys.exit(f"DB not found at {db}")

con = sqlite3.connect(str(db))
print("before:", con.execute(
    "SELECT username, active, locked, failed_attempts FROM users").fetchall())
n = con.execute(
    "UPDATE users SET locked=0, failed_attempts=0 WHERE username=?", (user,)).rowcount
con.commit()
print(f"unlocked rows for {user!r}: {n}")
print("after :", con.execute(
    "SELECT username, active, locked, failed_attempts FROM users").fetchall())
con.close()
