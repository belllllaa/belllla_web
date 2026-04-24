# 实盘策略说明：`strategy_my_watchlist_intraday_atr_1m_live_signal.py`

本文说明与解释对应 Python 文件的行为、参数与日志，**策略源码内仅保留极简注释**；细节以本 Markdown 为准。**各封装函数含义见第 11 节。**

---

## 1. 策略做什么（一句话）

在 **QMT 1 分钟 K 线** 上，从 **自选板块** 取股票池，按 **开盘涨跌幅分档** 做 **分批买入**，用 **上证指数 MA** 做门控与清仓条件之一，并用 **全天相对昨收止损、尾盘相对成本止损、上证 MA10 清仓、ATR 止盈** 等做 **卖出与风控**；满足条件时在实盘下 **`passorder`** 下单，否则只打 **`[SIGNAL]`** / **`[ORDER]`** 相关日志。

---

## 2. 和哪些文件对齐

| 关系 | 路径 |
|------|------|
| 规则与参数对齐（回测） | `qmt/回测策略/strategy_my_watchlist_intraday_atr.py` |
| bar 调度思路参考 | `qmt/实盘策略/strategy_sideways_breakout_sz_ma240_1m_live.py`（`is_last_bar`、墙钟门控等） |

---

## 3. 名词解释（你之前问的 `\u…` 解码后就是这些）

- **自选**：股票池来自 QMT 板块，默认板块名 **`我的自选`**（可用参数 `watchlist_sector_name` 改）。
- **当日再首买**：默认 **`block_same_day_rebuy_after_sell=True`**：只要本策略 **`_signal_sell_sim` 成功走通卖单**（含实盘挂单、回测信号卖），该规范代码记入 **`g._same_day_sold_canon`**，**同一交易日内** **`_try_first_buy_watchlist_stock` 不再对该票首买**；换日后集合清空。若你在客户端**手工卖出**而未经过本策略卖逻辑，**不会**自动记入该集合，仍可能首买（与账户是否仍显示持仓、`already` 快照有关）。
- **分档**：用 **今开 / 昨收 − 1** 得到开盘缺口 `gap`，再划到 A/B/C/D 档；不同档 **首笔买入比例、触发价、加仓腿** 不同（细节与回测策略文档一致）。
- **开仓 / 买入**：在门控通过时，按分档与金字塔逻辑 **`passorder` 买入**（受 `live_orders`、资金账号、非回测等约束）。
- **上证 MA 门控**：用 **000001.SH** 日线：例如最新收盘在 **MA5 下方** 时 **不开新仓**；**破 MA10** 时可触发 **清自选池内仓位**（与参数、时段有关）。
- **风控卖（与 ATR 并列的几类）**：
  - **全天·相对昨收**：连续竞价内，**现价 / 昨收 − 1 ≤ `intraday_touch_pct`**（默认 **−9%**，与持仓成本无关），见 `run_risk_sell_signal`。
  - **尾盘·相对成本**：自 **`tail_clear_start_hhmmss`**（默认 **14:50**）起，遍历 **当日自选池** 内有仓标的，**现价 / 成本 − 1 ≤ `tail_cost_stop_pct`**（默认继承 **`hard_stop_pct` = −8%**），见 `_run_tail_watchlist_cost_stop`（在 `run_risk_sell_signal` 末尾调用）。
  - **上证 MA10 清仓**：收在 MA10 下方时清自选池内仓，且须 **`non_atr_sell_start_hhmmss`**（默认约 **14:54**）之后、连续竞价，见 `run_index_liquidate_signal`。
- **ATR 止盈**：持仓 **盈利** 时，用日线窗口 + 多源现价抬升后的 **吊灯式回撤** 算止盈线，触发则卖（全天随 1m 评估）。**最低利润保护**（`_atr_profit_lock_floor_price`）：持仓日历天数 **`dh_cal` ≥ `atr_lock_floor_min_days`**（默认 **10**）且浮盈已超过 **`atr_lock_min_profit_dec`**（默认约 **15%**）时，抬高止损地板价。

---

## 4. QMT 使用前提

- 策略周期请选 **1 分钟**。
- 在策略参数或 `init` 里配置 **资金账号** `accountid` / `account_id`（代码内有默认占位，实盘务必改成自己的）。
- 需要 **talib**（ATR 计算）及行情接口正常。

---

## 5. `handlebar` 何时执行

