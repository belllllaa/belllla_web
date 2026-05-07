# 实盘策略说明：`strategy_my_watchlist_intraday_atr_1m_live_signal.py`

本文说明与解释对应 Python 文件的行为、参数与日志，**策略源码内仅保留极简注释**；细节以本 Markdown 为准。**各封装函数含义见第 11 节。**

---

## 1. 策略做什么（一句话）

在 **QMT 1 分钟 K 线** 上，从 **自选板块** 取股票池，按 **开盘涨跌幅分档** 做 **分批买入**，用 **上证指数 T-1 的 MA5 门控**（开新仓）与 **指数均线条件清仓**（`index_liquidate_ma_period`，默认 **5** 日，可理解为「破 MA5」式清仓）等；卖出侧默认 **`sell_engine_mode=grid_d3`**：以 **手工 CSV 中的开仓日** 锚定 **D0 开盘价**，按 **网格止损/止盈价** 与 **当日 1m 累计高/低** 做触价判断，并含 **D1 不强、转弱、到期** 等规则；与 **`legacy`** 模式下的 **全天昨收触价、尾盘成本/MA5、ATR 止盈** 等并存或按模式切换。满足条件时在实盘下 **`passorder`** 下单，否则只打 **`[SIGNAL]`** / **`[ORDER]`** 相关日志。

---

## 2. 和哪些文件对齐

| 关系 | 路径 |
|------|------|
| 规则与参数对齐（回测） | `qmt/回测策略/strategy_my_watchlist_intraday_atr.py` |
| bar 调度思路参考 | `qmt/实盘策略/strategy_sideways_breakout_sz_ma240_1m_live.py`（`is_last_bar`、墙钟门控等） |

---

## 3. 名词解释（你之前问的 `\u…` 解码后就是这些）

- **自选**：股票池来自 QMT 板块，默认板块名 **`我的自选`**（可用参数 `watchlist_sector_name` 改）。
- **当日卖出后不回补**：默认 **`block_same_day_rebuy_after_sell=True`**：只要本策略 **`_signal_sell_sim` 成功走通卖单**（含实盘挂单、回测信号卖），该规范代码记入 **`g._same_day_sold_canon`**；同一交易日内不仅 **首买** 会拦截，统一买入口 **`_signal_buy_leg`** 也会拦截（含金字塔加腿），即当日不再买回；换日后集合清空。若你在客户端**手工卖出**而未经过本策略卖逻辑，**不会**自动记入该集合。
- **分档**：用 **今开 / 昨收 − 1** 得到开盘缺口 `gap`，再划到 A/B/C/D 档；不同档 **首笔买入比例、触发价、加仓腿** 不同（细节与回测策略文档一致）。
- **开仓 / 买入**：在门控通过时，按分档与金字塔逻辑 **`passorder` 买入**（受 `live_orders`、资金账号、非回测等约束）。
- **上证 MA5 开新仓门控**（`require_sse_above_ma5_for_new`，默认开）：指数 **000001.SH** 日线。比较的是 **上一完整交易日（T-1）的收盘价** 与 **同一日 T-1 的日线 MA5**（最近 5 根**已完成**日 K 的收盘均值，窗口以 T-1 为最后一根；若日线最后一根已是当日未收市 K，则 T-1 取倒数第二根）。**T-1 收 ≥ T-1 的 MA5** 才允许当日 **无仓首买**（仍受其它门控与时段约束）。**换日时**清空当日闩锁；**首次**出现 bar 的 `hhmmss ≥ sse_ma5_gate_latch_hhmmss`（默认 **93000**，即连续竞价开盘后第一根满足条件的 K）时，将上述比较结果 **冻结**，当日后续 bar **不再重算**该布尔门控（9:30 前若已进入主流程，仍用同一 T-1 公式，与冻结值一致）。详见 **§6.2**。
- **手工开仓 CSV（持仓日历 / 网格 D0）**：默认启用 **`use_manual_hold_days_csv`**，在 **`open_date_csv_path`**（或 **`manual_open_date_csv`**，缺省时解析策略目录旁 **`manual_open_date_my_holdings.csv`** / 环境变量 **`MANUAL_OPEN_DATE_CSV`**）中读取每只票的 **开仓日 YYYYMMDD**。用于：**持仓天数**、**grid_d3 的 D0 开盘价锚点**、**`[POS]` 网格止损/止盈价**。开仓日须落在 **`get_market_data_ex` 日线窗口**（见 **`bar_count`**）内，否则网格解析失败。
- **风控卖（概要；细则见 §7）**：
  - **`grid_d3`（默认）**：连续竞价内 **`run_risk_sell_signal`** — **昨收止损**后进入网格：**开盘**对照 **止损价 = D0×(1+grid_stop_loss_pct)**、**止盈价 = D0×(1+grid_take_profit_pct)**（默认 **−10% / +6.5%**）；盘中用 **日线当日 bar 低/高** 与 **`_intraday_low_since_open` / `_intraday_high_since_open`**（1m 全日）**取 min/max 合并** 后与触价线比较；可选 **`grid_intraday_*`** 覆盖盘中触价比例。**收盘类网格规则**（D1 不强、转弱、到期/超期）仅在 **`hhmmss ≥ tail_clear_start_hhmmss`**（默认 **14:50**）后评估，避免盘中误触发。**`grid_d3` 不会在 `run_risk_sell_signal` 末尾调用 `_run_tail_watchlist_cost_stop`**（无「第 N 天弱势 / 尾盘成本线 / 尾盘 MA」那条 legacy 尾盘链）。
  - **全天·相对昨收**：**现价 / 昨收 − 1 ≤ `intraday_touch_pct`**（默认 **−5%**）。**`simple_log_mode=True`**（默认）会把 **`tail_intraday_log` 置假**，往往看不到 **`[昨收止损]`**。
  - **`hard_stop_pct`（默认 −5%）**：**不作为**独立「全天成本卖单」条件；主要用于 **`[ATR-MON]`** 备注里拼接**硬止损参考线**。持仓相对成本的亏损卖在 **`legacy`** 下由尾盘函数 **`_run_tail_watchlist_cost_stop`** 用 **`tail_cost_stop_pct`**（默认同为 **−5%**，可单独配）实现。
  - **尾盘·`_run_tail_watchlist_cost_stop`**：**仅 `sell_engine_mode=legacy`** 时在 **`run_risk_sell_signal` 末尾**调用。自 **`tail_clear_start_hhmmss`** 起顺序：**③** 持仓天数 ≥ **`third_day_tail_clear_days`** 且浮盈 < **`third_day_tail_clear_min_pnl`**；否则 **①** **现价/成本 − 1 ≤ `tail_cost_stop_pct`**；否则 **②** **`tail_sell_below_ma5`** 时 **现价 < 估计 MA**。
  - **上证指数均线清仓**：**最新一根日线收 < 最近 N 日收盘均**（**N = `index_liquidate_ma_period`**，默认 **5**）时 `index_liquidate_all` 为真；须连续竞价、**`≥ non_atr_sell_start_hhmmss`** 且 **`≥ tail_clear_start_hhmmss`**，**`run_index_liquidate_signal`** 每轮一次。与 **§6.2 的 T-1 MA5 开新仓门控** 不是同一条比较（门控用 T-1 整根，清仓用**含当日的**最后一根收 vs 短期均）。
