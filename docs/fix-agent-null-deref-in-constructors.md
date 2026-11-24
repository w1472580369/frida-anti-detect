# 修复：agent 在 ELF 构造函数中空指针崩溃（注入后目标进程被杀）

## 症状

App 内注入器对**任何**目标（含 `com.android.settings`、`com.termux`、`com.dump.echo`）附加后：

```
[inject] 执行: /data/local/tmp/.svc-helper -p 22647 -s /data/local/tmp/.svc-bridge-27176.js
[inject] Agent connection closed unexpectedly
[inject] 进程结束，退出码 4
```

宿主侧报 `failed to connect to 127.0.0.1:<port> ... ECONNREFUSED after 900ms`，**目标进程被连带杀死**。

设备：Redmi K30i 5G / Android 12 / MIUI V13.0.4.0 / arm64-v8a。

## Tombstone 关键帧

```
signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x38
Cause: null pointer dereference
     x0  0000000000000000          <-- NULL
     pc  0000006fe3fed194  lr 0000006fe3fed358
Process uptime: 0s                  <-- 进程刚起就被注入
backtrace:
  #00 pc b10194  /memfd:frida-agent-64.so (deleted)
  #01 pc b10354
  ...
  #21 pc a8303c
  #22 pc 052bb4  linker64 (__dl__ZN6soinfo17call_constructorsEv+628)
  #23 pc 03d018  linker64 (__dl__Z9do_dlopenPKciPK17android_dlextinfoPKv+2284)
```

`#22 call_constructors` → 崩溃发生在 **agent 的 ELF 构造函数**里，不是 Java helper 层。

## 崩溃指令

内嵌 agent（`libhelper-64.so` / 上游 soname `libfrida-agent-raw.so`）偏移 `0xb10194`：

```asm
0xb1017c: stp x29, x30, [sp, #-0x50]!   ; 函数入口
...
0xb10194: ldr x8, [x0, #0x38]           ; <-- x0 = NULL, fault addr 恰好 0x38
0xb10198: mov x19, x0
...
0xb101a8: blr x8                        ; 调用 [x0+0x38] 处的函数指针
0xb101ac: cmp w0, #1
0xb101c8: mul w8, w24, w8
0xb101d0: ldr w9, [x19, #8]             ; hash_table->mask
0xb101d4: udiv w10, w8, w9
0xb101d8: msub w21, w10, w9, w8         ; idx % mask
0xb101dc: ldr x8, [x19, #0x28]          ; hash_table->values
```

字段布局 `+0x08` mask、`+0x28` values、`+0x38` 回调指针、`+0x40` key_equal_func，
**完全对应 GLib `GHashTable`**。即：对一张 ** 哈希表**做 `g_hash_table_lookup/add`。

## 根因

`frida-core/lib/payload/libc-shim.c` 的构造函数：

```c
static GHashTable * frida_streams = NULL;

__attribute__ ((constructor)) static void
frida_libc_shim_init (void)
{
  if (frida_libc_shim_initialized)
    return;

  gum_init_embedded ();          // <-- ① 先初始化 gum

  G_LOCK (frida_stdio);
  frida_streams = g_hash_table_new (g_direct_hash, g_direct_equal);   // <-- ② 之后才建表
  G_UNLOCK (frida_stdio);
  ...
}
```

而 gum 的初始化路径会读 `/proc/self/auxv`：

`frida-gum/gum/backend-linux/gummoduleregistry-linux.c`

```c
gum_read_auxv_from_proc (void)
{
  ElfW(auxv_t) * auxv = NULL;
  _gum_acquire_dumpability ();
  g_file_get_contents ("/proc/self/auxv", (gchar **) &auxv, NULL, NULL);
  _gum_release_dumpability ();
  return auxv;
}
```

`g_file_get_contents()` 对 `/proc` 这类**非普通文件**走 `fdopen()`；而 frida 的
libc-shim 把 `fdopen()` 替换成了自己的实现：

