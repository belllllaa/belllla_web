# 量化开源项目索引（接 Cursor 便于日后调用）

本仓库已接入以下开源项目，便于在 Cursor 中引用策略思路、因子与风控逻辑。  
**在 Cursor 里怎么用**：聊天时可 @ 本文件或 @ `references/` 下克隆的目录，或说「参考量化开源索引」让 AI 优先参考这些项目。

---

## 国内 A 股向

| 项目 | 说明 | GitHub | 本地路径（若已克隆） |
|------|------|--------|----------------------|
| **Sequoia** | A 股自动选股：海龟、缠论买点等形态 | https://github.com/sngyai/Sequoia | `references/Sequoia` |
| **vnpy** | 国内常用 Python 量化/交易框架 | https://github.com/vnpy/vnpy | —（体量大，建议仅参考文档） |
| **strategy-vnpy** | 为 vnpy 写的策略库，开箱即用 | https://github.com/qtbrain/strategy-vnpy | `references/strategy-vnpy` |
| **选股器 xuanguqi** | 多因子选股、A 股数据与可视化 | https://github.com/jinyang756/xuanguqi | — |
| **InStock** | 数据抓取、指标与 K 线形态、选股+回测 | https://github.com/coomia/InStock | — |
| **Stock-picking-strategy** | 风险调整动量、多因子、风控与回测 | https://github.com/promise1121/Stock-picking-strategy | — |

## 通用回测 / 策略框架

| 项目 | 说明 | GitHub |
|------|------|--------|
| **backtrader** | 经典 Python 回测框架 | https://github.com/mementum/backtrader |
| **Qantify** | 多交易所、向量化回测、ML | https://github.com/Alradyin/qantify |
| **StratVector** | 向量化回测、蒙特卡洛、参数优化 | 可搜 StratVector backtest |

---

## 热点/新闻爬取 + 选股 + 定时推送

| 项目 | 说明 | GitHub |
|------|------|--------|
| **daily_stock_analysis** | LLM 驱动：多数据源行情 + 实时新闻 + Gemini 决策仪表盘；企业微信/飞书/Telegram/钉钉/邮件推送；GitHub Actions 定时，支持 A/H/美股 | https://github.com/ZhuLinsen/daily_stock_analysis |
| **zMain** | 选股机器人：MySQL + AKShare/tushare/baoStock + 筹码计算、选股、**邮件提醒** | https://github.com/tianjingle/zMain |
| **stock_news** | 每日股票信息爬虫 + 推送，支持 ETF 分析，GitHub Actions 定时 | https://github.com/steveyeh9872/stock_news |
| **XCrawler** | 轻量 A 股爬虫，含通知模块、数据爬取 | https://github.com/Stock-Fund/XCrawler |
| **Stock-trading-news-alert** | 新闻 API 抓股相关新闻 + Alpha Vantage 盯盘，**Twilio 短信推送到手机** | https://github.com/pragyan7/Stock-trading-news-alert-project |
| **sentiment-trading** | 爬 Yahoo 财经标题 + 情绪分析（Hugging Face）+ 交易执行，**React 前端 + GitHub Actions 自动化** | https://github.com/rudrap31/sentiment-trading |

## 期货 / 原油 / 大宗监控与资讯爬取

| 项目 | 说明 | GitHub |
|------|------|--------|
| **MonitorCrude** | **纽约原油监控助手**，Python，含配置与主逻辑，适合盯原油行情/地缘事件（如伊朗局势） | https://github.com/itimetime/MonitorCrude |
| **QhNews** | **期货资讯爬虫**，爬期货市场热点新闻，Python，含 DAO/工具模块 | https://github.com/wukuiqing49/QhNews |
| **invest-watcher** | 贵金属、**原油、天然气**等：实时行情、**点位报警**、持仓、历史数据 | https://github.com/haoshen/invest-watcher |
| **fushare** | 中国商品期货基础数据（基本面等） | https://github.com/LowinLi/fushare |
| **futures_cn_ohlc** | 国内商品期货 OHLC（tushare/tqsdk），支持 CFFEX/DCE/CZCE/**INE 原油**等 | https://github.com/ww12358/futures_cn_ohlc |
| **cfmmc_crawler** | 中国期货市场监控中心日结算单批量下载 | https://github.com/jicewarwick/cfmmc_crawler |

**和你说的场景对应**：  
- 「伊朗战、原油暴涨、相关信息爬取」→ 可参考 **MonitorCrude**（原油监控）+ **QhNews**（期货资讯爬虫），再自己加新闻源（如新浪财经、东方财富期货要闻、Reuters 能源标题）做关键词/地缘爬取与推送。  
- 热点选股 + 定时推送 → **daily_stock_analysis**（最全，带新闻+LLM+多推送）、**zMain**（邮件提醒）、**stock_news**（轻量定时）。

---

## 在 Cursor 中的调用方式

1. **@ 引用**：输入 `@quant_open_source_projects.md` 或 `@docs/quant_open_source_projects.md`，让 AI 按本索引选项目参考。
2. **@ 本地代码**：若已克隆到 `references/`，可 @ `references/strategy-vnpy` 等目录，直接引用具体策略代码。
3. **自然语言**：说「参考 GitHub 量化开源索引里的策略」「按 Sequoia 的选股思路改一版」等，AI 会结合本索引与规则回答。
4. **克隆更多**：需要某仓库本地化时，在项目根执行（PowerShell）。详见 `references/README.md`。
   ```powershell
   git clone --depth 1 https://github.com/qtbrain/strategy-vnpy.git references/strategy-vnpy
   git clone --depth 1 https://github.com/sngyai/Sequoia.git references/Sequoia
   ```

---

## 与本仓库 QMT 策略的对接说明

- 本仓库策略运行在 **QMT**，数据与下单走 QMT 接口。
- 上表项目主要用于 **借鉴逻辑**：选股条件、出场规则、风控、因子构造等，改写成 QMT 的 `get_market_data_ex` / `passorder` 等即可。
- 规则文件 `.cursor/rules/quant-open-source.mdc` 会在编辑策略相关文件时提醒 AI 参考本索引与本地 `references/`。