- **ATR 止盈**：自选池内在 **`hhmmss ≥ tail_clear_start_hhmmss`**（默认 **14:50**）之后才 **`_check_atr_take_profit_only`** 并可能 **`passorder` 卖**（与 **`atr_take_profit_tail_only`** 初始化打印一致；持仓 **盈利**、吊灯线与 **`atr_ref_high_use_intraday`** 等见 §11.7）。**最低利润保护**见 **`_atr_profit_lock_floor_price`**。

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
- **时段**：`run_pyramid_and_entry_signal` 内，**有仓金字塔**默认仅在 **`_in_session_trade`**（约 **9:30–11:30、13:00–15:00**）执行；**例外**：若 **`a_first_buy_start_hhmmss < 93000`**，则在 **`a_first_buy_start_hhmmss ≤ hhmmss < 93000`** 时仍允许 **A 档**有仓金字塔或 **A 档无仓首买**（见 `_a_preopen_for_first_buy`）。**无仓首买**在上述集合末段仅 **A**；B/C/D 首买须从 **9:30 连续竞价** 起。`run_risk_sell_signal`（昨收止损、**`grid_d3`** 网格与 ATR、**`legacy`** 另含 `_run_tail_*`）及 `run_index_liquidate_signal`（指数均线清仓）仅在 **`_in_session_trade`** 为真时进入主路径（集合竞价末段不按此路径卖；**`grid_d3`+极简** 在非交易时段可打 **`[GRID]`**）。
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

### 6.2 上证 MA5 开新仓门控（T-1 + 当日冻结）

