#coding:gbk
"""
\u6301\u4ed3\u5929\u6570\u63a2\u6d4b\uff08\u4ec5 print\uff0c\u65e0\u4e0b\u5355\uff09

\u76ee\u7684\uff1a\u5bf9\u6bd4\u5404\u6765\u6e90\u662f\u5426\u80fd\u5012\u63a8\u300c\u5f00\u4ed3/\u4e70\u5165\u65e5\u300d\u4e0e\u65e5\u5386\u610f\u4e49\u4e0a\u7684\u6301\u4ed3\u5929\u6570\uff08\u975e\u4ea4\u6613\u65e5\u5386\u5dee\uff0c\u4e0e\u884c\u60c5\u8f6f\u4ef6 T+N \u53ef\u80fd\u4e0d\u540c\uff09\u3002

\u5efa\u8bae\uff1a\u5468\u671f\u9009 1m\uff1b\u5b9e\u76d8\u9ed8\u8ba4\u4ec5\u5728 is_last_bar \u4e14\u6bcf\u4ea4\u6613\u65e5\u9996\u6b21\u89e6\u53d1\u65f6\u6253\u5305\uff08\u907f\u514d\u6bcf\u5206\u949f\u5237\u5c4f\uff09\u3002

\u53ef\u5728 init \u524d\u7f6e\u5c5e\u6027\u8bbe ContextInfo\uff08\u4e0e\u4e3b\u7b56\u7565\u7c7b\u4f3c\uff09\uff1a
  - account_type: \u9ed8\u8ba4 STOCK
  - hold_days_log_mode: 'daily'\uff08\u9ed8\u8ba4\uff09\u6216 'each'\uff08\u6bcf\u6b21\u89e6\u53d1\u90fd\u6253\uff09
  - history_lookback: \u5386\u53f2\u6210\u4ea4\u56de\u6eaf\u5929\u6570\uff0c\u9ed8\u8ba4 120
  - handlebar_each_bar: \u56de\u6d4b\u65f6 True \u5219\u6bcf\u6839 K \u7ebf\u90fd\u53ef\u89e6\u53d1\uff08\u4ecd\u53d7 log_mode \u9650\u5236\uff09
  - gtd_strategy_name: \u82e5\u6210\u4ea4\u67e5\u8be2\u9700\u7b56\u7565\u540d\uff0c\u586b\u4e0e\u4e0b\u5355\u7b56\u7565\u540c\u540d\uff08\u4f1a\u4f18\u5148\u8bd5 4 \u53c2\u6570 get_trade_detail_data\uff09
  - deal_probe_max: \u6210\u4ea4\u5012\u63a8\u5931\u8d25\u65f6\u6bcf\u7c7b\u578b\u6700\u591a\u6253\u51e0\u6761\u6837\u672c\u884c\uff0c\u9ed8\u8ba4 5
  - deal_infer_relaxed: \u9ed8\u8ba4 True\u3002\u6210\u4ea4\u5012\u63a8\u65f6\u9664\u201c\u660e\u786e\u5356\u51fa\u201d\u5916\u53ef\u8ba1\u5165\u65e5\u671f\uff08\u65b9\u5411\u672a\u77e5\u65f6\uff09\uff0c\u4fbf\u4e8e\u5012\u63a8 2\u30013 \u5929\u524d\u4e70\u5165\u3002\u82e5\u8bef\u5305\u5356\u5355\u6539 False\u3002
  - trust_m_bIsToday: \u9ed8\u8ba4 False\u3002\u4ec5\u5728\u65e0\u6210\u4ea4/\u65e0\u660e\u6587\u5f00\u4ed3\u65e5\u4e14\u4f60\u786e\u8ba4\u8981\u7528\u201c\u4eca\u65e5\u6807\u8bb0\u201d\u8fd1\u4f3c\u4eca\u65e5\u5f00\u4ed3\u65f6\u6539 True\uff08\u5426\u5219\u65e5\u5386\u6301\u4ed3\u5929\u6570\u663e\u793a\u672a\u77e5\uff0c\u907f\u514d\u8bef\u663e 1 \u5929\uff09\u3002
  - step_trace_first_trade: \u9ed8\u8ba4 True\u3002\u6253\u5370 STEP1~\u6027\u522b\u68c0\u6d4b\u660e\u6587\u5f00\u4ed3/\u6df1\u5ea6\u626b\u63cf/holdings/\u5f53\u65e5\u6210\u4ea4/\u5386\u53f2\u6210\u4ea4/\u6c47\u603b\uff0c\u4e13\u6d4b\u201c\u9996\u6b21\u6210\u4ea4\u65e5\u201d\u662f\u5426\u53ef\u53d6\u3002
  - open_date_csv_path / manual_open_date_csv: \u672c\u5730 CSV \u8def\u5f84\uff08\u4e8c\u9009\u4e00\uff09\u3002\u4e24\u5217\uff1a\u4ee3\u7801, \u5f00\u4ed3\u65e5(YYYYMMDD)\uff1b\u652f\u6301 # \u6ce8\u91ca\u4e0e utf-8/gbk\u3002\u624b\u5de5\u8bb0\u5f55\u4f18\u5148\u4e8e\u63a5\u53e3\u5012\u63a8\u3002\u6587\u4ef6\u53d8\u66f4\u540e\u4e0b\u6839 K \u7ebf\u81ea\u52a8\u91cd\u8f7d\u3002

\u5173\u4e8e m_bIsToday\uff1a\u5f88\u591a\u7248\u672c\u91cc\u4e0d\u7b49\u4ef7\u4e8e\u771f\u5b9e\u9996\u6b21\u4e70\u5165\u65e5\u3002\u811a\u672c\u4f18\u5148\u5386\u53f2/\u5f53\u65e5\u6210\u4ea4\u5012\u63a8\u3001\u6301\u4ed3\u5bf9\u8c61\u6df1\u5ea6\u5b57\u6bb5\u626b\u63cf\u3002
"""

import csv
import os
import sys
import time
import datetime

STRATEGY_TAG = '[HOLD-DAYS-PROBE]'


class G(object):
	pass


g = G()


def _get_trade_detail_data_fn():
	fn = getattr(sys.modules.get('__main__'), 'get_trade_detail_data', None)
	if fn is None:
		fn = globals().get('get_trade_detail_data')
	return fn


def _get_history_trade_detail_data_fn():
	fn = getattr(sys.modules.get('__main__'), 'get_history_trade_detail_data', None)
	if fn is None:
		fn = globals().get('get_history_trade_detail_data')
	return fn


def _holdings_fn():
	fn = getattr(sys.modules.get('__main__'), 'holdings', None)
	if fn is None:
		fn = globals().get('holdings')
	return fn


def timetag_to_datetime(timetag, format_str='%Y%m%d%H%M%S'):
	try:
		return time.strftime(format_str, time.localtime(float(timetag) / 1000.0))
	except Exception:
		try:
			return time.strftime(format_str, time.localtime(float(timetag)))
		except Exception:
			return str(timetag)


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


