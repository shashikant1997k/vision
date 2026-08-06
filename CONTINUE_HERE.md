# CONTINUE HERE — session handoff

**For a fresh assistant session, or for picking this up on another PC.**
Read this, then [GUIDE.md](GUIDE.md) for how the application works.

Owner: Control Print Ltd. Goal: replace bought-in vision software with our own
licensed product for pharma packaging lines, then extend it to label inspection,
fill level and sorting.

---

## The two repositories

| Repo | Contains | Branch |
|---|---|---|
| [`vision`](https://github.com/shashikant1997k/vision) | the application (package `vis`) | `main` (public) |
| [`ocr-trainer`](https://github.com/shashikant1997k/ocr-trainer) | model training + the shipped ONNX models | `master` (private) |

Put them side by side — the app looks for models in `../ocr-trainer/model`:

```
camera/
  vision/
  ocr-trainer/
```

### Set up on a new PC

```bash
git clone git@github.com:shashikant1997k/vision.git
git clone git@github.com:shashikant1997k/ocr-trainer.git
cd vision && python3 -m venv .venv && .venv/bin/pip install -e ".[engine,ocr,dev]"
.venv/bin/python -m pytest tests -q        # expect 516 passed
VIS_CAMERA=file VIS_TEXT_READER=vis_ocr .venv/bin/vis-hmi
```

> **Pushing:** these repos belong to the personal GitHub account
> `shashikant1997k`. If the machine's default SSH key is a work key, pushes are
> rejected — use the right key:
> `GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_github -o IdentitiesOnly=yes" git push`

---

## Where the project actually stands

**Working and tested (516 tests green):** the inspection engine, recipes,
batches, audit trail, reports, HMI, image archive, Modbus line I/O, licensing
with capability packs and encrypted models, and the OCR/OCV stack at **97.9%
field accuracy with grammar-constrained decoding**.

**The honest caveats** (all detailed in GUIDE.md §8):
- macOS cannot run a live camera — settled, do not re-litigate it.
- Raw OCR is 38.5% field accuracy; 97.9% is *with* constrained decoding.
- `template_match` cannot verify text; use OCV.

---

## What to do next

**Blocked on the owner's decision**
1. **Live camera on a Windows or Linux PC.** Nothing runs against real product
   until this exists. macOS is ruled out. A Windows 11 VM on Apple Silicon was
   being considered — note that Apple Silicon cannot dual-boot Windows, so it
   would be a VM (ARM Windows + x64 GAPI through emulation), and the first thing
   to prove is whether the vendor viewer streams at all before building on it.
2. **Teach-flow rework** — the biggest remaining UX piece, deliberately not
   started: it needs to be designed around how the engineers actually set up a
   new product, not a guess.

**Required before a first sale**
3. Compiled build (Nuitka Commercial ~€250/yr — PyInstaller and PyArmor are both
   trivially unpacked).
4. Production Ed25519 signing keypair; compile the public key into the build and
   keep the private key offline. Only test keys exist today.
5. Executed IQ/OQ validation document pack (templates in `docs/validation/`).

**Improvements, not urgent**
6. Per-font model registry (`vis_ocr:<name>`) so a recipe can pick its font model.
7. Retrain: wider inputs (the ONNX is locked to 256 px by an export bug), export
   the unused `svtr256_v2` / `svtr384` checkpoints, and align the `INTER_AREA`
   (training) vs `INTER_LINEAR` (evaluate.py) mismatch.
8. PLC drivers beyond Modbus — OPC UA northbound, then S7 / EtherNet-IP.
9. `EdgeMatch` tool (minor — `template_match` covers most cases).

---

## Decisions already made — don't redo these

| Decision | Why |
|---|---|
| macOS is a **development-only** platform | three driver stacks (Aravis, MVS app, MVS SDK under Rosetta) all fail to hold a GigE link; the same hardware works on Windows |
| Develop against **saved images** (`VIS_CAMERA=file`) | the whole pipeline runs natively at full speed with no camera and no VM |
| **One model per print technology**, never one merged model | avoids cross-font confusion, keeps inference small, and stops every retrain from revalidating already-approved fonts |
| **Capability packs** are the unit of sale, one binary | mirrors HALCON/MERLIC/Aurora; a new market is a new pack, not a new product |
| **Constrained decoding** is the accuracy strategy | fixing character accuracy alone can't beat `0.9^n` compounding over a field |
| Encrypted models + signed licenses, **not** obfuscation alone | PyArmor/PyInstaller are publicly unpackable; the moat is the retraining service, validation docs and Control Print's field network |

The reasoning behind the commercial choices — incumbent licensing, pricing,
market — is in the productization strategy document (an artifact from the
research session; ask the owner for the link).

---

## Working agreements that produced good results

- **Measure, don't assume.** Every accuracy claim here came from running the real
  golden set. A documented 93.5% turned out to be unreproducible, and a
  long-ignored failing test turned out to be a genuine defect (`MRP00000` read as
  `MRP0000`).
- **A wrong read is worse than no read.** Pharmacode, constrained decoding and
  the I/O layer all refuse rather than guess when ambiguous.
- **Don't delete working features to look tidy.** The "duplicate" screens turned
  out to be one implementation reachable from two places.
- Run `pytest` and `ruff` before every commit; keep the suite green.