- **标的**：上证指数 **`000001.SH`** 日线（`get_market_data_ex`，`period='1d'`），经 **`_align_daily_ohlc_chronological`** 时间升序对齐。
- **T-1 定位**：**`_sse_t1_close_index`**：若最后一根日线日期等于当前 K 线交易日 `d_str`（视为含当日未收市 K），则 T-1 为 **倒数第二根**；否则最后一根即为上一完整交易日。
- **MA5**：在 T-1 上取 **含 T-1 在内** 的最近 **`ma_index_period_short`（默认 5）** 根收盘的算术均值。
- **允许开新仓**（仅影响 **`run_pyramid_and_entry_signal`** 里 **无仓首买**；**有仓金字塔**仍先执行，与 MA5 门控无交叉判断）：**T-1 收 ≥ T-1 的 MA5**。日线不足 5 根落在 T-1 上时，源码对该门控 **放行**（`allow_new=True`）。
- **当日冻结**：换日时重置 **`g._sse_ma5_gate_latched` / `g._sse_ma5_gate_frozen_allow`**。当本根 **`hhmmss ≥ sse_ma5_gate_latch_hhmmss`**（默认 **93000**）且尚未闩锁时，将当前 T-1 比较得到的布尔值写入冻结变量并闩锁；**当日后续 bar** 使用该冻结值，避免盘中因「当日未完成日 K 进入序列」而反复改写门控。
- **关闭门控**：设 **`require_sse_above_ma5_for_new=False`**（或 `C` 传入等价）则始终允许首买（仍受其它条件限制）。
- **与指数清仓**：**清仓条件**用 **最后一根日线收**（可含当日）与 **`index_liquidate_ma_period`（默认 5）** 日均比较；与 **T-1 MA5 门控** 不是同一公式，见 **§7.3**。

---

## 7. 卖出与风控

- **卖单监控范围**：以 **自选池** `g._mon_pool_codes` 为主；账户仓是否纳入与自选交集的风控卖，由 **`monitor_account_risk_sells`**（默认 True）控制。
- **连续竞价**：**`run_risk_sell_signal` / `run_index_liquidate_signal`** 等主卖逻辑仅在 **`_in_session_trade(hhmmss)`** 为真时执行（约 **9:30–11:30、13:00–15:00**）。**非交易时段**早退时，**`grid_d3` + `simple_log_mode`** 下仍可能对持仓打 **`[GRID]`** 探针（用于核对 D0/止损/止盈价）。

### 7.0 卖出引擎 `sell_engine_mode`

| 值 | 含义 |
|----|------|
| **`grid_d3`（默认）** | 在 **`_grid_resolve_d0_and_day_idx`** 成功时：按 D0 与 **D 序 day_idx** 做 **开盘止损/开盘止盈**、**盘中最低/最高触价**（日线 bar 与 **1m 全日** 合并，与 `[POS]` 同源思路）、**尾盘** **D1 不强、转弱、到期/超期** 等。触价用 **`grid_stop_loss_pct` / `grid_take_profit_pct`**；若设置 **`grid_intraday_stop_loss_pct` / `grid_intraday_take_profit_pct`** 则盘中触价改为该比例。参数 **`grid_strong_threshold_pct`、`grid_max_hold_day`、`grid_weaken_threshold_pct`** 见 `init(C)`。 |
| **`legacy`** | 不跑上述网格分支；**`run_risk_sell_signal` 末尾**仍调用 **`_run_tail_watchlist_cost_stop`**（尾盘成本/MA5/第 N 天弱势清仓）。 |

### 7.1 全天：现价相对昨收（与成本无关）

- **条件**：`px_live / prev_ref - 1 ≤ intraday_touch_pct`，默认源码 **`intraday_touch_pct = -0.05`（−5%）**；**与持仓成本无关**。
- **昨收 `prev_ref`**：优先 `g.prev_close_ref[code]`，否则日线对齐后的 **`closes[-2]`**。
- **时段**：连续竞价内 **`run_risk_sell_signal`**。
- **去重 / 日志**：`g._intraday_prev_ref_stop_done`；**`tail_intraday_log`** 在 **`simple_log_mode=True`** 时会被置 **`False`**，可能看不到 **`[昨收止损]`**。

### 7.2 尾盘 `_run_tail_watchlist_cost_stop`（仅 `sell_engine_mode=legacy`）

- **前提**：源码仅在 **`legacy`** 时于 **`run_risk_sell_signal` 末尾**调用；**`grid_d3` 不执行本段**。
- **时间门**：`hhmmss ≥ tail_clear_start_hhmmss`（默认 **145000**）且 **`_in_session_trade`**。
- **评估顺序**（同一次循环每票最多一次卖出）：先 **③** **持仓天数（`_stock_hold_days`）≥ `third_day_tail_clear_days`**（默认 **3**）且 **浮盈 < `third_day_tail_clear_min_pnl`**（默认 **0.05**）→ 弱势清仓；否则 **①** **现价/成本 − 1 ≤ `tail_cost_stop_pct`**（默认 **−5%**，与 **`hard_stop_pct` 默认相同**）；否则 **②** **`tail_sell_below_ma5`** 时 **现价 < 估计 MA**。
- **去重**：`g._tail_cost_stop_sold`。

