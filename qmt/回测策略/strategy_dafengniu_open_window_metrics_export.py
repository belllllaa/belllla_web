#coding:gbk
"""
QMT \u56de\u6d4b\uff1a\u8bfb dafengniu_manual_open_dates.csv\uff0c\u62c9\u65e5\u7ebf\u524d\u590d\u6743\uff08front_ratio\uff09\uff0c
\u8ba1\u7b97\u5f00\u4ed3\u65e5\uff08\u542b\uff09\u8d77\u8fde\u7eed 6 \u4e2a\u4ea4\u6613\u65e5\u7684\u5f00/\u6536\u76d8\u4ef7\u3001MA5\u3001MA10\uff08MA \u4fdd\u75592 \u4f4d\u5c0f\u6570\uff09\uff0c
\u4e24\u4e2a\u6807\u7b7e\uff0c\u5e76\u5199\u5165 CSV\uff08UTF-8-BOM\uff09\u3002

\u9ed8\u8ba4\u8def\u5f84\uff08\u7b56\u7565\u6587\u4ef6\u5728 qmt/\u56de\u6d4b\u7b56\u7565/\uff09\uff1a
  \u8f93\u5165 ../\u5b9e\u76d8\u7b56\u7565/dafengniu_manual_open_dates.csv
  \u8f93\u51fa ../\u5b9e\u76d8\u7b56\u7565/dafengniu_open_window_metrics_qmt.csv

ContextInfo \u53ef\u9009\uff1adafengniu_csv_path\uff0cdafengniu_export_csv_path\uff0cdafengniu_export_limit

Same path rules as watchlist resolve_manual_hold_open_csv_path, plus ASCII folder:
../dafengniu_csv/dafengniu_manual_open_dates.csv (under qmt, no Chinese path - copy CSV here if QMT fails on 实盘策略).

Keep only ONE strategy file on disk: prefer qmt/回测策略/strategy_dafengniu_open_window_metrics_export.py ; the copy under 实盘策略 was synced from it.
"""

import csv
import io
import os
import sys
import time
from datetime import datetime, timedelta

class G:
	pass


g = G()

N_WINDOW_DAYS = 6
DROP_RATIO = -0.09


def timetag_to_datetime(timetag, format_str='%Y%m%d%H%M%S'):
	try:
		import time as _t
		x = float(timetag)
		if x > 1e12:
			return _t.strftime(format_str, _t.localtime(x / 1000.0))
		if x > 1e9:
			return _t.strftime(format_str, _t.localtime(x))
	except Exception:
		pass
	try:
		s = str(timetag).strip()
		if len(s) >= 8 and s[:8].isdigit():
			return s[:8] + '000000'
	except Exception:
		pass
	return str(timetag)


def _ohlc_to_list(raw):
	if raw is None:
		return []
	try:
		import pandas as pd
		if isinstance(raw, pd.Series):
			return [float(x) for x in raw.tolist()]
		if isinstance(raw, pd.DataFrame):
			return [float(x) for x in raw.iloc[:, 0].tolist()]
	except Exception:
		pass
	if hasattr(raw, 'tolist') and not isinstance(raw, (list, tuple, bytes)):
		try:
			return [float(x) for x in raw.tolist()]
		except Exception:
			pass
	try:
		return [float(x) for x in list(raw)]
	except Exception:
		return []


def _ohlc_time_list(data, stock):
	if not data or stock not in data:
		return None
	for key in (
		'timetag', 'Timetag', 'time', 'Time', 'stime', 'Stime',
		'datetime', 'DateTime', 'trade_date', 'TradeDate', 'tradedate',
	):
		raw = data[stock].get(key)
		if raw is None:
			continue
		if hasattr(raw, 'tolist'):
			try:
				return list(raw.tolist())
			except Exception:
				pass
		try:
			return list(raw)
		except Exception:
			pass
	return None


