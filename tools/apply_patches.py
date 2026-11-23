#!/usr/bin/env python3
"""
Apply every patch in patches/series to the freshly cloned frida tree.

Each series line looks like:
    NN-name.patch\t[gum|core] path/to/file

- gum  patches apply inside frida/subprojects/frida-gum
- core patches apply inside frida/subprojects/frida-core

Patches are standard unified diffs (including GIT binary patches),
applied with `git apply`. Idempotent: already-applied patches are skipped.
"""
import subprocess, sys, pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]
PATCHES = BASE / "patches"
FRIDA = BASE / "frida"

REPO_FOR_PREFIX = {
    "gum": FRIDA / "subprojects" / "frida-gum",
    "core": FRIDA / "subprojects" / "frida-core",
}

def run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)

def main():
    series = PATCHES / "series"
    if not series.exists():
        sys.exit(f"missing {series}")

    if not FRIDA.exists():
        sys.exit(f"frida tree not found at {FRIDA}")

    applied = skipped = failed = 0
    for raw in series.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        patch_name, _, meta = raw.partition("\t")
        meta = meta.strip()
        # meta like "[core] src/..."
        if not meta.startswith("["):
            sys.exit(f"bad series line: {raw!r}")
        prefix = meta[1:meta.index("]")]
        repo = REPO_FOR_PREFIX.get(prefix)
        if repo is None:
            sys.exit(f"unknown prefix {prefix!r} in {raw!r}")
        patch_file = PATCHES / patch_name

        # First try a strict apply.
        check = run(["git", "apply", "--check", "-v", str(patch_file)], repo)
        if check.returncode == 0:
            do = run(["git", "apply", "-v", str(patch_file)], repo)
            if do.returncode != 0:
                print(f"[FAIL] {patch_name}\n{do.stderr}")
                failed += 1
                continue
            print(f"[applied] {patch_name}")
            applied += 1
            continue

        # Already applied? Use reverse-check to detect.
        rev = run(["git", "apply", "--check", "--reverse", str(patch_file)], repo)
        if rev.returncode == 0:
            print(f"[skip] {patch_name} (already applied)")
            skipped += 1
            continue

        print(f"[FAIL] {patch_name}\n-- forward check --\n{check.stderr}\n"
              f"-- reverse check --\n{rev.stderr}")
        failed += 1

    print(f"\nresult: {applied} applied, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
