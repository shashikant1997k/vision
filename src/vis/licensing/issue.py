"""VENDOR-SIDE tooling — issue licenses and build per-customer model packages.

Run by Control Print, never on a customer station. Requires the private signing
key, which lives in the vendor's key vault and is never distributed.

    vis-license keygen                          # once: create the vendor keypair
    vis-license fingerprint                     # on the customer PC: read the ID
    vis-license issue --customer "Sun Pharma — Halol L3" \
        --packs pharma-ocv,codes --machine <fingerprint> --expires 2027-08-06
    vis-license package --license CPL-2026-0007 --models model/*.onnx --out dist/

``package`` encrypts each model to that license, so a copied model file is inert
elsewhere and identifies the customer it was issued to.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import date
from pathlib import Path

from .license import sign_license
from .model_crypto import ENC_SUFFIX, encrypt_model
from .packs import PACKS


def _keygen(args) -> int:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )

    key = Ed25519PrivateKey.generate()
    priv = base64.b64encode(
        key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    ).decode()
    pub = base64.b64encode(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    out = Path(args.out)
    out.write_text(json.dumps({"private_key": priv, "public_key": pub}, indent=2))
    out.chmod(0o600)
    print(f"vendor keypair written to {out} (KEEP THE PRIVATE KEY SECRET — back it up offline)")
    print(f"\ncompile this into the product build (license.VENDOR_PUBLIC_KEY_B64):\n  {pub}")
    return 0


def _issue(args) -> int:
    keyfile = Path(args.keyfile)
    if not keyfile.is_file():
        print(
            f"signing key not found: {keyfile}\n"
            "Create the vendor keypair once with:  vis-license keygen --out "
            f"{keyfile}\n"
            "(or pass --keyfile pointing at the existing one). Keep the private "
            "key offline — it is what makes licenses unforgeable.",
            file=sys.stderr,
        )
        return 2
    try:
        keys = json.loads(keyfile.read_text())
    except Exception as exc:
        print(f"cannot read the signing key {keyfile}: {exc}", file=sys.stderr)
        return 2
    if "private_key" not in keys:
        print(f"{keyfile} has no 'private_key' — is it a vis-license keygen file?",
              file=sys.stderr)
        return 2
    packs = [p.strip() for p in args.packs.split(",") if p.strip()]
    unknown = [p for p in packs if p not in PACKS]
    if unknown:
        print(f"unknown pack(s): {', '.join(unknown)}\nknown: {', '.join(PACKS)}", file=sys.stderr)
        return 2
    payload = {
        "license_id": args.license_id or f"CPL-{date.today():%Y}-{args.serial:04d}",
        "customer": args.customer,
        "packs": packs,
        "machines": [m for m in (args.machine or []) if m],
        "seats": args.seats,
        "issued": date.today().isoformat(),
        "expires": args.expires,
        "grace_days": args.grace_days,
    }
    doc = sign_license(payload, keys["private_key"])
    out = Path(args.out or f"{payload['license_id']}.lic")
    out.write_text(json.dumps(doc, indent=2))
    print(f"license {payload['license_id']} -> {out}")
    print(f"  customer : {payload['customer']}")
    print(f"  packs    : {', '.join(packs)}")
    print(f"  machines : {len(payload['machines']) or 'any (not node-locked)'}")
    print(f"  expires  : {payload['expires'] or 'perpetual'}")
    return 0


def _package(args) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    master = args.master.encode("utf-8") if args.master else None
    for src in (Path(p) for p in args.models):
        if not src.is_file():
            print(f"  skip (missing): {src}", file=sys.stderr)
            continue
        blob = encrypt_model(src.read_bytes(), args.license, src.name, master)
        dst = out_dir / (src.name + ENC_SUFFIX)
        dst.write_bytes(blob)
        # sidecars travel with the model (charset, integrity manifest, metadata)
        for extra in src.parent.glob(f"{src.stem}*"):
            if extra != src and extra.suffix in (".txt", ".json", ".sha256"):
                (out_dir / extra.name).write_bytes(extra.read_bytes())
        print(f"  {src.name} -> {dst.name}  ({len(blob):,} bytes, license {args.license})")
    print(f"model package for {args.license} written to {out_dir}")
    return 0


def _fingerprint(args) -> int:
    from .fingerprint import fingerprint_report

    report = fingerprint_report()
    if args.json:            # machine-readable: JSON only, nothing else on stdout
        print(json.dumps(report))
        return 0
    if args.plain:           # just the id, for scripts/copy-paste
        print(report["fingerprint"])
        return 0
    print(f"Station : {report['hostname']}  ({report['system']})")
    print(f"Fingerprint: {report['fingerprint']}")
    print("\nGive the fingerprint to Control Print to issue this station's license.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("vis-license", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("keygen", help="create the vendor signing keypair (once)")
    k.add_argument("--out", default="vendor_keys.json")
    k.set_defaults(func=_keygen)

    f = sub.add_parser("fingerprint", help="print this machine's fingerprint")
    f.add_argument("--json", action="store_true", help="JSON only (machine-readable)")
    f.add_argument("--plain", action="store_true", help="the fingerprint alone")
    f.set_defaults(func=_fingerprint)

    i = sub.add_parser("issue", help="issue a signed license")
    i.add_argument("--keyfile", default="vendor_keys.json")
    i.add_argument("--customer", required=True)
    i.add_argument("--packs", required=True, help=f"comma-separated: {', '.join(PACKS)}")
    i.add_argument("--machine", action="append", help="fingerprint to lock to (repeatable)")
    i.add_argument("--seats", type=int, default=1)
    i.add_argument("--expires", default=None, help="YYYY-MM-DD (omit = perpetual)")
    i.add_argument("--grace-days", type=int, default=14)
    i.add_argument("--license-id", default=None)
    i.add_argument("--serial", type=int, default=1)
    i.add_argument("--out", default=None)
    i.set_defaults(func=_issue)

    p = sub.add_parser("package", help="encrypt models for one license")
    p.add_argument("--license", required=True, help="license_id the models are issued to")
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--out", default="dist/models")
    p.add_argument("--master", default=None, help="master secret (else VIS_MODEL_MASTER_KEY)")
    p.set_defaults(func=_package)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