def _tag_to_yyyymmdd(raw):
	if raw is None:
		return None
	if isinstance(raw, str):
		s = raw.strip()
		if len(s) >= 8 and s[:8].isdigit():
			return s[:8]
		digits = ''.join(ch for ch in s if ch.isdigit())
		if len(digits) >= 8:
			return digits[:8]
		return None
	try:
		s = timetag_to_datetime(raw, '%Y%m%d%H%M%S')
		if len(s) >= 8 and s[:8].isdigit():
			return s[:8]
	except Exception:
		pass
	try:
		x = float(raw)
		if x > 1e12:
			s = timetag_to_datetime(x, '%Y%m%d%H%M%S')
			if len(s) >= 8 and s[:8].isdigit():
				return s[:8]
		s = str(int(x))
		if len(s) == 8 and s.isdigit():
			return s
	except Exception:
		pass
	return None


def _norm_date_series(s):
	import pandas as pd
	return pd.to_datetime(s).dt.normalize()


def _pick_open_positions(d, target_date):
	import pandas as pd
	if d is None or d.empty or 'date' not in d.columns:
		return None, 'empty'
	dd = _norm_date_series(d['date']).dt.date
	for i in range(len(dd)):
		if dd.iloc[i] == target_date:
			return i, None
	for i in range(len(dd)):
		if dd.iloc[i] >= target_date:
			return i, 'first_trade_on_or_after_%s' % dd.iloc[i].isoformat()
	return None, 'no_bar_on_or_after'


def yyyymmdd_shift(d8, delta_days):
	d = datetime.strptime(d8, '%Y%m%d').date() + timedelta(days=delta_days)
	return d.strftime('%Y%m%d')


def _qmt_bars_to_sorted_df(data, sym):
	"""get_market_data_ex \u5355\u6807\u7684\u8fd4\u56de -> date/open/high/low/close \u5347\u5e8f DataFrame\u3002"""
	try:
		import numpy as np
		import pandas as pd
	except Exception:
		return None
	if not data or sym not in data:
		return None
	stk = data[sym]
	if isinstance(stk, pd.DataFrame):
		df = stk.reset_index()
		df.rename(columns={df.columns[0]: 'date'}, inplace=True)
		df['date'] = pd.to_datetime(df['date'])
		for k in ('open', 'high', 'low', 'close'):
			if k not in df.columns:
				return None
		return df[['date', 'open', 'high', 'low', 'close']].sort_values('date').reset_index(drop=True)

	o = _ohlc_to_list(stk.get('open'))
	h = _ohlc_to_list(stk.get('high'))
	lw = _ohlc_to_list(stk.get('low'))
	c = _ohlc_to_list(stk.get('close'))
	tags = _ohlc_time_list(data, sym)
	n = min(len(o), len(h), len(lw), len(c))
	if n <= 0:
		return None
	o, h, lw, c = o[:n], h[:n], lw[:n], c[:n]
	if tags and len(tags) >= n:
		pairs = []
		for i in range(n):
			td = _tag_to_yyyymmdd(tags[i])
			if not td:
				continue
			try:
				pairs.append((int(td), i))
			except Exception:
				pass
		if len(pairs) >= 2:
			pairs.sort(key=lambda x: x[0])
			idx = [x[1] for x in pairs]
			if len(idx) == n:
				o = [o[j] for j in idx]
				h = [h[j] for j in idx]
				lw = [lw[j] for j in idx]
				c = [c[j] for j in idx]
				tags = [tags[j] for j in idx]
	dts = []
	for i in range(len(o)):
		if tags and i < len(tags):
			td = _tag_to_yyyymmdd(tags[i])
			if td:
				try:
					dts.append(datetime.strptime(td, '%Y%m%d'))
					continue
				except Exception:
					pass
		dts.append(None)
	if any(x is None for x in dts):
		return None
	return pd.DataFrame({
		'date': dts,
		'open': o,
		'high': h,
		'low': lw,
		'close': c,
	})


