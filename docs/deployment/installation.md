# Deployment & Installation

Two install paths: a **packaged Windows build** (operators) and a **Python/dev
install** (engineering, CI, macOS dev). See the [validation IQ](../validation/02-iq.md)
for the formal qualification checklist.

## 1. Prerequisites (line PC)

- Windows 10/11 x64 (or Linux x64), ≥ 8 CPU cores (≥12 for max config), ≥ 16 GB RAM.
- **PostgreSQL 14+** (local or central).
- Dedicated **GigE NIC**: enable jumbo frames (MTU 9014), raise RX buffers, tune
  interrupt moderation toward latency (D-011).
- Vendor **GenTL producer** (`.cti`) for the camera.
- Digital reject I/O (Modbus TCP block or I/O card) and lighting controller.
- **NTP** time sync (for trustworthy audit timestamps).

## 2. Database setup (PostgreSQL)

```sql
CREATE DATABASE vis;
CREATE ROLE vis_app LOGIN PASSWORD '••••••';
GRANT ALL PRIVILEGES ON DATABASE vis TO vis_app;
```

Point the app at it and apply migrations:

```bash
set DATABASE_URL=postgresql+psycopg://vis_app:••••@localhost/vis   # Windows: setx
pip install -e ".[postgres]"
alembic upgrade head
```

**Lock the audit table (Part 11 — enforce append-only at the DB):**

```sql
REVOKE UPDATE, DELETE ON audit_entries FROM vis_app;
```

## 3. Install the application

**Python install (dev / engineering / CI):**

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[codes,ocr,camera,io,hmi,postgres]"  # install only the licensed extras
```

Extras: `codes` (1D/2D decode), `ocr` (ONNX PaddleOCR), `camera` (GenICam/Harvester),
`io` (Modbus reject), `hmi` (Qt desktop UI), `postgres` (driver + migrations).

**Packaged Windows build (operators):** install the MSI produced by
[packaging](../../packaging/README.md) — it bundles Python, the app, and the Qt HMI.

## 4. Configure

1. Set `VIS_GENTL_CTI` to the GenTL producer path (real camera).
2. First launch of `vis-hmi` seeds a default **admin / admin123** — **change it
   immediately** and create real users/roles.
3. Configure the **station** (cameras, reject lanes, lighting) — persisted & audited.
4. Pin the **OCR/AI model version** (D-007); record its sha256 (IQ-C6).
5. Set the **image-retention policy** and archive path.

## 5. Run

```bash
vis-hmi                                  # the Qt operator HMI (login → live)
vis-demo --source ocr --frames 10        # headless demo / smoke check
vis-demo --db sqlite:///run.db --station "Line-1"   # run from a persisted station
```

## 6. Verify (smoke / IQ-E)

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q        # all tests should pass
```

## Notes

- **macOS dev:** GenICam acquisition is not available on macOS (D-011); use the
  simulation/file sources. Everything else runs and is testable on macOS.
- **Backups:** back up the PostgreSQL database and the image archive on the
  customer's schedule; verify restores.