def _load_manual_open_date_csv(path_str):
	"""\u8fd4\u56de {canonical_code: YYYYMMDD}\uff0c\u8bfb\u5931\u8d25\u8fd4\u56de ({}, err)\u3002"""
	out = {}
	if not path_str or not str(path_str).strip():
		return out, None
	path_str = os.path.normpath(str(path_str).strip())
	if not os.path.isfile(path_str):
		return out, 'not_a_file'
	last_err = None
	for enc in ('utf-8-sig', 'gbk', 'utf-8'):
		try:
			with open(path_str, 'r', encoding=enc, newline='') as f:
				for row in csv.reader(f):
					if not row or len(row) < 2:
						continue
					a = row[0].strip()
					b = row[1].strip()
					if not a or a.startswith('#'):
						continue
					al = a.lower()
					if al in ('code', 'symbol', 'stock', 'stock_code', 'ts_code'):
						continue
					cc = _canonical_stock_code(a) or a.strip().upper()
					d = _tag_to_yyyymmdd(b)
					if cc and d:
						out[cc] = d
			return out, None
		except Exception as e:
			last_err = str(e)[:100]
			out = {}
			continue
	return out, last_err or 'read_failed'


def _ensure_manual_open_dates():
	"""\u6309\u6587\u4ef6 mtime \u91cd\u8f7d\u624b\u5de5\u5f00\u4ed3\u8868\u3002"""
	path = str(getattr(g, 'open_date_csv_path', '') or '').strip()
	if not path:
		g._manual_open_dates = {}
		g._manual_csv_mtime = None
		g._manual_csv_load_err = ''
		return
	try:
		mt = os.path.getmtime(path)
	except Exception as e:
		g._manual_open_dates = {}
		g._manual_csv_mtime = None
		g._manual_csv_load_err = str(e)[:80]
		return
	if getattr(g, '_manual_csv_mtime', None) == mt and isinstance(getattr(g, '_manual_open_dates', None), dict):
		return
	mp, err = _load_manual_open_date_csv(path)
	g._manual_open_dates = mp
	g._manual_csv_mtime = mt
	g._manual_csv_load_err = err or ''


def _canonical_stock_code(s):
	if s is None:
		return ''
	t = str(s).strip().upper().replace('\u3000', ' ')
	if not t:
		return ''
	if '.' in t:
		a, b = t.split('.', 1)
		if len(a) == 6 and a.isdigit() and b in ('SH', 'SZ', 'BJ'):
			return '%s.%s' % (a, b)
		if a in ('SH', 'SZ', 'BJ') and len(b) == 6 and b.isdigit():
			return '%s.%s' % (b, a)
	if len(t) >= 8 and t[:2] in ('SH', 'SZ', 'BJ') and t[2:8].isdigit():
		return '%s.%s' % (t[2:8], t[:2])
	return t


def _normalize_position_code(pos):
	if pos is None:
		return ''
	ins = (getattr(pos, 'm_strInstrumentID', None) or getattr(pos, 'stock_code', None) or '')
	try:
		ins = str(ins).strip()
	except Exception:
		ins = ''
	ex = (getattr(pos, 'm_strExchangeID', None) or getattr(pos, 'exchange_id', None) or '')
	try:
		ex = str(ex).upper().strip()
	except Exception:
		ex = ''
	if '.' in ins:
		return _canonical_stock_code(ins)
	if not ins:
		return ''
	if ex in ('SH', 'SS', '\u4e0a\u6d77'):
		return ins + '.SH'
	if ex in ('SZ', '\u6df1\u5733'):
		return ins + '.SZ'
	if ex:
		return ins + '.' + ex
	if ins.startswith(('60', '68', '51')):
		return ins + '.SH'
	return ins + '.SZ'


def _holdings_code(pos):
	try:
		ins = getattr(pos, 'instrumentid', None) if not isinstance(pos, dict) else pos.get('instrumentid')
		ex = getattr(pos, 'exchangeid', None) if not isinstance(pos, dict) else pos.get('exchangeid')
		ins = (str(ins).strip() if ins is not None else '')
		ex = (str(ex).strip().upper() if ex is not None else '')
		if ins and ex:
			return _canonical_stock_code('%s.%s' % (ins, ex))
		if ins:
			return _canonical_stock_code(ins)
	except Exception:
		pass
	return ''


def _is_long_holding(pos):
	try:
		d = getattr(pos, 'direction', None) if not isinstance(pos, dict) else pos.get('direction')
		if d is None or str(d).strip() == '':
			return True
		return int(d) == 48
	except Exception:
		return True


def _position_volume(p):
	try:
		v = int(getattr(p, 'm_nVolume', 0) or getattr(p, 'volume', 0) or 0)
		if v <= 0 and isinstance(p, dict):
			v = int(p.get('m_nVolume') or p.get('volume') or 0)
		return v
	except Exception:
		return 0


def _open_date_from_position_obj(p):
	for nm in (
		'opendate', 'openDate', 'm_strOpenDate', 'm_strFirstOpenDate',
		'm_strOpen', 'OpenDate', 'm_nOpenDate', 'm_nCreateDate', 'm_strCreateDate',
	):
		try:
			raw = (getattr(p, nm, None) if not isinstance(p, dict) else p.get(nm))
			d = _tag_to_yyyymmdd(raw)
			if d:
				return d, nm
		except Exception:
			continue
	return None, None


def _open_date_deep_scan_position(p, asof_yyyymmdd):
	"""\u660e\u6587\u5b57\u6bb5\u7a7a\u65f6\uff0c\u626b\u63cf\u6301\u4ed3\u5bf9\u8c61\u4e0a\u53ef\u80fd\u85cf\u5f00\u4ed3\u65e5\u7684\u5c5e\u6027\uff08\u4fdd\u5b88\uff09\u3002"""
	if p is None or not asof_yyyymmdd:
		return None, None
	prefer = (
		'm_strStockOpenDate', 'm_strOpenDate', 'm_nOpenDate', 'm_strFirstOpenDate',
		'm_strCreateDate', 'm_nCreateDate', 'm_strInitDate', 'm_strPositionOpenDate',
	)
	for nm in prefer:
		try:
			raw = getattr(p, nm, None) if not isinstance(p, dict) else p.get(nm)
			d = _tag_to_yyyymmdd(raw)
			if d and int(d) <= int(asof_yyyymmdd):
				return d, nm
		except Exception:
			continue
	skip_sub = (
		'instrument', 'exchange', 'volume', 'amount', 'price', 'profit', 'turnover',
		'last', 'float', 'static', 'cover', 'direction', 'today', 'market', 'underlying',
		'canuse', 'onroad', 'margin', 'cost', 'tax', 'fee', 'serial', 'order', 'remark',
	)
	best_d, best_nm = None, None
	try:
		for nm in dir(p):
			if nm.startswith('_'):
				continue
			ln = nm.lower()
			if any(s in ln for s in skip_sub):
				continue
			if 'tradingday' in ln and 'open' not in ln and 'first' not in ln:
				continue
			if not any(w in ln for w in ('open', 'first', 'create', 'init', 'date', 'time', 'day')):
				continue
			try:
				raw = getattr(p, nm)
				if callable(raw):
					continue
			except Exception:
				continue
			d = _tag_to_yyyymmdd(raw)
			if not d:
				continue
			try:
				if int(d) > int(asof_yyyymmdd):
					continue
			except Exception:
				continue
			if best_d is None or int(d) < int(best_d):
				best_d, best_nm = d, nm
	except Exception:
		pass
	return best_d, best_nm


