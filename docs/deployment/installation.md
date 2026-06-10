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

## Line-PC OCR accuracy & speed checklist

The proven wiring for reliable on-line reading:

1. **Hardware trigger** the GigE camera (Settings → Trigger → hardware/encoder)
   so every product is captured at the same position — strobe the light from the
   same signal to freeze motion.
2. **Fixed ROI per field** drawn in the teach screen (tight box, but leave a few
   pixels of margin — a box that clips a character reads partial text like
   "XP 10" for "EXP. 10/2026").
3. **Recognition-first reading is automatic**: a fixed single-line ROI goes
   straight to the PP-OCR recogniser (no detector), which is faster and immune
   to fragment reads; multi-line/loose boxes fall back to detect+recognise.
4. **Acceleration**: on a line PC with an NVIDIA GPU,
   `pip install onnxruntime-gpu` and set `VIS_OCR_CUDA=1` — det/cls/rec run on
   the GPU. Note: rapidocr 1.2.x supports the **CUDA** execution provider only;
   `onnxruntime-openvino` is NOT picked up by this version — for Intel-only
   line PCs use the PP-OCRv4 models (CPU, default) or a licensed engine through
   the reader seam (`vis.tools.readers`).
5. **Models**: `python scripts/fetch_ocr_models.py` (PP-OCRv4; `--server` for the
   most accurate recogniser).
6. **Verification tolerance**: matching ignores spaces/punctuation and folds
   confusable glyphs (O→0, I/L→1, S→5, Z→2) on BOTH sides — '"B.N0" read for
   "B.No"' passes; a genuinely wrong digit still rejects.
