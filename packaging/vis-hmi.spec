# PyInstaller spec for the Windows line-PC build.
#
#   pip install pyinstaller
#   pyinstaller packaging/vis-hmi.spec --noconfirm
#   -> dist/vis-hmi/            <- copy this WHOLE FOLDER to the line PC
#
# This is a ONEDIR build on purpose. The result is a folder containing
# vis-hmi.exe plus every DLL and data file it needs — copy it to the machine and
# run it; no Python, no pip, no internet on the line PC. It is also the right
# choice for a validated installation: every file is visible and can be
# checksummed for IQ, and startup is much faster than a onefile build (which
# unpacks itself to a temp folder on every launch).
#
# What is deliberately NOT bundled:
#   - the GenTL producer (.cti) — vendor-licensed, installed with the camera SDK
#     and located at runtime via VIS_GENTL_CTI / the site config
#   - the trained models — shipped per customer (and encrypted per licence by
#     `vis-license package`), so they live beside the exe in model\ and can be
#     replaced without a rebuild
#   - the licence file — issued per station
#
# See docs/deployment/installation.md for the install and validation steps.

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

datas = []
binaries = []
hiddenimports = []

# --- the app's own package + its dist-info -----------------------------------
# collect_submodules picks up modules reached only through a registry/string, and
# the metadata is what `--selftest` reports as the version (the IQ record).
hiddenimports += collect_submodules("vis")
try:
    datas += copy_metadata("vision-inspection")
except Exception:
    pass

# --- optional OCR engine (bundled models live inside the wheel) -------------
try:
    datas += collect_data_files("rapidocr_onnxruntime")
    hiddenimports += collect_submodules("rapidocr_onnxruntime")
except Exception:
    pass

# --- onnxruntime: compiled providers are easy for PyInstaller to miss -------
try:
    binaries += collect_dynamic_libs("onnxruntime")
    datas += collect_data_files("onnxruntime")
except Exception:
    pass

# --- GigE acquisition: harvesters + the genicam SWIG bindings ---------------
# genicam ships compiled .pyd/.dll files that PyInstaller does not follow from
# the import graph. Without these the build has no GenTL path at all and falls
# back to the simulator on a line PC — which build_windows.py now fails on.
for _pkg in ("harvesters", "genicam"):
    try:
        hiddenimports += collect_submodules(_pkg)
        binaries += collect_dynamic_libs(_pkg)
        datas += collect_data_files(_pkg)
    except Exception:
        pass

# --- EVERY module that registers something by import side effect ------------
# Missing one of these builds an app whose tool/reader simply is not there, and
# it fails at run time on the line rather than at build time here. Keep this
# list in step with vis/tools/__init__.py and vis/tools/readers.py.
hiddenimports += [
    # inspection tools (registered via @register on import)
    "vis.tools.code_verify",
    "vis.tools.general",
    "vis.tools.ocr",
    "vis.tools.ocv_font",
    "vis.tools.print_inspect",
    "vis.tools.stub_ocv",
    # readers + the OCR/OCV engine
    "vis.tools.readers",
    "vis.tools.vis_ocr_reader",
    "vis.tools.constrained_decode",
    "vis.tools.line_detector",
    "vis.tools.pharmacode",
    "vis.tools.model_integrity",
    "vis.tools.ocv_score",
    "vis.tools.print_quality",
    "vis.tools.grading",
    "vis.tools.gs1",
    "vis.tools.transform",
    # licensing (signed licences + encrypted models) — needs cryptography
    "vis.licensing",
    "vis.licensing.license",
    "vis.licensing.fingerprint",
    "vis.licensing.packs",
    "vis.licensing.model_crypto",
    "cryptography",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.primitives.ciphers.aead",
    "cryptography.hazmat.primitives.kdf.hkdf",
    # camera backends available on Windows
    "vis.camera.genicam",
    "vis.camera.hikrobot",
    "vis.camera.file_source",
    # line I/O
    "vis.io.digital_io",
    "vis.io.encoder_reject",
    # database migrations
    "vis.db.models",
]

# SQLAlchemy picks its dialect by string at run time
hiddenimports += collect_submodules("sqlalchemy.dialects.sqlite")

block_cipher = None

a = Analysis(
    ["vis_hmi_entry.py"],   # NOT src/vis/hmi/app.py — see that file's docstring
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # keep the build lean: these pull in large trees we never use
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "torch"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vis-hmi",
    console=False,          # GUI app: no console window on the line PC
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="vis-hmi")
