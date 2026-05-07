# -*- coding: utf-8 -*-
"""
dafengniu 相关 CSV 目录（与 qmt/实盘策略 下子文件夹一致，避免脚本硬编码分散导致路径错误）。

  · 大疯牛妖股数据/  — 股票池明细、同步开仓日、Baostock 扩展表、特征导出等
  · 测试组合表格/   — 组合回测、网格对比等中间结果表
"""
from __future__ import annotations

import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# qmt/实盘策略
LIVE_STRATEGY_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "实盘策略"))

# ---------- 大疯牛妖股数据 ----------
DIR_DFN_DATA = os.path.join(LIVE_STRATEGY_DIR, "大疯牛妖股数据")
HOLDINGS_DETAIL_CSV = os.path.join(DIR_DFN_DATA, "dafengniu_holdings_detail.csv")
SYNC_OPEN_DATES_CSV = os.path.join(DIR_DFN_DATA, "dafengniu_sync_open_dates.csv")
SYNC_OPEN_BAOSTOCK_CSV = os.path.join(DIR_DFN_DATA, "dafengniu_sync_open_baostock.csv")
SIGNAL_FEATURES_CSV = os.path.join(DIR_DFN_DATA, "dafengniu_signal_features.csv")
# 参考基准（默认策略）：T−1 上证≥MA5 门控 + 尾盘上证收盘低于 MA5 清仓；主输出即下两路径
BENCHMARK_REF_TRADES_CSV = os.path.join(DIR_DFN_DATA, "dafengniu_benchmark_ref_trades.csv")
BENCHMARK_REF_SUMMARY_JSON = os.path.join(DIR_DFN_DATA, "dafengniu_benchmark_ref_summary.json")
# 与主文件同义（历史/外部若引用「sse_exit_ma5」文件名，请改为主文件名）
BENCHMARK_REF_TRADES_SSE_EXIT_MA5_CSV = BENCHMARK_REF_TRADES_CSV
BENCHMARK_REF_SUMMARY_SSE_EXIT_MA5_JSON = BENCHMARK_REF_SUMMARY_JSON
BENCHMARK_REF_TRADES_NO_GATE_CSV = os.path.join(DIR_DFN_DATA, "dafengniu_benchmark_ref_trades_no_sse_gate.csv")
BENCHMARK_REF_SUMMARY_NO_GATE_JSON = os.path.join(DIR_DFN_DATA, "dafengniu_benchmark_ref_summary_no_sse_gate.json")
BENCHMARK_REF_TRADES_NO_SSE_MA10_EXIT_CSV = os.path.join(
	DIR_DFN_DATA, "dafengniu_benchmark_ref_trades_no_sse_ma10_exit.csv"
)
BENCHMARK_REF_SUMMARY_NO_SSE_MA10_EXIT_JSON = os.path.join(
	DIR_DFN_DATA, "dafengniu_benchmark_ref_summary_no_sse_ma10_exit.json"
)
BENCHMARK_REF_TRADES_NO_GATE_NO_SSE_MA10_EXIT_CSV = os.path.join(
	DIR_DFN_DATA, "dafengniu_benchmark_ref_trades_no_gate_no_sse_ma10_exit.csv"
)
BENCHMARK_REF_SUMMARY_NO_GATE_NO_SSE_MA10_EXIT_JSON = os.path.join(
	DIR_DFN_DATA, "dafengniu_benchmark_ref_summary_no_gate_no_sse_ma10_exit.json"
)
BENCHMARK_REF_TRADES_SSE_EXIT_MA10_CSV = os.path.join(
	DIR_DFN_DATA, "dafengniu_benchmark_ref_trades_sse_exit_ma10.csv"
)
BENCHMARK_REF_SUMMARY_SSE_EXIT_MA10_JSON = os.path.join(
	DIR_DFN_DATA, "dafengniu_benchmark_ref_summary_sse_exit_ma10.json"
)
BENCHMARK_REF_TRADES_NO_GATE_SSE_EXIT_MA5_CSV = os.path.join(
	DIR_DFN_DATA, "dafengniu_benchmark_ref_trades_no_gate_sse_exit_ma5.csv"
)
BENCHMARK_REF_SUMMARY_NO_GATE_SSE_EXIT_MA5_JSON = os.path.join(
	DIR_DFN_DATA, "dafengniu_benchmark_ref_summary_no_gate_sse_exit_ma5.json"
)

# ORDER-C 梯子回测（首买+补仓）：等权 vs ORDER_C_BIN_WEIGHTS 加权汇总
ORDER_C_LADDER_SUMMARY_JSON = os.path.join(DIR_DFN_DATA, "dafengniu_order_c_ladder_summary.json")

# ---------- 测试组合表格 ----------
DIR_TEST_COMBO = os.path.join(LIVE_STRATEGY_DIR, "测试组合表格")
ALL_COMBO_COMPARE_FILTERED_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_all_combo_compare_filtered.csv")
BUY_COMBO_VS_SELL_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_buy_combo_vs_sell_compare.csv")
GRID_EXT_TRADES_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_grid_ext_sl7_tp7_th05_d0_D3_w0_trades.csv")
DYNAMIC_COMPARE_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_dynamic_compare.csv")
GRID_COMPARE_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_grid_compare.csv")
SELL_COMBO_SCAN_ROUND_A_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_sell_combo_scan_round_A.csv")
SELL_COMBO_SCAN_ROUND_B_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_sell_combo_scan_round_B.csv")
SELL_COMBO_SCAN_ROUND_C_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_sell_combo_scan_round_C.csv")
SELL_COMBO_SCAN_ROUND_D_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_sell_combo_scan_round_D.csv")
SELL_COMBO_SCAN_ROUND_E_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_sell_combo_scan_round_E.csv")
SELL_COMBO_SCAN_META_JSON = os.path.join(DIR_TEST_COMBO, "dafengniu_sell_combo_scan_meta.json")
SELL_ATTRIBUTION_GRID_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_sell_attribution_grid.csv")
# 买入规则组合扫描（固定卖出与回测 D 一致：−10%/6.5%·盘中同档·上证破 MA5 尾盘·D1 弱·D3）
BUY_COMBO_SCAN_ROUND12_CSV = os.path.join(DIR_TEST_COMBO, "dafengniu_buy_combo_scan_round_1_2.csv")
BUY_COMBO_SCAN_META_JSON = os.path.join(DIR_TEST_COMBO, "dafengniu_buy_combo_scan_meta.json")

# ---------- 仍放在 实盘策略 根目录的常用表（未迁入上述子文件夹）----------
OPEN_WINDOW_METRICS_QMT_CSV = os.path.join(LIVE_STRATEGY_DIR, "dafengniu_open_window_metrics_qmt.csv")
MANUAL_OPEN_DATES_LEGACY_CSV = os.path.join(LIVE_STRATEGY_DIR, "dafengniu_manual_open_dates.csv")