def _infer_open_date_from_position_flags(p, d_str):
	"""\u5907\u9009\uff1a m_bIsToday=True \u65f6\u7528 d_str \u8fd1\u4f3c\u5f00\u4ed3\u65e5\uff08\u4ec5\u5728\u65e0\u6210\u4ea4/\u65e0\u660e\u6587\u5f00\u4ed3\u5b57\u6bb5\u65f6\u91c7\u7528\uff09\u3002"""
	if not d_str:
		return None, None
	for nm in ('m_bIsToday', 'm_bToday', 'mbIsToday', 'is_today', 'isToday'):
		try:
			v = getattr(p, nm, None) if not isinstance(p, dict) else p.get(nm)
		except Exception:
			v = None
		if v is True or v == 1:
			return d_str, nm
		if isinstance(v, str) and v.strip().upper() in ('TRUE', '1', 'Y', 'YES', 'T'):
			return d_str, '%s=%s' % (nm, v)
	return None, None


def _position_reported_hold_days(p):
	"""\u6709\u5219\u8fd4\u56de\u63a5\u53e3\u62a5\u544a\u7684\u6301\u4ed3\u5929\u6570\u5b57\u6bb5\uff08\u4ec5\u53c2\u8003\uff09\u3002"""
	for nm in ('m_nHoldingDays', 'm_nHoldDays', 'm_lHoldingDays', 'holding_days', 'HoldDays', 'm_nHoldDay'):
		try:
			raw = getattr(p, nm, None) if not isinstance(p, dict) else p.get(nm)
			if raw is None:
				continue
			n = int(raw)
			if n >= 0:
				return n, nm
		except Exception:
			continue
	return None, None


def _attrs_interest_scan(obj, max_all=40):
	"""m_ \u524d\u7f00\u5168\u91cf\uff1b\u5176\u4f59\u5b57\u6bb5\u4ec5\u6253\u5305\u542b\u5173\u952e\u5b57\u7684\u884c\u3002"""
	if obj is None:
		return 'None', []
	if isinstance(obj, dict):
		keys = list(obj.keys())
		lines = []
		for k in sorted(keys):
			if str(k).lower().startswith('m_') or _attr_name_interesting(str(k)):
				try:
					lines.append('%s=%r' % (k, obj.get(k)))
				except Exception:
					lines.append('%s=?' % k)
		return 'dict', lines
	lines = []
	all_pub = [k for k in dir(obj) if not k.startswith('_')]
	for k in sorted(all_pub):
		if not k.startswith('m_') and not _attr_name_interesting(k):
			continue
		try:
			v = getattr(obj, k)
			if callable(v):
				continue
			lines.append('%s=%r' % (k, v))
		except Exception:
			lines.append('%s=?', k)
	if len(lines) > max_all:
		lines = lines[:max_all] + ['... truncated ...']
	return type(obj).__name__, lines


def _attr_name_interesting(name):
	n = name.lower()
	for w in ('open', 'date', 'day', 'hold', 'time', 'trade', 'buy', 'first', 'create', 'cost', 'price', 'volume', 'direction', 'today'):
		if w in n:
			return True
	return False


def _calendar_hold_days(buy_yyyymmdd, asof_yyyymmdd):
	"""\u540c\u4e3b\u7b56\u7565\u53e3\u5f84\uff1a\u5f53\u65e5\u5dee 0 \u8bb0\u4e3a 1 \u5929\u3002"""
	if not buy_yyyymmdd or not asof_yyyymmdd:
		return None
	try:
		dh = (datetime.datetime.strptime(asof_yyyymmdd, '%Y%m%d') -
		      datetime.datetime.strptime(buy_yyyymmdd, '%Y%m%d')).days
		return max(1, int(dh))
	except Exception:
		return None


def _min_trade_date_any_side(rows, want_code):
	"""\u5339\u914d\u4ee3\u7801\u7684\u884c\u91cc\u53ef\u89e3\u6790\u7684\u6700\u65e9\u6210\u4ea4/\u65e5\u671f\uff08\u4e0d\u7ba1\u4e70\u5356\uff09\uff0c\u7528\u4e8e\u6392\u67e5\u65b9\u5411\u8fc7\u6ee4\u662f\u5426\u8bef\u6740\u5168\u90e8\u3002"""
	best = None
	for x in rows or []:
		try:
			if not _codes_match(want_code, _trade_row_code(x)):
				continue
			d = _trade_row_date_wide(x)
			if not d:
				continue
			if best is None or int(d) < int(best):
				best = d
		except Exception:
			continue
	return best


def _row_compact_trace_line(x):
	"""STEP \u6837\u672c\u884c\u4e00\u884c\u3002"""
	try:
		c = _trade_row_code(x)
		dw = _trade_row_date_wide(x)
		ds = _trade_row_date(x)
		buy = _trade_row_is_buy(x)
		off = _offset_implies_buy(x)
		return 'code=%r norm_date=%s strict_date=%s is_buy=%s offset_buy=%s' % (c, dw, ds, buy, off)
	except Exception:
		return '?'