def _compute_window(work, open_yyyymmdd, code):
	import pandas as pd
	if work is None or work.empty:
		return None, 'empty'
	try:
		target = datetime.strptime(open_yyyymmdd, '%Y%m%d').date()
	except ValueError:
		return None, 'bad_open_date'
	w = work.sort_values('date').reset_index(drop=True)
	for col in ('open', 'high', 'low', 'close'):
		if col not in w.columns:
			return None, 'missing_%s' % col
		w[col] = pd.to_numeric(w[col], errors='coerce')
	w['date'] = _norm_date_series(w['date'])
	w['ma5'] = w['close'].rolling(5, min_periods=5).mean()
	w['ma10'] = w['close'].rolling(10, min_periods=10).mean()

	pos, hint = _pick_open_positions(w, target)
	if pos is None:
		return None, hint or 'no_position'
	if pos + N_WINDOW_DAYS > len(w):
		return None, 'short_tail'

	win = w.iloc[pos:pos + N_WINDOW_DAYS]

	tag_3_oc = True
	for j in range(min(3, len(win))):
		o = win.iloc[j]['open']
		cl = win.iloc[j]['close']
		if pd.isna(o) or pd.isna(cl) or not (float(o) > float(cl)):
			tag_3_oc = False
			break

	tag_dd9 = False
	for j in range(len(win)):
		row_idx = pos + j
		if row_idx <= 0:
			continue
		prev_c = w.iloc[row_idx - 1]['close']
		low_j = w.iloc[row_idx]['low']
		if pd.isna(prev_c) or pd.isna(low_j) or float(prev_c) <= 0:
			continue
		if float(low_j) / float(prev_c) - 1.0 <= DROP_RATIO + 1e-12:
			tag_dd9 = True
			break

	row = {'\u4ee3\u7801': code, '\u5f00\u4ed3\u65e5': open_yyyymmdd}
	if hint:
		row['\u65e5\u671f\u5bf9\u9f50\u8bf4\u660e'] = hint

	for k in range(N_WINDOW_DAYS):
		prefix = 'D%d' % k
		if k >= len(win):
			row['%s_\u5f00\u76d8' % prefix] = ''
			row['%s_\u6536\u76d8' % prefix] = ''
			row['%s_MA5' % prefix] = ''
			row['%s_MA10' % prefix] = ''
			continue
		r = win.iloc[k]
		row['%s_\u5f00\u76d8' % prefix] = float(r['open']) if pd.notna(r['open']) else ''
		row['%s_\u6536\u76d8' % prefix] = float(r['close']) if pd.notna(r['close']) else ''
		m5 = r['ma5']
		m10 = r['ma10']
		row['%s_MA5' % prefix] = round(float(m5), 2) if pd.notna(m5) else ''
		row['%s_MA10' % prefix] = round(float(m10), 2) if pd.notna(m10) else ''

	if pos > 0:
		pc = w.iloc[pos - 1]['close']
		if pd.notna(pc):
			row['D0\u524d\u6536\u76d8'] = round(float(pc), 4)
		else:
			row['D0\u524d\u6536\u76d8'] = ''
	else:
		row['D0\u524d\u6536\u76d8'] = ''

	row['\u6807\u7b7e_\u5f00\u4ed3\u8d773\u4ea4\u6613\u65e5\u7686\u5f00\u76d8\u9ad8\u4e8e\u6536\u76d8'] = 1 if tag_3_oc else 0
	row['\u6807\u7b7e_\u7a97\u53e3\u5185\u6700\u4f4e\u8f83\u524d\u6536\u8dcc\u8d859pct'] = 1 if tag_dd9 else 0
	return row, None


def _base_dir():
	try:
		return os.path.dirname(os.path.abspath(__file__))
	except NameError:
		pass
	try:
		a0 = (sys.argv[0] or '').strip()
		if a0 and a0 not in ('-c', '-'):
			ap = os.path.abspath(a0)
			if os.path.isfile(ap):
				return os.path.dirname(ap)
	except Exception:
		pass
	return os.path.abspath(os.getcwd())