- **实盘**：主逻辑在 **`C.is_last_bar()` 为真** 时跑（本根 1m K 已走完，数据相对稳定）。
- **回测**：若识别为回测上下文，或你设置了 **`C.handlebar_each_bar=True`**，则 **每根 1m** 都会进主逻辑（便于调试；日志会多）。
- **墙钟**：若当前墙钟 **不在 09:25–15:00**（与 `_session_gate_pass` 粗门控一致），会 **早退**：仍可能打 `[MIN]` 等轻量汇总，但 **不做完整买卖主流程**；`[MIN]` 里「今开/昨收」等仍按 **K 线 bar 的交易日** 算，不一定等于墙钟的「今天」。
- **异常隔离（主流程不中断整根 K 线）**：门控早退路径与主路径中，**自选池 / 持仓代码 / 换日重置 / 上证均线 / 卖单重试 / 主持仓代码** 等关键步骤各自 **`try/except`**，失败时打 **`[gate-early]` / `[pos_codes]` / `[pool]` / `[roll_day]` / `[sse_ma_state]`** 等带 `STRATEGY_TAG` 的日志并采用安全默认值。**`handlebar` 内层** `run_index…` / `run_risk…` / `run_pyramid…` 仍包在 **`try/except`**，异常时 **`handlebar ERR`** 与 **`_mr_set('执行异常…')`**。**`finally`** 中的 **`[MIN]` / `[MON]` / `[POS]`** 各自再包 **`try/except`**，避免某一汇总失败拖死另外两条；失败时打印 **`[emit MIN]` / `[emit MON]` / `[emit POS]`**（主路径）或 **`[emit MIN gate]`** 等（门控早退路径）。

---

## 6. 买入逻辑（概要）

- 自选池为候选；**已持有（含账户 + 策略记账）** 则不再重复开新。

### 6.0 买入分档条件（A / B / C / D）

分档只看 **当日缺口**（与昨收比），**不看**当前分钟价是否已回落（回落影响的是各档 **首买/加仓价格条件**，见 §6.1）。

**定义**（源码 `_gap_bracket`，回测同名逻辑一致）：

- `gap = 今开 / 昨收 - 1`（小数形式，如 `gap = 0.03` 表示今开较昨收 **+3%**）。
- `昨收`、**今开** 由 `_opc_get` 等得到，与 bar 上用于分档的口径一致。

**判断顺序**（与 `if` 链一致，**先匹配先定档**）：

| 档位 | 条件（`gap`） | 等价表述（今开相对昨收） | 边界说明 |
|------|----------------|--------------------------|----------|
| **D** | `gap ≤ -0.05` | 今开 ≤ 昨收 × **0.95**（低开不少于约 **5%**） | **-5%** 整点归 **D** |
| **A** | `gap < 0.03` 且未落入 D（即 **-0.05 < gap < 0.03**） | 昨收 × **0.95** ＜ 今开 ＜ 昨收 × **1.03** | 严格 **小于 +3%** 才是 A，故 **+3%** 不归 A |
| **B** | `gap < 0.07` 且非 D、非 A（即 **0.03 ≤ gap < 0.07**） | 昨收 × **1.03** ≤ 今开 ＜ 昨收 × **1.07** | 即 **[+3%, +7%)** |
| **C** | 其余（`gap ≥ 0.07`） | 今开 ≥ 昨收 × **1.07**（高开不少于约 **7%**） | **+7%** 起归 **C** |

代码等价（便于对照 `strategy_my_watchlist_intraday_atr_1m_live_signal.py` / 回测 `strategy_my_watchlist_intraday_atr.py`）：

```text
if gap <= -5%     → D
elif gap < +3%    → A
elif gap < +7%    → B
else               → C
```

- **名义比例**：各档三腿合计为单票预算 `per_stock_amount` 的 **50% + 30% + 20%**（D 档仅首买 50%，无加仓腿）。
- **时段**：`run_pyramid_and_entry_signal` 内，**有仓金字塔**默认仅在 **`_in_session_trade`**（约 **9:30–11:30、13:00–15:00**）执行；**例外**：若 **`a_first_buy_start_hhmmss < 93000`**，则在 **`a_first_buy_start_hhmmss ≤ hhmmss < 93000`** 时仍允许 **A 档**有仓金字塔或 **A 档无仓首买**（见 `_a_preopen_for_first_buy`）。**无仓首买**在上述集合末段仅 **A**；B/C/D 首买须从 **9:30 连续竞价** 起。`run_risk_sell_signal`（含全天昨收止损与尾盘成本止损）及 `run_index_liquidate_signal`（MA10 清仓）仅在 **`_in_session_trade`** 为真时进入主逻辑（集合竞价末段不按此路径卖）。
- **加仓锚点**：A / B / C 档的第二、三腿触发价均为 **相对今开** 的累计跌幅（见下表），**不以首买成交价**为锚。

### 6.1 各档首买与金字塔（与 `strategy_my_watchlist_intraday_atr.py` 对齐）

