#!/usr/bin/env python3
"""Generate numbered .patch files, one per changed file (robust split)."""
import subprocess, pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]
FRIDA = BASE / "frida"
OUT = BASE / "patches"
OUT.mkdir(exist_ok=True)
# clear stale
for f in OUT.glob("*.patch"):
            try: f.unlink()
            except FileNotFoundError: pass
if (OUT/"series").exists(): (OUT/"series").unlink()

def git(repo, *args):
    return subprocess.run(["git","-C",str(repo),*args], capture_output=True, text=True).stdout

jobs = [
    (FRIDA/"subprojects/frida-gum", "gum", "gum"),
    (FRIDA/"subprojects/frida-core", "core", "core"),
]
index=[]; n=1
for repo,prefix,label in jobs:
    # changed tracked-new paths
    status = git(repo,"status","--porcelain")
    paths=[]
    for line in status.splitlines():
        if not line.strip(): continue
        st=line[0:2]
        p=line[3:].strip()
        if st.startswith("??"):   # intents-to-add (new)
            paths.append((p,"new"))
        else:
            paths.append((p,None))
    # unique
    seen=set(); import collections
    for p,kind in paths:
        # normalize rename 'a -> b': status porcelain for rename shows 'R  old -> new'
        import re
        m=re.match(r"(.+) -> (.+)$",p)
        target=m.group(2) if m else p
        if target in seen: continue
        seen.add(target)
        diff=git(repo,"diff","--binary","--no-color","--",target)
        if not diff.strip():
            # maybe new (intent-to-add) not shown by diff; use --no-index vs /dev/null
            diff=git(repo,"diff","--no-color","--no-index","/dev/null",target)
        if not diff.strip() or "diff --git" not in diff:
            continue
        safe=target.replace("/","_")
        name=f"{n:02d}-{label}_{safe}.patch"
        (OUT/name).write_text(diff if diff.endswith("\n") else diff+"\n",encoding="utf-8")
        index.append((name,prefix,target)); n+=1
with (OUT/"series").open("w",encoding="utf-8") as f:
    for name,prefix,target in index:
        f.write(f"{name}\t[{prefix}] {target}\n")
print(f"Generated {len(index)} patches")
for name,prefix,target in index: print(f"  {name}  ({prefix}:{target})")
