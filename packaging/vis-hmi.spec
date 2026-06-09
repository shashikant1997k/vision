# PyInstaller spec for the Qt desktop HMI (Windows build).
#
# Build (on Windows, in the project venv with [hmi] + licensed extras installed):
#   pip install pyinstaller
#   pyinstaller packaging/vis-hmi.spec
#   -> dist/vis-hmi/vis-hmi.exe
#
# Notes / caveats:
#   - rapidocr-onnxruntime bundles ONNX models as data files; collect them or the
#     OCR tool will fail at runtime. We use collect_data_files for them below.
#   - zxing-cpp (zxingcpp), onnxruntime, and PySide6 ship compiled extensions;
#     PyInstaller's hooks usually handle them, but verify on the target machine.
#   - The GenTL producer (.cti) is NOT bundled — it is installed separately and
#     located via the VIS_GENTL_CTI env var (vendor licensing).

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
hiddenimports = []

# OCR models + package data (only if the [ocr] extra is installed)
try:
    datas += collect_data_files("rapidocr_onnxruntime")
    hiddenimports += collect_submodules("rapidocr_onnxruntime")
except Exception:
    pass

# Ensure our inspection tools are imported (registered via side effect)
hiddenimports += [
    "vis.tools.code_verify",
    "vis.tools.ocr",
    "vis.tools.ocv_font",
    "vis.tools.general",
    "vis.tools.readers",
    "vis.tools.stub_ocv",
]

block_cipher = None

a = Analysis(
    ["../src/vis/hmi/app.py"],
    pathex=["../src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vis-hmi",
    console=False,  # GUI app
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="vis-hmi")