| 档位 | 首买条件（无仓） | 首买名义 | 第二腿（有仓，`leg_done[1]`） | 第三腿（`leg_done[2]`） |
|------|------------------|----------|--------------------------------|-------------------------|
| **A** | 须在 **`a_first_buy_start_hhmmss`～`a_first_buy_end_hhmmss`**（默认 **92500～102559**，即约 **9:25–10:25:59**）内；否则本日等待该窗口 | **50%** | 现价 ≤ **今开 ×0.95**（相对今开 **-5%**），**30%** | 现价 ≤ **今开 ×0.92**（**-8%**），**20%** |
| **B** | 现价 ≤ **今开 ×0.97**（相对今开 **-3%**） | **50%** | 现价 ≤ **今开 ×0.95**（**-5%**），**30%** | 现价 ≤ **今开 ×0.92**（**-8%**），**20%** |
| **C** | 现价 ≤ **今开 ×0.96**（相对今开 **-4%**） | **50%** | 现价 ≤ **今开 ×0.91**（**-9%**），**30%** | 现价 ≤ **今开 ×0.88**（**-12%**），**20%** |
| **D** | 无额外价格门槛（在允许时段内按现价首买） | **50%** | 无 | 无 |

- **HHMMSS 参数**：`92500` 表示 9:25:00；整数比较，与 bar 的 `hhmmss` 一致即可（配置为字符串 `"092500"` 时 `int()` 后仍为 `92500`）。
- **`anchor_buy`**：首买成交后仍会写入，供「有锚才跑金字塔」等判断；**B/C 加仓阈值已改为今开**（见上表）。

---

## 7. 卖出与风控（概要）

- **卖单监控范围**：以 **自选池** `g._mon_pool_codes` 为主；账户仓是否纳入与自选交集的风控卖，由 **`monitor_account_risk_sells`**（默认 True）控制。

### 7.1 全天：现价相对昨收（与成本无关）

- **条件**：`px_live / prev_ref - 1 ≤ intraday_touch_pct`，默认 **`intraday_touch_pct = -0.09`（−9%）**，便于在逼近跌停前留出挂单空间；**与持仓成本无关**。
- **昨收 `prev_ref`**：优先 `g.prev_close_ref[code]`（首买路径会写入），否则日线对齐后的 **`closes[-2]`**。
- **时段**：仅在 **`_in_session_trade`**（约 9:30–11:30、13:00–15:00）内，由 **`run_risk_sell_signal`** 评估。
- **候选集合 `cand`**：模拟仓在自选池内的代码 ∪（若 `monitor_account_risk_sells`）账户持仓代码 ∩ 自选池。
- **去重**：`g._intraday_prev_ref_stop_done` 存 `(规范代码, 交易日)`；**仅当 `_signal_sell_sim` 返回成功**才写入，下单失败当日可再试。
- **日志**：`tail_intraday_log` 为真时，首次越过阈值打 **`[昨收止损]`**（含阈值%、昨收、现价、当前跌幅）；卖单备注含「现价相对昨收…(全天)」。
- **状态**：`g.prev_close_stop_touch_day` 仅用于上述日志去重（换日由换日逻辑重置相关集合；清模拟仓时 `_clear_sim_stock` 会 `pop`）。

### 7.2 尾盘：现价相对成本（与昨收无关）

- **入口**：模块函数 **`_run_tail_watchlist_cost_stop`**，在 **`run_risk_sell_signal`** 每根处理完 `cand` 后调用。
- **时间门**：`hhmmss ≥ tail_clear_start_hhmmss`（默认 **145000**）且仍在 **`_in_session_trade`**。
- **范围**：遍历 **当日自选池** 全部代码；有账户或模拟持仓、且成本与现价有效时，判断 **`px_live / avg_c - 1 ≤ tail_cost_stop_pct`**。默认 **`tail_cost_stop_pct`** 等于 **`hard_stop_pct`（−0.08，即 −8%）**。
- **与 `[POS]` 一致**：盈亏比例与 **`_pnl_pct_vs_cost`** 同为 **现价/成本−1**（`[POS]` 显示为百分比数字 ×100）；成本取数路径与 **`_account_position_detail`** / **`_position_volume_and_avg`** 一致（若 `m_dOpenPrice` 为 0，账户明细里可能回退 **`m_dLastPrice`**，与纯 `[POS]` 偶有不一致，见源码注释）。
- **去重**：`g._tail_cost_stop_sold`，成功卖单后写入。

### 7.3 上证 MA10 清仓

- **`run_index_liquidate_signal`**：指数 **`index_liquidate_all`**（最新收 < MA10）为真时，须 **连续竞价** 且 **`_non_atr_sell_time_ok`**（`≥ non_atr_sell_start_hhmmss`，默认约 **14:54**），且 **`g._ma10_signal_latched`** 未占用；对自选池内账户仓与模拟仓发卖。

### 7.4 ATR 止盈

- 仅 **浮盈** 时 **`_check_atr_take_profit_only`** 可能触发卖；多源现价与 **`atr_ref_high_use_intraday`** 等见 §11.7。
- **最低利润保护**：**`atr_lock_floor_min_days`**（默认 **10**）与 **`atr_lock_min_profit_dec`**（默认 **0.15**）参与 **`_atr_profit_lock_floor_price`**，抬高 ATR 止损地板（详见源码 docstring）。

### 7.5 下单失败与日志