_MANUAL_CSV_NAME = 'dafengniu_manual_open_dates.csv'
_EXPORT_CSV_NAME = 'dafengniu_open_window_metrics_qmt.csv'


def default_dafengniu_manual_csv_path():
	"""\u4e0e strategy_my_watchlist_intraday_atr_1m_live_signal.default_manual_hold_open_csv_path \u540c\u53e3\u5f84\uff1aCSV \u9ed8\u8ba4\u5728\u7b56\u7565\u6587\u4ef6\u540c\u76ee\u5f55\u3002"""
	base = _base_dir()
	if not base:
		return ''
	return os.path.normpath(os.path.join(base, _MANUAL_CSV_NAME))


def _abs_if_file(path_str):
	if not path_str:
		return None
	p = os.path.normpath(os.path.abspath(str(path_str).strip()))
	if os.path.isfile(p):
		return p
	if os.name == 'nt' and not p.startswith('\\\\?\\') and not p.startswith('\\\\'):
		lp = '\\\\?\\' + p
		try:
			if os.path.isfile(lp):
				return p
		except Exception:
			pass
	return None


def _read_file_bytes(path_str):
	"""\u8bfb\u53d6\u6587\u4ef6\u5b57\u8282\uff1bWindows \u6ccc\u7528 \\\\?\\ \u957f\u8def\u5f84\u907f\u514d\u4e2d\u6587\u8def\u5f84\u5f02\u5e38\u3002"""
	if not path_str:
		return None, None
	p0 = os.path.normpath(os.path.abspath(str(path_str).strip()))
	cands = [p0]
	if os.name == 'nt' and not p0.startswith('\\\\?\\') and not p0.startswith('\\\\'):
		cands.append('\\\\?\\' + p0)
	last = None
	for p in cands:
		try:
			with open(p, 'rb') as bf:
				return bf.read(), None
		except Exception as e:
			last = e
	return None, last


def _iter_manual_csv_candidates():
	"""\u4e0e resolve_manual_hold_open_csv_path \u7684 _iter_manual_hold_csv_candidates \u540c\u7ed3\u6784\uff0c\u4ec5\u6587\u4ef6\u540d\u6539\u4e3a dafengniu_manual_open_dates.csv\u3002"""
	seen = set()
	name = _MANUAL_CSV_NAME
	base = _base_dir()
	for p in (
		default_dafengniu_manual_csv_path(),
		os.path.normpath(os.path.join(base, '..', 'dafengniu_csv', name)),
		os.path.normpath(os.path.join(base, '..', '\u5b9e\u76d8\u7b56\u7565', name)),
		os.path.join(
			os.environ.get('USERPROFILE', '') or '',
			'Documents',
			'belllla_web',
			'qmt',
			'\u5b9e\u76d8\u7b56\u7565',
			name,
		),
		os.path.join(
			r'c:\Users\admin\Documents\belllla_web',
			'qmt',
			'\u5b9e\u76d8\u7b56\u7565',
			name,
		),
		os.path.join(os.environ.get('USERPROFILE', '') or '', 'belllla_web', 'qmt', '\u5b9e\u76d8\u7b56\u7565', name),
		os.path.join('D:', 'belllla_web', 'qmt', '\u5b9e\u76d8\u7b56\u7565', name),
	):
		if not p:
			continue
		n = os.path.normpath(p)
		if n in seen:
			continue
		seen.add(n)
		yield n


