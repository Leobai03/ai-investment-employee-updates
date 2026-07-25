# 开源项目调研、复用与许可证边界

> 核验日期：2026-07-25  
> 本产品当前没有复制下列项目的源码。现阶段只借鉴公开架构思想，并以本项目原创代码实现。今后若实际引入依赖或复制代码，必须在本文件登记版本、文件、许可证和修改内容。

## 结论

最适合老板需求的不是直接部署某一个“AI 炒股”项目，而是组合三类能力：

1. 用 Vibe-Trading / LangAlpha 的长期研究工作区、可追溯运行记录和任务编排思想做底座；
2. 用 daily_stock_analysis 的多市场数据源降级与定时任务思想补 A/H/美/日/韩覆盖；
3. 用 FinRobot / FinSight 的公司深度研究与专业报告结构提升产出质量。

交易信号、买卖点、仓位、券商日志、即时通讯推送和自动交易模块不进入本产品。

## 优先参考

| 项目 | 许可证 | 值得借鉴 | 本产品边界 |
| --- | --- | --- | --- |
| [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | MIT | A/H/US 跨市场研究、持久记忆、run card、假设登记、数据源降级、安全默认值 | 不引入 Shadow Account、券商日志、策略代码、交易团队和任何执行入口 |
| [ginlix-ai/LangAlpha](https://github.com/ginlix-ai/langalpha) | Apache-2.0 | workspace、长期记忆、来源追踪、任务状态、沙箱和研究过程可见性 | 美股数据栈不能直接当作 A/H 主数据源；不引入分享和外部协作入口 |
| [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) | MIT | A/H/US/日/韩多市场识别、数据源 fallback、定时任务、断点续传、交易日判断 | 不引入买卖点、评分、持仓、推送渠道、预测回测和“决策仪表盘”措辞 |
| [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | Apache-2.0 | 公司财务分析、估值、同业比较、专业报告流水线 | 先借鉴报告契约；其数据接口偏美股，且不得把预测或交易策略接进来 |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | MIT | 多视角检查清单和正反方讨论的产品表达 | 不模仿投资人身份，不生成交易信号、仓位上限或组合动作 |

## 仅研究，不复制

| 项目 | 原因 | 允许做什么 |
| --- | --- | --- |
| [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | 混合许可证；`app/` 后端和 `frontend/` 前端为专有组件，商业使用需另行授权 | 只观察中文 A/H 用户流程；不复制前后端代码、样式或资源 |
| [RUC-NLPIR/FinSight](https://github.com/RUC-NLPIR/FinSight) | GPL-3.0 | 只借鉴“证据可追溯、图表服务结论、报告可出版”的抽象原则 |
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | AGPL-3.0 | 只作为未来独立数据服务候选；接入前做单独法律和部署审查 |
| [666ghj/BettaFish](https://github.com/666ghj/BettaFish) | GPL-2.0，且面向舆情预测 | 只借鉴多来源互证和反方舆情检查思想，不复制代码 |

## 复用纪律

- MIT / Apache-2.0 也必须保留版权和许可证通知。
- 仓库许可证只约束代码，不自动授予行情、财报、新闻、商标或第三方 API 数据权利。
- 免费数据源可能限流、改接口或禁止再分发；产品必须显示来源、时间和降级状态。
- GPL / AGPL / 专有组件默认不并入本产品；任何例外都必须先取得明确书面许可。
- 所有外部能力先经过安全裁剪：无券商、无账户、无通讯录、无微信、无自动下单、无个性化交易指令。

## 当前原创实现

v0.11.0 的 GitHub 安全更新、完整资料快照和失败回滚，v0.10.0 的跨平台运行层，以及 v0.9.0 的来源可信度、数据采集契约、可靠调度和双员工复核为本项目原创实现：

- 只按域名保守识别一手来源，区分正文引用与检索参考；
- 汇总一手来源、独立域名、域名集中度、数字同行引用和证据缺口；
- A/H/美/日/韩适配层只登记官方入口、字段契约、授权状态与失败降级，不绕过数据许可；
- 双员工复核只设置事实核验员和反方研究员，没有交易角色；
- 正式定时计划使用本机 SQLite 原子占位、防重与中断恢复；
- GitHub Release 更新执行 ZIP 与逐文件 SHA-256 校验，只允许覆盖通用程序和插件；
- 更新前制作 SQLite 一致性备份和完整老板资料快照，新版健康检查失败自动回滚；
- 旧报告读取时动态审计，不篡改历史正文；
- 不使用任何外部项目源码。
