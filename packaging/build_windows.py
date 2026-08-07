#!/usr/bin/env python3
"""Build the Windows distribution folder, and prove it is complete.

    python packaging/build_windows.py            # build + verify
    python packaging/build_windows.py --verify-only dist/vis-hmi

Produces ``dist/vis-hmi/`` — copy that whole folder to the line PC and run
``vis-hmi.exe``. No Python, no pip, no internet needed there.

The verification step exists because of how PyInstaller fails: a tool or reader
that is registered by import side effect can be silently dropped from the
bundle, and you only find out when an operator runs that inspection on a live
line. Here we start the frozen app and make it *list what it actually has*, so a
missing tool fails the build instead of the batch.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "vis-hmi.spec"
DIST = ROOT / "dist" / "vis-hmi"

# What a usable build must contain. Checked against the frozen app itself.
REQUIRED_TOOLS = [
    "code_verify", "color_check", "measure", "ocv_font", "ocv_stub",
    "ocv_text", "presence", "print_inspect", "template_match",
]
REQUIRED_READERS = {"text": ["builtin", "vis_ocr"], "code": ["builtin", "pharmacode"]}
# Without harvesters bundled there is no GenTL path, so the app quietly runs the
# SIMULATOR on a line PC with a real camera attached. Build with the `camera`
# extra installed.
REQUIRED_CAMERA_BACKENDS = ["gentl"]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, **kw)


def build() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is not installed:  pip install pyinstaller")
    for stale in (ROOT / "build", DIST):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)
    result = run([sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm",
                  "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build")])
    if result.returncode != 0:
        sys.exit("PyInstaller failed — see the output above.")


def verify(dist: Path) -> list[str]:
    """Ask the FROZEN app what it can do. Import-time registration is exactly
    what PyInstaller drops silently, so this must run the built exe, not this
    interpreter."""
    problems: list[str] = []
    exe = dist / ("vis-hmi.exe" if sys.platform == "win32" else "vis-hmi")
    if not exe.exists():
        return [f"executable missing: {exe}"]

    out = subprocess.run([str(exe), "--selftest"], capture_output=True, text=True, timeout=180)
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("VERIFY")), None)
    if line is None:
        return ["the frozen app did not report its capabilities — run it by hand:\n"
                f"    {exe} --selftest\n"
                f"  stdout: {out.stdout[-300:]}\n  stderr: {out.stderr[-300:]}"]

    got = json.loads(line[len("VERIFY"):])
    for key in ("tools_error", "readers_error", "license_error"):
        if got.get(key):
            problems.append(f"{key.replace('_', ' ')}: {got[key]}")
    for tool in REQUIRED_TOOLS:
        if tool not in got.get("tools", []):
            problems.append(f"tool '{tool}' is missing from the build "
                            "(add it to hiddenimports in vis-hmi.spec)")
    for kind, names in REQUIRED_READERS.items():
        available = got.get(f"{kind}_readers", [])
        for name in names:
            if name not in available:
                problems.append(f"{kind} reader '{name}' is missing from the build")
    for backend in REQUIRED_CAMERA_BACKENDS:
        if backend not in got.get("camera_backends", []):
            problems.append(
                f"camera backend '{backend}' is missing — this build cannot open a "
                "real camera and would fall back to the simulator. Install the extra "
                'first:  pip install -e ".[camera]"'
            )
    if not got.get("frozen"):
        problems.append("the executable does not report itself as frozen — "
                        "is this really a PyInstaller build?")
    print(f"  reported: {len(got.get('tools', []))} tools, "
          f"text readers {got.get('text_readers')}, code readers {got.get('code_readers')}, "
          f"cameras {got.get('camera_backends')}")
    return problems


def write_starter_config(dist: Path) -> None:
    """Ship an editable config.json beside the exe, with DEFAULT values only.

    The app would write one on first run anyway, but a plant engineer should be
    able to set the camera and I/O BEFORE the first launch. Never copy the build
    machine's own config — its camera serial and GenTL path are wrong for every
    other station."""
    sys.path.insert(0, str(ROOT / "src"))
    from vis.config import DEFAULTS

    target = dist / "config.json"
    target.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")
    print(f"  wrote {target.name} (defaults — edit on the line PC)")


def write_manifest(dist: Path) -> Path:
    """SHA-256 of every shipped file.

    An IQ has to state what was installed, and "the folder off the build PC" is
    not a statement anyone can check a year later. This is, and it also tells an
    upgrade exactly which files changed.
    """
    import hashlib

    lines = []
    manifest = dist / "SHA256SUMS.txt"
    for f in sorted(dist.rglob("*")):
        if not f.is_file() or f == manifest:
            continue
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {f.relative_to(dist).as_posix()}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {manifest.name} ({len(lines)} files)")
    return manifest


def report_layout(dist: Path) -> None:
    size = sum(f.stat().st_size for f in dist.rglob("*") if f.is_file()) / 1e6
    print(f"\n  folder : {dist}")
    print(f"  size   : {size:.0f} MB, {sum(1 for _ in dist.rglob('*') if _.is_file())} files")
    has_models = (dist / "model").is_dir()
    # not an f-string expression: a backslash inside one is Python 3.12+ only,
    # and this project supports 3.11
    staged = "staged in model\\ (plaintext)" if has_models else "NOT staged"
    print("\n  models : " + staged)
    print("\n  Copy this whole folder to the line PC and run vis-hmi.exe.")
    print("  Install the camera vendor's GenTL producer there separately —")
    print("  it is vendor-licensed and cannot be bundled.")
    print("\n  Before selling this to a customer, add beside vis-hmi.exe:")
    print("    vision.lic       the licence issued for that station")
    if has_models:
        print("    model\\           re-staged with `vis-license package` so the")
        print("                     models are encrypted to that licence")
    print("  See INSTALL.txt in the folder and docs/deployment/build-and-install.md.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify-only", metavar="DIST", help="check an existing build folder")
    ap.add_argument("--no-models", action="store_true",
                    help="do not stage the trained models (ship model\\ separately, "
                         "e.g. encrypted per licence by `vis-license package`)")
    args = ap.parse_args()

    dist = Path(args.verify_only) if args.verify_only else DIST
    if not args.verify_only:
        print("Building the Windows distribution folder…")
        build()
        if not args.no_models:
            # Must happen BEFORE verify: the vis_ocr reader registers itself only
            # when it can find a model, so verification of an unstaged build
            # would (correctly) report that reader as missing.
            print("\nStaging the trained models…")
            from stage_models import DEFAULT_MODELS, stage

            stage(DEFAULT_MODELS, dist)

        install_note = ROOT / "packaging" / "INSTALL.txt"
        if install_note.is_file():
            shutil.copy2(install_note, dist / "INSTALL.txt")
        write_starter_config(dist)

    print("\nVerifying the build actually contains every tool and reader…")
    problems = verify(dist)
    if problems:
        print("\n  BUILD IS INCOMPLETE:")
        for p in problems:
            print(f"    - {p}")
        print("\n  Fix the spec and rebuild. Shipping this would fail on the line,\n"
              "  not here.")
        return 1
    print("  every required tool and reader is present ✓")
    write_manifest(dist)
    report_layout(dist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