def _print_step_trace_first_trade(can, d_str, manual_open_d, explicit_d, explicit_nm, deep_d, deep_nm,
				  hd_date, hd_nm, has_holdings_row,
				  live_buckets, hist_strict, hist_relaxed, hist_dbg):
	"""\u5206\u6b65\u68c0\u6d4b\u662f\u5426\u80fd\u53d6\u5230\u9996\u6b21\u6210\u4ea4/\u5f00\u4ed3\u65e5\u671f\u3002"""
	print('%s   ========== STEP_TRACE %s asof=%s ==========' % (STRATEGY_TAG, can, d_str))
	csvp = str(getattr(g, 'open_date_csv_path', '') or '-')
	print('%s   STEP0 manual_csv file=%r date=%s (highest priority if set)' % (STRATEGY_TAG, csvp, manual_open_d or 'NONE'))
	print('%s   STEP1 position explicit(open* fields): date=%s field=%s'
	      % (STRATEGY_TAG, explicit_d or 'NONE', explicit_nm or '-'))
	print('%s   STEP2 position deep_scan(open/first/date* names): date=%s field=%s'
	      % (STRATEGY_TAG, deep_d or 'NONE', deep_nm or '-'))
	print('%s   STEP3 holdings(account) api: row_found=%s date=%s field=%s'
	      % (STRATEGY_TAG, 'Y' if has_holdings_row else 'N', hd_date or 'NONE', hd_nm or '-'))

	print('%s   STEP4 live get_trade_detail_data (\u540c\u4ee3\u7801\u884c\u6570/\u5012\u63a8\u65e5\u671f):' % STRATEGY_TAG)
	for kind in sorted(live_buckets.keys()):
		payload = live_buckets[kind]
		if not isinstance(payload[0], int):
			print('%s      [%s] ERR %s' % (STRATEGY_TAG, kind, payload[0]))
			continue
		n, rows = payload[0], payload[1]
		nm = sum(1 for x in (rows or []) if _codes_match(can, _trade_row_code(x)))
		es = _infer_earliest_buy_from_rows(rows, can, False)
		er = _infer_earliest_buy_from_rows(rows, can, True)
		ea = _min_trade_date_any_side(rows, can)
		print('%s      [%s] total_rows=%d match_this_code=%d earliest_buy_strict=%s relaxed=%s any_side_earliest=%s'
		      % (STRATEGY_TAG, kind, n, nm, es or '-', er or '-', ea or '-'))
		shown = 0
		for x in rows or []:
			if not _codes_match(can, _trade_row_code(x)):
				continue
			print('%s         sample: %s' % (STRATEGY_TAG, _row_compact_trace_line(x)))
			shown += 1
			if shown >= 3:
				break
		if nm > 0 and shown == 0:
			print('%s         (match>0 but code_fn empty -> check _trade_row_code)' % STRATEGY_TAG)

	union = getattr(g, '_hist_union_rows', None) or []
	nmu = sum(1 for x in union if _codes_match(can, _trade_row_code(x)))
	es_u = _infer_earliest_buy_from_rows(union, can, False)
	er_u = _infer_earliest_buy_from_rows(union, can, True)
	ea_u = _min_trade_date_any_side(union, can)
	hs = hist_strict.get(can)
	hr = hist_relaxed.get(can)
	print('%s   STEP5 history get_history_trade_detail_data:' % STRATEGY_TAG)
	try:
		print('%s      union_rows=%s by_kind=%s swap_extra=%s'
		      % (STRATEGY_TAG, len(union), hist_dbg.get('by_kind', {}), hist_dbg.get('swap_rows', 0)))
	except Exception:
		pass
	print('%s      match_this_code=%d recompute_buy_strict=%s relaxed=%s any_side=%s'
	      % (STRATEGY_TAG, nmu, es_u or '-', er_u or '-', ea_u or '-'))
	print('%s      dict hist_strict[%s]=%s hist_relaxed[%s]=%s'
	      % (STRATEGY_TAG, can, hs or '-', can, hr or '-'))
	shown = 0
	for x in union:
		if not _codes_match(can, _trade_row_code(x)):
			continue
		print('%s         sample: %s' % (STRATEGY_TAG, _row_compact_trace_line(x)))
		shown += 1
		if shown >= 5:
			break

	live_bs = live_br = live_ba = None
	for kind in sorted(live_buckets.keys()):
		payload = live_buckets[kind]
		if not isinstance(payload[0], int):
			continue
		rows = payload[1] or []
		xs = _infer_earliest_buy_from_rows(rows, can, False)
		if xs and (live_bs is None or int(xs) < int(live_bs)):
			live_bs = xs
		xr = _infer_earliest_buy_from_rows(rows, can, True)
		if xr and (live_br is None or int(xr) < int(live_br)):
			live_br = xr
		xa = _min_trade_date_any_side(rows, can)
		if xa and (live_ba is None or int(xa) < int(live_ba)):
			live_ba = xa

	parts = []
	for label, val in (
		('manual_csv', manual_open_d),
		('explicit', explicit_d), ('deep', deep_d), ('holdings', hd_date),
		('live_buy_strict_best', live_bs), ('live_buy_relaxed_best', live_br), ('live_any_side_best', live_ba),
		('hist_strict_dict', hs), ('hist_relaxed_dict', hr),
		('hist_union_buy_strict', es_u), ('hist_union_buy_relaxed', er_u),
		('hist_union_any_side', ea_u),
	):
		if val:
			parts.append((label, val))
	best_date, best_src = None, None
	if manual_open_d:
		best_date, best_src = manual_open_d, 'manual_csv'
	else:
		for lab, vd in parts:
			if not vd:
				continue
			if best_date is None or int(vd) < int(best_date):
				best_date, best_src = vd, lab
	print('%s   STEP6 summary: candidates=%s -> picked=%s from=%s (\u624b\u5de5CSV\u82e5\u6709\u5219\u76f4\u63a5\u91c7\u7528)'
	      % (STRATEGY_TAG, parts, best_date or 'NONE', best_src or '-'))
	print('%s   ========== STEP_TRACE end %s ==========' % (STRATEGY_TAG, can))


def _pick_open_date_for_calendar(manual_open_d, gtd_date, gtd_nm, hd_date, hd_nm, flag_d, flag_src, inf_live, inf_hist, trust_today_flag):
	"""\u624b\u5de5 CSV > \u660e\u6587\u5f00\u4ed3 > holdings > \u5386\u53f2 > \u5f53\u65e5\uff1b trust_today \u7528 m_bIsToday\u3002"""
	if manual_open_d:
		return manual_open_d, 'manual_csv'
	pairs = (
		(gtd_date, 'position_field:%s' % (gtd_nm or '-')),
		(hd_date, 'holdings_field:%s' % (hd_nm or '-')),
		(inf_hist, 'history_deal'),
		(inf_live, 'live_deal'),
	)
	for d, src in pairs:
		if d:
			return d, src
	if trust_today_flag and flag_d:
		return flag_d, 'today_flag(last_resort):%s' % (flag_src or '-')
	return None, None


def _codes_match(want_code, row_code):
	"""\u6210\u4ea4\u884c\u4ee3\u7801\u53ef\u80fd\u65e0\u5e02\u573a\u540e\u7f00\uff0c\u4e0e 600699.SH \u5bbd\u5339\u914d\u3002"""
	if not want_code or not row_code:
		return False
	if want_code == row_code:
		return True
	wa = want_code.split('.')[0] if '.' in want_code else want_code
	rb = row_code.split('.')[0] if '.' in row_code else row_code
	try:
		return len(wa) == 6 and wa.isdigit() and wa == rb
	except Exception:
		return False


