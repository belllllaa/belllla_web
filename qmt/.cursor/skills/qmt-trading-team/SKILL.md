---
name: qmt-trading-team
description: QMT 量化策略开发 Skill。支持两种模式：(1) 模拟股票团队工作框架——分析、多空辩论、决策、风险评估、审批后生成实盘代码；(2) 简单需求模式——严格依据 QMT 函数文档先写回测代码，客户确认通过后再写实盘代码。在用户开发 QMT 策略、编写量化交易代码、使用 passorder/get_market_data_ex/talib 时使用。
---

# QMT 量化策略开发 Skill

## 必读文档

开发前必须查阅 [qmt_complete_functions.md](../../../qmt_complete_functions.md)，所有函数调用必须严格符合该文档。

---

## 模式一：模拟股票团队工作框架

适用于需要深度分析、多空辩论、风险审查的复杂策略开发。

### 流程概览

```
分析 → 研究与辩论 → 决策 → 风险评估 → 审批 → 实盘代码
```

### 1. 分析（搜集市场数据）

- 明确标的、周期、时间范围
- 列出需搜集的数据类型：K 线（OHLCV）、技术指标、资金流向、龙虎榜、北向等
- 对应 QMT 函数：`get_market_data_ex`、`get_turnover_rate`、`get_longhubang`、`get_north_finance_change` 等
- 输出：结构化数据清单与数据来源说明

### 2. 研究与辩论（看涨 vs 看跌）

- **看涨方**：列举支持做多的证据（技术形态、资金、基本面等）
- **看跌方**：列举支持做空的证据
- **批判性评估**：指出各方论据的局限性、数据偏差、样本偏差
- 输出：多空观点对比表 + 关键分歧点

### 3. 决策（形成交易计划）

- 综合分析结论与辩论结果
- 明确：标的、方向、入场条件、出场条件、仓位比例
- 输出：交易计划（可执行规格）

### 4. 风险评估（多角度辩论）

从以下角度审视计划：

- **市场风险**：流动性、波动率、极端行情
- **执行风险**：滑点、冲击成本、成交概率
- **模型风险**：过拟合、参数敏感度
- **资金风险**：最大回撤、单笔亏损上限

输出：风险清单 + 缓解措施

### 5. 审批（生成实盘代码）

- 审查风险调整后的计划
- 确认无重大遗漏后，生成 QMT 实盘代码
- 代码要求：
  - 实现 `init`、`after_init`、`handlebar` 三个入口
  - 使用 `passorder` 下单（opType 23/24，orderType 1101/1102，prType 5）
  - 从 `config.config` 读取 STOCK_LIST、ACCOUNT_ID 等
  - 参考 [strategies/template_sma.py](../../../strategies/template_sma.py) 和 [strategies/template_rsi.py](../../../strategies/template_rsi.py) 结构

---

## 模式二：简单需求策略（回测优先）

适用于客户需求明确、逻辑简单的策略。

### 铁律

**先回测，后实盘。** 客户确认回测通过前，不写实盘代码。

### 流程

1. **理解需求**：标的、信号逻辑、仓位、周期
2. **写回测代码**：
   - 严格依据 [qmt_complete_functions.md](../../../qmt_complete_functions.md)
   - 使用 `order_value`、`order_target_percent` 等回测专用函数
   - 使用 `get_market_data_ex` 获取行情
   - 使用 `utils/indicators` 中的 ma、ema、rsi、macd、bbands
3. **客户确认**：回测结果、逻辑、参数均通过
4. **写实盘代码**：
   - 在回测代码基础上，将 `order_value`/`order_target_percent` 替换为 `core.order_helper` 的 `buy`/`sell`
   - 或直接调用 `passorder(23, 1101, account, stock, 5, 0, volume, ...)`

### 模式二参考代码

完整回测样板见 [mode2_reference_code.md](mode2_reference_code.md)，包含：

1. **布林带突破 - 中证1000**（[strategy_bollinger_csi1000.py](../../../strategies/strategy_bollinger_csi1000.py)）：下轨买入、上轨卖出，get_sector、get_trade_detail_data、passorder
2. **旋风冲锋 - 涨停板**（[strategy_whirlwind_limitup.py](../../../strategies/strategy_whirlwind_limitup.py)）：近20日涨停选股、多条件卖出、滑点手续费、draw_text

---

## 代码规范

### 策略文件结构

```python
# -*- coding: utf-8 -*-
"""策略说明"""

import sys, os
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from config.config import STOCK_LIST, PERIOD, ACCOUNT_ID, STRATEGY_NAME
from utils.data_helper import get_ohlcv_df
from utils.indicators import ma, rsi, macd  # 按需

def _get_close(df):
    if df is None: return None
    if hasattr(df, "columns") and "close" in df.columns:
        return df["close"].values
    return df.values.flatten() if hasattr(df, "values") else None

def init(ContextInfo):
    ContextInfo.stock_list = STOCK_LIST
    # 可选: download_history_data(...)

def after_init(ContextInfo):
    pass

def handlebar(ContextInfo):
    # 获取数据、计算指标、产生信号、下单
    pass
```

### 回测 vs 实盘下单

| 场景 | 买入 | 卖出 |
|------|------|------|
| 回测 | `order_value(stock, value, ContextInfo)` | `order_target_percent(stock, 0, ContextInfo)` |
| 实盘 | `passorder(23, 1101, account, stock, 5, 0, volume, ...)` 或 `core.order_helper.buy(...)` | `passorder(24, 1101, account, stock, 5, 0, volume, ...)` 或 `core.order_helper.sell(...)` |

### passorder 参数速查

- opType: 23 买入, 24 卖出
- orderType: 1101 按股数, 1102 按金额
- prType: 5 最新价, 11 指定价
- quickTrade: 1 非历史 bar 立即触发

---

## 参考策略

- [strategies/template_sma.py](../../../strategies/template_sma.py)：双均线金叉/死叉
- [strategies/template_rsi.py](../../../strategies/template_rsi.py)：RSI 超买超卖

两者均采用：BaseStrategy 子类 + 回测/实盘双模式下单。

---

## 补充资源

- 详细流程与检查清单：[reference.md](reference.md)
- 输出示例说明：[examples.md](examples.md)
