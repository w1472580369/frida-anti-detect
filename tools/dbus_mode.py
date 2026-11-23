#!/usr/bin/env python3
"""
Switch the Frida host-session D-Bus protocol between official and stealth names.

  --mode compat   : re.frida.* interfaces + /re/frida/* object paths
                    (official frida-tools / frida Python bindings can connect)
  --mode stealth  : app.svc.* interfaces + /app/svc/* object paths
                    (requires the matching client wheel built by this repo)

Only lib/base/session.vala is touched. The Android helper package name and all
other anti-detection changes (paths, thread names, ports, RPC marker) stay as-is.
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SESSION = ROOT / "frida" / "subprojects" / "frida-core" / "lib" / "base" / "session.vala"

PAIRS = [
    ("re.frida.", "app.svc."),
    ("/re/frida/", "/app/svc/"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["compat", "stealth"], required=True)
    ap.add_argument("--frida", default=str(ROOT / "frida"), help="frida source root")
    args = ap.parse_args()

    session = pathlib.Path(args.frida) / "subprojects" / "frida-core" / "lib" / "base" / "session.vala"
    if not session.exists():
        sys.exit(f"[FAIL] missing {session}")

    text = session.read_text(encoding="utf-8")
    if args.mode == "compat":
        src, dst = "app.svc.", "re.frida."
        src_path, dst_path = "/app/svc/", "/re/frida/"
    else:
        src, dst = "re.frida.", "app.svc."
        src_path, dst_path = "/re/frida/", "/app/svc/"

    n1 = text.count(src)
    n2 = text.count(src_path)
    if n1 == 0 and n2 == 0:
        print(f"[ok] already in {args.mode} mode")
        return

    text = text.replace(src, dst).replace(src_path, dst_path)
    session.write_text(text, encoding="utf-8")
    print(f"[ok] {args.mode}: {n1} interface name(s), {n2} object path(s) -> {dst}")


if __name__ == "__main__":
    main()