- **`[SELL]`**：在调用 **`passorder` 卖** 之前打印（含数量、成本、现价、盈亏%、原因）；**不代表柜台已接单**。
- **`passorder` 抛异常**：日志前缀为 **`STRATEGY_TAG`**（源码常量，如 **`我的自选分档建仓[实盘]`**）+ **`passorder ERR …`**。
- **`passorder` 返回 Python `False`**：同上前缀 + **`passorder 拒单/ret=False …`**（常见于拒单、T+1 不可卖等，取决于 QMT 返回值约定）。
- **下单返回 `False`（股数、未找到函数等）**：`**时间** 单边失败 代码 原因=…**`。
- **卖单未成撤单重试**：**`_process_sell_unfilled_cancel_retry`**（参数 **`sell_unfilled_timeout_sec`**、**`sell_unfilled_max_retry`**）；重挂失败有 **`[卖重挂]passorder失败`** 等日志。
- **成交回报**：**`[SELL-OK]`**（价、量、成本、盈亏%、金额、原因）。
- **自选板块删票**：若 **`auto_remove_sold_from_watchlist=True`**，在 **`[SELL-OK]`** 之后尝试 **`remove_stock_from_sector(板块名, 代码)`**，从 **`watchlist_sector_name`** 对应板块移除该票（与客户端「自选板块」一致时即等价于从自选删掉）。失败打 **`[自选移除ERR]`**；成功打 **`[自选移除OK]`**。

---

## 8. 策略参数一览（`init(C)` 从 `C` 读取）

以下为 **属性名** 与 **默认值/含义摘要**；默认值以源码 `getattr(C, '…', 默认)` 为准。

| 参数 | 默认（约） | 含义摘要 |
|------|------------|----------|
| `accountid` / `account_id` | 代码内占位 | 资金账号 |
| `accountType` / `account_type` | STOCK | 账户类型 |
| `watchlist_sector_name` | 我的自选 | 板块名 |
| `per_stock_amount` | 100000 | 单票预算（元） |
| `min_order_shares` | 100 | 最小交易单位 |
| `max_hold_count` | 0 | 最大同时持仓只数（含账户持仓与策略模拟持仓）；**0 或负数表示不限制**，正整数为上限 |
| `session_gate_prefer_bar_time` | True | **`True`（默认）**：粗门控「是否处 **9:25–15:00**」优先用 **K 线时间** `hhmmss`；夜间复盘/回放不会因本机墙钟不在盘中而整段跳过；设为 `False` 则仅用本机时钟（兼容旧习惯） |
| `a_first_buy_start_hhmmss` | 92500 | **A 档首买**允许的最早时刻（含边界）；若起点早于 93000，则 **9:25–9:30** 仅走 A 首买或已持仓 A 的金字塔 |
| `a_first_buy_end_hhmmss` | 102559 | **A 档首买**的最晚时刻（含边界）；默认约 **10:25:59**（与源码一致；加仓腿不受此窗限制） |
| `require_sse_above_ma5_for_new` | True | 上证收盘不低于 MA5 才开新仓 |
| `ma_index_period_short` / `long` | 5 / 10 | 指数均线周期 |
| `atr_period` | 14 | ATR 周期 |
| `atr_stop_mult` | 2.0 | 止盈距离 = ATR × 倍数 |
| `atr_ref_high_use_intraday` | True | HH 是否合并分时/现价等 |
| `bar_count` | 80 | 日线拉取根数 |
| `allow_atr_same_day` | True | **强烈建议实盘保持 True**。当日买入时，`dh_eff` 若为 0 会导致 ATR 无效、`[ATR-MON]` 备注为「持仓不满1日」。若设为 False，自选当日买入容易出现止损线全为 `--` |
| `atr_lock_floor_min_days` | 10 | **最低利润保护**生效所需持仓日历天数下限（`dh_cal ≥` 该值）；与 `_atr_profit_lock_floor_price` 一致 |
| `atr_lock_min_profit_dec` | 0.15 | 最低利润保护还要求当前浮盈 **>** 该小数（默认约 **+15%**） |
| `hard_stop_pct` | -0.08 | **尾盘成本止损**默认阈值：当未单独设置 **`tail_cost_stop_pct`** 时，**`tail_cost_stop_pct` 继承本值**；判断式为 **现价/持仓成本 − 1** |
| `tail_cost_stop_pct` | 继承 `hard_stop_pct` | 尾盘遍历自选时，**持仓亏损**达到该比例（小数）则卖；见 §7.2 |
| `intraday_touch_pct` | -0.09 | **全天**相对昨收：现价/昨收−1 ≤ 该值触发卖（默认 **−9%**）；**与成本无关** |
| `intraday_fail_recover_pct` | -0.06 | 仍从 `C` 读取并保存在 **`g`**，**当前版本卖出主路径未使用**（预留参数） |
| `tail_clear_start_hhmmss` | 145000 | **尾盘成本止损**开始评估的最早 `hhmmss`（默认 **14:50:00**） |
| `non_atr_sell_start_hhmmss` | 145400 | **`_non_atr_sell_time_ok`**：主要用于 **上证 MA10 清仓**等须在收盘前较晚时刻才评估的逻辑（默认约 **14:54**）；**不等于**尾盘成本止损的起始时刻 |
| `tail_intraday_log` | True | **`[昨收止损]`** 等全天相对昨收触阈首条日志开关（名称历史遗留，不仅「尾盘」） |
| `atr_intraday_log` | True | 每分钟 ATR 监控日志 |
| `atr_log_account_non_watchlist` | True | 自选外持仓是否打 ATR 日志（一般不自动卖） |
| `use_tick_first` | True | 取价优先 tick 等 |
| `signal_trace_log` | True | `[TRACE]` |
| `minute_summary_log` | True | `[MIN]` |
| `position_summary_log` | True | `[POS]` |
| `sell_monitor_summary_log` | True | `[MON]` 总览 |
| `monitor_account_risk_sells` | True | 账户仓是否纳入自选侧风控卖 |
| `block_same_day_rebuy_after_sell` | True | **当日**策略卖单成功后禁止对该票再**首买**（防「刚卖几分钟又首买」）；设为 `False` 恢复旧行为 |
| `auto_remove_sold_from_watchlist` | False | **`True`** 时：在 **`[SELL-OK]`**（卖单成交确认）后调用 QMT **`remove_stock_from_sector`**，从 **`watchlist_sector_name`** 所指板块中**删除该代码**（与客户端「我的自选」同源则即删自选）；默认 **关** 以免误删共用板块；需环境提供 `remove_stock_from_sector`（多在 `__main__`） |
| `handlebar_each_bar` | False | 强制每根 1m 执行（多用于回测） |
| `live_orders` | True | 是否真下单 |
| `strategy_order_name` | 自选分档 | 委托备注名（截断） |
| `quick_trade` | 2 | 下单快速参数 |
| `sell_unfilled_timeout_sec` | 60 | 卖单未成交超时（秒）后撤单重挂逻辑，见 **`_process_sell_unfilled_cancel_retry`** |
| `sell_unfilled_max_retry` | 0 | 重挂次数上限；**0** 表示不限制（与源码打印「无限」一致） |