```c
G_GNUC_INTERNAL FILE *
fdopen (int fd, const char * mode)
{
  ...
  impl = frida_file_new (fd, TRUE, _IOFBF);
  result = frida_file_wrap (impl);
  frida_stdio_register_stream (result);   // -> g_hash_table_add (frida_streams, stream)
  return result;
}
```

于是形成**构造顺序缺陷**：

```
frida_libc_shim_init()
  └─ gum_init_embedded()
       └─ _gum_query_program_modules()
            └─ gum_read_auxv_from_proc()
                 └─ g_file_get_contents("/proc/self/auxv")
                      └─ fdopen()          [被 shim 替换]
                           └─ frida_stdio_register_stream()
                                └─ g_hash_table_add(frida_streams == NULL, ...)
                                     └─ 读 [+0x38]  →  SIGSEGV (fault addr 0x38)
```

哈希表要到 `gum_init_embedded()` **返回之后**才创建，为时已晚。

### 为什么在 Android 12 / MIUI 上必现

`Process uptime: 0s` —— 注入发生在进程刚启动时。此时 `/proc/self/auxv` 走
`g_file_get_contents` 的 `fdopen` 分支（非普通文件），而构造顺序缺陷使
`frida_streams` 必然为 NULL。这是**确定性崩溃**，与目标 App 无关
（系统设置、Termux、自研 App 全部同样崩溃），也解释了 `com.android.settings`
等系统应用被附加后直接消失。

> 说明：本项目的 13 个反检测补丁均未改动 `libc-shim.c`，此缺陷来自上游构造顺序，
> 只是反检测构建让它更容易被触发。

## 修复

把 stream/dir 哈希表的创建**提前到 `gum_init_embedded()` 之前**，使 shim 在 gum
启动过程中就可安全使用：

```c
__attribute__ ((constructor)) static void
frida_libc_shim_init (void)
{
  if (frida_libc_shim_initialized)
    return;

  f0 = f1 = f2 = NULL;

  G_LOCK (frida_stdio);
  frida_streams = g_hash_table_new (g_direct_hash, g_direct_equal);
#ifdef HAVE_FRIDA_DIR
  frida_dirs = g_hash_table_new (g_direct_hash, g_direct_equal);
#endif
  G_UNLOCK (frida_stdio);

  gum_init_embedded ();      // 现在 gum 内部任何 fopen/fdopen 都是安全的
  ...
}
```

补丁文件：`patches/37-core_lib_payload_libc-shim.c.patch`

```bash
python3 tools/apply_patches.py      # 含本修复
```

## 影响面

- 修复的是 **agent 侧**（`libfrida-agent-raw.so` / 打包后的 `libhelper-64.so`），
  同时影响 `libfinj.so`（injector 内嵌 agent）与 `libfsrv.so`（server 内嵌 agent）。
- 需**重新构建** `frida-inject` / `frida-server` 并替换
  `android-app/jniLibs/arm64-v8a/` 下的两个 `.so`，重新打包 APK 才生效。
- 纯二进制补丁无法修（这是初始化顺序问题，不是单条指令）。

## 附带发现：compat 版 frida-server 启动即退出

```
Frida:ERROR:../subprojects/frida-core/src/linux/linux-host-session.vala:744:
frida_android_helper_service_do_start: assertion failed: (backend_class != null)
Bail out!
```

`20442` 端口从未监听（每 2s 探测全部 CLOSED）。这是**另一个独立问题**：
Linux host-session 的 Android helper backend 未注册。`frida_start_server` 返回
`ok:true` 只代表启动命令已发出，不代表进程存活，需用端口探测/日志确认。

## 复现与验证要点

1. `adb shell` 或 MCP 附加任意进程，观察 `[inject] Agent connection closed unexpectedly`。
2. 从 `/data/tombstones/` 取崩溃日志，确认 `#22 call_constructors` 与 `fault addr 0x38`。
3. 从 `libfinj.so` 中提取内嵌 agent（ELF magic，`DT_SONAME = libfrida-agent-raw.so`），
   反汇编 `+0xb10194` 应为 `ldr x8, [x0, #0x38]`。
4. 修复后重新注入，应能正常附加且目标进程不被杀死。
