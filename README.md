# AI 投研数字员工｜程序更新仓库

这个仓库只发布通用程序和 Codex 投研插件，不保存任何老板个人投研资料。

## 自动更新链路

1. 开发版本通过测试后，将 `product/VERSION`、应用版本和插件版本统一更新；
2. 推送 `vX.Y.Z` Git 标签；
3. GitHub Actions 在 Windows 和 Linux 上运行自动化测试；
4. 测试通过后生成 `AI投研数字员工_Update_vX.Y.Z.zip` 和 SHA-256；
5. 老板电脑每 6 小时读取 GitHub 最新正式 Release；
6. 下载、校验、备份、停止旧版、覆盖程序并启动新版；
7. 新版健康检查失败时，自动恢复旧程序和升级前数据库。

## 永不上传或覆盖

- `product/.env` 和 API Key；
- `product/投研数字员工/` 下的老板说明书、自选、决策、纠正和待确认记忆；
- SQLite 数据库、网页/Codex 对话、报告、导出、来源资料和备份；
- 运行日志、PID、截图、虚拟环境和缓存。

更新包内部有逐文件 SHA-256 清单。更新器只允许写入 `product/` 的程序文件和 `codex-plugin-marketplace/`；任何试图覆盖老板资料的路径都会被拒绝。

## 发布

```bash
cd product
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/python scripts/release_check.py --tag v0.11.0
git tag v0.11.0
git push origin main --tags
```

正式 Release 由 `.github/workflows/release.yml` 自动创建，不手工覆盖已有版本。