def resolve_dafengniu_manual_csv(context_raw):
	"""\u4e0e resolve_manual_hold_open_csv_path \u540c\u6b65\u5e8f\uff1aContext -> \u73af\u5883\u53d8\u91cf -> \u5019\u9009\u8def\u5f84\u3002
	\u73af\u5883\u53d8\u91cf\u5305\u542b\u5b9e\u76d8\u7b56\u7565\u5df2\u7528\u7684 MANUAL_OPEN_DATE_CSV / BELLLLA_MANUAL_OPEN_CSV\uff08\u683c\u5f0f\u5747\u4e3a code,open_date \u65f6\u53ef\u5171\u7528\uff09\uff0c\u518d\u8bd5 DAFENGNIU_* \u3002"""
	cr = (context_raw or '').strip()
	if cr:
		got = _abs_if_file(cr)
		if got:
			return os.path.normpath(os.path.abspath(got)), 'context'
	for ev in (
		'MANUAL_OPEN_DATE_CSV',
		'BELLLLA_MANUAL_OPEN_CSV',
		'DAFENGNIU_MANUAL_CSV',
		'BELLLLA_DAFENGNIU_CSV',
	):
		got = _abs_if_file(os.environ.get(ev))
		if got:
			return got, ev
	for cand in _iter_manual_csv_candidates():
		got = _abs_if_file(cand)
		if got:
			return os.path.normpath(os.path.abspath(got)), 'auto_found'
	if cr:
		return os.path.normpath(os.path.abspath(cr)), 'context_missing_file'
	base = default_dafengniu_manual_csv_path()
	return base, 'fallback_default'


def resolve_dafengniu_export_csv(context_raw, manual_resolved_path):
	cr = (context_raw or '').strip()
	if cr:
		return os.path.normpath(os.path.abspath(cr)), 'context'
	base_dir = os.path.dirname(manual_resolved_path)
	if base_dir and os.path.isdir(base_dir):
		return os.path.normpath(os.path.join(base_dir, _EXPORT_CSV_NAME)), 'same_dir_as_manual'
	return os.path.normpath(os.path.join(_base_dir(), '..', '\u5b9e\u76d8\u7b56\u7565', _EXPORT_CSV_NAME)), 'fallback_default'


def _normalize_csv_cell(s):
	s = (s or '').strip().strip('\ufeff').strip('"').strip()
	return s.strip()


def _row_first_is_comment_or_header(a_lc):
	if not a_lc:
		return True
	if a_lc.startswith('#'):
		return True
	if a_lc in ('code', 'symbol', 'stock', 'stock_code', 'ts_code'):
		return True
	return False


def _load_pairs(path_str):
	if not path_str:
		return [], 'missing'
	if not _abs_if_file(path_str):
		return [], 'missing'
	raw, berr = _read_file_bytes(path_str)
	if raw is None:
		return [], 'read_binary:%s' % (str(berr)[:120] if berr else 'open_fail')
	last_err = None

	for enc in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'cp936'):
		out = []
		try:
			text = raw.decode(enc)
		except UnicodeDecodeError as e:
			last_err = 'decode_%s:%s' % (enc, str(e)[:80])
			continue
		except Exception as e:
			last_err = str(e)[:120]
			continue
		try:
			for row in csv.reader(io.StringIO(text)):
				if len(row) < 2:
					continue
				a = _normalize_csv_cell(row[0])
				b = _normalize_csv_cell(row[1])
				al = a.lower()
				if _row_first_is_comment_or_header(al):
					continue
				if len(b) >= 8 and b[:8].isdigit():
					out.append((a, b[:8]))
			if len(out) > 0:
				return out, None
			last_err = 'no_rows_after_%s' % enc
		except Exception as e:
			last_err = 'parse_%s:%s' % (enc, str(e)[:100])
			continue

	return [], 'read_fail:%s' % (last_err or 'unknown')


