# AI 投研数字员工｜自动更新与 GitHub 发布说明

## 老板电脑怎么更新

v0.11.0 开始，Windows 正式版默认每 6 小时检查一次固定 GitHub 仓库的最新正式 Release。

发现新版本后：

1. 下载 `AI投研数字员工_Update_vX.Y.Z.zip` 和对应 `.sha256`；
2. 校验 ZIP 的 SHA-256；
3. 校验 ZIP 内 `UPDATE_MANIFEST.json` 登记的每个程序文件；
4. 生成一致性 SQLite 备份和完整老板资料快照；
5. 停止旧版研究台；
6. 只覆盖程序文件和 Codex 投研插件；
7. 安装新依赖并启动新版；
8. 检查 `/api/health` 返回的版本是否正确；
9. 失败则自动恢复旧程序、旧数据库和升级前资料。

老板也可以在网页“老板偏好 → 安全自动更新”查看状态、检查新版本和手动安装，或双击 `Windows_检查并更新.cmd`。

## 永远不覆盖的数据

更新器硬编码保护：

- `product/.env` 和 API Key；
- `product/.venv/`；
- `product/runtime/` 和运行日志；
- `product/dist/`；
- `product/投研数字员工/` 下的老板说明书、自选、板块、研究原则、决策、待确认记忆和纠正记录；
- SQLite 数据库、网页/Codex 对话、报告、导出、来源资料和备份。

只有 `product/投研数字员工/.system/` 中的通用程序脚本允许随版本更新。更新清单如果出现任何其他老板资料路径，安装会在覆盖前直接失败。

## GitHub 仓库结构

默认更新仓库：

```text
Leobai03/ai-investment-employee-updates
```

为了让老板电脑不保存 GitHub Token，更新仓库及 Release 必须公开。仓库的 `.gitignore` 会从 Git 层排除全部老板资料、密钥、数据库、对话、报告、备份、日志和历史交付包。

如果未来改用私有仓库，必须另行设计最小权限下载凭据；不要把开发者 GitHub Token 写入老板电脑或 `.env.example`。

## 开发者每次发布

1. 修改功能并补测试；
2. 同步更新以下版本：
   - `product/VERSION`
   - `product/app/__init__.py`
   - `product/app/main.py`
   - `product/scripts/build_delivery.py`
   - Codex 插件 `plugin.json`
3. 本地运行：

   ```bash
   cd product
   .venv/bin/pytest -q
   node --check app/static/app.js
   .venv/bin/python scripts/release_check.py --tag vX.Y.Z
   ```

4. 提交代码并推送 `vX.Y.Z` 标签；
5. GitHub Actions 在 Ubuntu 和原生 Windows 上测试；
6. Windows 流程额外执行一次真实的停止、备份、覆盖、依赖安装、启动和资料留存测试；
7. 全部通过后，工作流创建不可变 Release 并上传更新 ZIP 与 SHA-256；
8. 老板电脑下一次检查时自动获取正式版。

工作流不会在测试失败时发布 Release，也不会覆盖同名旧 Release。

## 升级备份和人工恢复

升级备份位于：

```text
product/投研数字员工/backups/update-日期-时间-from-v旧版-to-v新版/
```

其中包括程序回滚文件、`ROLLBACK_STATE.json` 和 `老板资料升级前快照.zip`。自动更新成功后不会立即删除这些备份。

自动回滚失败属于必须人工处理的异常。此时不要继续反复覆盖，保留错误日志和升级备份，先停止研究台再恢复。

