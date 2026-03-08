# QMT 策略示例参考

## 双均线策略 (template_sma.py)

- 逻辑：MA5 上穿 MA20 买入，下穿卖出
- 结构：BaseStrategy 子类 + init/after_init/handlebar 入口
- 下单：回测用 order_value/order_target_percent，实盘用 core.order_helper.buy/sell

## RSI 策略 (template_rsi.py)

- 逻辑：RSI < 30 买入，RSI > 70 卖出
- 结构：同上
- 参数：rsi_period=14, oversold=30, overbought=70

## 布林带突破策略 - 中证1000版 (strategy_bollinger_csi1000.py)

- 逻辑：价格下穿布林带下轨买入，上穿上轨卖出
- 股票池：中证1000（000852.ZZ），按市值从小到大选最小10只
- 特点：使用 get_sector、get_trade_detail_data、passorder，含滑点与手续费

## 旋风冲锋策略 - 涨停板样板 (strategy_whirlwind_limitup.py) 【回测样板参考】

- 逻辑：近20日内有过涨停(>=9.9%)的股票，开盘涨幅 -3%~+8% 时买入
- 卖出：跌停止损、大跌减亏、冲高回落、炸板回落、破5日线
- 股票池：中证800/沪深300 或预设池
- 特点：完整回测样板，含选股函数、滑点手续费、draw_text 标注

## 模式一（团队框架）输出示例

完成分析→辩论→决策→风险评估→审批后，输出应包含：

1. **交易计划**：标的、方向、入场/出场条件、仓位
2. **风险清单**：市场/执行/模型/资金风险及缓解措施
3. **实盘代码**：完整 .py 文件，可直接在 QMT 加载

## 模式二（简单需求）输出示例

1. **回测代码**：使用 order_value、get_market_data_ex、indicators
2. **客户确认**：等待用户确认回测通过
3. **实盘代码**：在回测基础上替换为 passorder 或 order_helper

**完整参考代码**：见 [mode2_reference_code.md](mode2_reference_code.md)（布林带突破、旋风冲锋）
