# 回测策略

本目录存放 **仅用于 QMT 回测** 的策略脚本。

## 用途

- 在 QMT 中加载本目录下的 `.py` 文件进行历史回测
- 策略通常使用 `init(C)` + `handlebar(C)`，通过 `C.get_market_data_ex` 等获取历史数据，用 `passorder` 模拟下单
- 参数可在脚本内 `init` 中集中配置，便于调参对比

## 当前策略

| 文件 | 说明 |
|------|------|
| strategy_sideways_breakout_sz_ma240.py | 横盘异动突破 + 深证MA240 过滤，全扫描、截面按市值排序 |
| strategy_turtle_rotation_10.py | 海龟突破 + 指数成分池扫描；突破后按动量打分排序买入；单票上限 10 万、无加仓；见 `init` 参数 |

### strategy_sideways_breakout_sz_ma240 要点（与实盘一致）

- **突破与涨幅**：`today_return`、`today_high_return` 均为 **相对昨收**（`prev_close = closes[-2]`）：  
  - 当日涨幅：`(当日收盘 - 昨收) / 昨收`  
  - 当日最高涨幅：`(当日最高 - 昨收) / 昨收`（用于过滤盘中冲过高、如近涨停的票）  
- **横盘条件**仍为过去 N 日振幅/波动区间（不含「今开」口径）。  
- 与 **`实盘策略/strategy_sideways_breakout_sz_ma240_1m_live.py`** 买入筛选口径对齐；回测用日线收盘价、实盘 14:45 用 tick/1m 取「当前价」，尾盘差异通常较小。

## 约定

- **回测专用**：不依赖实盘接口（如 `get_trade_detail_data`、全推行情），可在无实盘环境下回测
- 新回测策略请放在本目录，与 `实盘策略` 区分管理

## 其他说明

- 双均线等示例策略（ETF/银行股，见 `strategies/strategy_etf_ma5_20.py` 等）仍在 **strategies/** 目录，说明见 [strategies/README_三策略说明.md](../strategies/README_三策略说明.md)。