---

## 9. 日志标签（控制台）

| 标签 | 大致含义 |
|------|----------|
| `[ORDER]` / `[ORDER][卖]` | 实盘 **`passorder`** 已调用或卖单重挂等 |
| `[SIGNAL]` | 非回测或未开 `live_orders` 时的信号说明 |
| `[SELL]` | 卖出意图与要素（在 **`passorder` 卖** 之前打印） |
| `[SELL-OK]` | 卖单成交回报（价、量、成本、盈亏%、金额、原因） |
| `[昨收止损]` | 全天相对昨收触阈首日志（受 `tail_intraday_log` 控制） |
| `[ATR-MON]` | ATR 与止盈线监控 |
| `[MIN]` / `[POS]` / `[MON]` | 分钟汇总、持仓汇总、监控总览 |
| `[TRACE]` | 细粒度跟踪 |
| `handlebar ERR` / `[风控卖异常]` | 主流程异常、单票风控循环异常 |
| `passorder ERR` / `passorder 拒单/ret=False` | 下单异常或显式返回 `False` |
| `[emit MIN]` / `[emit MON]` / `[emit POS]` | 汇总阶段单条输出失败（不阻断其它汇总） |
| `[gate-early]`、`[pos_codes]`、`[pool]` 等 | 主路径准备阶段子步骤失败时的带标签日志 |
| `[自选移除OK]` / `[自选移除ERR]` | 卖成后从板块移除成分成功/失败（需 `auto_remove_sold_from_watchlist=True`） |

---

## 10. 技术说明：`passorder` 与 `get_trade_detail_data`

QMT 常把 **`passorder`、`get_trade_detail_data`** 注入在 **`__main__`**，而不是策略模块的 `globals`。本策略用 **`_passorder_fn()` / `_get_trade_detail_data_fn()`** 统一从 `__main__` 或本模块全局取函数，避免 **NameError** 或 **取不到持仓价**（进而影响 ATR 现价合并）。

**`passorder` 返回值**：`_passorder_go` 在调用无异常时，若返回值为 Python **`False`**，会再打一行 **`passorder 拒单/ret=False …`** 并视下单失败（**`False`** 与 **`None`/缺省成功** 区分，避免误杀常见 void 返回）；仍依赖各 QMT 版本实际约定。

---

## 11. 封装函数说明（按逻辑分组）

以下为模块内 **`def`**：下划线前缀多为内部工具；**`handlebar` 内**另有三个 **嵌套函数**（每次进入 `handlebar` 时定义，仅供本轮调用链使用）。

### 11.1 QMT 接口封装

| 函数 | 作用 |
|------|------|
| `_passorder_fn` | 从 `sys.modules['__main__']` 或本模块 `globals` 取 `passorder`，避免 QMT 只把接口挂在主模块导致未定义。 |
| `_get_trade_detail_data_fn` | 同上取 `get_trade_detail_data`，供读持仓、账户 last 价等。 |