def _trade_row_code(x):
	try:
		for nm in ('m_strWindCode', 'm_strFullCode', 'm_strSecuritiesID', 'm_strProductID'):
			v = (getattr(x, nm, None) if not isinstance(x, dict) else x.get(nm))
			if v is None or str(v).strip() == '':
				continue
			s = str(v).strip().upper().replace('\u3000', ' ')
			if '.' in s:
				return _canonical_stock_code(s)
			if len(s) >= 8 and s[:2] in ('SH', 'SZ', 'BJ') and s[2:8].isdigit():
				return _canonical_stock_code('%s.%s' % (s[2:8], s[:2]))
		ins = (getattr(x, 'instrumentid', None) or getattr(x, 'm_strInstrumentID', None) or
		       getattr(x, 'stock_code', None) or (x.get('instrumentid') if isinstance(x, dict) else None) or
		       (x.get('m_strInstrumentID') if isinstance(x, dict) else None))
		ex = (getattr(x, 'exchangeid', None) or getattr(x, 'm_strExchangeID', None) or
		      (x.get('exchangeid') if isinstance(x, dict) else None) or
		      (x.get('m_strExchangeID') if isinstance(x, dict) else None))
		ins = (str(ins).strip() if ins is not None else '')
		ex = (str(ex).strip().upper() if ex is not None else '')
		if ins and ex:
			return _canonical_stock_code('%s.%s' % (ins, ex))
		if ins:
			s = ins.upper()
			if len(s) >= 8 and s[:2] in ('SH', 'SZ', 'BJ') and s[2:8].isdigit():
				return _canonical_stock_code('%s.%s' % (s[2:8], s[:2]))
			return _canonical_stock_code(ins)
	except Exception:
		pass
	return ''


def _trade_row_is_buy(x):
	try:
		dv = (getattr(x, 'direction', None) if not isinstance(x, dict) else x.get('direction'))
		if dv is None:
			dv = (getattr(x, 'm_nDirection', None) if not isinstance(x, dict) else x.get('m_nDirection'))
		if dv is not None and str(dv).strip() != '':
			try:
				iv = int(dv)
				if iv in (48, 1, 23):
					return True
				if iv in (49, -1, 2, 24):
					return False
			except Exception:
				s = str(dv).strip().upper()
				if s in ('BUY', 'B', 'LONG', '\u591a', '\u4e70'):
					return True
				if s in ('SELL', 'S', 'SHORT', '\u7a7a', '\u5356'):
					return False
		for nm in ('bsflag', 'side', 'entrust_bs', 'm_nBSFlag', 'm_strBsFlag', 'm_strBSFlag'):
			v = (getattr(x, nm, None) if not isinstance(x, dict) else x.get(nm))
			if v is None:
				continue
			if isinstance(v, int):
				if v in (66, ord('B')):
					return True
				if v in (83, ord('S')):
					return False
			s = str(v).strip().upper()
			if s in ('B', 'BUY', '0', '48', 'BUY_OPEN'):
				return True
			if s in ('S', 'SELL', '1', '49', 'SELL_CLOSE'):
				return False
	except Exception:
		pass
	return None


def _offset_implies_buy(x):
	"""\u6210\u4ea4/\u59d4\u6258\u504f\u79fb\u65b9\u5411\uff1b\u65e0\u6cd5\u5224\u65ad\u8fd4\u56de None\u3002"""
	for nm in ('m_nOffsetFlag', 'm_nCombOffsetFlag', 'offset_flag', 'm_strOffsetFlag'):
		try:
			v = getattr(x, nm, None) if not isinstance(x, dict) else x.get(nm)
			if v is None or str(v).strip() == '':
				continue
			try:
				iv = int(v)
				if iv in (48, 23, 0):
					return True
				if iv in (49, 24, 1):
					return False
			except Exception:
				s = str(v).strip().upper()
				if s in ('B', '48', 'OPEN', 'BUY'):
					return True
				if s in ('S', '49', 'CLOSE', 'SELL'):
					return False
		except Exception:
			continue
	return None


def _trade_row_date(x):
	for nm in (
		'm_strTradeDate', 'm_strDealDate', 'm_strBusinessDate', 'm_strDateTime',
		'opendate', 'trade_date', 'tradingday', 'date', 'tradedate',
		'm_strDate', 'm_strTradingDay', 'm_strOpenDate', 'm_nTradeDate',
		'm_strMatchedDate', 'm_strSettleDate', 'm_strReportDate',
	):
		try:
			raw = (getattr(x, nm, None) if not isinstance(x, dict) else x.get(nm))
			d = _tag_to_yyyymmdd(raw)
			if d:
				return d
		except Exception:
			continue
	return None


def _trade_row_date_wide(x):
	"""\u5728\u6807\u51c6\u5b57\u6bb5\u65e0\u65e5\u671f\u65f6\uff0c\u4ece\u6210\u4ea4\u884c\u5c5e\u6027\u540d\u4e2d\u542b date/time/day \u7684\u5b57\u6bb5\u91cc\u53d6\u6700\u65e9\u53ef\u89e3\u6790\u65e5\u671f\u3002"""
	d0 = _trade_row_date(x)
	if d0:
		return d0
	skip = ('instrument', 'code', 'volume', 'amount', 'price', 'profit', 'balance', 'serial', 'order', 'remark', 'status', 'direction', 'offset', 'bs', 'flag')
	found = []
	try:
		for k in dir(x):
			if k.startswith('_'):
				continue
			lk = k.lower()
			if any(s in lk for s in skip):
				continue
			if not any(w in lk for w in ('date', 'time', 'day')):
				continue
			try:
				v = getattr(x, k)
				if callable(v):
					continue
			except Exception:
				continue
			td = _tag_to_yyyymmdd(v)
			if td:
				found.append(td)
	except Exception:
		pass
	if not found:
		return None
	return min(found, key=lambda s: int(s))


def _row_counts_as_buy_for_infer(x, relaxed):
	"""\u662f\u5426\u8ba1\u5165\u201c\u5012\u63a8\u4e70\u5165/\u5f00\u4ed3\u201d\u6210\u4ea4\u3002relaxed \u65f6\u53ea\u6392\u9664\u660e\u786e\u5356\u51fa\u3002"""
	b = _trade_row_is_buy(x)
	if b is True:
		return True
	if b is False:
		return False
	if not relaxed:
		return False
	off = _offset_implies_buy(x)
	if off is True:
		return True
	if off is False:
		return False
	return True


def _infer_earliest_buy_from_rows(rows, want_code, relaxed=False):
	best = None
	for x in rows or []:
		try:
			c = _trade_row_code(x)
			if not _codes_match(want_code, c):
				continue
			if not _row_counts_as_buy_for_infer(x, relaxed):
				continue
			d = _trade_row_date_wide(x)
			if not d:
				continue
			if best is None or int(d) < int(best):
				best = d
		except Exception:
			continue
	return best


def _deal_row_debug_line(x):
	"""\u7d27\u51d1\u4e00\u884c\uff0c\u7528\u4e8e\u6210\u4ea4\u65b9\u5411\u5b57\u6bb5\u4e0d\u5339\u914d\u65f6\u6392\u67e5\u3002"""
	try:
		parts = []
		for nm in ('m_strInstrumentID', 'instrumentid', 'm_strExchangeID', 'exchangeid',
		           'm_nDirection', 'direction', 'm_nBSFlag', 'bsflag', 'm_strTradingDay',
		           'm_strTradeDate', 'm_strDate', 'trade_date', 'm_dTradeAmount', 'm_nVolume',
		           'm_nOffsetFlag'):
			v = (getattr(x, nm, None) if not isinstance(x, dict) else x.get(nm))
			if v is not None and str(v).strip() != '':
				parts.append('%s=%r' % (nm, v))
		return '; '.join(parts[:14])
	except Exception:
		return '?'


