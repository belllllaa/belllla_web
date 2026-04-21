# 实盘策略说明：`strategy_my_watchlist_intraday_atr_1m_live_signal.py`

本文说明与解释对应 Python 文件的行为、参数与日志，**策略源码内仅保留极简注释**；细节以本 Markdown 为准。**各封装函数含义见第 11 节。**

---

## 1. 策略做什么（一句话）

在 **QMT 1 分钟 K 线** 上，从 **自选板块** 取股票池，按 **开盘涨跌幅分档** 做 **分批买入**，用 **上证指数 MA** 做门控与清仓条件之一，并用 **硬止损、尾盘规则、MA10、ATR** 等做 **卖出与风控**；满足条件时在实盘下 **`passorder`** 下单，否则只打 **`[SIGNAL]`** 日志。

---

## 2. 和哪些文件对齐

| 关系 | 路径 |
|------|------|
| 规则与参数对齐（回测） | `qmt/回测策略/strategy_my_watchlist_intraday_atr.py` |
| bar 调度思路参考 | `qmt/实盘策略/strategy_sideways_breakout_sz_ma240_1m_live.py`（`is_last_bar`、墙钟门控等） |

---

## 3. 名词解释（你之前问的 `\u…` 解码后就是这些）

- **自选**：股票池来自 QMT 板块，默认板块名 **`我的自选`**（可用参数 `watchlist_sector_name` 改）。
- **分档**：用 **今开 / 昨收 − 1** 得到开盘缺口 `gap`，再划到 A/B/C/D 档；不同档 **首笔买入比例、触发价、加仓腿** 不同（细节与回测策略文档一致）。
- **开仓 / 买入**：在门控通过时，按分档与金字塔逻辑 **`passorder` 买入**（受 `live_orders`、资金账号、非回测等约束）。
- **上证 MA 门控**：用 **000001.SH** 日线：例如最新收盘在 **MA5 下方** 时 **不开新仓**；**破 MA10** 时可触发 **清自选池内仓位**（与参数、时段有关）。
- **风控卖**：硬止损、尾盘「曾触 -8% 且未收回至 -6%」、上证 MA10 清仓等；其中多项受 **`non_atr_sell_start_hhmmss`** 约束（默认约 14:54 后才评估）。
- **ATR 止盈**：持仓 **盈利** 时，用日线窗口 + 多源现价抬升后的 **吊灯式回撤** 算止盈线，触发则卖（全天随 1m 评估，与上面「非 ATR 卖出时段」可不同）。

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
- **时段**：`run_pyramid_and_entry_signal` 内，**有仓金字塔**默认仅在 **`_in_session_trade`**（约 **9:30–11:30、13:00–15:00**）执行；**例外**：若 **`a_first_buy_start_hhmmss < 93000`**，则在 **`a_first_buy_start_hhmmss ≤ hhmmss < 93000`** 时仍允许 **A 档**有仓金字塔或 **A 档无仓首买**（见 `_a_preopen_for_first_buy`）。**无仓首买**在上述集合末段仅 **A**；B/C/D 首买须从 **9:30 连续竞价** 起。`run_risk_sell_signal` / `run_index_liquidate_signal` 仅在 **`_in_session_trade`** 为真时执行（不在 9:25–9:30 集合末段卖）。
- **加仓锚点**：A / B / C 档的第二、三腿触发价均为 **相对今开** 的累计跌幅（见下表），**不以首买成交价**为锚。

### 6.1 各档首买与金字塔（与 `strategy_my_watchlist_intraday_atr.py` 对齐）

| 档位 | 首买条件（无仓） | 首买名义 | 第二腿（有仓，`leg_done[1]`） | 第三腿（`leg_done[2]`） |
|------|------------------|----------|--------------------------------|-------------------------|
| **A** | 须在 **`a_first_buy_start_hhmmss`～`a_first_buy_end_hhmmss`**（默认 **92500～93559**）内；否则本日等待该窗口 | **50%** | 现价 ≤ **今开 ×0.95**（相对今开 **-5%**），**30%** | 现价 ≤ **今开 ×0.92**（**-8%**），**20%** |
| **B** | 现价 ≤ **今开 ×0.97**（相对今开 **-3%**） | **50%** | 现价 ≤ **今开 ×0.95**（**-5%**），**30%** | 现价 ≤ **今开 ×0.92**（**-8%**），**20%** |
| **C** | 现价 ≤ **今开 ×0.96**（相对今开 **-4%**） | **50%** | 现价 ≤ **今开 ×0.91**（**-9%**），**30%** | 现价 ≤ **今开 ×0.88**（**-12%**），**20%** |
| **D** | 无额外价格门槛（在允许时段内按现价首买） | **50%** | 无 | 无 |

