#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Replace the embedded Android helper dex inside a frida-server / frida-inject
binary without touching any other bytes.

The helper dex is identified by the presence of the HelperBackend class marker;
the replacement may be smaller than the original slot (the tail is zeroed).
"""
import argparse
import hashlib
import struct
import sys


def md5(data):
    return hashlib.md5(data).hexdigest()


def replace_helper_dex(data, dex):
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
        marker = bytes(data[i:i + file_size])
        if (header_size == 0x70 and len(dex) <= file_size
                and b"HelperBackend" in marker):
            data[i:i + len(dex)] = dex
            data[i + len(dex):i + file_size] = b"\0" * (file_size - len(dex))
            count += 1
            print("replaced helper dex at 0x%x (%d -> %d bytes, slot %d)"
                  % (i, file_size, len(dex), file_size))
        start = i + 4
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--dex", required=True)
    args = ap.parse_args()

    data = bytearray(open(args.input, "rb").read())
    dex = open(args.dex, "rb").read()
    before = md5(data)
    n = replace_helper_dex(data, dex)
    if n == 0:
        sys.exit("error: no embedded helper dex matched; refusing to write")
    with open(args.output, "wb") as f:
        f.write(data)
    print("input : %s (%d bytes, md5 %s)" % (args.input, len(data), before))
    print("output: %s (%d bytes, md5 %s)" % (args.output, len(data), md5(data)))
    print("embedded helper dex replaced: %d" % n)


if __name__ == "__main__":
    main()
