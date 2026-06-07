"""Qt desktop HMI — the line operator interface (PySide6, D-015).

  image.py        numpy frame -> QPixmap
  login.py        LoginDialog (authenticates via UserService)
  main_window.py  MainWindow — live view (annotated feed + counters + start/stop)
  app.py          entry point (vis-hmi)

The real-time line UI is a desktop app; the web UI (separate) is reporting/admin
only. This HMI consumes the existing backend (LiveView, overlays, LiveStats,
recipes, auth, runtime) — no new inspection logic lives here.
"""
