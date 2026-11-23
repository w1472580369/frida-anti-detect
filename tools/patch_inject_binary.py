#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binary-level anti-detection patch for frida-inject 17.19.0.

The stock frida-inject embeds its agents and the Android helper dex as
uncompressed blobs.  This tool rewrites the high-signal strings in place and
swaps the embedded helper dex for the one built from the patched sources.

It is intentionally conservative:
  * only NUL-terminated printable C strings are shortened (the tail is shifted
    left and the old tail is zero-filled);
  * tokens that live inside JavaScript source or shellcode use a same-length
    replacement so code offsets never move;
  * the embedded helper dex may be smaller than its slot; the tail is zeroed.
"""

import argparse
import hashlib
import struct
import sys

# Same-length replacements.  These occur inside embedded JavaScript source,
# shellcode, or length-prefixed D-Bus strings, so their length must not change.
SAME = [
    (b"frida:rpc", b"app:rpc01"),            # 9 -> 9
    (b"re.frida", b"app.svc0"),              # 8 -> 8
    (b"frida-zymbiote", b"svc-zymbiote01"),  # 14 -> 14
]

# NUL-terminated C strings.  Longest first.  Shortening is safe because the
# remainder of the string is shifted left and the old bytes are zeroed.
CSTR = [
    (b"/data/local/tmp/frida-helper-", b"/data/local/tmp/.svc-"),
    (b"/data/local/tmp/frida-gadget-", b"/data/local/tmp/.gadget-"),
    (b"/re/frida/", b"/app/svc/"),
    (b"re/frida/", b"app/svc/"),
    (b"/frida-helper-", b"/svc-"),
    (b"frida-generate-certificate", b"svc-gen-cert"),
    (b"frida-agent-container", b"agent-worker"),
    (b"frida-agent-emulated", b"agent-emulated"),
    (b"frida-android-helper", b"android-svc"),
    (b"frida-eternal-agent", b"svc-eternal"),
    (b"frida-helper-64", b"svc-64"),
    (b"frida-helper-32", b"svc-32"),
    (b"frida-agent-64.so", b"libhelper-64.so"),
    (b"frida-agent-32.so", b"libhelper-32.so"),
    (b"frida:stdout", b"app:stdout"),
    (b"frida:stderr", b"app:stderr"),
    (b"gum-js-loop", b"main-loop"),
    (b"gum-probe", b"svc-probe"),
    (b"frida_memfd", b"svc_memfd"),
    (b"frida_file", b"svc_file"),
    (b"27042", b"20442"),
    (b"27052", b"20452"),
]

VERIFY = [
    b"frida:rpc",
    b"re.frida",
    b"/re/frida/",
    b"frida-eternal-agent",
    b"gum-js-loop",
    b"frida-zymbiote",
    b"frida-helper-64",
    b"frida-agent-64.so",
    b"/data/local/tmp/frida-helper-",
    b"27042",
]


def cstr_sub(data, old, new):
    """Replace old inside NUL-terminated printable strings, shifting the tail."""
    if len(new) > len(old):
        raise ValueError("replacement longer than original: %r -> %r" % (old, new))
    count = 0
    start = 0
    while True:
        i = data.find(old, start)
        if i < 0:
            break
        b = i
        while b > 0 and data[b - 1] != 0:
            b -= 1
        e = i + len(old)
        while e < len(data) and data[e] != 0:
            e += 1
        s = bytes(data[b:e])
        if all(32 <= c < 127 for c in s):
            tail = bytes(data[i + len(old):e])
            repl = new + tail
            if len(repl) <= e - i:
                data[i:e] = repl + b"\0" * (e - i - len(repl))
                count += 1
        start = i + len(new)
    return count


def replace_dex(data, dex):
    """Replace the embedded helper dex, padding a smaller dex with zeroes."""
    count = 0
    start = 0
    while True:
        i = data.find(b"dex\n03", start)
        if i < 0:
            break
        if i + 0x70 > len(data):
            break
        file_size = struct.unpack_from("<I", data, i + 0x20)[0]
        header_size = struct.unpack_from("<I", data, i + 0x24)[0]
        # Only touch the Android helper dex.  A larger embedded agent dex must
        # not be overwritten by a smaller helper dex.
        marker = bytes(data[i:i + file_size])
        if (header_size == 0x70 and len(dex) <= file_size
                and b"HelperBackend" in marker):
            data[i:i + len(dex)] = dex
            data[i + len(dex):i + file_size] = b"\0" * (file_size - len(dex))
            count += 1
        else:
            sys.stderr.write(
                "warning: dex at 0x%x has file_size=%d header=%d, expected <=%d; skipped\n"
                % (i, file_size, header_size, len(dex))
            )
        start = i + 4
    return count


def md5(data):
    return hashlib.md5(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--dex", required=True, help="patched helper classes.dex (must fit the 27608-byte slot)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    data = bytearray(open(args.input, "rb").read())
    original_size = len(data)
    before = md5(data)

    dex_count = 0
    if args.dex:
        dex = open(args.dex, "rb").read()
        dex_count = replace_dex(data, dex)
        if dex_count == 0:
            raise SystemExit("error: no embedded dex matched %s; refusing to write a broken injector" % args.dex)

    for old, new in SAME:
        if len(old) != len(new):
            raise SystemExit("same-length map is broken: %r -> %r" % (old, new))
        data = bytearray(bytes(data).replace(old, new))

    cstr_counts = []
    for old, new in CSTR:
        cstr_counts.append((old, cstr_sub(data, old, new)))

    if len(data) != original_size:
        raise SystemExit("internal error: size changed")

    with open(args.output, "wb") as f:
        f.write(data)

    if not args.quiet:
        print("input : %s (%d bytes, md5 %s)" % (args.input, original_size, before))
        print("output: %s (%d bytes, md5 %s)" % (args.output, len(data), md5(data)))
        print("embedded dex replaced: %d" % dex_count)
        for old, n in cstr_counts:
            if n:
                print("cstr %-36s %d" % (old.decode("ascii", "replace"), n))
        print("verification:")
        text = bytes(data)
        for pat in VERIFY:
            print("  %-36s %d" % (pat.decode("ascii", "replace"), text.count(pat)))


if __name__ == "__main__":
    main()