def _print_deal_probe_for_code(rows, want_code, tag, max_rows):
	n = 0
	for x in rows or []:
		try:
			if not _codes_match(want_code, _trade_row_code(x)):
				continue
			print('%s   [%s] row#%d %s' % (STRATEGY_TAG, tag, n, _deal_row_debug_line(x)))
			n += 1
			if n >= max_rows:
				break
		except Exception:
			continue
	if n == 0 and rows:
		# \u6210\u4ea4\u6709\u6570\u636e\u4f46\u4ee3\u7801\u683c\u5f0f\u4e0d\u5339\u914d\uff1a\u6253\u524d\u51e0\u6761\u539f\u59cb\u6837\u672c
		for i, x in enumerate(rows[:3]):
			print('%s   [%s] sample_row#%d %s' % (STRATEGY_TAG, tag, i, _deal_row_debug_line(x)))


def _gtd_call_variants(gtd_fn, kind):
	"""Try 4-arg then 3-arg get_trade_detail_data; return (rows, None) or ([], err)."""
	last_err = None
	args_list = []
	sn = getattr(g, 'gtd_strategy_name', None) or ''
	sn = str(sn).strip()
	if sn:
		args_list.append((g.accid, g.account_type, kind, sn))
	args_list.append((g.accid, g.account_type, kind))
	for args in args_list:
		try:
			rows = gtd_fn(*args) or []
			return rows, None
		except TypeError as e:
			last_err = str(e)[:80]
		except Exception as e:
			return [], str(e)[:80]
	return [], last_err or 'gtd_call_failed'


def _scan_live_deal_kinds(gtd_fn):
	out = {}
	for kind in ('deal', 'trade', 'trades', 'deal_list'):
		rows, err = _gtd_call_variants(gtd_fn, kind)
		if err:
			out[kind] = ('ERR:%s' % err, [])
		else:
			out[kind] = (len(rows), rows)
	return out


def _scan_history_deals(hist_fn, d_str, lookback):
	"""\u5408\u5e76\u591a\u7c7b\u578b\u5386\u53f2\u6210\u4ea4\uff0c\u5c1d\u8bd5\u65e5\u671f\u53c2\u6570\u6b63\u53cd\u5e8f\uff1b\u8fd4\u56de (best_strict, best_relaxed, err, dbg)\u3002"""
	start = (datetime.datetime.strptime(d_str, '%Y%m%d') -
	         datetime.timedelta(days=max(1, int(lookback)))).strftime('%Y%m%d')
	best_s, best_r = {}, {}
	err = []
	dbg = {'by_kind': {}, 'union_rows': 0, 'swap_rows': 0, 'sample_codes': []}
	seen = set()
	union = []
	kinds = ('deal', 'trade', 'trades', 'order', 'HisDeal', 'hisdeal', 'his_deal', 'historydeal')

	def _ingest(rows):
		for x in rows or []:
			i = id(x)
			if i in seen:
				continue
			seen.add(i)
			union.append(x)

	for kind in kinds:
		try:
			rows = hist_fn(g.accid, g.account_type, kind, start, d_str) or []
		except Exception as e:
			err.append('%s:%s' % (kind, str(e)[:40]))
			dbg['by_kind'][kind] = -1
			continue
		dbg['by_kind'][kind] = len(rows)
		_ingest(rows)

	try:
		alt = hist_fn(g.accid, g.account_type, 'deal', d_str, start) or []
		dbg['swap_rows'] = len(alt)
		_ingest(alt)
	except Exception as e:
		dbg['swap_err'] = str(e)[:60]

	dbg['union_rows'] = len(union)
	for x in union[:400]:
		c0 = _trade_row_code(x)
		if c0 and c0 not in dbg['sample_codes']:
			dbg['sample_codes'].append(c0)
		if len(dbg['sample_codes']) >= 12:
			break

	for x in union:
		try:
			c = _trade_row_code(x)
			if not c:
				continue
			d = _trade_row_date_wide(x)
			if not d:
				continue
			if _row_counts_as_buy_for_infer(x, False):
				old = best_s.get(c)
				if old is None or int(d) < int(old):
					best_s[c] = d
			if _row_counts_as_buy_for_infer(x, True):
				old = best_r.get(c)
				if old is None or int(d) < int(old):
					best_r[c] = d
		except Exception:
			continue
	try:
		g._hist_union_rows = union
	except Exception:
		pass
	return best_s, best_r, err, dbg


def _account_type():
	t = getattr(g, 'account_type', None) or 'STOCK'
	return str(t) if t else 'STOCK'


def _is_qmt_backtest_context(C):
	if bool(getattr(C, 'do_back_test', False)):
		return True
	if bool(getattr(C, 'isDoBackTest', False)):
		return True
	rm = getattr(C, 'run_mode', None)
	if rm is None:
		rm = getattr(C, 'runMode', None)
	try:
		if rm is not None and int(rm) == 1:
			return True
	except (TypeError, ValueError):
		pass
	if isinstance(rm, str) and rm.strip().upper() in ('BACKTEST', 'TRUE', '1', 'T'):
		return True
	return False


def _handlebar_should_run(C):
	try:
		if C.is_last_bar():
			return True
	except Exception:
		return True
	if bool(getattr(g, 'handlebar_each_bar', False)):
		return True
	if _is_qmt_backtest_context(C):
		return True
	return False


def _holdings_list():
	if not (g.accid or '').strip():
		return []
	hd = _holdings_fn()
	if not hd:
		return []
	try:
		return hd(g.accid) or []
	except Exception:
		return []


def _holdings_row_for_code(can):
	for p in _holdings_list():
		try:
			if not _is_long_holding(p):
				continue
			vol = int((getattr(p, 'volume', None) if not isinstance(p, dict) else p.get('volume')) or 0)
			if vol <= 0:
				continue
			c = _holdings_code(p)
			if c != can:
				continue
			return p
		except Exception:
			continue
	return None


def _positions_from_gtd():
	_gtd = _get_trade_detail_data_fn()
	if not _gtd or not (g.accid or '').strip():
		return []
	try:
		return _gtd(g.accid, _account_type(), 'position') or []
	except Exception:
		return []


