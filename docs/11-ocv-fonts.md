# OCV font library — industrial print types & fonts

Industrial coding is printed in a small set of known technologies and font
families. OCV (verification) reads "by defined pixels": each character is
matched against a **trained font model** (per print technology + size), the way
Cognex In-Sight's *OCV/OCR Font Training* dialog and Keyence's registered-
character dictionaries work. This file records the landscape our font library
models, from vendor/industry sources.

## Print technologies (what makes the glyphs)

| Type | How it prints | Glyph character | Typical char height |
|---|---|---|---|
| **CIJ** (continuous inkjet) | deflected ink drops | **dot matrix** — 5×5, 7×5, 9×7, 12×12, 16×10, 24×18 grids | 0.8 – 14 mm |
| **TIJ** (thermal inkjet) | 300–600 dpi cartridge | near-solid strokes, slight banding | 2 – 12.7 mm |
| **DOD** (large-character valve jet) | big individual dots | coarse dot matrix (7, 16, 32 dots) | 12 – 70 mm |
| **Laser** (CO₂/fiber) | engraved/annealed vector strokes | solid thin strokes, low contrast | 1 – 10 mm |
| **TTO** (thermal transfer overprint) | ribbon on film | solid, crisp (TTF-like) | any (300 dpi) |
| **Digital/offset (pre-printed)** | plate/digital press | solid, high quality | any |

Key consequences for reading:
- **CIJ/DOD**: characters are separated dots — generic OCR fails; the reader must
  dot-connect (morphological close) before/while matching. Matrix density (5×5 …
  24×18) changes the look of the *same* character → each matrix is its own font.
- **Laser**: thin strokes, often low contrast on foil — contrast normalisation
  matters more than dot handling.
- **TIJ/TTO/digital**: close to solid type — template match works directly.

## Standard machine-readable fonts
- **OCR-A** (ANSI X3.17 / ISO 1073-1) — blocky, designed for machine reading.
- **OCR-B** (ISO 1073-2) — cleaner, used on pharma cartons (incl. EU serialization).
- **SEMI** (M12/M13) — wafer/electronics marking.
- Vendor coder fonts: Videojet/Domino/Markem-Imaje/Linx each ship their own dot
  matrices (e.g. 5×5 "high speed", 7×5 standard, 9×7 quality, 16×10 bold,
  two-line stacks) — these are what customers actually print.

## How our library maps this
- A **FontModel** = name + print type + dot-connect kernel + per-character glyph
  templates (multiple samples per character; matching is best-of-list NCC).
- **Built-in starter fonts** (generated): "Dot matrix 5×7 (CIJ)", "Dot matrix
  9×7 (CIJ quality)", "Solid print (TIJ/TTO/laser)". Starters bootstrap demos;
  real deployments **train the customer's actual coder font from line images**
  (Add sample → annotate characters → saved into the model). More samples per
  character = retraining, exactly like the Cognex/Keyence flow.
- The teach screen's **Verify Text (OCV)** inspection selects a font; the glyphs
  are embedded into the recipe (self-contained, survives export/import; changing
  a font later does NOT silently change approved recipes — a GMP property).

Sources: [EBS CIJ](https://ebs-inkjet.de/en/products/cij/),
[Videojet CIJ](https://www.propac.com/packaging-equipment/printing-date-coding/videojet/continuous-inkjet/),
[Markem-Imaje CIJ](https://www.markem-imaje.com/products/continuous-inkjet-printers),
[Cognex OCV/OCR Font Training](https://support.cognex.com/docs/is_590/web/EN/ise/Content/Dialogs/OCV-OCRFontTrainingDialog.htm),
[Keyence OCR/OCV](https://www.keyence.com/products/vision/vision-sys/applications/ocr-verification-and-character-inspection.jsp),
[Clearview: OCR for machine vision](https://clearview-imaging.com/blogs/news/introduction-to-optical-character-recognition-for-machine-vision),
[AIA OCR/OCV insights](https://www.automate.org/vision/industry-insights/the-latest-on-ocr-ocv-machine-vision-applications).

## Research-validated architecture (deep-research pass, 2026-06)

A 106-agent research sweep (Cognex OCVMax/CVL docs, Keyence, Zebra Aurora,
US 5,212,741, AIA) adversarially verified 23 claims. What it confirmed and what
we implemented from it:

| Verified finding | Status in our engine |
|---|---|
| OCV (verify against expected) and OCR (read) are architecturally distinct; pharma verification should be OCV-first | ✅ `verify_text` per-position vs expected; OCR is the read/fallback path |
| Whitespace segmentation structurally fails on dot print; dot-connect must happen at GREY level (spatial average, kernel ∝ dot pitch) before binarization | ✅ `_prepare_binary`: grey blur (kernel = font dot_kernel) → contrast stretch → binarize; per-print-type kernel in the font model |
| OCVMax decision gate = accept threshold + confusion check + top-1-minus-top-2 margin | ✅ `verify_text` margin gate (`char_margin`, default 0.05) |
| Per-character threshold tuning is the robustness lever for hard substrates | ✅ `min_char_score` / `char_margin` per tool config |
| Floors: chars ≥ ~20×15 px and ≥ ~30 grey levels of contrast, else fix optics/lighting | ✅ teach-time warnings (`print_quality`) shown on Test |
| Charset/lexicon constraining improves accuracy (all vendors) | ✅ per-field Charset (digits/letters/alnum/custom) on the OCV tool |
| Multi-exemplar registration per character; augment with small rotation/shear/dilate/erode (excess degrades) | ✅ best-of-list NCC + auto-augmentation on training (±3°, dilate/erode) |
| Commercial trend: pretrained DL readers (Zebra Aurora DL-OCR, Keyence AI-OCR) with per-char confidence gates complement classical OCV | ✅ reader seam ready for a licensed engine; confidence gating present |

Open (needs hands-on benchmarking, no verified external data): which ONNX
recognizer (PP-OCRv5/SVTR/PARSeq) fine-tunes best on dot-matrix fonts — use
`vis-ocrbench` golden sets to decide empirically; specular/blister + laser-on-
glass preprocessing recipes; photometric stereo for embossed/dot-peen.
