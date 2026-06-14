上游数据源（原始真源）
========================

本目录存放回测/分析的**原始输入表**，与派生结果（大疯牛妖股数据、测试组合表格 下的明细/汇总）分开，降低误删风险。

当前文件：
  · dafengniu_sync_open_baostock.csv   — 大疯牛开仓日 Baostock 宽表（真源）
  · 26异动监管测.xls                  — 异动监管原始表（真源）
  · yidong_regulation_stocks_2026.csv — 异动监管合并 CSV（由 xls 转换 + Baostock 补全）

补全缺失股票代码：
  python qmt/scripts/patch_yidong_xls_stock_codes_baostock.py

异动监管回测明细/汇总请输出到 **实盘策略/测试组合表格/**：
  python qmt/scripts/export_yidong_regulation_trades.py
  python qmt/scripts/export_yidong_regulation_split_trades.py

脚本路径常量：qmt/scripts/dafengniu_paths.py
  · DIR_UPSTREAM_DATA / SYNC_OPEN_BAOSTOCK_CSV
  · YIDONG_REGULATION_XLS / YIDONG_REGULATION_STOCKS_CSV
  · YIDONG_REGULATION_*_TRADES_* → DIR_TEST_COMBO

新增同类原始数据请放在本目录，勿与派生 CSV/JSON 混放。
