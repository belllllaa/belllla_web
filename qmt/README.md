# QMT 个人量化项目

基于迅投 QMT 内置 Python 函数的个人量化交易开发框架。

## 目录结构

```
qmt/
├── qmt_complete_functions.md  # QMT 内置函数完整文档（开发必读）
├── config/                    # 配置（账户、标的池、参数）
├── core/                      # 核心框架（ContextInfo 封装、下单封装）
├── strategies/                # 策略（基类、均线、RSI 等）
├── utils/                     # 工具（指标、数据获取）
├── backtest/                  # 回测相关
└── docs/                      # 文档（函数速查等）
```

## 快速上手

1. 在 `config/config.py` 中配置账户 ID、标的池、回测时间
2. 选择或编写策略（如 `strategies/template_sma.py`）
3. 在 QMT 中加载策略脚本进行回测或实盘

## 策略开发

策略需实现 QMT 要求的三个入口函数：

- `init(ContextInfo)` - 初始化
- `after_init(ContextInfo)` - 后初始化（可选）
- `handlebar(ContextInfo)` - 每根 K 线触发

可继承 `strategies/base_strategy.py` 中的 `BaseStrategy` 简化开发。

## 策略文件

| 文件 | 说明 |
|------|------|
| template_sma.py | 双均线策略（MA5/MA20） |
| template_rsi.py | RSI 超买超卖策略 |
| strategy_bollinger_csi1000.py | 布林带突破 - 中证1000 |
| strategy_whirlwind_limitup.py | 旋风冲锋 - 涨停板回测样板 |

## 注意事项

- `order_lots`、`order_value` 等仅回测可用，实盘需用 `passorder`
- 实盘下单请使用 `core/order_helper.py` 中的封装接口