- **HHMMSS 参数**：`92500` 表示 9:25:00；整数比较，与 bar 的 `hhmmss` 一致即可（配置为字符串 `"092500"` 时 `int()` 后仍为 `92500`）。
- **`anchor_buy`**：首买成交后仍会写入，供「有锚才跑金字塔」等判断；**B/C 加仓阈值已改为今开**（见上表）。

---

## 7. 卖出与风控（概要）

- **卖单监控范围**：以 **自选池** 为主；自选外账户仓是否参与部分风控，由 **`monitor_account_risk_sells`** 等参数控制（详见 `init`）。
- **硬止损**：如总浮亏 ≤ **-8%**（`hard_stop_pct`），在允许时段内清仓。
- **尾盘规则**：当日曾跌至昨收约 **-8%** 等标记后，若收盘前仍低于约 **-6%**（`intraday_fail_recover_pct`），在 **`non_atr_sell_start_hhmmss`** 之后可触发卖。
- **上证 MA10**：满足条件时清 **自选池内** 相关持仓（与 `run_index_liquidate_signal` 等逻辑一致）。
- **ATR**：仅作 **盈利侧止盈**；与 tick/1m/持仓价等合并取价，避免仅用未更新的日线收盘作现价导致止盈线异常偏低（见 `atr_ref_high_use_intraday` 等）。

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
| `a_first_buy_end_hhmmss` | 93559 | **A 档首买**的最晚时刻（含边界）；默认覆盖 **9:25–9:35** |
| `require_sse_above_ma5_for_new` | True | 上证收盘不低于 MA5 才开新仓 |
| `ma_index_period_short` / `long` | 5 / 10 | 指数均线周期 |
| `atr_period` | 14 | ATR 周期 |
| `atr_stop_mult` | 2.0 | 止盈距离 = ATR × 倍数 |
| `atr_ref_high_use_intraday` | True | HH 是否合并分时/现价等 |
| `bar_count` | 80 | 日线拉取根数 |
| `allow_atr_same_day` | True | **强烈建议实盘保持 True**。当日买入时，`dh_eff` 若为 0 会导致 ATR 无效、`[ATR-MON]` 备注为「持仓不满1日」。若设为 False，自选当日买入容易出现止损线全为 `--` |
| `hard_stop_pct` | -0.08 | 硬止损比例 |
| `intraday_touch_pct` | -0.08 | 日内触阈记录（如 -8%） |
| `intraday_fail_recover_pct` | -0.06 | 尾盘未收回阈值（如 -6%） |
| `tail_clear_start_hhmmss` | 145000 | 尾盘相关时间窗 |
| `non_atr_sell_start_hhmmss` | 145400 | 非 ATR 类卖出评估起始时刻 |
| `tail_intraday_log` | True | 尾盘触阈过程日志 |
| `atr_intraday_log` | True | 每分钟 ATR 监控日志 |
| `atr_log_account_non_watchlist` | True | 自选外持仓是否打 ATR 日志（一般不自动卖） |
| `use_tick_first` | True | 取价优先 tick 等 |
| `signal_trace_log` | True | `[TRACE]` |
| `minute_summary_log` | True | `[MIN]` |
| `position_summary_log` | True | `[POS]` |
| `sell_monitor_summary_log` | True | `[MON]` 总览 |
| `monitor_account_risk_sells` | True | 账户仓是否纳入自选侧风控卖 |
| `handlebar_each_bar` | False | 强制每根 1m 执行（多用于回测） |
| `live_orders` | True | 是否真下单 |
| `strategy_order_name` | 自选分档 | 委托备注名（截断） |
| `quick_trade` | 2 | 下单快速参数 |

---

## 9. 日志标签（控制台）

| 标签 | 大致含义 |
|------|----------|
| `[ORDER]` | 实盘下单相关 |
| `[SIGNAL]` | 非回测或未开 `live_orders` 时的信号说明 |
| `[ATR-MON]` | ATR 与止盈线监控 |
| `[TAIL-ARM]` / `[TAIL-PEND]` | 尾盘触阈标记与跟踪 |
| `[MIN]` | 分钟汇总 |
| `[POS]` | 持仓汇总 |
| `[MON]` | 监控总览 |
| `[TRACE]` | 细粒度跟踪 |

---

## 10. 技术说明：`passorder` 与 `get_trade_detail_data`