### 11.2 时间与序列工具

| 函数 | 作用 |
|------|------|
| `timetag_to_datetime` | 将 bar 的 timetag（毫秒或秒）格式化为 `YYYYMMDDhhmmss` 等字符串。 |
| `_ohlc_to_list` | 把行情 dict 里的 `high`/`low`/`close` 等列（含 pandas 序列）转成 `float` 列表。 |
| `_ohlc_time_list` | 从 `get_market_data_ex` 返回的 dict 取与 K 线对齐的时间列（多字段名兼容）。 |
| `_tag_to_yyyymmdd` | 将多种时间表示统一为 8 位交易日 `YYYYMMDD`，失败返回 `None`。 |
| `_m1_last_close` | 拉指定标的、截止 `dt_full` 的 **最新一根 1m** 收盘价。 |
| `_m1_last_high` | 同上取 **最新一根 1m** 最高价（用于抬价 / ATR 的 `ref_high`）。 |

### 11.3 日线顺序与今开昨收（OPC）

| 函数 | 作用 |
|------|------|
| `_daily_last_bar_date` | 由日线时间列与收盘列对齐，取最后一根 K 对应交易日。 |
| `_daily_bars_need_reverse` | 判断日线是否「最新在前」或相对现价误差暗示需 **整体反转** 才能时间升序。 |
| `_normalize_daily_hlc_order` | 截齐 `high/low/close` 长度后，必要时做整体反转。 |
| `_align_daily_ohlc_chronological` | 优先按 timetag 将 HLC 排成时间升序；若无可靠时间列则退回 normalize。 |
| `_prev_close_without_daily_time` | 无日线时间表时，用收盘价序列近似 **昨收**。 |
| `_opc_reset_day` | 换交易日后清空 `g._opc_map` 中今开昨收缓存。 |
| `_opc_get` | 按交易日缓存并返回 **今开、昨收**（经 `_opc_compute` 与 tick 覆盖），供 gap 分档、`[MIN]`、首买与 `_per_stock_watch_hint`。 |
| `_first_open_today_from_1m` | 从 1m 序列推断当日首次有效价，作 **今开** 参考。 |
| `_opc_compute` | 综合 tick、日线、1m 等计算今开、昨收并写入 `_opc_map`。 |

### 11.4 价格、Tick 与代码规范化

| 函数 | 作用 |
|------|------|
| `_parse_tick_scalar` | 在 tick 对象或 dict 上按多个候选字段名取 **第一个有效正数**。 |
| `_parse_tick_price` | 从 tick 取 **最新价**（多字段名兼容）。 |
| `_tick_pre_open` | 通过 `get_full_tick` 取 **昨收、今开**（若接口提供）。 |
| `_get_current_price` | 现价链：**tick_map → get_full_tick → `account_last`（可选）→ 最新 1m 收 → fallback_close**。 |
| `_canonical_stock_code` | 证券代码规范为 `600000.SH` / `000001.SZ` 等形式。 |
| `_normalize_position_code` | 将 QMT **持仓对象** 上的代码与交易所字段规范为全代码。 |

### 11.5 分档、指数、资金与盈亏

| 函数 | 作用 |
|------|------|
| `_snapshot_price_chg_open` | 返回 **(今开, 涨跌幅%, 现价)**；若传入 `opc` 则不再重复请求日线。 |
| `_sse_ma_state` | 拉 **000001.SH** 日线，算最新收、MA5/MA10，及「允许新开」「是否破 MA10」等。 |
| `_gap_bracket` | 由 `gap = 今开/昨收 - 1` 映射分档 **`A/B/C/D`**；阈值见 **§6.0**（`≤-5%` / `<+3%` / `<+7%` / 否则 C）。 |
| `_shares_for_cash` | 按现金、现价与 **最小交易单位** 算可买 **整手** 股数。 |
| `_avg_cost` | 从策略记账 `g` 算某标的 **平均成本**。 |
| `_pnl_pct_vs_cost` | 相对成本价的 **浮动盈亏百分比**。 |
| `_account_type` | 返回账户类型字符串（如 `STOCK`），供 `get_trade_detail_data` 等使用。 |

### 11.6 自选池与账户持仓

