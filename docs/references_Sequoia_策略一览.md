# references 目录遍历总结

## 一、strategy-vnpy（`references/strategy-vnpy`）

- **内容**：仅 **README.md**，无策略源码（仓库可能已迁移或未上传策略文件）。
- **用途**：README 说明为 vnpy 定制策略库，可放入 `vn.trader/ctaAlgo/strategy` 使用。当前仅作占位，参考价值有限。

---

## 二、Sequoia（`references/Sequoia`）

**数据**：AKShare（东方财富），**选股系统**，可多策略组合；支持回测（`config.yaml` 里设 `end_date`）、微信推送。

### 目录结构概览

| 路径 | 说明 |
|------|------|
| `main.py` | 入口，拉全 A 股、跑策略、推送 |
| `work_flow.py` | 策略调度：定义策略名→函数映射，逐个跑并推送结果 |
| `data_fetcher.py` | 取 K 线等行情数据 |
| `utils.py` / `settings.py` / `push.py` | 工具、配置、推送 |
| `config.yaml.example` | 配置示例（含 `end_date` 回测、cron、wxpusher） |
| `strategy/` | **所有选股策略实现** |

### 策略列表与逻辑摘要（与 QMT 可借鉴点）

| 策略名 | 文件 | 核心逻辑（可改写成 QMT） |
|--------|------|---------------------------|
| **放量上涨** | `strategy/enter.py` → `check_volume` | 最后一根 K 线：收盘突破区间最高价 + 放量（结合 ATR/量能），且收盘/开盘 > 1.06、收盘 > 前高、开盘参与条件 |
| **突破平台** | `strategy/breakthrough_platform.py` | 平台突破：某日 **开盘 < MA60 ≤ 收盘**（站上 60 日线）+ 放量；且突破前一段时间内收盘在 MA60 附近震荡（-5%～+20%），可对应你当前「横盘突破」的形态过滤 |
| **海龟交易法则** | `strategy/turtle_trade.py` | **N 日最高价突破**：区间内最高价 = 最后一根 K 线收盘价（创新高），偏趋势跟踪 |
| **回踩年线** | `strategy/backtrace_ma250.py` | 回踩 MA250：近期在年线附近有高低点、回踩不破等条件，偏趋势+支撑 |
| **停机坪** | `strategy/parking_apron.py` | 涨停后 3 日内「横盘不破涨停价」：涨停日识别 + 之后几天收盘/开盘在涨停价上方且振幅收窄（约 97%～103%），类似横盘整理再突破 |
| **持续上涨** | `strategy/keep_increasing.py` | MA30 单调向上：取 30 日三段（前 1/3、2/3、末），MA30 递增且末段 MA30 > 1.2× 首段，偏趋势过滤 |
| **高而窄的旗形** | `strategy/high_tight_flag.py` | 龙虎榜机构 + 14 日内最低到最高涨幅 ≥ 90% + **连续两天涨幅 ≥ 9.5%**（连板），偏强势形态 |
| **低回撤稳步上涨** | `strategy/low_backtrace_increase.py` | 区间涨幅 ≥ 60% + 无单日大跌（无单日 -7%、无单日高开低走 -7%、无两日 -10% 等），偏趋势+风控 |
| **低 ATR 成长** | `strategy/low_atr.py` | MA 多头 + 区间波动（ATR/涨跌幅）在一定范围内，偏低波动趋势 |
| **放量跌停** | `strategy/climax_limitdown.py` | 当日跌停（约 -9.5%）+ 量比 ≥ 4 + 成交额 ≥ 2 亿，偏恐慌/抄底逻辑 |

### work_flow 中实际启用的策略（`work_flow.py`）

- 放量上涨、均线多头、停机坪、回踩年线、无大幅回撤、海龟交易法则、高而窄的旗形、放量跌停。  
- **突破平台** 在代码里被注释掉，未参与每日选股；若你要做「横盘突破」，可重点参考 `breakthrough_platform.py` + `enter.check_volume` 的放量条件。

### 和当前 QMT 策略的对应关系

- **横盘突破**（`strategy_range_breakout_20d.py`）：最接近 Sequoia 的 **突破平台**（MA60 附近震荡 + 站上 MA60 + 放量）和 **停机坪**（涨停后窄幅整理）。可借鉴：突破前「价格在均线附近震荡」的区间定义、放量判定、以及停机坪的「涨停后几日振幅」写法。
- **数据与接口**：Sequoia 用 AKShare + DataFrame；QMT 用 `get_market_data_ex`。只需把「日期/开盘/收盘/成交量/均线」等映射到 QMT 取到的序列，逻辑可平移。

---

## 三、在 Cursor 里怎么用

- 看某条策略细节：**@references/Sequoia/strategy/breakthrough_platform.py** 等具体文件。
- 看整体流程与策略组合：**@references/Sequoia/work_flow.py**、**@references/Sequoia/main.py**。
- 让 AI 按 Sequoia 思路改 QMT 策略：**@references/Sequoia** 或 **@docs/quant_open_source_projects.md**，并说明要借鉴哪一条（如「突破平台」「停机坪」）。
