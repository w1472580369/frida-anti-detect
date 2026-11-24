# GitHub Actions workflows

工作流已迁移到仓库根目录的 `.github/workflows/`，GitHub Actions 会自动识别。

包含：
- `build.yml`：从 Frida 17.19.0 源码构建 server + injector（arm64），可选 compat / stealth，
  并应用 `patches/` 中的全部补丁（含 `37-core_lib_payload_libc-shim.c.patch`）。
- `client-wheel.yml`：构建 stealth 模式配套 frida-python wheel。
- `anti-detect-build.yml`：全量构建保底路径。

触发方式：Actions 页面选择 `source-build` → Run workflow，`mode` 选 `compat`（APK 默认）。

> 注意：推送 `.github/workflows/*.yml` 需要 token 具备 `workflow` scope。