| 函数 | 作用 |
|------|------|
| `_pool_from_sector` | 用 `g.watchlist_sector_name` 调 `get_stock_list_in_sector`，规范化、去重、排序得到自选列表。 |
| `_remove_stock_from_sector_fn` | 从 `__main__` 或本模块取 **`remove_stock_from_sector`**（QMT 板块 API）。 |
| `_try_remove_sold_stock_from_watchlist_sector` | 在 **`auto_remove_sold_from_watchlist`** 为真时，从 **`watchlist_sector_name`** 板块移除已卖代码；由 **`_emit_sell_fill_success`** 在 **`[SELL-OK]`** 后调用。 |
| `_position_codes_from_account` | 账户中 **有量** 持仓的代码集合。 |
| `_account_position_detail` | 某标的：`(持仓量, 参考成本)`，无仓则 `(None, None)`。 |
| `_account_last_price_map` | 一次扫描账户持仓，得到 **规范代码 → `m_dLastPrice`**，供 `[MIN]`、ATR 现价与 `_live_px_max_for_atr` 复用。 |
| `_position_volume_and_avg` | **账户仓优先**，否则策略模拟仓：返回 `(股数, 均价)` 供卖与日志。 |

### 11.7 ATR 与日内高价

| 函数 | 作用 |
|------|------|
| `_intraday_high_since_open` | 当日从开盘到 `dt_full` 的 **1m high 最大值**（用于抬 `ref_high`）。 |
| `_live_px_max_for_atr` | 多路价格（`base_px`、tick_map、全推、**参数 `account_last`**、1m 收、1m high）取 **max**；`account_last` 由调用方从 `_account_last_price_map` 传入，避免函数内再扫一遍持仓。 |
| `_atr_trailing_stop_numbers` | 用 `talib.ATR` 与持有天数窗口、`ref_high` 算 **吊灯止损** 相关数值 `(stop, atr, hh_eff, err, hh_daily)`。 |
| `_atr_dynamic_mult` | 由持仓日历天数 **`dh_cal`** 对初始 ATR 倍数做衰减（半衰期 **`atr_stop_half_life_days`** 等），夹在 **`atr_stop_mult_min`** / **`atr_stop_mult_max`** 之间。 |
| `_atr_profit_lock_floor_price` | **最低利润保护**：`dh_cal ≥ atr_lock_floor_min_days` 且浮盈 **>** `atr_lock_min_profit_dec` 时返回抬高的 **止损地板价**；否则 **`None`**。 |
| `_atr_pack_for_position` | 汇总 **`_atr_stop_mult_for_hold_days`**、floor、`ref_high`、`dh_cal` 等供监控与止盈判断。 |
| `_check_atr_take_profit_only` | **仅浮盈** 时判断是否 **现价 ≤ ATR 止损线**，返回是否止盈及说明。 |
| `_emit_atr_mon_line` | 按分钟键去重后打一条 **`[ATR-MON]`**（盈亏%、止损线、缓冲 ATR 倍等）；**现=** 与传入的 **`px`** 一致，取价链为 **tick / 全推 / 持仓 `m_dLastPrice` / 1m**，**不用日线最后一根 `close` 作现价后备**（易与昨收/日收混淆）。 |
| `_emit_atr_non_watchlist_account_positions` | 对 **自选外** 账户持仓只打 **`[ATR-MON]`**，不触发本策略卖单。 |

### 11.8 日志与分钟汇总（MR）

| 函数 | 作用 |
|------|------|
| `_vb` | 读 `g.verbose_log`，控制部分详细打印是否输出。 |
| `_trace` | 若 `signal_trace_log` 开启，打印 **`[TRACE]`** 调试行。 |
| `_mr_set` | 写入本分钟汇总用字段：操作说明、股数、参考价（供 `_emit_minute_summary` 读取）。 |
| `_emit_minute_summary` | 打印 **`[MIN]`**：池、持仓、指数门控、候选首只、今开/昨收等；**现价**与 `[POS]` 一致，对**已有账户持仓**优先用持仓里的 **`m_dLastPrice`**，避免仅依赖 1m 末根 `close` 在数据滞后时看起来像昨收。 |
| `_emit_pos_line` | 打印单行 **`[POS]`**。 |
| `_emit_position_holdings` | 遍历账户与模拟仓，输出 **`[POS]`** 汇总。 |
| `_emit_monitor_unified_summary` | 打印 **`[MON]`**：自选池与账户持仓代码关系总览。 |
| `_per_stock_watch_hint` | **无持仓** 时，对自选首只打印监视提示（档位、等待条件等）。 |

### 11.9 下单、卖单与状态清理

