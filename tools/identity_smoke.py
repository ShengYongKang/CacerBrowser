"""Phase 1 end-to-end smoke: create -> launch -> verify presentation.

Creates a real identity via core.identity, maps it through
core.launcher.build_launch_options, launches the actual Camoufox engine
(persistent context, headed), and asserts that what the page sees matches
the identity file. Exit 0 = smoke passed.

Usage:
  python tools/identity_smoke.py [--os macos] [--country FR]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.identity import create_identity, Identity  # noqa: E402
from core.launcher import build_launch_options  # noqa: E402
from tools.fp_probe import PROBE_JS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--os", default="macos")
    ap.add_argument("--country", default=None)
    ap.add_argument("--profiles", default="data/smoke-profiles")
    args = ap.parse_args()

    print("[smoke] creating identity...")
    ident = create_identity(
        f"smoke-{args.os}", os=args.os, country=args.country,
        profiles_dir=Path(args.profiles),
    )
    print(f"[smoke] identity {ident.id}: {ident.engine_os} / {ident.geo.country} / "
          f"{ident.geo.locale} / {ident.geo.timezone}")
    if ident.warnings():
        print(f"[smoke] warnings: {ident.warnings()}")

    opts = build_launch_options(ident, profiles_dir=Path(args.profiles))
    print(f"[smoke] profile dir: {opts['user_data_dir']}")

    from camoufox.sync_api import Camoufox

    print("[smoke] launching engine (headed, persistent)...")
    with Camoufox(**opts) as browser:
        page = browser.new_page()
        page.goto("about:blank")
        data = page.evaluate("mw:" + PROBE_JS)
        page.screenshot(path=str(Path(args.profiles) / ident.id / "smoke.png"))

    fp_nav = ident.fingerprint["navigator"]
    fp_screen = ident.fingerprint["screen"]
    checks = [
        ("userAgent",
         data["userAgent"] == fp_nav["userAgent"].replace("146.0", "156.0"),
         f"{data['userAgent']}"),
        ("platform", data["platform"] == fp_nav["platform"], data["platform"]),
        ("oscpu", data["oscpu"] == fp_nav["oscpu"], data["oscpu"]),
        ("cores", data["hardwareConcurrency"] == ident.launcher.hardwareConcurrency,
         str(data["hardwareConcurrency"])),
        ("maxTouchPoints", data["maxTouchPoints"] == ident.launcher.maxTouchPoints,
         str(data["maxTouchPoints"])),
        ("timezone", data["timezone"] == ident.geo.timezone, data["timezone"]),
        ("language", data["language"] == opts["locale"][0], data["language"]),
        ("locale",
         data["locale"].split("-")[0].lower()
         == ident.geo.languages[0].split("-")[0].lower(),
         data["locale"]),
        ("languages", list(data["languages"]) == opts["locale"],
         str(data["languages"])),
        ("screen.width", data["screen"]["width"] == fp_screen["width"],
         str(data["screen"]["width"])),
        ("screen.height", data["screen"]["height"] == fp_screen["height"],
         str(data["screen"]["height"])),
        ("webglRenderer is not the host GPU",
         "Apple M" in data["webgl"]["unmaskedRenderer"]
         or "ANGLE" in data["webgl"]["unmaskedRenderer"],
         data["webgl"]["unmaskedRenderer"]),
    ]

    failures = [f"{name}: presented {detail}" for name, ok, detail in checks if not ok]
    for name, ok, detail in checks:
        print(f"[smoke] {'PASS' if ok else 'FAIL'}  {name} = {detail}")

    # profile dir must contain a real persistent profile
    profile_files = list((Path(args.profiles) / ident.id / "profile").rglob("*"))
    print(f"[smoke] profile entries: {len(profile_files)}")

    if failures:
        print("\n[smoke] FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\n[smoke] PASS: identity -> launcher -> engine presentation all match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