QMT 常把 **`passorder`、`get_trade_detail_data`** 注入在 **`__main__`**，而不是策略模块的 `globals`。本策略用 **`_passorder_fn()` / `_get_trade_detail_data_fn()`** 统一从 `__main__` 或本模块全局取函数，避免 **NameError** 或 **取不到持仓价**（进而影响 ATR 现价合并）。

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
| `_passorder_go` | 股数按最小单位向下取整后调用 `_passorder_fn()`，备注截断等。 |
| `_signal_buy_leg` | 一笔 **固定金额** 买腿：算股数、日志或 **`[ORDER]`** 买。 |
| `_print_sell_signal` | 格式化卖出 **`[SIGNAL]`** 及参考价。 |
| `_signal_sell_sim` | 卖出口：打印、更新 **`g` 记账**、条件触发 **`passorder` 卖**。 |
| `_clear_sim_stock` | 清除某标的在 **`g`** 中的模拟持仓、分档、金字塔腿、`touch` 等状态。 |

### 11.10 时段与 bar 调度

| 函数 | 作用 |
|------|------|
| `_session_gate_pass` | 粗门控：K 线或墙钟时间是否在 **92500–150000**（默认与 A 档 9:25 首买窗口对齐）；不通过则早退主流程。 |
| `_in_session_trade` | 是否在 **连续竞价**：**93000–113000**、**130000–150000**（硬止损、风控卖、指数清仓、有仓金字塔（除 A 集合末段例外）等）。 |
| `_a_preopen_for_first_buy` | 当 **`a_first_buy_start_hhmmss < 93000`** 且 **`a_first_buy_start_hhmmss ≤ hhmmss < 93000`** 时为真：集合竞价末段 **仅 A** 无仓首买或 **已持仓且分档为 A** 的金字塔；与 `_session_gate_pass` 下限配合。 |
| `_a_first_buy_window_ok` | **A 档首买**是否落在 **`a_first_buy_start_hhmmss`～`a_first_buy_end_hhmmss`**（加仓腿不受此窗限制）。 |
| `_fmt_hhmmss_colon` | 将六位 `hhmmss` 格式化为 **`HH:MM:SS`** 供监视提示等。 |
| `_non_atr_sell_time_ok` | 当前 bar 的 **hh:mm:ss** 是否已不早于 **`non_atr_sell_start_hhmmss`**（硬止损/尾盘/MA10 等）。 |
| `_fmt_non_atr_sell_start` | 将 `non_atr_sell_start_hhmmss` 格式化为 **`HH:MM`** 供日志。 |
| `_is_qmt_backtest_context` | 综合 `do_back_test`、`isDoBackTest`、`run_mode` 等判断是否 **回测**。 |
| `_handlebar_should_run` | 实盘通常仅 **`is_last_bar`**；回测或 **`handlebar_each_bar`** 则每根执行。 |

### 11.11 策略入口

| 函数 | 作用 |
|------|------|
| `init(C)` | 从 **`C`** 读入参数写入 **`g`**，初始化持仓/分档/日志闩锁等字典，打印初始化摘要。 |
| `handlebar(C)` | **主循环**：bar 去重、时间、自选池、墙钟早退、换日重置；依次调用嵌套的指数清仓、风控卖、ATR 自选外日志、金字塔与开仓；**`finally`** 中打 `[MIN]` / `[MON]` / `[POS]`。 |
| `handleBar` / `handle_bar` | 兼容 QMT 命名，内部 **`handlebar(C)`**。 |

### 11.12 `handlebar` 内嵌套函数（每轮 handlebar 定义一次）

| 函数 | 作用 |
|------|------|
| `run_index_liquidate_signal` | 上证 **破 MA10** 时，对 **自选池内** 账户仓发 **一次性清仓**（受非 ATR 卖出时刻与 **`g._ma10_signal_latched`** 限制）。 |
| `run_risk_sell_signal` | 自选池内：**硬止损**、**尾盘 -8/-6**、**ATR 止盈**；维护日内低、**`touch_neg8`**，打 **`[TAIL-*]`** / **`[ATR-MON]`**。 |
| `run_pyramid_and_entry_signal` | **有主仓**：金字塔加仓腿；**无仓** 且过门控：按 **A/B/C/D** 档做首买及后续腿。 |

---

## 12. 维护建议

- 改规则时 **优先改回测脚本** 并对齐本实盘文件，避免两边漂移。
- 若本说明与源码不一致，**以源码为准**，并请更新本 MD。
- 新增或重命名函数时，请同步更新 **第 11 节** 表格。