def init(C):
	ctx_csv = (
		getattr(C, 'dafengniu_csv_path', None)
		or getattr(C, 'open_date_csv_path', None)
		or getattr(C, 'manual_open_date_csv', None)
	)
	ctx_out = getattr(C, 'dafengniu_export_csv_path', None)
	g.csv_path, g._csv_resolve = resolve_dafengniu_manual_csv(ctx_csv)
	g.export_path, g._out_resolve = resolve_dafengniu_export_csv(ctx_out, g.csv_path)
	g.max_rows = int(getattr(C, 'dafengniu_export_limit', 0) or 0)
	print('[dafengniu-qmt] csv=%s (%s)' % (g.csv_path, getattr(g, '_csv_resolve', '')))
	print('[dafengniu-qmt] out=%s (%s)' % (g.export_path, getattr(g, '_out_resolve', '')))
	if not _abs_if_file(g.csv_path):
		print('[dafengniu-qmt] WARN: csv not found. Copy %s next to strategy, or into ../dafengniu_csv/ , or set DAFENGNIU_MANUAL_CSV / ContextInfo.' % _MANUAL_CSV_NAME)


def after_init(C):
	pairs, err = _load_pairs(g.csv_path)
	if err or not pairs:
		print('[dafengniu-qmt] load csv failed err=%s path=%s' % (err, g.csv_path))
		print('[dafengniu-qmt] Fix: copy %s into QMT user data folder, or set env DAFENGNIU_MANUAL_CSV=absolute path to that file' % _MANUAL_CSV_NAME)
		return
	if g.max_rows > 0:
		pairs = pairs[:g.max_rows]

	out_rows = []
	for sym, od in pairs:
		try:
			try:
				download_history_data(sym, '1d', yyyymmdd_shift(od, -180), yyyymmdd_shift(od, 90))  # noqa: F821
			except Exception:
				pass
			time.sleep(0.05)
			data = C.get_market_data_ex(
				['open', 'high', 'low', 'close'],
				[sym],
				period='1d',
				start_time=yyyymmdd_shift(od, -180),
				end_time=yyyymmdd_shift(od, 90),
				dividend_type='front_ratio',
				fill_data=True,
				subscribe=False,
			)
			if not data or sym not in data:
				out_rows.append({'\u4ee3\u7801': sym, '\u5f00\u4ed3\u65e5': od, '_error': 'no_qmt_data'})
				continue
			df = _qmt_bars_to_sorted_df(data, sym)
			if df is None or df.empty:
				out_rows.append({'\u4ee3\u7801': sym, '\u5f00\u4ed3\u65e5': od, '_error': 'df_convert_fail'})
				continue
			row, er2 = _compute_window(df, od, sym)
			if row is None:
				out_rows.append({'\u4ee3\u7801': sym, '\u5f00\u4ed3\u65e5': od, '_error': er2 or 'compute_fail'})
				continue
			out_rows.append(row)
		except Exception as e:
			out_rows.append({'\u4ee3\u7801': sym, '\u5f00\u4ed3\u65e5': od, '_error': str(e)[:120]})

	try:
		import pandas as pd
		dfo = pd.DataFrame(out_rows)
		for _t in ('\u6807\u7b7e_\u5f00\u4ed3\u8d773\u4ea4\u6613\u65e5\u7686\u5f00\u76d8\u9ad8\u4e8e\u6536\u76d8', '\u6807\u7b7e_\u7a97\u53e3\u5185\u6700\u4f4e\u8f83\u524d\u6536\u8dcc\u8d859pct'):
			if _t in dfo.columns:
				dfo[_t] = pd.to_numeric(dfo[_t], errors='coerce').fillna(0).astype(int)
		for _col in list(dfo.columns):
			if '_MA5' in _col or '_MA10' in _col:
				def _fmt_ma(v):
					if v is None or v == '':
						return ''
					try:
						if pd.isna(v):
							return ''
					except Exception:
						pass
					try:
						return '%.2f' % float(v)
					except Exception:
						return v
				dfo[_col] = dfo[_col].map(_fmt_ma)
		os.makedirs(os.path.dirname(g.export_path), exist_ok=True)
		dfo.to_csv(g.export_path, index=False, encoding='utf-8-sig', float_format='%.4f')
		print('[dafengniu-qmt] wrote rows=%d -> %s' % (len(dfo), g.export_path))
	except Exception as e:
		print('[dafengniu-qmt] write csv failed:', e)


def handlebar(C):
	pass