def init(C):
	g.accid = getattr(C, 'accountid', '') or getattr(C, 'account_id', '') or '30262698'
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'
	g.handlebar_each_bar = bool(getattr(C, 'handlebar_each_bar', False))
	g.hold_days_log_mode = str(getattr(C, 'hold_days_log_mode', 'daily') or 'daily').lower()
	g.history_lookback = int(getattr(C, 'history_lookback', 120))
	g.gtd_strategy_name = str(
		getattr(C, 'gtd_strategy_name', None) or getattr(C, 'strategyName', None) or
		getattr(C, 'strategy_order_name', None) or ''
	).strip()
	g.deal_probe_max = int(getattr(C, 'deal_probe_max', 5))
	g.deal_infer_relaxed = bool(getattr(C, 'deal_infer_relaxed', True))
	g.trust_m_bIsToday = bool(getattr(C, 'trust_m_bIsToday', False))
	g.step_trace_first_trade = bool(getattr(C, 'step_trace_first_trade', True))
	g.open_date_csv_path = str(
		getattr(C, 'open_date_csv_path', None) or getattr(C, 'manual_open_date_csv', None) or ''
	).strip()
	g._manual_open_dates = {}
	g._manual_csv_mtime = None
	g._manual_csv_load_err = ''
	_ensure_manual_open_dates()
	g._last_handlebar_barpos = None
	g._logged_days = set()
	print('=' * 64)
	print('%s init accid=%s account_type=%s log_mode=%s lookback=%d gtd_strategy_name=%r deal_probe_max=%d deal_infer_relaxed=%s trust_m_bIsToday=%s step_trace_first_trade=%s handlebar_each_bar=%s'
	      % (STRATEGY_TAG, g.accid, g.account_type, g.hold_days_log_mode, g.history_lookback,
	         g.gtd_strategy_name, g.deal_probe_max, g.deal_infer_relaxed, g.trust_m_bIsToday,
	         g.step_trace_first_trade, g.handlebar_each_bar))
	if g.open_date_csv_path:
		print('%s manual_open_date_csv path=%r loaded_codes=%d err=%r'
		      % (STRATEGY_TAG, g.open_date_csv_path, len(getattr(g, '_manual_open_dates', {}) or {}),
		         getattr(g, '_manual_csv_load_err', '')))
	print('%s \u4ec5\u6253\u5370\uff0c\u4e0d\u4e0b\u5355\u3002' % STRATEGY_TAG)
	print('=' * 64)