| 函数 | 作用 |
|------|------|
| `_should_passorder` | 需 `live_orders`、`accid` 非空，且 **非** 回测上下文才允许真实 **`passorder`**。 |
| `_passorder_go` | 股数按最小单位向下取整后调用 `_passorder_fn()`；投资备注截断；**捕获异常**并识别 **`ret is False`** 拒单。 |
| `_run_tail_watchlist_cost_stop` | **尾盘**遍历自选池内有仓标的：**现价/成本−1 ≤ `tail_cost_stop_pct`** 则 **`_signal_sell_sim`**；依赖 **`tail_clear_start_hhmmss`** 与 **`g._tail_cost_stop_sold`** 去重。 |
| `_compact_sell_order_remark` | 生成实盘卖单 **`userOrderId`** 短备注（如 **`SL*`**），与 pending 字典键一致。 |
| `_stock_has_pending_sell` | 某代码是否已有未完结策略卖单（防重复 **`passorder` 卖**）。 |
| `_process_sell_unfilled_cancel_retry` | 扫描 **`g._sell_order_pending`**：超时未成交则撤单并重挂（受 **`sell_unfilled_*`** 参数约束）。 |
| `_emit_sell_fill_success` | 成交匹配后打 **`[SELL-OK]`** 并清理 pending。 |
| `_signal_buy_leg` | 一笔 **固定金额** 买腿：算股数、日志或 **`[ORDER]`** 买。 |
| `_print_sell_signal` | 打印 **`[SELL]`** 行并视 **`live_orders`** 调用 **`_passorder_go` 卖**；失败时 **`单边失败`** 并返回 **`False`**。 |
| `_signal_sell_sim` | 卖统一入口： pending 卖单去重、**`_print_sell_signal`**；回测/关单时可清 **`g`** 模拟仓。 |
| `_clear_sim_stock` | 清除某标的在 **`g`** 中的模拟持仓、分档、金字塔腿、**`prev_close_stop_touch_day`** 等状态。 |

### 11.10 时段与 bar 调度

| 函数 | 作用 |
|------|------|
| `_session_gate_pass` | 粗门控：K 线或墙钟时间是否在 **92500–150000**（默认与 A 档 9:25 首买窗口对齐）；不通过则早退主流程。 |
| `_in_session_trade` | 是否在 **连续竞价**：**93000–113000**、**130000–150000**（硬止损、风控卖、指数清仓、有仓金字塔（除 A 集合末段例外）等）。 |
| `_a_preopen_for_first_buy` | 当 **`a_first_buy_start_hhmmss < 93000`** 且 **`a_first_buy_start_hhmmss ≤ hhmmss < 93000`** 时为真：集合竞价末段 **仅 A** 无仓首买或 **已持仓且分档为 A** 的金字塔；与 `_session_gate_pass` 下限配合。 |
| `_a_first_buy_window_ok` | **A 档首买**是否落在 **`a_first_buy_start_hhmmss`～`a_first_buy_end_hhmmss`**（加仓腿不受此窗限制）。 |
| `_fmt_hhmmss_colon` | 将六位 `hhmmss` 格式化为 **`HH:MM:SS`** 供监视提示等。 |
| `_non_atr_sell_time_ok` | 当前 bar 的 **`hhmmss`** 是否 **≥ `non_atr_sell_start_hhmmss`**；用于 **上证 MA10 清仓**等；**尾盘成本止损**用 **`tail_clear_start_hhmmss`**，二者默认不同。 |
| `_fmt_non_atr_sell_start` | 将 `non_atr_sell_start_hhmmss` 格式化为 **`HH:MM`** 供日志。 |
| `_is_qmt_backtest_context` | 综合 `do_back_test`、`isDoBackTest`、`run_mode` 等判断是否 **回测**。 |
| `_handlebar_should_run` | 实盘通常仅 **`is_last_bar`**；回测或 **`handlebar_each_bar`** 则每根执行。 |

### 11.11 策略入口

| 函数 | 作用 |
|------|------|
| `init(C)` | 从 **`C`** 读入参数写入 **`g`**，初始化持仓/分档/日志闩锁等字典，打印初始化摘要。 |
| `handlebar(C)` | **主循环**：bar 去重、时间、自选池、墙钟早退、换日重置；准备阶段对 **池/持仓/指数/卖单重试** 等 **分散 `try/except`**；内层 **`try`** 依次调用指数清仓、风控卖（内含尾盘成本止损）、ATR 自选外日志、金字塔与开仓；**`finally`** 中 **`[MIN]` / `[MON]` / `[POS]`** 各自 **`try/except`**（见 §5）。 |
| `handleBar` / `handle_bar` | 兼容 QMT 命名，内部 **`handlebar(C)`**。 |

### 11.12 `handlebar` 内嵌套函数（每轮 handlebar 定义一次）

| 函数 | 作用 |
|------|------|
| `run_index_liquidate_signal` | 上证 **破 MA10** 时，对 **自选池内** 账户仓与模拟仓发卖（受 **`_non_atr_sell_time_ok`**、连续竞价与 **`g._ma10_signal_latched`** 限制）。 |
| `run_risk_sell_signal` | 自选池候选：**全天现价相对昨收**止损、**ATR 止盈**；末尾调用 **`_run_tail_watchlist_cost_stop`**（**尾盘现价相对成本**）。单票异常打 **`[风控卖异常]`**，不阻断其它票。 |
| `run_pyramid_and_entry_signal` | **有主仓**：金字塔加仓腿；**无仓** 且过门控：按 **A/B/C/D** 档做首买及后续腿。 |

---

## 12. 维护建议

- 改规则时 **优先改回测脚本** 并对齐本实盘文件，避免两边漂移。
- 若本说明与源码不一致，**以源码为准**，并请更新本 MD。
- 新增或重命名函数时，请同步更新 **第 11 节** 表格。
