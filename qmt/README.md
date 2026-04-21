# QMT 个人量化项目

基于迅投 QMT 内置 Python 的个人量化交易与数据处理框架。

---

## 目录结构

```
qmt/
├── README.md                    # 本说明
├── __init__.py
├── config/                      # 配置
│   ├── __init__.py
│   └── config.py                # 账户、标的池、回测时间等
├── core/                        # 核心封装
│   ├── __init__.py
│   ├── context_wrapper.py       # ContextInfo 封装
│   └── order_helper.py          # 下单封装（实盘 passorder 等）
├── strategies/                  # 通用策略（可回测/可实盘）
│   ├── __init__.py
│   ├── base_strategy.py         # 策略基类
│   ├── README_三策略说明.md     # 三策略（ETF/银行/双ETF）说明
│   ├── template_sma.py          # 双均线 MA5/MA20 模板
│   ├── template_rsi.py          # RSI 模板
│   ├── strategy_etf_ma5_20.py           # 沪深300ETF 双均线+止损
│   ├── strategy_etf_dual_ma_dual_target.py  # 双 ETF 双均线
│   ├── strategy_bank_ma5_20.py           # 银行股池 双均线
│   ├── strategy_bollinger_csi1000.py     # 布林带-中证1000
│   ├── strategy_whirlwind_limitup.py    # 涨停板回测样板
│   ├── strategy_dual_ma_official_example.py  # 双均线官方示例
│   ├── strategy_momentum_small_cap.py   # 小盘动量
│   ├── strategy_momentum_reversal.py    # 动量反转
│   ├── strategy_mean_reversion.py       # 均值回归
│   ├── strategy_sideways_breakout.py    # 横盘突破（通用）
│   └── strategy_sideways_breakout_qmt_style.py  # 横盘突破 qmt_style
├── 回测策略/                    # 仅用于 QMT 回测的策略
│   ├── __init__.py
│   ├── README.md                # 回测策略说明与约定
│   ├── strategy_sideways_breakout_sz_ma240.py   # 横盘异动突破 + 深证MA240（突破涨幅相对昨收，见该目录 README）
│   └── strategy_momentum_trend_rotation.py     # 强势趋势轮动（多周期动量+量能）
├── 实盘策略/                    # 用于 QMT 实盘/模拟的策略
│   ├── __init__.py
│   ├── README.md                # 实盘策略说明与约定
│   ├── README_横盘突破策略_QMT合规检查.md
│   ├── strategy_sideways_breakout_official_style.py  # 横盘突破（官方框架、全推、撤单重下）
│   ├── strategy_sideways_breakout_sz_ma240_live.py   # 横盘异动+深证MA240 实盘
│   └── strategy_sideways_breakout_sz_ma240_1m_live.py # 同上 1 分钟周期 / 14:45；买入涨幅相对昨收
├── utils/                       # 工具
│   ├── __init__.py
│   ├── data_helper.py           # 数据获取封装
│   ├── indicators.py            # 指标
│   └── barra_factors.py         # Barra 因子
├── fund_flow/                   # 资金流向与每日汇总
│   ├── __init__.py
│   ├── README_约定与流程.md
│   ├── README_数据说明.md
│   ├── README_数据获取与代理.md
│   ├── 数据需求说明.md
│   ├── run_once.py              # 每日运行：拉取+汇总
│   ├── run_once_from_json.py    # 从 JSON 生成汇总
│   ├── run_once_akshare_only.py # 仅 akshare 拉取
│   ├── fill_daily_history.py    # 补全历史列
│   ├── fetcher.py / clean.py / excel_io.py / verify_excel.py
│   ├── calendar_utils.py / industry_fetcher.py / export_industry_map.py
│   └── output/                  # 输出（xlsx、json 等）
├── docs/                        # 文档与知识库
│   ├── qmt_complete_functions.md    # QMT 内置函数完整文档
│   ├── qmt_functions_ref.md         # 函数速查
│   ├── QMT知识库_全站索引.md
│   ├── QMT知识库_完整示例目录.md
│   ├── 因子参考表.md
│   ├── quant_open_source_projects.md # 量化开源项目索引
│   ├── Peter_Lynch_策略与A股量化.md
│   ├── references_Sequoia_策略一览.md
│   ├── README_单因子扫描.md
│   └── 因子/                    # 因子表与导出脚本
│       ├── README.md
│       ├── factor_reference.xlsx
│       └── export_factor_reference.py
├── references/                 # 外部参考
│   ├── README.md
│   ├── Sequoia/                 # Sequoia 策略参考（突破平台、放量等）
│   └── strategy-vnpy/           # vnpy 相关
└── scripts/                     # 独立脚本
    ├── README.md
    └── peg_top5_eastmoney.py    # PEG<0.5 前 5 只（东方财富）
```

---

## 策略分类

| 目录 | 用途 | 说明 |
|------|------|------|
| **strategies/** | 通用策略 | 双均线、RSI、布林带、横盘突破等，可在 QMT 中用于回测或实盘 |
| **回测策略/** | 仅回测 | 不依赖实盘接口（如 get_trade_detail_data、全推），适合历史回测 |
| **实盘策略/** | 实盘/模拟 | 使用账户、持仓、委托回报等，带防超单、撤单重下、全推价等 |

- 回测策略说明：[回测策略/README.md](回测策略/README.md)（横盘 `sz_ma240`：突破/涨幅 **相对昨收**）
- 实盘策略说明：[实盘策略/README.md](实盘策略/README.md)（`sz_ma240_1m_live` 与回测同口径）
- 三策略（ETF/银行/双ETF）说明：[strategies/README_三策略说明.md](strategies/README_三策略说明.md)

---

## 快速上手

1. **配置**：在 `config/config.py` 中配置账户 ID、标的池、回测时间（若需要）。
2. **选策略**：从 `strategies/`、`回测策略/` 或 `实盘策略/` 中选一个 `.py`，在 QMT 中加载。
3. **回测**：在 QMT 中设置回测区间与资金，运行策略。
4. **实盘**：使用 `实盘策略/` 下脚本，确保账户、全推行情等已配置。

策略需实现 QMT 入口：`init(C)`、可选 `after_init(C)`、`handlebar(C)`。可参考 `strategies/base_strategy.py` 或 `strategies/strategy_dual_ma_official_example.py`。

---

## 文档与知识库

- **开发必读**：`docs/qmt_complete_functions.md`（QMT 内置函数）
- **速查**：`docs/qmt_functions_ref.md`、`docs/QMT知识库_全站索引.md`
- **因子**：`docs/因子参考表.md`、`docs/因子/`（Excel 因子表与导出脚本）
- **开源参考**：`docs/quant_open_source_projects.md`

---

## 其他模块

- **fund_flow**：每日资金流向拉取、汇总表生成、历史列补全；见各 README。
- **scripts**：独立小工具，如 `peg_top5_eastmoney.py`（PEG 选股）；见 `scripts/README.md`。
- **references**：Sequoia、vnpy 等参考代码与思路，见 `references/README.md`。

---

## 注意事项

- `order_lots`、`order_value` 等仅回测可用；实盘需用 `passorder`，并注意投资备注长度等合规要求。
- 实盘下单可配合 `core/order_helper.py` 中的封装。
- 实盘策略通常依赖全推行情（如 get_full_tick）获取实时价与涨跌幅，需在 QMT 中开启全推。