def handlebar(C):
	if not _handlebar_should_run(C):
		return
	bp = getattr(C, 'barpos', None)
	if bp is not None and bp == getattr(g, '_last_handlebar_barpos', None):
		return
	g._last_handlebar_barpos = bp

	dt_full = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	d_str = dt_full[:8]

	if g.hold_days_log_mode == 'daily' and d_str in g._logged_days:
		return

	if not (g.accid or '').strip():
		print('%s %s \u9519\u8bef: accid \u7a7a\uff0c\u8bf7\u5728 QMT \u7b56\u7565\u91cc\u7ed1\u5b9a\u8d44\u91d1\u8d26\u6237\u3002' % (dt_full, STRATEGY_TAG))
		return

	gtd = _get_trade_detail_data_fn()
	if not gtd:
		print('%s %s \u9519\u8bef: get_trade_detail_data \u4e0d\u53ef\u7528\u3002' % (dt_full, STRATEGY_TAG))
		return

	pos_list = _positions_from_gtd()
	codes = []
	for p in pos_list:
		can = _normalize_position_code(p)
		can = _canonical_stock_code(can) or can
		if not can or _position_volume(p) <= 0:
			continue
		codes.append((can, p))

	if not codes:
		print('%s %s \u8d26\u6237\u65e0\u6301\u4ed3\u91cf>0 \u7684 position \u8bb0\u5f55\uff08\u6216\u67e5\u8be2\u5931\u8d25\uff09\u3002'
		      % (dt_full, STRATEGY_TAG))
		if g.hold_days_log_mode == 'daily':
			g._logged_days.add(d_str)
		return

	_ensure_manual_open_dates()

	live_buckets = _scan_live_deal_kinds(gtd)
	hist_strict, hist_relaxed, hist_err, hist_dbg = {}, {}, [], {}
	hfn = _get_history_trade_detail_data_fn()
	if hfn:
		hist_strict, hist_relaxed, hist_err, hist_dbg = _scan_history_deals(hfn, d_str, g.history_lookback)

	print('')
	print('%s ========== %s bar=%s ==========' % (STRATEGY_TAG, dt_full, bp))
	if hist_err:
		print('%s history_scan_errors: %s' % (STRATEGY_TAG, hist_err))
	try:
		print('%s hist union_rows=%d swap_extra=%s by_kind=%s sample_instruments=%s'
		      % (STRATEGY_TAG, int(hist_dbg.get('union_rows', 0)), hist_dbg.get('swap_rows', 0),
		         hist_dbg.get('by_kind', {}), hist_dbg.get('sample_codes', [])))
	except Exception:
		pass
	for kind, payload in sorted(live_buckets.items()):
		if isinstance(payload[0], int):
			print('%s live %s rows=%d' % (STRATEGY_TAG, kind, payload[0]))
		else:
			print('%s live %s %s' % (STRATEGY_TAG, kind, payload[0]))

	for can, p in codes:
		vol = _position_volume(p)
		manual_open_d = (getattr(g, '_manual_open_dates', None) or {}).get(can)
		if manual_open_d:
			print('%s   [manual_csv] %s open_date=%s' % (STRATEGY_TAG, can, manual_open_d))
		explicit_d, explicit_nm = _open_date_from_position_obj(p)
		deep_d, deep_nm = _open_date_deep_scan_position(p, d_str)
		gtd_date = explicit_d or deep_d
		gtd_nm = (explicit_nm if explicit_d else deep_nm)
		if deep_d and not explicit_d:
			print('%s   [infer_position_scan] open_date=%s from %s' % (STRATEGY_TAG, deep_d, deep_nm))
		if explicit_d and deep_d and explicit_d != deep_d:
			print('%s   [warn] explicit_open=%s vs deep_scan=%s (use explicit for merge)' % (STRATEGY_TAG, explicit_d, deep_d))
		typ, lines = _attrs_interest_scan(p)
		print('')
		print('%s ---- %s vol=%d position_obj_type=%s ----' % (STRATEGY_TAG, can, vol, typ))
		for ln in lines:
			print('%s   %s' % (STRATEGY_TAG, ln))

		hrow = _holdings_row_for_code(can)
		hd_date, hd_nm = None, None
		if hrow is not None:
			hd_date, hd_nm = _open_date_from_position_obj(hrow)
			htyp, hlines = _attrs_interest_scan(hrow)
			print('%s   [holdings] type=%s opendate(%s)=%s' % (STRATEGY_TAG, htyp, hd_nm, hd_date))
			for ln in hlines[:24]:
				print('%s   [holdings] %s' % (STRATEGY_TAG, ln))
		else:
			print('%s   [holdings] no matching row or API missing' % STRATEGY_TAG)

		flag_d, flag_src = _infer_open_date_from_position_flags(p, d_str)
		rep_days, rep_nm = _position_reported_hold_days(p)
		if rep_days is not None:
			print('%s   [position] broker_numeric %s=%r' % (STRATEGY_TAG, rep_nm, rep_days))
		if flag_d:
			chd0 = _calendar_hold_days(flag_d, d_str)
			print('%s   [infer_flag] %s -> would_map open_date=%s calendar_hold_days=%s (only_used_if_trust_m_bIsToday=True)'
			      % (STRATEGY_TAG, flag_src, flag_d, chd0))

		inf_live = None
		inf_live_mode = None
		for kind, payload in live_buckets.items():
			if isinstance(payload[0], int) and payload[0] > 0:
				got = _infer_earliest_buy_from_rows(payload[1], can, False)
				if got:
					inf_live = got
					inf_live_mode = 'strict'
					print('%s   [infer_live] kind=%s earliest_buy=%s (strict)' % (STRATEGY_TAG, kind, got))
					break
		if inf_live is None and getattr(g, 'deal_infer_relaxed', True):
			for kind, payload in live_buckets.items():
				if isinstance(payload[0], int) and payload[0] > 0:
					got = _infer_earliest_buy_from_rows(payload[1], can, True)
					if got:
						inf_live = got
						inf_live_mode = 'relaxed'
						print('%s   [infer_live] kind=%s earliest_buy=%s (relaxed=\u9664\u660e\u786e\u5356\u5916\u53ef\u8ba1\u5165)'
						      % (STRATEGY_TAG, kind, got))
						break
		if inf_live is None:
			print('%s   [infer_live] no row matched\u3002\u6210\u4ea4\u975e\u7a7a\u65f6\u6253 deal_probe_* \u6837\u672c\u3002' % STRATEGY_TAG)
			for kind, payload in live_buckets.items():
				if not isinstance(payload[0], int) or payload[0] <= 0:
					continue
				_print_deal_probe_for_code(payload[1], can, 'deal_probe_' + kind, int(getattr(g, 'deal_probe_max', 5)))

		inf_hist_s = hist_strict.get(can)
		inf_hist_r = hist_relaxed.get(can) if getattr(g, 'deal_infer_relaxed', True) else None
		inf_hist = inf_hist_s or inf_hist_r
		if inf_hist:
			src = 'strict' if inf_hist_s else 'relaxed'
			print('%s   [infer_hist] earliest_buy=%s (%s, lookback=%dd)'
			      % (STRATEGY_TAG, inf_hist, src, g.history_lookback))
		else:
			print('%s   [infer_hist] no buy-like row in history window' % STRATEGY_TAG)
			try:
				union = getattr(g, '_hist_union_rows', None) or []
				nm = sum(1 for x in union if _codes_match(can, _trade_row_code(x)))
				if union:
					print('%s   [hist_debug] code=%s rows_match_code=%d / union=%d (\u82e5>0\u4f46\u65e0\u65e5\u671f/\u65b9\u5411\uff0c\u770b deal_probe)'
					      % (STRATEGY_TAG, can, nm, len(union)))
			except Exception:
				pass

		if getattr(g, 'step_trace_first_trade', True):
			try:
				_print_step_trace_first_trade(
					can, d_str, manual_open_d, explicit_d, explicit_nm, deep_d, deep_nm,
					hd_date, hd_nm, hrow is not None,
					live_buckets, hist_strict, hist_relaxed, hist_dbg)
			except Exception as e:
				print('%s   STEP_TRACE ERR %s' % (STRATEGY_TAG, str(e)[:120]))

		candidates = []
		for label, d in (
			('manual_csv', manual_open_d),
			('gtd_field:%s' % (gtd_nm or '-'), gtd_date),
			('holdings_field:%s' % (hd_nm or '-'), hd_date),
			('history_deal', inf_hist),
			('live_deal:%s' % (inf_live_mode or '-'), inf_live),
			('position_today_flag:%s' % (flag_src or '-'), flag_d),
		):
			if d:
				candidates.append((label, d))
		uniq = sorted(set(d for _, d in candidates))
		print('%s   [summary] open_date_candidates=%s unique_dates=%s' % (STRATEGY_TAG, candidates, uniq))
		for label, d in candidates:
			hd = _calendar_hold_days(d, d_str)
			print('%s   [summary] %s -> calendar_hold_days(asof %s)=%s' % (STRATEGY_TAG, label, d_str, hd))

		open_cal, src_cal = _pick_open_date_for_calendar(
			manual_open_d,
			gtd_date, gtd_nm, hd_date, hd_nm, flag_d, flag_src, inf_live, inf_hist,
			bool(getattr(g, 'trust_m_bIsToday', False)))
		if flag_d and open_cal and int(open_cal) < int(flag_d):
			print('%s   [warn] m_bIsToday suggests open=%s but chosen open=%s (%s) \u2192 \u4ee5\u6210\u4ea4/\u660e\u6587\u5b57\u6bb5\u4e3a\u51c6'
			      % (STRATEGY_TAG, flag_d, open_cal, src_cal))
		if (not open_cal) and flag_d and not getattr(g, 'trust_m_bIsToday', False):
			print('%s   [hint] \u65e5\u5386\u5f00\u4ed3\u672a\u77e5\uff1b\u53ef\u8bbe ContextInfo.open_date_csv_path=\u672c\u5730CSV(\u4ee3\u7801,\u5f00\u4ed3\u65e5)\uff1b\u6216 trust_m_bIsToday=True\uff1b\u6216\u5ba2\u6237\u7aef\u4ea4\u5272\u5355\u3002'
			      % STRATEGY_TAG)
		cal_hold = _calendar_hold_days(open_cal, d_str) if open_cal else None
		if rep_days is not None:
			print('%s   \u3010\u6301\u4ed3\u5929\u6570\u3011\u63a5\u53e3\u6570\u5b57\u5b57\u6bb5 %s = %s (\u82e5\u4e0e\u65e5\u5386\u53e3\u5f84\u4e0d\u540c\u4ee5\u63a5\u53e3\u4e3a\u51c6)'
			      % (STRATEGY_TAG, rep_nm, rep_days))
		if cal_hold is not None:
			print('%s   \u3010\u6301\u4ed3\u5929\u6570\u3011\u65e5\u5386\u53e3\u5f84 = %s \u5f00\u4ed3\u65e5=%s asof=%s \u4f9d\u636e=%s'
			      % (STRATEGY_TAG, cal_hold, open_cal, d_str, src_cal))
		else:
			print('%s   \u3010\u6301\u4ed3\u5929\u6570\u3011\u65e5\u5386\u53e3\u5f84 = \u672a\u77e5\uff08\u65e0\u53ef\u7528\u5f00\u4ed3\u65e5\uff0c\u6210\u4ea4\u5012\u63a8\u4e5f\u7a7a\uff09'
			      % STRATEGY_TAG)

	if g.hold_days_log_mode == 'daily':
		g._logged_days.add(d_str)
	print('%s ========== end ==========' % STRATEGY_TAG)
	print('')


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
