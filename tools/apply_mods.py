#!/usr/bin/env python3
"""
Apply anti-detection modifications to the Frida source tree.
Run inside the frida root (after submodules are checked out).
Idempotent: each replacement asserts expected occurrence count.
"""
import sys, pathlib, shutil

ROOT = pathlib.Path(__file__).resolve().parents[1] / "frida"

def locate(*candidates):
    """Return the first existing path among candidates (supports renamed dirs)."""
    for c in candidates:
        p = ROOT / c
        if p.exists():
            return p
    sys.exit(f"[FAIL] none of these exist: {candidates}")

def relocate(src_rel, dst_rel):
    """Move a file/dir from src to dst (idempotent)."""
    src = ROOT / src_rel
    dst = ROOT / dst_rel
    if dst.exists():
        if src.exists():
            if src.is_dir():
                shutil.rmtree(src)
            else:
                src.unlink()
        print(f"[ok] relocate {src_rel} -> {dst_rel} (already present)")
        return
    if not src.exists():
        sys.exit(f"[FAIL] relocate source missing: {src_rel}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    print(f"[ok] relocate {src_rel} -> {dst_rel}")

def patch(rel, edits, alt_rels=None):
    p = locate(rel, *(alt_rels or []))
    src = p.read_text(encoding="utf-8")
    applied_here = 0
    for old, new, count in edits:
        n_old = src.count(old)
        n_new = src.count(new)
        if n_old == count:
            src = src.replace(old, new)
            applied_here += 1
        elif n_old == 0 and n_new >= 1:
            pass  # edit already applied in a previous run
        else:
            sys.exit(f"[FAIL] {p.relative_to(ROOT)}: expected {count} occurrence(s) of {old!r} "
                     f"(found {n_old}); new text already present {n_new} time(s)")
    p.write_text(src, encoding="utf-8")
    print(f"[ok] {p.relative_to(ROOT)} ({applied_here} new / {len(edits) - applied_here} already applied)")

# ---------------------------------------------------------------- frida-gum
patch("subprojects/frida-gum/bindings/gumjs/gumscriptscheduler.c", [
    ('g_thread_new ("gum-js-loop",',
     'g_thread_new ("main-loop",', 1),
])

patch("subprojects/frida-gum/bindings/gumjs/guminspectorserver.c", [
    ('json_builder_add_string_value (builder, "Frida Agent");',
     'json_builder_add_string_value (builder, "System");', 1),
    ('json_builder_add_string_value (builder, "Frida/v" FRIDA_VERSION);',
     'json_builder_add_string_value (builder, "System/v" FRIDA_VERSION);', 1),
])

patch("subprojects/frida-gum/bindings/gumjs/gummemoryvfs.c", [
    ('self->name = g_strdup_printf ("gum-%d",',
     'self->name = g_strdup_printf ("shm-%d",', 1),
])

patch("subprojects/frida-gum/gum/gum.c", [
    ('g_set_prgname ("frida");',
     'g_set_prgname ("system");', 1),
])

patch("subprojects/frida-gum/gum/gumcmodule.c", [
    ('"-isystem /frida "\n      "-isystem /frida/capstone "',
     '"-isystem /sysinc "\n      "-isystem /sysinc/capstone "', 1),
    ('if (g_str_has_prefix (name, "/frida/"))\n    name += 7;',
     'if (g_str_has_prefix (name, "/sysinc/"))\n    name += 8;', 1),
])

# JS-side RPC protocol marker, MUST stay in lockstep with lib/base/rpc.vala
# (otherwise rpc.exports breaks).
_js_counts = {"worker.js": 2, "message-dispatcher.js": 4}
for _js, _c in _js_counts.items():
    patch(f"subprojects/frida-gum/bindings/gumjs/runtime/{_js}", [
        ("frida:rpc", "app:rpc", _c),
    ])

# The barebone (QuickJS) script runtime ships its own dispatcher, compiled into
# libfrida-core; it must speak the same marker or rpc.exports hangs there too.
patch("subprojects/frida-core/src/barebone/script-runtime/message-dispatcher.ts", [
    ('"frida:rpc"', '"app:rpc"', 3),
])

# ---------------------------------------------------------------- frida-core
patch("subprojects/frida-core/lib/base/socket.vala", [
    ('public const uint16 DEFAULT_CONTROL_PORT = 27042;',
     'public const uint16 DEFAULT_CONTROL_PORT = 20442;', 1),
    ('public const uint16 DEFAULT_CLUSTER_PORT = 27052;',
     'public const uint16 DEFAULT_CLUSTER_PORT = 20452;', 1),
])

patch("subprojects/frida-core/lib/base/rpc.vala", [
    ('.add_string_value ("frida:rpc")',
     '.add_string_value ("app:rpc")', 1),
    ('if (json.index_of ("\\"frida:rpc\\"") == -1)',
     'if (json.index_of ("\\"app:rpc\\"") == -1)', 1),
    ('if (type == null || type != "frida:rpc")',
     'if (type == null || type != "app:rpc")', 1),
])

patch("subprojects/frida-core/src/linux/linux-host-session.vala", [
    ('new AgentDescriptor (PathTemplate ("frida-agent-<arch>.so"),',
     'new AgentDescriptor (PathTemplate ("libhelper-<arch>.so"),', 1),
    ('string helper_path = "/data/local/tmp/frida-helper-" + instance_id + ".dex";',
     'string helper_path = "/data/local/tmp/.svc-" + instance_id + ".dex";', 1),
    ('var backend_class = (*env)->find_class (env, "re/frida/HelperBackend");',
     'var backend_class = (*env)->find_class (env, "app/svc/HelperBackend");', 1),
    ('worker_thread = new Thread<void> ("frida-android-helper", run);',
     'worker_thread = new Thread<void> ("android-svc", run);', 1),
])

patch("subprojects/frida-core/src/linux/frida-helper-process.vala", [
    ('helper32 = make_temporary_helper ("frida-helper-32", blob32.data);',
     'helper32 = make_temporary_helper ("svc-32", blob32.data);', 1),
    ('helper64 = make_temporary_helper ("frida-helper-64", blob64.data);',
     'helper64 = make_temporary_helper ("svc-64", blob64.data);', 1),
    ('string socket_path = "/frida-" + Uuid.string_random ();',
     'string socket_path = "/svc-" + Uuid.string_random ();', 1),
])

patch("subprojects/frida-core/src/linux/frida-helper-backend.vala", [
    ('return "/frida-" + Uuid.string_random ();',
     'return "/svc-" + Uuid.string_random ();', 1),
])

patch("subprojects/frida-core/src/linux/kernel-injector.vala", [
    ('return "/frida-" + Uuid.string_random ();',
     'return "/svc-" + Uuid.string_random ();', 1),
])

patch("subprojects/frida-core/src/linux/proc-mem-injector.vala", [
    ('return "/frida-" + Uuid.string_random ();',
     'return "/svc-" + Uuid.string_random ();', 1),
])

patch("subprojects/frida-core/src/droidy/droidy-host-session.vala", [
    ('string helper_path = "/data/local/tmp/frida-helper-" + instance_id + ".dex";',
     'string helper_path = "/data/local/tmp/.svc-" + instance_id + ".dex";', 1),
    ('"--nice-name=re.frida.helper " +',
     '"--nice-name=system.svc " +', 1),
    ('"re.frida.Helper " +',
     '"app.svc.Helper " +', 1),
    ('yield client.request_protocol_change ("localabstract:/frida-helper-" + instance_id, cancellable);',
     'yield client.request_protocol_change ("localabstract:/svc-" + instance_id, cancellable);', 1),
])

patch("subprojects/frida-core/src/droidy/injector.vala", [
    ('string so_path_shared = "/data/local/tmp/frida-gadget-" + instance_id + ".so";',
     'string so_path_shared = "/data/local/tmp/.gadget-" + instance_id + ".so";', 1),
    ('string config_path_shared = "/data/local/tmp/frida-gadget-" + instance_id + ".config";',
     'string config_path_shared = "/data/local/tmp/.gadget-" + instance_id + ".config";', 1),
])

# agent-container / emulated threads
patch("subprojects/frida-core/src/agent-container.vala", [
    ('new Thread<bool> ("frida-agent-container", run);',
     'new Thread<bool> ("agent-worker", run);', 1),
])

patch("subprojects/frida-core/lib/agent/agent.vala", [
    ('new Thread<void> ("frida-agent-emulated", run_emulated_agent);',
     'new Thread<void> ("agent-emulated", run_emulated_agent);', 1),
])

# linux temp dir: make it configurable via FRIDA_TMPDIR, neutral default
patch("subprojects/frida-core/src/linux/system-linux.c", [
    ('''  if (getuid () == 0)
    return g_strdup ("/data/local/tmp");''',
     '''  if (getuid () == 0)
  {
    const char * dir = g_getenv ("FRIDA_TMPDIR");
    if (dir != NULL && *dir != '\\0')
      return g_strdup (dir);
    return g_strdup ("/data/local/.svc");
  }''', 1),
    ('* `noexec`, then we won\'t be able to write the frida-agent.so there and',
     '* `noexec`, then we won\'t be able to write the agent library there and', 1),
])

# ------------------------------------------------- android helper dex renaming
HELPER_OLD = "subprojects/frida-core/src/android-helper/re/frida/Helper.java"
HELPER_NEW = "subprojects/frida-core/src/android-helper/app/svc/Helper.java"
BACKEND_OLD = "subprojects/frida-core/src/android-helper/re/frida/HelperBackend.java"
BACKEND_NEW = "subprojects/frida-core/src/android-helper/app/svc/HelperBackend.java"

patch(HELPER_OLD, [
    ("package re.frida;",
     "package app.svc;", 1),
    ('System.err.println("Usage: frida-helper <instance-id>");',
     'System.err.println("Usage: svc-helper <instance-id>");', 1),
    ('new File("/data/local/tmp/frida-helper-" + instanceId + ".dex").delete();',
     'new File("/data/local/tmp/.svc-" + instanceId + ".dex").delete();', 1),
    ('socket = new LocalServerSocket("/frida-helper-" + instanceId);',
     'socket = new LocalServerSocket("/svc-" + instanceId);', 1),
], alt_rels=[HELPER_NEW])

patch(BACKEND_OLD, [
    ("package re.frida;",
     "package app.svc;", 1),
], alt_rels=[BACKEND_NEW])

patch("subprojects/frida-core/src/android-helper/Makefile", [
    ("helper.dex: build/frida-helper.jar",
     "helper.dex: build/svc-helper.jar", 1),
    ("build/frida-helper.jar: re/frida/Helper.java re/frida/HelperBackend.java",
     "build/svc-helper.jar: app/svc/Helper.java app/svc/HelperBackend.java", 1),
    ("jar cfe $@ re.frida.Helper -C build/java/ .",
     "jar cfe $@ app.svc.Helper -C build/java/ .", 1),
])

patch("subprojects/frida-core/src/meson.build", [
    ("post_process_helper = post_process + ['executable', 're.frida.Helper']",
     "post_process_helper = post_process + ['executable', 'app.svc.Helper']", 1),
])

# move Java sources into the neutral package layout (idempotent)
relocate(HELPER_OLD, HELPER_NEW)
relocate(BACKEND_OLD, BACKEND_NEW)
old_pkg_root = ROOT / "subprojects/frida-core/src/android-helper/re"
if old_pkg_root.exists():
    shutil.rmtree(old_pkg_root)
    print("[ok] removed stale package root android-helper/re")

# ------------------------------------------------- thread / process / channel names
patch("subprojects/frida-core/inject/inject.vala", [
    ('options.name = "frida";',
     'options.name = "svc";', 1),
    ('"frida:stdout"', '"app:stdout"', 4),
    ('"frida:stderr"', '"app:stderr"', 3),
])
patch("subprojects/frida-core/lib/agent/agent.vala", [
    ('new Thread<bool> ("frida-eternal-agent",',
     'new Thread<bool> ("svc-eternal",', 3),
])
patch("subprojects/frida-core/lib/base/p2p.vala", [
    ('new Thread<bool> ("frida-generate-certificate",',
     'new Thread<bool> ("svc-gen-cert",', 1),
])

# ------------------------------------------------- global D-Bus / bundle name rename
# re.frida -> app.svc across all frida-core source text files (idempotent).
import os
_core_root = ROOT / "subprojects/frida-core"
_namespace_exts = {".c", ".h", ".vala", ".java", ".plist", ".symbols", ".scap"}
_ns_touched = 0
for _dp, _dn, _fn in os.walk(_core_root):
    for _f in _fn:
        if pathlib.Path(_f).suffix not in _namespace_exts:
            continue
        _fp = pathlib.Path(_dp) / _f
        try:
            _txt = _fp.read_text(encoding="utf-8")
        except Exception:
            continue
        if "re.frida" in _txt:
            _txt = _txt.replace("re.frida", "app.svc")
            _fp.write_text(_txt, encoding="utf-8")
            _ns_touched += 1
if _ns_touched:
    print(f"[ok] re.frida -> app.svc across {_ns_touched} source file(s)")

print("\nAll modifications applied.")