### 7.3 上证指数均线清仓（`index_liquidate_ma_period`）

- **`_sse_ma_state`**：`index_liquidate_all = (最新日线收 < MA(N))`，**N = `index_liquidate_ma_period`**（默认 **5**）。
- **`run_index_liquidate_signal`**：须 **`index_liquidate_all`**、**连续竞价**、**`hhmmss ≥ non_atr_sell_start_hhmmss`**（默认 **145400**）、**`hhmmss ≥ tail_clear_start_hhmmss`**（默认 **145000**）、**`g._ma10_signal_latched`** 未占用（变量名历史遗留，实际对应「指数清仓已占用」闩锁）。

### 7.4 ATR 止盈（自选池内）

- **`[ATR-MON]`** 可在盘中打印；**实际发卖**前须 **`hhmmss ≥ tail_clear_start_hhmmss`**（与 **`atr_take_profit_tail_only`** 默认 **True** 的设计一致）。仅 **浮盈** 时 **`_check_atr_take_profit_only`** 可能为真。
- **最低利润保护**：**`atr_lock_*`**，见 **`_atr_profit_lock_floor_price`**。

### 7.5 `[POS]` 持仓行：当日低/高与网格价

- **当日低 / 当日高**：**`_grid_today_low_high_for_stock`** — 优先 **`_intraday_session_high_low_pair`**（同一次请求拉 **1m high+low**，**`_intraday_session_end_dt`** 将盘后 bar 的 **`end_time` 截到当日 15:00**）；**深市**若 timetag 与 K 线数量不一致或日期筛空，在 **同日 9:30–15:00 窗口** 内退化为 **窗口内全部 1m** 求 **min(low)/max(high)**。日线仅作补充：**`_daily_raw_hl_for_trade_date`** 要求日线 **timetag 精确等于当日 `d_str`**，**不再**用易误判的「最后一根」索引。**不再**用现价扩区间（避免盘后「高=收盘」）。
- **网格止损价 / 网格止盈价**：**`_grid_pos_tp_sl_prices`** — **D0×(1+sl)**、**D0×(1+tp)**，盘中比例可被 **`grid_intraday_*`** 覆盖。若 **`_grid_resolve_d0_and_day_idx`** 失败（CSV 无票、开仓日不在日线窗口等）则显示 **`--`**，**与是否在交易时段无关**。
- **`[MON]`** 提示当日低/高及网格价见 **`[POS]`**。

### 7.6 下单失败与日志

- **`[SELL]` / `[ORDER]` / `[SELL-OK]`**：卖出原因统一为三段：**`规则类`**（指数 / 风控 / 网格 / 尾盘 / 止盈）、**`规则项`**（如上证 MA*N* 清仓、昨收止损、网格开盘/盘中止损止盈、ATR 吊灯、**legacy** 尾盘成本/跌破均线）、**`详情`**（阈值、止盈线、m、现价与 MA 等）；源码由 **`_fmt_sell_rule`** 编码，`_sell_rule_parts` 解析。**不代表柜台已接单**。
- **`passorder` 抛异常**：日志前缀为 **`STRATEGY_TAG`**（源码常量，如 **`我的自选分档建仓[实盘]`**）+ **`passorder ERR …`**。
- **`passorder` 返回 Python `False`**：同上前缀 + **`passorder 拒单/ret=False …`**（常见于拒单、T+1 不可卖等，取决于 QMT 返回值约定）。
- **下单返回 `False`（股数、未找到函数等）**：`**时间** 单边失败 代码 原因=…**`。
- **卖单未成撤单重试**：**`_process_sell_unfilled_cancel_retry`**（参数 **`sell_unfilled_timeout_sec`**、**`sell_unfilled_max_retry`**）；重挂失败有 **`[卖重挂]passorder失败`** 等日志。
- **成交回报**：**`[SELL-OK]`**（价、量、成本、盈亏%、金额及 **`规则类|规则项|详情`**）。
- **自选板块删票**：若 **`auto_remove_sold_from_watchlist=True`**，在 **`[SELL-OK]`** 之后尝试 **`remove_stock_from_sector(板块名, 代码)`**，从 **`watchlist_sector_name`** 对应板块移除该票（与客户端「自选板块」一致时即等价于从自选删掉）。失败打 **`[自选移除ERR]`**；成功打 **`[自选移除OK]`**。

---

## 8. 策略参数一览（`init(C)` 从 `C` 读取）

以下为 **属性名** 与 **默认值/含义摘要**；默认值以源码 `getattr(C, '…', 默认)` 为准。

