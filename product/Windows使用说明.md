# AI 投研数字员工｜Windows 安装与使用

## 第一次安装

1. 打开正式发布页：<https://github.com/Leobai03/ai-investment-employee-updates/releases/latest>。
2. 下载 `ai-investment-employee-windows-vX.Y.Z.zip` 和同名 `.sha256`。不要下载名字中带 `update` 的升级包。
3. 右键原始 ZIP →“属性”→勾选“解除锁定”→“应用”。必须在解压前做这一步；这是解决 Windows“来自 Internet 的文件被阻止”的安全做法。
4. 把整个 `AI投研数字员工_Windows` 文件夹解压到一个固定位置。不要直接在 ZIP 里运行，也不要只复制某个 `.cmd` 文件。
5. 打开 `product`，双击 `Windows_首次配置.cmd`。
6. 安装器会依次检查或安装 ChatGPT Windows 客户端、Python 3.14、Node.js LTS、OpenAI Codex CLI、`$ai-investment-employee` 插件和网页产品依赖。
7. 浏览器出现登录页时，用老板自己的 ChatGPT 账号完成 Codex 登录。
8. 安装完成后会自动打开 `http://127.0.0.1:8765`。以后直接双击 `Windows_启动研究台.cmd`。
9. 双击 `Windows_系统自检.cmd`；看到“Windows 核心依赖自检通过”后，首次安装完成。

安装器只使用 Microsoft Store、Windows `winget` 和 OpenAI 官方 npm 包，不下载来路不明的可执行文件。PowerShell 的 `ExecutionPolicy Bypass` 只对本次双击启动的进程生效，不永久修改 Windows 执行策略。

如果 ZIP 的属性页没有“解除锁定”，解压后在完整交付包根目录打开 PowerShell，执行：

```powershell
Get-ChildItem -Recurse -File | Unblock-File
```

不要为了安装而关闭 Windows Smart App Control 或防病毒保护。

## 网页怎么用

- 每日市场简报：生成 A 股、港股优先的市场简报；
- 我的公司：添加自选公司，查看研究、对话和持续跟踪；
- 连续对话：像发消息一样追问，旧对话可以继续；
- 定时汇报：配置每两小时、每天、每周、每月或每年的公开信息研究；
- 研究档案：查看来源，并下载 Markdown、Word 或 PDF；
- 老板偏好：维护投资说明书、自选、决策和纠正记录。

网页只监听 `127.0.0.1`，默认只能在这台电脑上访问。关闭浏览器不会停止后台任务，但关闭研究台、关机、睡眠或断网会暂停执行。

## Codex 怎么用

1. 打开 ChatGPT Windows 客户端中的 Codex；
2. 选择完整交付包里的 `product` 文件夹；
3. 输入：

   ```text
   请使用 $ai-investment-employee 作为我的投研数字员工。先读取本项目的老板说明书、自选公司、研究原则、决策和纠正记录，再问我今天想研究什么。只做公开信息研究和汇报，不给交易指令。
   ```

网页“连续对话”里的“在 Codex 中打开”会尝试自动打开正确文件夹。若 Windows 没有响应，请手动按上面两步操作。只有工作目录精确等于 `product` 的 Codex 对话会被研究台同步，不读取其他项目。

## 保持每两小时运行

1. 双击 `Windows_安装开机自启.cmd`；
2. 进入“设置 → 系统 → 电源和电池 → 屏幕、睡眠和休眠超时”；
3. 把“接通电源后，使设备进入睡眠状态”设为“从不”；
4. 保持电脑通电、联网，不要移动或重命名完整交付文件夹；
5. 网页“定时汇报”中再启用两小时消息扫描。该任务默认关闭，避免未经确认持续消耗 Codex 额度。

开机自启只在当前 Windows 用户登录后运行。后台守护每 20 秒检查一次本机网页；异常退出会尝试恢复。离线恢复后只补跑一份最近错过的正式计划，不把离线期间每个时点全部重复执行。

## 常用入口

| 文件 | 用途 |
| --- | --- |
| `Windows_首次配置.cmd` | 首次安装或修复 ChatGPT、Codex、Python、插件和产品依赖 |
| `Windows_启动研究台.cmd` | 启动正式研究台并打开网页 |
| `Windows_打开研究台.cmd` | 只打开已经运行的网页 |
| `Windows_停止研究台.cmd` | 停止研究台和当前后台守护 |
| `Windows_安装开机自启.cmd` | 当前 Windows 用户登录后自动运行 |
| `Windows_卸载开机自启.cmd` | 删除开机启动项并停止后台；不删数据 |
| `Windows_系统自检.cmd` | 检查 Python、Codex、登录、网页和自启状态 |
| `Windows_查看运行日志.cmd` | 用记事本打开错误日志 |
| `Windows_演示研究台.cmd` | 只看界面；不检索或虚构实时数据 |
| `Windows_检查并更新.cmd` | 立即检查 GitHub 正式版本，安全备份后安装 |

## 自动更新

- 默认每 6 小时检查一次 GitHub 正式 Release；
- 老板在 Codex 或网页连续对话中说“把投研数字员工更新到最新版”，会进入同一个安全更新器；
- 网页“老板偏好 → 安全自动更新”可以查看状态和手动安装；
- 老电脑必须先看到 GitHub 上的新正式 Release，点击“检查新版本”才会出现“安装新版本”；
- 更新前自动备份数据库、对话、报告、偏好、自选、决策、纠正和 `.env`；
- 更新包只能覆盖程序与插件，不能覆盖老板资料；
- 新版启动失败会自动恢复旧程序和升级前数据库；
- 升级备份保存在 `投研数字员工\backups\update-...`，不会在成功后马上删除。

自动更新要求 GitHub 更新仓库可以公开下载。老板电脑不保存开发者 GitHub Token。

## 出现问题时

- 提示没有 `winget`：在 Microsoft Store 安装或更新“应用安装程序”，重启后重试；
- 安装后仍找不到 Python、Node 或 Codex：重启 Windows，再运行首次配置；
- Codex 未登录：打开 PowerShell，执行 `codex login`；
- Codex 插件未安装：双击 `codex-plugin-marketplace\安装AI投研数字员工_Windows.cmd`；
- 网页打不开：先运行 `Windows_系统自检.cmd`，再看 `Windows_查看运行日志.cmd`；
- 端口 8765 被占用：先运行 `Windows_停止研究台.cmd`；不要把网页改为公网地址；
- Windows 安全中心提示：核对文件来自正式交付 ZIP 及其 SHA-256；不要关闭系统安全防护。

## 数据和边界

- 老板偏好、对话、报告和数据库保存在 `product\投研数字员工\`；
- 可选 API Key 只保存在 `product\.env`，不会进入正式交付包；
- 不连接微信、通讯录或证券账户，不自动下单；
- 只做公开信息研究和汇报，不给个性化买卖、仓位、目标价或收益保证；
- 卸载开机自启不会删除数据。恢复数据库前必须先停止研究台。

官方安装参考：

- ChatGPT Windows 客户端：https://learn.chatgpt.com/docs/windows/windows-app
- OpenAI Codex CLI：https://github.com/openai/codex
- Codex CLI 命令参考：https://learn.chatgpt.com/docs/codex/cli/reference
