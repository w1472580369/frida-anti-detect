#!/usr/bin/env python3
"""
Rebuild src/android-helper/helper.dex from the (renamed) Java sources.

Self-contained: downloads R8 (provides d8) on demand. Requires a JDK with
javac (set JAVA7_HOME / JAVA_HOME) and an android.jar (--android-jar).

Usage:
  python3 build_helper_dex.py --frida /path/to/frida --android-jar /path/android.jar
  python3 build_helper_dex.py --frida /path/to/frida --check   # verify current dex
"""
import argparse, os, pathlib, subprocess, sys, urllib.request

R8_URL = "https://dl.google.com/dl/android/maven2/com/android/tools/r8/8.13.24/r8-8.13.24.jar"
JAVA_REL = pathlib.Path("src/android-helper/app/svc")
DEX_REL = pathlib.Path("src/android-helper/helper.dex")
MIN_API = "26"

def find_java():
    for key in ("JAVA_HOME",):
        v = os.environ.get(key)
        if v and (pathlib.Path(v) / "bin" / "javac").exists():
            return pathlib.Path(v)
    # fallback: javac on PATH
    from shutil import which
    jc = which("javac")
    if jc:
        return pathlib.Path(jc).resolve().parents[1]
    return None

def ensure_r8(tooldir):
    tooldir.mkdir(parents=True, exist_ok=True)
    r8 = tooldir / "r8.jar"
    if r8.exists() and r8.stat().st_size > 1_000_000:
        return r8
    print(f"[*] downloading r8 from {R8_URL}")
    urllib.request.urlretrieve(R8_URL, r8)
    return r8

def run(cmd):
    print("    $", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frida", required=True)
    ap.add_argument("--android-jar")
    ap.add_argument("--check", action="store_true",
                    help="only verify the checked-in helper.dex has no 'frida' strings")
    ap.add_argument("--tooldir", default=None)
    args = ap.parse_args()

    frida = pathlib.Path(args.frida).resolve()
    # Accept either the frida checkout root or subprojects/frida-core.
    core = frida if (frida / "src" / "android-helper").is_dir() else (frida / "subprojects" / "frida-core")
    dex = core / DEX_REL

    if args.check:
        data = dex.read_bytes()
        if b"frida" in data or b"re/frida" in data:
            print("[check] helper.dex still contains frida markers")
            sys.exit(1)
        print("[check] helper.dex is clean")
        return

    if not args.android_jar:
        sys.exit("--android-jar is required unless --check")
    android_jar = pathlib.Path(args.android_jar).resolve()
    if not android_jar.exists():
        sys.exit(f"android.jar not found: {android_jar}")

    java = find_java()
    if java is None:
        sys.exit("no JDK with javac found (set JAVA_HOME)")

    tooldir = pathlib.Path(args.tooldir) if args.tooldir else (frida.parent / "toolchain")
    r8 = ensure_r8(tooldir)

    srcdir = core / JAVA_REL
    sources = sorted(srcdir.glob("*.java"))
    if not sources:
        sys.exit(f"no java sources under {srcdir}")

    import tempfile
    with tempfile.TemporaryDirectory(dir="/tmp") as td:
        td = pathlib.Path(td)
        classes = td / "classes"
        classes.mkdir()
        outdexdir = td / "dex"
        outdexdir.mkdir()

        run([java/"bin/javac",
             "-source", "8", "-target", "8", "-nowarn",
             "-bootclasspath", android_jar,
             "-cp", android_jar,
             "-d", classes,
             *sources])

        classfiles = sorted(classes.rglob("*.class"))
        run([java/"bin/java", "-cp", r8, "com.android.tools.r8.D8",
             "--release",
             "--min-api", MIN_API,
             "--classpath", android_jar,
             "--output", outdexdir,
             *classfiles])

        produced = outdexdir / "classes.dex"
        blob = produced.read_bytes()
        if b"frida" in blob:
            sys.exit("newly built dex unexpectedly contains 'frida'")
        dex.parent.mkdir(parents=True, exist_ok=True)
        dex.write_bytes(blob)
        print(f"[ok] wrote {dex} ({len(blob)} bytes)")

if __name__ == "__main__":
    main()
