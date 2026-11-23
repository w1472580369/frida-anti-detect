# GitHub Actions workflows

GitHub 拒绝 OAuth App 在没有 `workflow` scope 时推送 `.github/workflows/*.yml`。
因此本目录先保存工作流源文件。

启用方式（二选一）：

1. 给 `gh` 增加 workflow scope 后执行：
   ```bash
   gh auth refresh -h github.com -s workflow
   mkdir -p .github/workflows
   git mv ci/workflows/*.yml .github/workflows/
   git commit -m "Enable GitHub Actions workflows"
   git push
   ```
2. 直接在 GitHub 网页端新建 `.github/workflows/` 并粘贴本目录文件。

包含：
- `build.yml`：从 Frida 17.19.0 源码构建 server + injector，可选 compat / stealth
- `client-wheel.yml`：构建 stealth 模式配套 frida-python wheel
- `anti-detect-build.yml`：全量构建保底路径
