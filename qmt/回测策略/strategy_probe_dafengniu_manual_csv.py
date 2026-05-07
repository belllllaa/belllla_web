#coding:gbk
"""
探测《dafengniu_manual_open_dates.csv》中的代码与开仓日能否在 QMT 回测中拉到日线收盘价。

用法：
1. 先在本仓库运行：python qmt/scripts/excel_dafengniu_to_manual_csv.py
2. 在 QMT 中新建回测，加载本策略；回测区间需覆盖 CSV 中最早开仓日至结束日。
3. 查看「日志」中的 [probe] 行：bars>0 且 last_close 有值即表示本地/回测行情可读。

可选：在 init 里给 ContextInfo.dafengniu_csv_path 指定其它 CSV 绝对路径（列格式同 manual_open）。

Also export 6-day OHLC/MA/tags: python qmt/scripts/dafengniu_open_window_metrics.py
or strategy_dafengniu_open_window_metrics_export.py (same default CSV).
"""

import csv
import os


class G:
	pass


g = G()


def _strategy_base_dir():
	try:
		return os.path.dirname(os.path.abspath(__file__))
	except NameError:
		pass
	try:
		import sys
		a0 = (sys.argv[0] or '').strip()
		if a0 and a0 not in ('-c', '-'):
			ap = os.path.abspath(a0)
			if os.path.isfile(ap):
				return os.path.dirname(ap)
	except Exception:
		pass
	return os.path.abspath(os.getcwd())


def _default_manual_csv():
	base = _strategy_base_dir()
	sync_p = os.path.normpath(
		os.path.join(base, '..', '\u5b9e\u76d8\u7b56\u7565', '\u5927\u75af\u725b\u5996\u80a1\u6570\u636e', 'dafengniu_sync_open_dates.csv')
	)
	old_p = os.path.normpath(os.path.join(base, '..', '\u5b9e\u76d8\u7b56\u7565', 'dafengniu_manual_open_dates.csv'))
	if os.path.isfile(sync_p):
		return sync_p
	return old_p


def _load_pairs(path_str):
	out = []
	if not path_str or not os.path.isfile(path_str):
		print('[probe] \u6587\u4ef6\u4e0d\u5b58\u5728: %s' % path_str)
		return out
	last_err = None
	for enc in ('utf-8-sig', 'gbk', 'utf-8'):
		try:
			with open(path_str, 'r', encoding=enc, newline='') as f:
				for row in csv.reader(f):
					if len(row) < 2:
						continue
					a = row[0].strip()
					b = row[1].strip()
					if not a or a.startswith('#'):
						continue
					al = a.lower()
					if al in ('code', 'symbol', 'stock', 'stock_code', 'ts_code'):
						continue
					if len(b) >= 8 and b[:8].isdigit():
						out.append((a, b[:8]))
			return out
		except Exception as e:
			last_err = str(e)[:120]
			out = []
			continue
	print('[probe] \u8bfb CSV \u5931\u8d25: %s' % (last_err or 'unknown'))
	return out


def init(C):
	g.probe_done = False
	raw = getattr(C, 'dafengniu_csv_path', None)
	g.csv_path = (str(raw).strip() if raw else '') or _default_manual_csv()
	print('[probe] csv=%s' % g.csv_path)


def after_init(C):
	if getattr(g, 'probe_done', False):
		return
	g.probe_done = True
	pairs = _load_pairs(g.csv_path)
	if not pairs:
		print('[probe] \u65e0\u6709\u6548\u884c\uff0c\u8bf7\u5148\u751f\u6210 dafengniu_manual_open_dates.csv')
		return
	end = getattr(C, 'end_time', '20991231')
	if isinstance(end, (int, float)):
		end = str(int(end))[:8]
	else:
		end = (end or '20991231')[:8]
	ok = 0
	bad = []
	for stock, open_ymd in pairs:
		try:
			try:
				download_history_data(stock, '1d', open_ymd, end)  # noqa: F821 QMT \u5185\u7f6e
			except Exception:
				pass
			data = C.get_market_data_ex(
				['close'],
				[stock],
				period='1d',
				start_time=open_ymd,
				end_time=end,
				dividend_type='front_ratio',
				fill_data=True,
				subscribe=False,
			)
			cl = None
			if data and stock in data:
				cl = data[stock].get('close')
			n = len(cl) if cl is not None else 0
			last = float(cl[-1]) if n else None
			if n > 0 and last is not None:
				print('[probe] OK %s open=%s bars=%d last_close=%s' % (stock, open_ymd, n, last))
				ok += 1
			else:
				bad.append(stock)
				print('[probe] EMPTY %s open=%s' % (stock, open_ymd))
		except Exception as e:
			bad.append('%s:%s' % (stock, str(e)[:40]))
			print('[probe] ERR %s open=%s %s' % (stock, open_ymd, e))
	print('[probe] \u603b\u7ed3 ok=%d fail_or_empty=%d total=%d' % (ok, len(bad), len(pairs)))
	if bad and len(bad) <= 30:
		print('[probe] \u5f02\u5e38\u5217\u8868:', bad)


def handlebar(C):
	pass