| 参数 | 默认（约） | 含义摘要 |
|------|------------|----------|
| `accountid` / `account_id` | 代码内占位 | 资金账号 |
| `accountType` / `account_type` | STOCK | 账户类型 |
| `watchlist_sector_name` | 我的自选 | 板块名 |
| `per_stock_amount` | 200000 | 单票预算（元） |
| `min_order_shares` | 100 | 最小交易单位 |
| `max_hold_count` | 0（固定） | 当前版本在代码内固定为 **0=不限制**，不再读取 `C.max_hold_count` |
| `session_gate_start_hhmmss` | 92500 | 粗门控起始（与 A 档集合竞价首买窗口对齐）；见 **`_session_gate_pass`** |
| `session_gate_prefer_bar_time` | True | **`True`（默认）**：粗门控「是否处 **9:25–15:00**」优先用 **K 线时间** `hhmmss`；夜间复盘/回放不会因本机墙钟不在盘中而整段跳过；设为 `False` 则仅用本机时钟（兼容旧习惯） |
| `a_first_buy_start_hhmmss` | 92500 | **A 档首买**允许的最早时刻（含边界）；若起点早于 93000，则 **9:25–9:30** 仅走 A 首买或已持仓 A 的金字塔 |
| `a_first_buy_end_hhmmss` | 102559 | **A 档首买**的最晚时刻（含边界）；默认约 **10:25:59**（与源码一致；加仓腿不受此窗限制） |
| `require_sse_above_ma5_for_new` | True | **上证 MA5 开新仓门控**：为真时，须 **T-1 日收 ≥ T-1 日线 MA5** 才允许当日 **无仓首买**；`False` 可关闭。见 **§3**、**§6.2** |
| `sse_ma5_gate_latch_hhmmss` | 93000 | **首次**达到该 `hhmmss`（含）的 bar 将当日 MA5 门控结果 **冻结**至换日；若希望与集合竞价末段对齐可改为 **92500** 等 |
| `ma_index_period_short` | 5 | **开新仓门控**：T-1 收 vs T-1 MA(short) |
| `ma_index_period_long` | 10 | **`_sse_ma_state`** 拉上证日线：`count = max(ma_index_period_long, 15)`，保证有足够 K 算均线 |
| `index_liquidate_ma_period` | 5 | **指数清仓**：最后一根收 vs 最近 N 日均（默认 **5**） |
| `atr_period` | 14 | ATR 周期 |
| `atr_stop_mult` | 2.5 | ATR 动态倍数的初始值（`atr_stop_mult_initial` 未单设时继承） |
| `atr_stop_mult_min` / `atr_stop_mult_max` | 1.0 / 2.2 | ATR 动态倍数夹紧区间 |
| `atr_stop_half_life_days` | 7 | ATR 动态倍数从起点衰减到下限的参考半衰期（天） |
| `atr_ref_high_use_intraday` | True | HH 是否合并分时/现价等 |
| `bar_count` | 80 | 日线拉取根数 |
| `allow_atr_same_day` | True | **强烈建议实盘保持 True**。当日买入时，`dh_eff` 若为 0 会导致 ATR 无效、`[ATR-MON]` 备注为「持仓不满1日」。若设为 False，自选当日买入容易出现止损线全为 `--` |
| `atr_lock_floor_min_days` | 7 | **最低利润保护**生效所需持仓日历天数下限（`dh_cal ≥` 该值）；与 `_atr_profit_lock_floor_price` 一致 |
| `atr_lock_min_profit_dec` | 0.15 | 最低利润保护还要求当前浮盈 **≥** 该小数（默认 **+15%**） |
| `atr_lock_ratio_base` / `slope` / `cap` | 0.60 / 0.025 / 0.97 | 保护比例曲线：`lock_ratio=min(cap, base+slope*dh)`；值越大，保底线抬得越高，锁利润越强 |
| `hard_stop_pct` | -0.05 | **不触发**独立全天卖单；用于 **`[ATR-MON]`** 备注中的硬止损参考线；与 **`tail_cost_stop_pct`** 默认数值一致 |
| `tail_cost_stop_pct` | -0.05 | **仅 `legacy`**：**`_run_tail_watchlist_cost_stop`** 中相对成本止损阈值；见 §7.2 |
| `intraday_touch_pct` | -0.05 | **全天**相对昨收：现价/昨收−1 ≤ 该值触发卖；**与成本无关** |
| `sell_engine_mode` | `grid_d3` | `grid_d3`：网格 D0 + 触价 + 网格尾盘规则；`legacy`：不跑网格分支，但末尾跑 **`_run_tail_watchlist_cost_stop`** |
| `grid_stop_loss_pct` / `grid_take_profit_pct` | -0.10 / 0.065 | 开盘与盘中触价基准（除非设 **`grid_intraday_*`**） |
| `grid_intraday_stop_loss_pct` / `grid_intraday_take_profit_pct` | `None` | 非 `None` 时覆盖盘中触价所用比例 |
| `grid_strong_threshold_pct` | 0.005 | D1「不强」阈值（现价 vs D0×(1+该值)） |
| `grid_max_hold_day` | 3 | 网格持有天数上限（D 序） |
| `grid_weaken_threshold_pct` | 0 | 「转弱卖出」相对前收的带宽 |
| `simple_log_mode` | True | 为真时关闭 **`tail_intraday_log` / `atr_intraday_log` / `signal_trace_log`** 等噪音，保留 MIN/POS/MON/**GRID** 与买卖信号 |
| `third_day_tail_clear_days` | 3 | **仅 legacy** 尾盘：持仓天数 ≥ 此值且浮盈不足则卖 |
| `third_day_tail_clear_min_pnl` | 0.05 | **仅 legacy** 尾盘：弱势清仓要求的最低浮盈（小数） |
| `atr_take_profit_tail_only` | True | 为真时 **`_check_atr_take_profit_only`** 仅在 **`hhmmss ≥ tail_clear_start`** 后可能 **`passorder` 卖** |
| `use_manual_hold_days_csv` | True | 手工开仓 CSV：持仓日历与 **`_grid_resolve_d0_and_day_idx`** |
| `open_date_csv_path` / `manual_open_date_csv` | — | 见 §3「手工开仓 CSV」；缺省解析策略目录旁 CSV 或环境变量 **`MANUAL_OPEN_DATE_CSV`** |
| `tail_clear_start_hhmmss` | 145000 | **14:50** 起：网格 **D1 不强 / 转弱 / 到期** 等收盘规则、**`legacy`** 的 **`_run_tail_*`**、**ATR 实际卖单**（`atr_take_profit_tail_only` 默认开）均依赖该门限 |
| `tail_sell_below_ma5` | True | **尾盘**若 **现价 < 当日估计的日线 MA(`tail_ma5_period`)** 则卖（与成本无关）；`False` 关闭 |
| `tail_ma5_period` | 5 | 尾盘 MA 周期（默认 **5**，即 MA5）；须 ≥2 |
| `non_atr_sell_start_hhmmss` | 145400 | **`_non_atr_sell_time_ok`**：主要用于 **指数均线清仓**等须在收盘前较晚时刻才评估的逻辑（默认约 **14:54**）；**不等于** `tail_clear_start` |
| `tail_intraday_log` | True | **`[昨收止损]`** 等全天相对昨收触阈首条日志开关（名称历史遗留，不仅「尾盘」） |
| `atr_intraday_log` | True | 每分钟 ATR 监控日志 |
| `atr_log_account_non_watchlist` | True | 自选外持仓是否打 ATR 日志（一般不自动卖） |
| `use_tick_first` | True | 取价优先 tick 等 |
| `signal_trace_log` | True | `[TRACE]` |
| `minute_summary_log` | False | `[MIN]`；**回测**或 **`handlebar_each_bar=True`** 时 `init` 会额外提示「每根打 MIN」 |
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
| `sell_unfilled_max_retry` | 0（固定） | 当前版本代码内固定 **无限重挂**；卖单撤单/未同步超时后都会继续重挂直到成交或无可卖数 |

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
| `[GRID]` | **`grid_d3`**：每分钟至多一条的 **D0 / 止损价 / 止盈价 / 现价** 锚定快照；连续竞价内 **`_emit_grid_anchor_line`**；非交易时段在满足 **`simple_log_mode`** 与早盘墙钟门控时也可能输出探针 |
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

### 11.4.1 网格 D0、POS 当日区间与 `[GRID]`

| 函数 | 作用 |
|------|------|
| `_grid_resolve_d0_and_day_idx` | 用手工 CSV 开仓日与日线对齐，得到 **D0 开盘价**、**当日在日序列中的下标**、**D 序 day_idx**；失败返回 **`None`**（网格价、`[GRID]` 常为 **`--`**）。 |
| `_grid_pos_tp_sl_prices` | **`[POS]`** 行：**网格止损价 / 网格止盈价** = **D0×(1+sl/tp)**，`grid_intraday_*` 非空时盘中比例用其覆盖。 |
| `_grid_today_low_high_for_stock` | **`[POS]`** 行：**当日低 / 当日高**；内部 **`_intraday_session_high_low_pair`**（同拉 **high+low**）+ **`_daily_raw_hl_for_trade_date`** 补充；**不用现价扩区间**。 |
| `_intraday_session_end_dt` | 将 **`end_time` 截至当日 **15:00:00**，避免盘后分钟 bar 污染汇总。 |
| `_intraday_session_high_low_pair` | 多种 **1m** 请求规格下求 **min(low)/max(high)**，依赖 **`_intraday_pick_idxs_for_session`**。 |
| `_intraday_pick_idxs_for_session` | 按交易日筛 1m 索引；timetag 与 K 数不等时，若窗口覆盖单日或 **end+count** 满足 **`_spec_endtime_same_day_bounded`**，则退化为**当日全部 1m**（缓解深市 **H=L**）。 |
| `_spec_covers_single_trade_day` / `_spec_endtime_same_day_bounded` | 判断请求是否**单日连续竞价窗**或 **end_time+count 全日分钟量** 可信。 |
| `_daily_raw_hl_for_trade_date` | 日线 **timetag 精确等于 `d_str`** 的 **low/high**；无匹配则不用「最后一根」误配。 |
| `_intraday_low_since_open` / `_intraday_high_since_open` | **1m 全日**最低/最高（**`grid_d3` 盘中触价**与日线 bar **合并**用；与 `_intraday_session_high_low_pair` 思路一致、请求形态略简）。 |
| `_emit_grid_anchor_line` | 打 **`[GRID]`**；每票每自然分钟键去重。 |

### 11.5 分档、指数、资金与盈亏

| 函数 | 作用 |
|------|------|
| `_snapshot_price_chg_open` | 返回 **(今开, 涨跌幅%, 现价)**；若传入 `opc` 则不再重复请求日线。 |
| `_sse_t1_close_index` | 在上证日线升序 `closes` 上求 **T-1** 的下标（最后一根若为当日则取倒数第二根）。 |
| `_sse_ma_state` | 拉 **000001.SH** 日线：返回 **(T-1 收, T-1 MA5, MA(N) 清仓线, 允许开新仓, index_liquidate_all)**；**N = `index_liquidate_ma_period`（默认 5）**。**index_liquidate_all** =（**最后一根收 < 最近 N 日收盘均**）。**允许开新仓** 由 T-1 收 vs T-1 MA5 决定并在 **`sse_ma5_gate_latch_hhmmss`** 起冻结当日。 |
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
| `_atr_dynamic_mult` | 由持仓日历天数 **`dh_cal`** 在区间 **`[atr_stop_mult_min, atr_stop_mult_max]`** 内做平滑衰减（参考 `half_life` 天由起点降到下限），避免长期卡在上限。 |
| `_atr_profit_lock_floor_price` | **最低利润保护**：`dh_cal ≥ atr_lock_floor_min_days` 且浮盈 **≥** `atr_lock_min_profit_dec` 时返回抬高的 **止损地板价**；否则 **`None`**。 |
| `_atr_pack_for_position` | 汇总 **`_atr_stop_mult_for_hold_days`**、floor、`ref_high`、`dh_cal` 等供监控与止盈判断。 |
| `_check_atr_take_profit_only` | **仅浮盈** 时判断是否 **现价 ≤ ATR 止损线**，返回是否止盈及说明。 |
| `_emit_atr_mon_line` | 按分钟键去重后打一条 **`[ATR-MON]`**（盈亏%、止损线、**保底线**、缓冲 ATR 倍等）；展示价用 `px_display`（实时价），ATR 判定价用 `px`（可为多源 max）。 |
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
| `_stock_ma_tail_live` | 估计盘中 **日线 MA(n)**（末根为当日则用现价替换该根收盘）。 |
| `_run_tail_watchlist_cost_stop` | **仅 `legacy` 调用**（见 **`run_risk_sell_signal` 末尾**）。**尾盘**（≥`tail_clear_start`）遍历自选：先 **③** 第 N 天弱势，再 **①** 成本线，再 **②** 跌破估计 MA。去重 **`g._tail_cost_stop_sold`**。 |
| `_compact_sell_order_remark` | 生成实盘卖单 **`userOrderId`** 短备注（如 **`SL*`**），与 pending 字典键一致。 |
| `_stock_has_pending_sell` | 某代码是否已有未完结策略卖单（防重复 **`passorder` 卖**）。 |
| `_process_sell_unfilled_cancel_retry` | 扫描 **`g._sell_order_pending`**：未成交则撤单并重挂；订单已撤/未同步超时也会继续重挂，默认无上限，直到成交或无可卖数。 |
| `_emit_sell_fill_success` | 成交匹配后打 **`[SELL-OK]`** 并清理 pending。 |
| `_signal_buy_leg` | 一笔 **固定金额** 买腿：算股数、日志或 **`[ORDER]`** 买。 |
| `_fmt_sell_rule` / `_sell_rule_parts` | 组装 / 解析 **`规则类|规则项|详情`**，供各类卖出路径共用。 |
| `_print_sell_signal` | 打印 **`[SELL]`**（含 **`规则类|规则项|详情`**）并视 **`live_orders`** 调用 **`_passorder_go` 卖**；失败时 **`单边失败`** 并返回 **`False`**。 |
| `_signal_sell_sim` | 卖统一入口： pending 卖单去重、**`_print_sell_signal`**；回测/关单时可清 **`g`** 模拟仓。 |
| `_clear_sim_stock` | 清除某标的在 **`g`** 中的模拟持仓、分档、金字塔腿、**`prev_close_stop_touch_day`** 等状态。 |

### 11.10 时段与 bar 调度

| 函数 | 作用 |
|------|------|
| `_session_gate_pass` | 粗门控：K 线或墙钟时间是否在 **92500–150000**（默认与 A 档 9:25 首买窗口对齐）；不通过则早退主流程。 |
| `_in_session_trade` | 是否在 **连续竞价**：**93000–113000**、**130000–150000**（`run_risk_sell_signal`、指数清仓、有仓金字塔（除 A 集合末段例外）等）。 |
| `_a_preopen_for_first_buy` | 当 **`a_first_buy_start_hhmmss < 93000`** 且 **`a_first_buy_start_hhmmss ≤ hhmmss < 93000`** 时为真：集合竞价末段 **仅 A** 无仓首买或 **已持仓且分档为 A** 的金字塔；与 `_session_gate_pass` 下限配合。 |
| `_a_first_buy_window_ok` | **A 档首买**是否落在 **`a_first_buy_start_hhmmss`～`a_first_buy_end_hhmmss`**（加仓腿不受此窗限制）。 |
| `_fmt_hhmmss_colon` | 将六位 `hhmmss` 格式化为 **`HH:MM:SS`** 供监视提示等。 |
| `_non_atr_sell_time_ok` | 当前 bar 的 **`hhmmss`** 是否 **≥ `non_atr_sell_start_hhmmss`**；用于 **指数均线清仓**等；**`legacy` 尾盘成本/MA** 用 **`tail_clear_start_hhmmss`**，二者默认不同。 |
| `_fmt_non_atr_sell_start` | 将 `non_atr_sell_start_hhmmss` 格式化为 **`HH:MM`** 供日志。 |
| `_is_qmt_backtest_context` | 综合 `do_back_test`、`isDoBackTest`、`run_mode` 等判断是否 **回测**。 |
| `_handlebar_should_run` | 实盘通常仅 **`is_last_bar`**；回测或 **`handlebar_each_bar`** 则每根执行。 |

### 11.11 策略入口

| 函数 | 作用 |
|------|------|
| `init(C)` | 从 **`C`** 读入参数写入 **`g`**，初始化持仓/分档/日志闩锁等字典，打印初始化摘要。 |
| `handlebar(C)` | **主循环**：bar 去重、时间、自选池、墙钟早退、换日重置；准备阶段对 **池/持仓/指数/卖单重试** 等 **分散 `try/except`**；内层 **`try`** 依次调用指数清仓、**`run_risk_sell_signal`**（昨收/网格/ATR；**`legacy` 另含尾盘 `_run_tail_*`**）、ATR 自选外日志、金字塔与开仓；**`finally`** 中 **`[MIN]` / `[MON]` / `[POS]`** 各自 **`try/except`**（见 §5）。 |
| `handleBar` / `handle_bar` | 兼容 QMT 命名，内部 **`handlebar(C)`**。 |

### 11.12 `handlebar` 内嵌套函数（每轮 handlebar 定义一次）

| 函数 | 作用 |
|------|------|
| `run_index_liquidate_signal` | **`index_liquidate_all`**（上证最后一根收 **<** **`index_liquidate_ma_period`** 日均）时，对自选池内账户/模拟仓卖（须 **`_non_atr_sell_time_ok`**、连续竞价、**≥ tail_clear_start**、闩锁未占用）。 |
| `run_risk_sell_signal` | **连续竞价**：遍历候选；**①** **昨收止损**（成功则 `continue`）；**②** **`grid_d3`** 且 **`_grid_resolve_*` 成功** → 开盘止损/止盈、盘中合并 1m 触价、≥`tail_clear` 后网格收盘规则；**③** **`_emit_atr_mon_line`** +（≥`tail_clear`）**ATR 止盈**。**非连续竞价**且 **`grid_d3`+`simple_log_mode`**：仅 **`[GRID]`** 探针。**末尾**仅 **`legacy`** 调用 **`_run_tail_watchlist_cost_stop`**。 |
| `run_pyramid_and_entry_signal` | **有主仓**：金字塔加仓腿；**无仓** 且过门控：按 **A/B/C/D** 档做首买及后续腿。 |

---

## 12. 维护建议

- 改规则时 **优先改回测脚本** 并对齐本实盘文件，避免两边漂移。
- 若本说明与源码不一致，**以源码为准**，并请更新本 MD。
- 新增或重命名函数时，请同步更新 **第 11 节** 表格。
