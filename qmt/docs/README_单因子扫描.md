# 单因子扫描与结果分析

用于逐因子调参、评估有效性与收益关联性，并统计每次修改的结果，便于剔除无效因子。

## 1. 因子配置

- **文件**：`factor_config.py`
- **内容**：按策略列出可调因子（参数）及其默认值、候选值。当前支持：
  - `three_strategies`：ma_fast, ma_slow, stop_loss_pct
  - `momentum_small_cap`：max_stocks, per_stock_amount, min_hold_days, min_market_cap, max_market_cap
- 修改候选值即可改变扫描范围。

## 2. 运行单因子扫描

```bash
cd qmt/backtest
python run_single_factor_sweep.py --demo
python run_single_factor_sweep.py --demo --strategies three_strategies
python run_single_factor_sweep.py --baostock --strategies momentum_small_cap
python run_single_factor_sweep.py --output output/my_sweep.csv
```

- `--demo`：使用本地生成数据，不拉取网络，适合快速试跑。
- `--baostock` / `--eastmoney`：指定数据源（三策略可用）。
- `--strategies`：逗号分隔的策略 ID，空则跑全部。
- 结果写入 `output/factor_sweep_results.csv`（或 `--output` 指定路径）。

## 3. 结果表字段

- **experiment_id, run_time, strategy_id, strategy_display_name**
- **factor_name, factor_value, is_baseline**
- **total_return, annual_return, max_drawdown, win_rate, trade_count, sell_count, final_equity**
- **annual_return_vs_baseline, max_drawdown_vs_baseline**（相对默认配置的差异）

## 4. 分析扫描结果

```bash
python analyze_factor_results.py
python analyze_factor_results.py --input output/factor_sweep_results.csv --out-dir output
```

生成：

- `factor_sweep_summary_by_factor.csv`：按因子分组的收益/回撤汇总
- `factor_correlation_annual_return.csv`：因子取值与年化收益的相关系数
- `factor_effectiveness_summary.csv`：因子有效性小结（保留/建议剔除、最优取值）

## 5. 回测脚本与参数注入

- **三策略**：`backtest_three_strategies.run_one_strategy(..., ma_fast=, ma_slow=, stop_loss_pct=)`；扫描时通过 `run_three_strategies_backtest(data_1, data_2, data_3, params_override)` 注入参数。
- **动量小市值**：`backtest_momentum_small_cap.run_backtest(..., params=)` 支持 max_stocks, per_stock_amount, min_hold_days, max_candidates 等覆盖。
