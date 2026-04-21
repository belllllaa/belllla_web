#coding:gbk
"""Live 1m watchlist strategy (passorder). Doc: strategy_my_watchlist_intraday_atr_1m_live_signal.md"""

import sys
import time
import datetime


def _passorder_fn():
	fn = getattr(sys.modules.get('__main__'), 'passorder', None)
	if fn is None:
		fn = globals().get('passorder')
	return fn


def _get_trade_detail_data_fn():
	"""与 passorder 类似：QMT 可能把 get_trade_detail_data 挂在 __main__ 而非本模块 globals。"""
	fn = getattr(sys.modules.get('__main__'), 'get_trade_detail_data', None)
	if fn is None:
		fn = globals().get('get_trade_detail_data')
	return fn


def _holdings_fn():
	"""QMT 公式风格持仓接口：holdings(account)。"""
	fn = getattr(sys.modules.get('__main__'), 'holdings', None)
	if fn is None:
		fn = globals().get('holdings')
	return fn


import numpy as np

try:
	import talib
except Exception:
	talib = None


STRATEGY_TAG = '\u6211\u7684\u81ea\u9009\u5206\u6863\u5efa\u4ed3[\u5b9e\u76d8]'
INDEX_SSE = '000001.SH'


class G:
	pass


g = G()


def timetag_to_datetime(timetag, format_str='%Y%m%d%H%M%S'):
	try:
		return time.strftime(format_str, time.localtime(float(timetag) / 1000.0))
	except Exception:
		try:
			return time.strftime(format_str, time.localtime(float(timetag)))
		except Exception:
			return str(timetag)


def _account_type():
	t = getattr(g, 'account_type', None) or 'STOCK'
	return str(t) if t else 'STOCK'


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


def _vb():
	return bool(getattr(g, 'verbose_log', True))


def _trace(dt_full, msg):
	if getattr(g, 'signal_trace_log', True):
		print('%s [TRACE] %s' % (dt_full, msg))


def _mr_set(op, sh=0, px=None):
	"""\u672c\u5206\u949f\u6c47\u603b\u884c\u7684\u64cd\u4f5c\u8bf4\u660e\uff08\u53ef\u591a\u6b21\u8986\u76d6\uff0c\u4ee5\u6700\u540e\u4e00\u6b21\u4e3a\u51c6\uff09"""
	g._mr_op = op
	if sh is not None:
		g._mr_sh = int(sh)
	if px is not None:
		try:
			g._mr_px = float(px)
		except Exception:
			pass


def _snapshot_price_chg_open(C, stock, dt_full, d_str, tick_map, opc=None):
	"""(\u4eca\u5f00, \u6da8\u8dcc\u5e45%%, \u5f53\u524d\u4ef7) \u5931\u8d25\u7528 None; opc \u4e3a (\u4eca\u5f00,\u6628\u6536) \u65f6\u4e0d\u518d\u8bf7\u6c42\u65e5\u7ebf"""
	if not stock or stock == '-':
		return None, None, None
	if opc is not None:
		ot, pc = opc
	else:
		ot, pc = _opc_get(C, stock, dt_full, d_str)
	fb = None
	try:
		m1 = C.get_market_data_ex(['close'], [stock], end_time=dt_full, period='1m', count=1, subscribe=False)
		if stock in m1:
			cm = _ohlc_to_list(m1[stock].get('close'))
			if cm:
				fb = float(cm[-1])
	except Exception:
		pass
	px = _get_current_price(C, stock, dt_full, fb, tick_map)
	if px is None or (pc is not None and pc <= 0):
		return ot, None, px
	ch = (px / float(pc) - 1.0) * 100.0 if pc else None
	return ot, ch, px


def _ohlc_time_list(data, stock):
	"""K \u7ebf dict \u4e0a\u4e0e\u957f\u5ea6\u5339\u914d\u7684\u65f6\u95f4\u5217\uff08\u65e5\u7ebf/1m \u901a\u7528\uff09\u3002"""
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
	"""\u7edf\u4e00\u6210 8 \u4f4d\u4ea4\u6613\u65e5 YYYYMMDD\uff0c\u5931\u8d25 None\u3002"""
	if raw is None:
		return None
	if isinstance(raw, str):
		s = raw.strip()
		if len(s) >= 8 and s[:8].isdigit():
			return s[:8]
		# 兼容 2026-04-20 / 2026/04/20 / 2026-04-20 15:00:00 等格式
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


def _m1_last_close(C, stock, dt_full):
	try:
		m1 = C.get_market_data_ex(['close'], [stock], end_time=dt_full, period='1m', count=1, subscribe=False)
		if not m1 or stock not in m1:
			return None
		cm = _ohlc_to_list(m1[stock].get('close'))
		if not cm:
			return None
		v = float(cm[-1])
		return v if v > 0 else None
	except Exception:
		return None


def _parse_tick_scalar(t, names):
	if t is None:
		return None
	for nm in names:
		v = getattr(t, nm, None) if not isinstance(t, dict) else t.get(nm)
		if v is None:
			continue
		try:
			x = float(v)
			if x > 0:
				return x
		except Exception:
			pass
	return None


def _tick_pre_open(C, stock):
	"""\u5b9e\u76d8 tick \u7684\u6628\u6536/\u4eca\u5f00\uff08\u4e0e\u884c\u60c5\u8f6f\u4ef6\u4e00\u81f4\u6027\u66f4\u597d\uff09\uff1b\u65e0 tick \u8fd4\u56de (None, None)\u3002"""
	try:
		if not hasattr(C, 'get_full_tick'):
			return None, None
		ticks = C.get_full_tick([stock])
		if not ticks or stock not in ticks:
			return None, None
		t = ticks[stock]
		pre = _parse_tick_scalar(
			t, ('preClose', 'preclose', 'm_dPreClose', 'm_dPreClosePrice', 'lastClose', 'yesterdayClose', 'YesterdayClose')
		)
		opn = _parse_tick_scalar(
			t, ('open', 'Open', 'm_dOpen', 'm_dOpenPrice', 'todayOpen', 'nOpen', 'm_nOpen')
		)
		return pre, opn
	except Exception:
		return None, None


def _daily_last_bar_date(data_d, stock, closes_d):
	tags = _ohlc_time_list(data_d, stock)
	if not tags or len(tags) != len(closes_d):
		return None
	return _tag_to_yyyymmdd(tags[-1])


def _daily_bars_need_reverse(data_d, stock, closes, ref_px=None):
	"""\u65e5\u7ebf\u662f\u5426\u4e3a\u300c\u6700\u65b0\u5728\u524d\u300d\uff1b\u82e5\u662f\u5219\u9700\u53cd\u8f6c\u6210\u65f6\u95f4\u5347\u5e8f\uff08highs[-1]\u624d\u662f\u6700\u8fd1\u4e00\u6839\uff09\u3002"""
	if not closes:
		return False
	n = len(closes)
	tags = _ohlc_time_list(data_d, stock) if data_d and stock in data_d else None
	if tags and len(tags) >= n:
		t0 = _tag_to_yyyymmdd(tags[0])
		t1 = _tag_to_yyyymmdd(tags[-1])
		if t0 and t1 and int(t0) > int(t1):
			return True
	if ref_px is not None and float(ref_px) > 0 and n >= 2:
		e0 = abs(float(closes[0]) - float(ref_px)) / float(ref_px)
		e1 = abs(float(closes[-1]) - float(ref_px)) / float(ref_px)
		if e0 + 1e-12 < e1:
			return True
	return False


def _normalize_daily_hlc_order(highs, lows, closes, data_d, stock, ref_px=None):
	if not highs or not lows or not closes:
		return highs, lows, closes
	n = min(len(highs), len(lows), len(closes))
	highs, lows, closes = list(highs[:n]), list(lows[:n]), list(closes[:n])
	if _daily_bars_need_reverse(data_d, stock, closes, ref_px):
		return highs[::-1], lows[::-1], closes[::-1]
	return highs, lows, closes


def _align_daily_ohlc_chronological(data_d, stock, highs, lows, closes, ref_px=None):
	"""\u5148\u6309 timetag \u6392\u6210\u65f6\u95f4\u5347\u5e8f\uff08\u627f\u63a5\u968f\u673a\u9519\u4f4d\uff09\uff1b\u5426\u5219\u56de\u9000\u5230\u6574\u4f53\u53cd\u8f6c/ref \u542f\u53d1\u3002"""
	if not highs or not lows or not closes:
		return highs, lows, closes
	n = min(len(highs), len(lows), len(closes))
	highs, lows, closes = list(highs[:n]), list(lows[:n]), list(closes[:n])
	tags = _ohlc_time_list(data_d, stock) if data_d and stock in data_d else None
	pairs = []
	if tags and len(tags) >= n:
		for i in range(n):
			td = _tag_to_yyyymmdd(tags[i])
			if not td:
				continue
			try:
				pairs.append((int(td), i))
			except Exception:
				pass
	if len(pairs) >= n:
		pairs.sort(key=lambda x: x[0])
		idx = [x[1] for x in pairs]
		highs = [highs[j] for j in idx]
		lows = [lows[j] for j in idx]
		closes = [closes[j] for j in idx]
		return highs, lows, closes
	return _normalize_daily_hlc_order(highs, lows, closes, data_d, stock, ref_px)


def _intraday_high_since_open(C, stock, dt_full, d_str):
	"""\u5f53\u65e5 1m \u5168\u5929 high \u6700\u5927\u503c\uff08\u8865\u65e5\u7ebf\u672b\u6839\u672a\u542b\u4eca\u65e5\u6216 high \u6ede\u540e\u4e8e\u73b0\u4ef7\uff09\u3002"""
	if not stock or not d_str:
		return None
	specs = (
		dict(start_time=d_str + '093000', end_time=dt_full, subscribe=False),
		dict(end_time=dt_full, count=480, subscribe=False),
	)
	for spec in specs:
		try:
			kw = dict(period='1m', **spec)
			data_m = C.get_market_data_ex(['high'], [stock], **kw)
		except TypeError:
			continue
		except Exception:
			continue
		if not data_m or stock not in data_m:
			continue
		hh = _ohlc_to_list(data_m[stock].get('high'))
		if not hh:
			continue
		tags = _ohlc_time_list(data_m, stock)
		if tags and len(tags) == len(hh):
			same = []
			for i, t in enumerate(tags):
				td = _tag_to_yyyymmdd(t)
				if td == d_str:
					same.append(hh[i])
			if same:
				try:
					return max(float(x) for x in same if x is not None and float(x) > 0)
				except Exception:
					continue
		try:
			return max(float(x) for x in hh if x is not None and float(x) > 0)
		except Exception:
			continue
	return None


def _prev_close_without_daily_time(C, stock, dt_full, closes_d, n):
	"""\u65e5\u7ebf\u65e0\u6cd5\u5bf9\u9f50\u65e5\u671f\u65f6\uff1a\u7528 1m \u6536\u76d8\u4ef7\u4e0e\u65e5\u7ebf\u6700\u540e\u4e00\u6839\u6536\u76d8\u662f\u5426\u63a5\u8fd1\u5224\u65ad\u662f\u5426\u542b\u201c\u5f53\u65e5\u672a\u5b8c\u6210\u65e5K\u201d\u3002"""
	if n < 2:
		return float(closes_d[-1])
	m1c = _m1_last_close(C, stock, dt_full)
	if m1c is None:
		return float(closes_d[-1])
	dc = float(closes_d[-1])
	if dc <= 0:
		return float(closes_d[-2])
	if abs(m1c - dc) / dc <= 0.015:
		return float(closes_d[-2])
	return float(closes_d[-1])


def _opc_reset_day(d_str):
	if getattr(g, '_opc_day', '') != d_str:
		g._opc_day = d_str
		g._opc_map = {}


def _opc_get(C, stock, dt_full, d_str):
	"""\u6309 K \u7ebf\u4ea4\u6613\u65e5 d_str \u7f13\u5b58\u65e5\u7ebf+1m \u63a8\u7b97\u7ed3\u679c\uff1b\u5b9e\u76d8\u4f18\u5148\u7528 tick \u7684\u6628\u6536/\u4eca\u5f00\u8986\u76d6\u4ee5\u5bf9\u9f50\u884c\u60c5\u3002"""
	if not stock or not d_str:
		return None, None
	_opc_reset_day(d_str)
	if stock not in g._opc_map:
		g._opc_map[stock] = _opc_compute(C, stock, dt_full, d_str)
	o, p = g._opc_map[stock]
	tp, top = _tick_pre_open(C, stock)
	if tp and tp > 0:
		p = tp
	if top and top > 0:
		if o is None or o <= 0:
			o = top
	return (o, p)


def _first_open_today_from_1m(C, stock, dt_full, d_str):
	"""\u5f53\u65e5\u7ebf\u672a\u5305\u542b\u4eca\u65e5K\u65f6\uff0c\u7528\u5c11\u91cf 1m \u627e\u5f53\u65e5\u9996\u6839 open\uff08\u4ec5\u5728\u7f13\u5b58\u672a\u547d\u4e2d\u65f6\u8c03\u7528\uff09\u3002"""
	if not d_str:
		return None
	st_0930 = d_str + '093000'
	st_eod = d_str + '150100'
	specs = (
		dict(start_time=st_0930, end_time=st_eod, count=120),
		dict(start_time=st_0930, end_time=dt_full, count=240),
		dict(end_time=dt_full, count=480),
	)
	for spec in specs:
		try:
			ed = spec.get('end_time', dt_full)
			kw = dict(period='1m', subscribe=False, end_time=ed, count=spec['count'])
			if 'start_time' in spec:
				kw['start_time'] = spec['start_time']
			data_m = C.get_market_data_ex(['open'], [stock], **kw)
		except TypeError:
			continue
		except Exception:
			continue
		if not data_m or stock not in data_m:
			continue
		opens1 = _ohlc_to_list(data_m[stock].get('open'))
		if not opens1:
			continue
		tags = _ohlc_time_list(data_m, stock)
		if tags and len(tags) == len(opens1):
			best_i, best_t = None, None
			for i, tt in enumerate(tags):
				s = timetag_to_datetime(tt, '%Y%m%d%H%M%S') if not isinstance(tt, str) else str(tt).strip()
				if len(s) < 8 or s[:8] != d_str:
					continue
				if len(s) < 14:
					s = s[:8] + '000000'
				hh = int(s[8:14])
				if hh < 93000:
					continue
				if best_t is None or s < best_t:
					best_t, best_i = s, i
			if best_i is not None and best_i < len(opens1):
				v = float(opens1[best_i])
				if v > 0:
					return v
	return None


def _opc_compute(C, stock, dt_full, d_str):
	"""
	\u6628\u6536/\u4eca\u5f00\u5747\u57fa\u4e8e K \u7ebf\u65f6\u95f4 dt_full\uff08\u4e0e\u5899\u949f\u65e0\u5173\uff09\u3002
	\u65e5\u7ebf\u6700\u540e\u4e00\u6839\u65e5\u671f==d_str \u2192 \u542b\u5f53\u65e5\u672a\u5b8c\u6210\u65e5K\uff1a\u6628\u6536=closes[-2]\uff0c\u4eca\u5f00=opens[-1]\u3002
	\u5426\u5219\u6700\u540e\u4e00\u6839\u5df2\u5b8c\u6210\uff1a\u6628\u6536\u901a\u5e38\u4e3a closes[-1]\uff1b\u82e5\u65e5\u7ebf\u65e0\u65f6\u95f4\u5217\uff0c\u7528 1m \u6536\u76d8\u4e0e\u65e5\u7ebf\u672b\u6536\u662f\u5426\u63a5\u8fd1\u6765\u5224\u65ad\u662f\u5426\u542b\u5f53\u65e5K\u3002
	\u4eca\u5f00\u5728\u65e5\u7ebf\u65e0\u5f53\u65e5\u65f6\u7528\u5c11\u91cf 1m \u627e\u5f53\u65e5\u9996\u6839 open\u3002
	"""
	try:
		data_d = C.get_market_data_ex(
			['open', 'close'], [stock],
			end_time=dt_full, period='1d', count=max(int(g.bar_count), 10), subscribe=False
		)
		if stock not in data_d:
			return None, None
		opens_d = _ohlc_to_list(data_d[stock].get('open'))
		closes_d = _ohlc_to_list(data_d[stock].get('close'))
		if not opens_d or not closes_d:
			return None, None
		n = len(closes_d)
		last_date = _daily_last_bar_date(data_d, stock, closes_d)
		if last_date == d_str and n >= 2:
			prev_close = float(closes_d[-2])
			open_today = float(opens_d[-1])
			if prev_close <= 0 or open_today <= 0:
				return None, None
			return open_today, prev_close
		if last_date == d_str and n < 2:
			return None, None
		if last_date is None:
			prev_close = _prev_close_without_daily_time(C, stock, dt_full, closes_d, n)
		else:
			prev_close = float(closes_d[-1])
		if prev_close <= 0:
			return None, None
		open_today = _first_open_today_from_1m(C, stock, dt_full, d_str)
		if open_today is None or open_today <= 0:
			return None, prev_close
		return open_today, prev_close
	except Exception:
		return None, None


def _daily_open_prevclose(C, stock, dt_full, d_str=None):
	ds = d_str or (dt_full[:8] if isinstance(dt_full, str) and len(dt_full) >= 8 else '')
	return _opc_get(C, stock, dt_full, ds)


def _emit_minute_summary(C, dt_full, d_str, hhmmss, tick_map, pool, ph0, already, index_allow_new):
	if not getattr(g, 'minute_summary_log', True):
		return
	tr_st = getattr(g, '_mr_trade_stock', None)
	seen = set()
	lines = []
	if ph0 and ph0 not in (pool or []):
		lines.append(ph0)
	for s in pool or []:
		if s not in seen:
			seen.add(s)
			lines.append(s)
	focus = getattr(g, '_mr_focus', None)
	for st in lines:
		opc = _opc_get(C, st, dt_full, d_str) if st else (None, None)
		ot, chg, px = _snapshot_price_chg_open(C, st, dt_full, d_str, tick_map, opc=opc) if st else (None, None, None)
		if focus and st == focus:
			op = getattr(g, '_mr_op', '-')
			sh = int(getattr(g, '_mr_sh', 0) or 0)
			out_px = getattr(g, '_mr_px', None)
		else:
			op = _per_stock_watch_hint(C, st, dt_full, d_str, hhmmss, tick_map, already, index_allow_new, opc=opc)
			sh = int(getattr(g, '_mr_sh', 0) or 0) if (tr_st and st == tr_st) else 0
			out_px = getattr(g, '_mr_px', None) if (tr_st and st == tr_st) else None
		if out_px is None:
			out_px = px
		prev_s = ('%.3f' % float(opc[1])) if (opc and opc[1] is not None and float(opc[1]) > 0) else '--'
		open_s = ('%.3f' % float(ot)) if ot is not None and float(ot) > 0 else '--'
		cur_s = ('%.3f' % float(px)) if px is not None and float(px) > 0 else '--'
		chg_s = ('%.2f%%' % chg) if chg is not None else '--'
		ref_s = ('%.3f' % float(out_px)) if out_px is not None else '--'
		dh = _stock_hold_days(st, d_str)
		dh_s = ('%d' % dh) if dh is not None else '--'
		print('[MIN] \u65f6\u95f4=%s|\u4ee3\u7801=%s|\u6628\u6536=%s|\u4eca\u5f00=%s|\u73b0\u4ef7=%s|\u6da8\u8dcc\u5e45=%s|\u64cd\u4f5c=%s|\u80a1\u6570=%d|\u6301\u4ed3\u5929\u6570=%s|\u53c2\u8003\u4ef7=%s'
		      % (dt_full, st, prev_s, open_s, cur_s, chg_s, op, sh, dh_s, ref_s))
	if not lines:
		st = '-'
		op = getattr(g, '_mr_op', '-')
		sh = int(getattr(g, '_mr_sh', 0) or 0)
		ot, chg, px = (None, None, None)
		out_px = getattr(g, '_mr_px', None) or px
		prev_s = '--'
		open_s = '--'
		cur_s = '--'
		chg_s = ('%.2f%%' % chg) if chg is not None else '--'
		ref_s = ('%.3f' % float(out_px)) if out_px is not None else '--'
		print('[MIN] \u65f6\u95f4=%s|\u4ee3\u7801=%s|\u6628\u6536=%s|\u4eca\u5f00=%s|\u73b0\u4ef7=%s|\u6da8\u8dcc\u5e45=%s|\u64cd\u4f5c=%s|\u80a1\u6570=%d|\u6301\u4ed3\u5929\u6570=--|\u53c2\u8003\u4ef7=%s'
		      % (dt_full, st, prev_s, open_s, cur_s, chg_s, op, sh, ref_s))


def _emit_pos_line(dt_full, src_tag, st, vol, avg, px, pnl, in_watchlist=None, d_str=None):
	avg_s = ('%.3f' % float(avg)) if avg is not None and float(avg) > 0 else '--'
	px_s = ('%.3f' % float(px)) if px is not None and float(px) > 0 else '--'
	pnl_s = ('%.2f%%' % pnl) if pnl is not None else '--'
	dh_s = '--'
	if d_str:
		dh = _stock_hold_days(st, d_str)
		if dh is not None:
			dh_s = str(int(dh))
	wl_s = '--'
	if in_watchlist is True:
		wl_s = '\u662f'
	elif in_watchlist is False:
		wl_s = '\u5426'
	print('[POS] \u65f6\u95f4=%s|\u6765\u6e90=%s|\u4ee3\u7801=%s|\u6301\u4ed3\u6570=%d|\u6301\u4ed3\u5929\u6570=%s|\u6210\u672c=%s|\u73b0\u4ef7=%s|\u6301\u4ed3\u76c8\u4e8f=%s|\u81ea\u9009=%s'
	      % (dt_full, src_tag, st, int(vol), dh_s, avg_s, px_s, pnl_s, wl_s))


def _emit_position_holdings(C, dt_full, d_str, tick_map):
	"""\u6bcf\u5206\u949f\u6c47\u603b\uff1a\u8d26\u6237+\u6a21\u62df\u6301\u4ed3\u4e0e\u76c8\u4e8f\u6bd4\u4f8b\u3002"""
	if not getattr(g, 'position_summary_log', True):
		return
	seen = set()
	if (g.accid or '').strip():
		_gtd = _get_trade_detail_data_fn()
		if _gtd:
			try:
				pos = _gtd(g.accid, _account_type(), 'position')
			except Exception:
				pos = []
		else:
			pos = []
		for p in pos or []:
			try:
				st = _normalize_position_code(p)
				st = _canonical_stock_code(st) or st
				if not st or int(getattr(p, 'm_nVolume', 0) or 0) <= 0:
					continue
				vol = int(getattr(p, 'm_nVolume', 0) or 0)
				avg = float(getattr(p, 'm_dOpenPrice', 0) or 0)
				if avg <= 0:
					avg = None
				lp = float(getattr(p, 'm_dLastPrice', 0) or 0)
				fb = lp if lp > 0 else None
				px = _get_current_price(C, st, dt_full, fb, tick_map) or (lp if lp > 0 else None)
				pnl = _pnl_pct_vs_cost(avg, px)
				in_wl = st in getattr(g, '_mon_pool_codes', frozenset())
				_emit_pos_line(dt_full, '\u8d26\u6237', st, vol, avg, px, pnl, in_wl, d_str=d_str)
				seen.add(st)
			except Exception:
				continue
	for k in list(g.holding.keys()):
		if not g.holding.get(k):
			continue
		st = _canonical_stock_code(k) or k
		if st in seen:
			continue
		vol = int(g.buy_shares.get(st, 0) or 0)
		if vol <= 0:
			continue
		avg = _avg_cost(st)
		fb = None
		try:
			m1 = C.get_market_data_ex(['close'], [st], end_time=dt_full, period='1m', count=1, subscribe=False)
			if st in m1:
				cm = _ohlc_to_list(m1[st].get('close'))
				if cm:
					fb = float(cm[-1])
		except Exception:
			pass
		px = _get_current_price(C, st, dt_full, fb, tick_map)
		pnl = _pnl_pct_vs_cost(avg, px)
		in_wl = st in getattr(g, '_mon_pool_codes', frozenset())
		_emit_pos_line(dt_full, '\u6a21\u62df', st, vol, avg, px, pnl, in_wl, d_str=d_str)


def _emit_monitor_unified_summary(dt_full, pos_codes_set, pool_codes_set):
	"""\u81ea\u9009 vs \u8d26\u6237\u5168\u90e8\u6301\u4ed3\uff0c\u4fbf\u4e8e\u5b9e\u76d8\u7edf\u4e00\u76d1\u63a7\u56de\u6d4b\u65e5\u5fd7\u3002"""
	if not getattr(g, 'sell_monitor_summary_log', True):
		return
	try:
		ps = frozenset(pos_codes_set or [])
		pl = frozenset(pool_codes_set or [])
	except Exception:
		return
	n_ps, n_pl = len(ps), len(pl)
	both = len(ps & pl)
	out_only = len(ps - pl)
	mon = getattr(g, 'monitor_account_risk_sells', True)
	acct_mode = '\u81ea\u9009\u5185\u8d26\u6237+g' if mon else '\u4ec5\u81ea\u9009\u5185g\u8bb0\u8d26'
	print('[MON] \u65f6\u95f4=%s|\u81ea\u9009\u6c60\u6570=%d|\u8d26\u6237\u6301\u4ed3\u6570=%d|\u81ea\u9009\u2229\u6301\u4ed3=%d|\u81ea\u9009\u5916(\u4e0d\u81ea\u52a8\u5356)=%d|\u5356\u5355\u8303\u56f4=%s|\u5907=M10/\u98ce\u63a7\u4ec5\u81ea\u9009'
	      % (dt_full, n_pl, n_ps, both, out_only, acct_mode))


def _per_stock_watch_hint(C, stock, dt_full, d_str, hhmmss, tick_map, already, index_allow_new, opc=None):
	if not _in_session_trade(hhmmss):
		return '\u975e\u8fde\u7eed\u7ade\u4ef7'
	if not index_allow_new:
		return '\u6307\u6570MA5\u4e0b(\u672c\u7968\u4ec5\u76d1\u63a7)'
	if stock in already:
		return '\u5df2\u6301\u4ed3'
	if opc is not None:
		o, pc = opc
	else:
		o, pc = _opc_get(C, stock, dt_full, d_str)
	if pc is None or pc <= 0:
		return '\u65e5\u7ebf\u7f3a\u5931\u8d25'
	if o is None or o <= 0:
		return '\u4eca\u5f00\u62c9\u53d6\u5931\u8d25'
	br = _gap_bracket(o / pc - 1.0)
	px = _get_current_price(C, stock, dt_full, None, tick_map)
	if br == 'A' and (hhmmss is None or not (93000 <= hhmmss <= 93559)):
		return '\u7b49\u5f85A\u6863\u9996\u4e70(9:30-9:35) \u6863=%s' % br
	if br == 'B' and px and px > o * 0.97:
		return '\u7b49\u5f85B\u6863\u56de\u8e22-3%% \u6863=%s' % br
	if br == 'C' and px and px > o * 0.96:
		return '\u7b49\u5f85C\u6863\u56de\u8e22-4%% \u6863=%s' % br
	if br == 'D':
		return '\u76d1\u63a7D\u6863(\u4ec5\u9996\u4e7050%%) \u6863=%s' % br
	return '\u76d1\u63a7\u5206\u6863=%s' % br


def _parse_tick_price(t):
	if t is None:
		return None
	p = (getattr(t, 'lastPrice', None) or getattr(t, 'last_price', None) or
	     getattr(t, 'm_nLastPrice', None) or getattr(t, 'nLast', None))
	if p is None and isinstance(t, dict):
		p = t.get('lastPrice') or t.get('last_price') or t.get('m_nLastPrice') or t.get('nLast')
	if p is not None:
		try:
			return float(p)
		except Exception:
			pass
	return None


def _get_current_price(C, stock, bar_date_str, fallback_close, tick_snapshot=None):
	if tick_snapshot is not None and stock in tick_snapshot and tick_snapshot[stock] > 0:
		return float(tick_snapshot[stock])
	try:
		if hasattr(C, 'get_full_tick'):
			ticks = C.get_full_tick([stock])
			if ticks and stock in ticks:
				p = _parse_tick_price(ticks[stock])
				if p is not None and p > 0:
					return float(p)
	except Exception:
		pass
	try:
		m1 = C.get_market_data_ex(['close'], [stock], period='1m', count=1, end_time=bar_date_str, subscribe=False)
		if m1 and stock in m1 and m1[stock].get('close'):
			c = m1[stock]['close']
			p = c[-1] if hasattr(c, '__getitem__') else list(c)[-1]
			if p is not None and float(p) > 0:
				return float(p)
	except Exception:
		pass
	if fallback_close is not None and float(fallback_close) > 0:
		return float(fallback_close)
	return None


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
	ins = (getattr(pos, 'm_strInstrumentID', None) or getattr(pos, 'stock_code', None) or '').strip()
	ex = (getattr(pos, 'm_strExchangeID', None) or getattr(pos, 'exchange_id', None) or '').upper().strip()
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
	"""positiondetail -> 规范代码。"""
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
	"""文档口径：direction=48 视作做多；缺失 direction 时按股票持仓兼容为 True。"""
	try:
		d = getattr(pos, 'direction', None) if not isinstance(pos, dict) else pos.get('direction')
		if d is None or str(d).strip() == '':
			return True
		return int(d) == 48
	except Exception:
		return True


def _account_holdings_list():
	"""优先返回 holdings(account) 列表（positiondetail）。"""
	if not (g.accid or '').strip():
		return []
	hd = _holdings_fn()
	if not hd:
		return []
	try:
		return hd(g.accid) or []
	except Exception:
		return []


def _pool_from_sector(C):
	name = (getattr(g, 'watchlist_sector_name', None) or '我的自选').strip()
	if not name or not hasattr(C, 'get_stock_list_in_sector'):
		return []
	try:
		raw = C.get_stock_list_in_sector(name)
		if not raw:
			return []
		out, seen = [], set()
		for x in raw:
			c = _canonical_stock_code(x) or str(x).strip()
			if c and c not in seen:
				seen.add(c)
				out.append(c)
		return sorted(out)
	except Exception:
		return []


def _position_codes_from_account():
	if not g.accid:
		return set()
	hpos = _account_holdings_list()
	if hpos:
		out = set()
		for p in hpos:
			try:
				if not _is_long_holding(p):
					continue
				vol = int((getattr(p, 'volume', None) if not isinstance(p, dict) else p.get('volume')) or 0)
				if vol <= 0:
					continue
				c = _holdings_code(p)
				if c:
					out.add(c)
			except Exception:
				continue
		if out:
			return out
	_gtd = _get_trade_detail_data_fn()
	if not _gtd:
		return set()
	try:
		pos = _gtd(g.accid, _account_type(), 'position')
	except Exception:
		return set()
	if not pos:
		return set()
	out = set()
	for p in pos:
		try:
			c = _normalize_position_code(p)
			if c and int(getattr(p, 'm_nVolume', 0) or 0) > 0:
				out.add(_canonical_stock_code(c) or c)
		except Exception:
			continue
	return out


def _account_position_detail(stock):
	"""\u8fd4\u56de (\u6301\u4ed3\u91cf, \u53c2\u8003\u6210\u672c\u4ef7/\u80a1)\uff0c\u65e0\u5219 (None, None)\u3002"""
	if not (g.accid or '').strip():
		return None, None
	can = _canonical_stock_code(stock) or stock
	hpos = _account_holdings_list()
	if hpos:
		for p in hpos:
			try:
				if not _is_long_holding(p):
					continue
				c = _holdings_code(p)
				if c != can:
					continue
				vol = int((getattr(p, 'volume', None) if not isinstance(p, dict) else p.get('volume')) or 0)
				if vol <= 0:
					continue
				op = (getattr(p, 'openprice', None) if not isinstance(p, dict) else p.get('openprice'))
				avg = float(op or 0)
				if avg <= 0:
					avg = None
				return vol, avg
			except Exception:
				continue
	_gtd = _get_trade_detail_data_fn()
	if not _gtd:
		return None, None
	try:
		pos = _gtd(g.accid, _account_type(), 'position')
	except Exception:
		return None, None
	can = _canonical_stock_code(stock) or stock
	for p in pos or []:
		try:
			c = _normalize_position_code(p)
			c = _canonical_stock_code(c) or c
			if c != can:
				continue
			vol = int(getattr(p, 'm_nVolume', 0) or 0)
			if vol <= 0:
				continue
			avg = float(getattr(p, 'm_dOpenPrice', 0) or getattr(p, 'm_dLastPrice', 0) or 0)
			if avg <= 0:
				avg = None
			return vol, avg
		except Exception:
			continue
	return None, None


def _stock_hold_days(stock, d_str):
	"""按买入日估算持仓天数；未知时临时按 1 天。"""
	if not stock or not d_str:
		return 1
	_emit_hold_days_debug_once(stock, d_str)
	bdate = _effective_buy_date(stock, d_str)
	if not bdate:
		return 1
	try:
		dh = (datetime.datetime.strptime(d_str, '%Y%m%d') - datetime.datetime.strptime(bdate, '%Y%m%d')).days
		return max(0, int(dh))
	except Exception:
		return 1


def _emit_hold_days_debug_once(stock, d_str):
	"""每票每天最多一条：持仓天数来源排查日志。"""
	if not getattr(g, 'signal_trace_log', True):
		return
	try:
		can = _canonical_stock_code(stock) or stock
		key = '%s@%s' % (can, d_str)
		if not hasattr(g, '_hold_days_dbg_marker'):
			g._hold_days_dbg_marker = {}
		if g._hold_days_dbg_marker.get(key):
			return
		g._hold_days_dbg_marker[key] = True
	except Exception:
		return

	hd_open = None
	hd_dir = None
	hd_vol = None
	try:
		for p in (_account_holdings_list() or []):
			c = _holdings_code(p)
			if c != can:
				continue
			hd_dir = (getattr(p, 'direction', None) if not isinstance(p, dict) else p.get('direction'))
			hd_vol = (getattr(p, 'volume', None) if not isinstance(p, dict) else p.get('volume'))
			hd_open = (getattr(p, 'opendate', None) if not isinstance(p, dict) else p.get('opendate'))
			break
	except Exception:
		pass

	gtd_open = None
	gtd_trd = None
	try:
		_gtd = _get_trade_detail_data_fn()
		if _gtd and (g.accid or '').strip():
			pos = _gtd(g.accid, _account_type(), 'position') or []
			for p in pos:
				c = _normalize_position_code(p)
				c = _canonical_stock_code(c) or c
				if c != can:
					continue
				gtd_open = getattr(p, 'opendate', None)
				gtd_trd = getattr(p, 'tradingday', None)
				break
	except Exception:
		pass

	try:
		eff = _effective_buy_date(can, d_str)
		print('[TRACE] HOLD-DAYS code=%s d=%s hd(opendate=%r,direction=%r,volume=%r) gtd(opendate=%r,tradingday=%r) g.buy_date=%r effective=%r'
		      % (can, d_str, hd_open, hd_dir, hd_vol, gtd_open, gtd_trd, g.buy_date.get(can), eff))
	except Exception:
		pass


def _account_open_date(stock):
	"""从账户持仓尝试读取开仓日(YYYYMMDD)；无则 None。"""
	if not (g.accid or '').strip():
		return None
	# 优先尝试 QMT 文档里的 holdings(account) 结构（含 opendate）
	can = _canonical_stock_code(stock) or stock
	hpos = _account_holdings_list()
	for p in hpos:
		try:
			if not _is_long_holding(p):
				continue
			vol = int((getattr(p, 'volume', None) if not isinstance(p, dict) else p.get('volume')) or 0)
			if vol <= 0:
				continue
			c = _holdings_code(p)
			if c != can:
				continue
			raw = (getattr(p, 'opendate', None) if not isinstance(p, dict) else p.get('opendate'))
			d = _tag_to_yyyymmdd(raw)
			if d:
				return d
		except Exception:
			continue
	_gtd = _get_trade_detail_data_fn()
	if not _gtd:
		return None
	try:
		pos = _gtd(g.accid, _account_type(), 'position')
	except Exception:
		return None
	can = _canonical_stock_code(stock) or stock
	for p in pos or []:
		try:
			c = _normalize_position_code(p)
			c = _canonical_stock_code(c) or c
			if c != can:
				continue
			vol = int(getattr(p, 'm_nVolume', 0) or getattr(p, 'volume', 0) or 0)
			if vol <= 0:
				continue
			for nm in ('opendate', 'openDate', 'm_strOpenDate'):
				raw = getattr(p, nm, None)
				d = _tag_to_yyyymmdd(raw)
				if d:
					return d
			if isinstance(p, dict):
				for nm in ('opendate', 'openDate', 'm_strOpenDate'):
					d = _tag_to_yyyymmdd(p.get(nm))
					if d:
						return d
		except Exception:
			continue
	return None


def _effective_buy_date(stock, d_str):
	"""买入日优先级：账户开仓日 > g.buy_date；未知返回 None。"""
	d = _account_open_date(stock)
	if d:
		return d
	return g.buy_date.get(stock)


def _trade_row_code(x):
	"""成交/委托行 -> 规范代码。"""
	try:
		ins = (getattr(x, 'instrumentid', None) or getattr(x, 'm_strInstrumentID', None) or
		       getattr(x, 'stock_code', None) or (x.get('instrumentid') if isinstance(x, dict) else None) or
		       (x.get('m_strInstrumentID') if isinstance(x, dict) else None) or
		       (x.get('stock_code') if isinstance(x, dict) else None))
		ex = (getattr(x, 'exchangeid', None) or getattr(x, 'm_strExchangeID', None) or
		      (x.get('exchangeid') if isinstance(x, dict) else None) or
		      (x.get('m_strExchangeID') if isinstance(x, dict) else None))
		ins = (str(ins).strip() if ins is not None else '')
		ex = (str(ex).strip().upper() if ex is not None else '')
		if ins and ex:
			return _canonical_stock_code('%s.%s' % (ins, ex))
		if ins:
			return _canonical_stock_code(ins)
	except Exception:
		pass
	return ''


def _trade_row_is_buy(x):
	"""尽量识别是否买入成交；无法识别返回 None。"""
	try:
		dv = (getattr(x, 'direction', None) if not isinstance(x, dict) else x.get('direction'))
		if dv is None:
			dv = (getattr(x, 'm_nDirection', None) if not isinstance(x, dict) else x.get('m_nDirection'))
		if dv is not None and str(dv).strip() != '':
			try:
				iv = int(dv)
				if iv in (48, 1):
					return True
				if iv in (49, -1, 2):
					return False
			except Exception:
				s = str(dv).strip().upper()
				if s in ('BUY', 'B', 'LONG', '多', '买'):
					return True
				if s in ('SELL', 'S', 'SHORT', '空', '卖'):
					return False
		for nm in ('bsflag', 'side', 'entrust_bs', 'm_nBSFlag'):
			v = (getattr(x, nm, None) if not isinstance(x, dict) else x.get(nm))
			if v is None:
				continue
			s = str(v).strip().upper()
			if s in ('B', 'BUY', '0', '48'):
				return True
			if s in ('S', 'SELL', '1', '49'):
				return False
	except Exception:
		pass
	return None


def _trade_row_date(x):
	"""成交行日期字段 -> YYYYMMDD。"""
	for nm in ('opendate', 'trade_date', 'tradingday', 'date', 'm_strDate', 'm_strTradingDay', 'm_strOpenDate'):
		try:
			raw = (getattr(x, nm, None) if not isinstance(x, dict) else x.get(nm))
			d = _tag_to_yyyymmdd(raw)
			if d:
				return d
		except Exception:
			continue
	return None


def _hydrate_buy_date_from_trades():
	"""从成交明细回填 g.buy_date（每票取最早买入日）。"""
	if not (g.accid or '').strip():
		return
	# 先打印接口可用性与 holdings 样本（每天初始化/换日各一次）
	if getattr(g, 'signal_trace_log', True):
		try:
			hd = _holdings_fn()
			gtd = _get_trade_detail_data_fn()
			hn = 0
			hkeys = []
			if hd:
				try:
					hrows = hd(g.accid) or []
					hn = len(hrows)
					if hrows:
						x0 = hrows[0]
						if isinstance(x0, dict):
							hkeys = list(x0.keys())[:12]
						else:
							hkeys = [k for k in dir(x0) if not k.startswith('_')][:12]
				except Exception as e:
					hkeys = ['ERR:%s' % str(e)[:40]]
			print('[TRACE] TRADE-PROBE api holdings=%s gtd=%s holdings_n=%s holdings_keys=%s'
			      % ('Y' if hd else 'N', 'Y' if gtd else 'N', hn, hkeys))
		except Exception:
			pass
	_gtd = _get_trade_detail_data_fn()
	if not _gtd:
		if getattr(g, 'signal_trace_log', True):
			print('[TRACE] TRADE-PROBE gtd unavailable, skip trade backfill.')
		return
	best = {}
	probe = []
	for kind in ('deal', 'trade', 'trades', 'deal_list', 'entrust', 'order'):
		try:
			rows = _gtd(g.accid, _account_type(), kind) or []
		except Exception as e:
			probe.append((kind, 'ERR:%s' % str(e)[:40], 0))
			rows = []
			continue
		probe.append((kind, 'OK', len(rows)))
		# 打印样本字段，帮助定位该环境真实字段名
		if rows and getattr(g, 'signal_trace_log', True):
			try:
				x = rows[0]
				if isinstance(x, dict):
					keys = list(x.keys())[:12]
				else:
					keys = [k for k in dir(x) if not k.startswith('_')][:12]
				print('[TRACE] TRADE-PROBE kind=%s n=%d sample_keys=%s' % (kind, len(rows), keys))
			except Exception:
				pass
		for x in rows:
			try:
				c = _trade_row_code(x)
				if not c:
					continue
				is_buy = _trade_row_is_buy(x)
				if is_buy is False:
					continue
				# side 无法识别时不强行写入，避免把卖出成交误标成买入日
				if is_buy is None:
					continue
				d = _trade_row_date(x)
				if not d:
					continue
				old = best.get(c)
				if old is None or int(d) < int(old):
					best[c] = d
			except Exception:
				continue
	if getattr(g, 'signal_trace_log', True):
		try:
			print('[TRACE] TRADE-PROBE summary=%s filled=%d'
			      % ([(k, s, n) for (k, s, n) in probe], len(best)))
		except Exception:
			pass
	for c, d in best.items():
		if c not in g.buy_date:
			g.buy_date[c] = d
		else:
			try:
				if int(d) < int(g.buy_date[c]):
					g.buy_date[c] = d
			except Exception:
				g.buy_date[c] = d


def _account_last_price(stock):
	"""\u8d26\u6237\u6301\u4ed3\u91cc\u7684\u6700\u65b0\u4ef7 m_dLastPrice\uff08\u8865 tick/1m \u5931\u8d25\u65f6\u907f\u514d\u7528\u65e5\u7ebf\u6536\u76d8\u4f5c\u73b0\u4ef7\uff09\u3002"""
	if not (g.accid or '').strip():
		return None
	_gtd = _get_trade_detail_data_fn()
	if not _gtd:
		return None
	try:
		pos = _gtd(g.accid, _account_type(), 'position')
	except Exception:
		return None
	can = _canonical_stock_code(stock) or stock
	for p in pos or []:
		try:
			c = _normalize_position_code(p)
			c = _canonical_stock_code(c) or c
			if c != can:
				continue
			lp = float(getattr(p, 'm_dLastPrice', 0) or getattr(p, 'last_price', 0) or 0)
			if lp > 0:
				return lp
		except Exception:
			continue
	return None


def _m1_last_high(C, stock, dt_full):
	"""\u6700\u65b0\u4e00\u6839 1m \u7684 high\uff08\u5f53\u6839\u5f62\u6210\u4e2d\u4ef7\u683c\u66f4\u65b0\uff09\u3002"""
	try:
		data_m = C.get_market_data_ex(
			['high'], [stock], end_time=dt_full, period='1m', count=1, subscribe=False
		)
		if not data_m or stock not in data_m:
			return None
		hh = _ohlc_to_list(data_m[stock].get('high'))
		if not hh:
			return None
		v = float(hh[-1])
		return v if v > 0 else None
	except Exception:
		return None


def _live_px_max_for_atr(C, stock, dt_full, tick_map, base_px):
	"""\u5408\u5e76\u591a\u8def\u5f84\u73b0\u4ef7\u53d6 max\uff0c\u907f\u514d\u65e5K\u672b\u6536\u505a fallback \u5bfc\u81f4 ATR \u7528\u5230\u5047\u4f4e\u4ef7\u3002"""
	vals = []
	try:
		if base_px is not None and float(base_px) > 0:
			vals.append(float(base_px))
	except Exception:
		pass
	if tick_map and stock in tick_map:
		try:
			v = float(tick_map[stock])
			if v > 0:
				vals.append(v)
		except Exception:
			pass
	try:
		if hasattr(C, 'get_full_tick'):
			ticks = C.get_full_tick([stock])
			if ticks and stock in ticks:
				p = _parse_tick_price(ticks[stock])
				if p is not None and float(p) > 0:
					vals.append(float(p))
	except Exception:
		pass
	try:
		m1 = C.get_market_data_ex(
			['close'], [stock], end_time=dt_full, period='1m', count=1, subscribe=False
		)
		if m1 and stock in m1 and m1[stock].get('close'):
			c = m1[stock]['close']
			p = c[-1] if hasattr(c, '__getitem__') else list(c)[-1]
			if p is not None and float(p) > 0:
				vals.append(float(p))
	except Exception:
		pass
	lp = _account_last_price(stock)
	if lp is not None and lp > 0:
		vals.append(float(lp))
	mh = _m1_last_high(C, stock, dt_full)
	if mh is not None and mh > 0:
		vals.append(float(mh))
	if not vals:
		return None
	return max(vals)


def _sse_ma_state(C, dt_full):
	"""\u8fd4\u56de (\u4e0a\u8bc1\u6700\u65b0\u65e5\u6536, MA5, MA10, \u5141\u8bb8\u5f00\u65b0\u4ed3, \u662f\u5426\u6e05\u5168\u4ed3)\u3002
	\u5141\u8bb8\u5f00\u65b0\u4ed3 = \u6700\u65b0\u65e5\u6536 >= MA5\uff08\u5927\u76d8\u5728 MA5 \u4e0a\u65b9\u6216\u7b49\u4ef7\uff09\uff1b\u53cd\u4e4b\u89c6\u4e3a\u7834\u4f4d MA5 \u5173\u95e8\u63a7\u3002"""
	n = max(int(g.ma_index_period_long), 15)
	try:
		data_d = C.get_market_data_ex(
			['close'], [INDEX_SSE],
			end_time=dt_full, period='1d', count=n, subscribe=False
		)
		if INDEX_SSE not in data_d:
			return None, None, None, True, False
		closes = _ohlc_to_list(data_d[INDEX_SSE].get('close'))
		if not closes or len(closes) < int(g.ma_index_period_long):
			return None, None, None, True, False
		cl0 = list(closes)
		_, _, closes = _align_daily_ohlc_chronological(data_d, INDEX_SSE, cl0, list(cl0), list(cl0), None)
		last = float(closes[-1])
		p5, p10 = int(g.ma_index_period_short), int(g.ma_index_period_long)
		ma5 = sum(float(x) for x in closes[-p5:]) / float(p5)
		ma10 = sum(float(x) for x in closes[-p10:]) / float(p10)
		allow_new = bool(last >= ma5)
		return last, ma5, ma10, allow_new, (last < ma10)
	except Exception:
		return None, None, None, True, False


def _gap_bracket(gap):
	if gap is None:
		return None
	if gap <= -0.05:
		return 'D'
	if gap < 0.03:
		return 'A'
	if gap < 0.07:
		return 'B'
	return 'C'


def _shares_for_cash(cash_yuan, price, mos):
	if price <= 0 or cash_yuan <= 0:
		return 0
	sh = int(float(cash_yuan) / float(price))
	return (sh // mos) * mos


def _avg_cost(stock):
	sh = int(g.buy_shares.get(stock, 0) or 0)
	tc = float(g.total_cost.get(stock, 0) or 0)
	if sh <= 0:
		return None
	return tc / float(sh)


def _pnl_pct_vs_cost(avg_px, cur_px):
	if avg_px is None or float(avg_px) <= 0 or cur_px is None or float(cur_px) <= 0:
		return None
	return (float(cur_px) / float(avg_px) - 1.0) * 100.0


def _position_volume_and_avg(stock):
	"""\u5356\u524d\u6301\u4ed3\u91cf\u4e0e\u5747\u4ef7\uff1a\u4f18\u5148\u8d26\u6237\u6301\u4ed3\uff0c\u5426\u5219 g.* \u6a21\u62df\u3002"""
	av, ac = _account_position_detail(stock)
	if av and av > 0 and ac and float(ac) > 0:
		return av, float(ac)
	sv = int(g.buy_shares.get(stock, 0) or 0)
	sc = _avg_cost(stock)
	if sv > 0 and sc and float(sc) > 0:
		return sv, float(sc)
	if av and av > 0:
		acv = float(ac) if (ac is not None and float(ac) > 0) else None
		return av, acv
	return 0, None


def _atr_trailing_stop_numbers(days_held_effective, highs, lows, closes, ref_high=None):
	"""\u8ba1\u7b97 ATR\u6b62\u76c8\u7ebf\u3002\u8fd4\u56de (stop, atr_v, hh_effective, err, hh_daily)\uff1a
	hh_daily=\u65e5\u7ebf\u7a97\u53e3\u5185\u6700\u9ad8\u4ef7\uff1b\u82e5 ref_high\uff08\u73b0\u4ef7/\u5206\u65f6\u6700\u9ad8\uff09\u66f4\u9ad8\u5219\u62ac\u5347 HH \u518d\u7b97\u6b62\u76c8\u7ebf\uff0c\u907f\u514d\u65e5K\u672a\u5237\u65b0\u5bfc\u81f4\u6b62\u76c8\u7ebf\u8fc7\u4f4e\u3002"""
	if talib is None:
		return None, None, None, 'talib', None
	if not highs or not lows or not closes or len(closes) < 2:
		return None, None, None, 'bar', None
	if days_held_effective < 1 and not bool(g.allow_atr_same_day):
		return None, None, None, 'hold', None
	n_since = min(max(days_held_effective, 1), len(highs))
	try:
		hh_daily = max(float(x) for x in highs[-n_since:])
	except Exception:
		return None, None, None, 'hh', None
	try:
		atr_arr = talib.ATR(
			np.array(highs, dtype=np.float64),
			np.array(lows, dtype=np.float64),
			np.array(closes, dtype=np.float64),
			int(g.atr_period),
		)
		atr_v = float(atr_arr[-1]) if len(atr_arr) and not np.isnan(atr_arr[-1]) else None
	except Exception:
		return None, None, None, 'atr_x', float(hh_daily)
	mult = float(g.atr_stop_mult)
	if atr_v is None or atr_v <= 0:
		return None, None, float(hh_daily), 'atr0', float(hh_daily)
	hh_eff = float(hh_daily)
	rh = None
	if ref_high is not None:
		try:
			rh = float(ref_high)
		except (TypeError, ValueError):
			rh = None
	if rh is not None and rh > 0:
		hh_eff = max(hh_eff, rh)
	stop = hh_eff - float(atr_v) * mult
	return stop, atr_v, hh_eff, None, float(hh_daily)


def _emit_atr_mon_line(dt_full, st, px, avg_c, dh_eff, highs, lows, closes, hold_shares=0, scope_tag='', ref_high=None):
	"""\u6bcf\u5206\u949f\u6700\u591a\u4e00\u6761 [ATR-MON]\uff1a\u6301\u4ed3\u3001\u6d6e\u76c8\u4e8f\u3001ATR\u3001\u6b62\u76c8\u7ebf\u3001\u7f13\u51b2\u4e0e\u76c8\u5229ATR\u500d\u6570\u7b49\u3002"""
	if not getattr(g, 'atr_intraday_log', True):
		return
	cur_key = dt_full[:12]
	if not hasattr(g, '_atr_last_minute_log'):
		g._atr_last_minute_log = {}
	if g._atr_last_minute_log.get(st) == cur_key:
		return
	g._atr_last_minute_log[st] = cur_key
	sc = (scope_tag or '--').replace('|', '/')
	sh = int(hold_shares) if hold_shares else 0
	if avg_c is None or float(avg_c) <= 0:
		print('[ATR-MON] \u8303\u56f4=%s|\u65f6\u95f4=%s|\u4ee3\u7801=%s|\u80a1=%d|\u6d6e\u76c8\u4e8f%%=--|\u73b0=%.3f|\u6210\u672c=--|\u6b62\u76c8\u7ebf=--|\u8ddd\u7ebf=--|\u8ddd\u7ebf%%=--|ATR=--|HH=--|\u8d85\u7ebfATR=--|\u76c8ATR\u500d=--|\u672c\u6839\u89e6\u53d1=--|\u5907\u6ce8=\u6210\u672c\u7f3a'
		      % (sc, dt_full, st, sh, px))
		return
	ac = float(avg_c)
	pnl_pct = (px / ac - 1.0) * 100.0
	if px <= ac:
		print('[ATR-MON] \u8303\u56f4=%s|\u65f6\u95f4=%s|\u4ee3\u7801=%s|\u80a1=%d|\u6d6e\u76c8\u4e8f%%=%+.2f%%|\u73b0=%.3f|\u6210\u672c=%.3f|\u6b62\u76c8\u7ebf=--|\u8ddd\u7ebf=--|\u8ddd\u7ebf%%=--|ATR=--|HH=--|\u8d85\u7ebfATR=--|\u76c8ATR\u500d=--|\u672c\u6839\u89e6\u53d1=--|\u5907\u6ce8=\u975e\u6d6e\u76c8\u4e0d\u8bc4ATR\u6b62\u76c8'
		      % (sc, dt_full, st, sh, pnl_pct, px, ac))
		return
	stop, atr_v, highest_high, err, hh_bar = _atr_trailing_stop_numbers(dh_eff, highs, lows, closes, ref_high=ref_high)
	if err is not None:
		em = {'talib': 'talib', 'bar': 'K\u7ebf', 'hold': '\u6301\u4ed31\u65e5', 'hh': 'HH', 'atr_x': 'ATR\u7b97', 'atr0': 'ATR\u65e0\u6548'}.get(err, err)
		print('[ATR-MON] \u8303\u56f4=%s|\u65f6\u95f4=%s|\u4ee3\u7801=%s|\u80a1=%d|\u6d6e\u76c8\u4e8f%%=%+.2f%%|\u73b0=%.3f|\u6210\u672c=%.3f|\u6b62\u76c8\u7ebf=--|\u8ddd\u7ebf=--|\u8ddd\u7ebf%%=--|ATR=--|HH=--|\u8d85\u7ebfATR=--|\u76c8ATR\u500d=--|\u672c\u6839\u89e6\u53d1=--|\u5907\u6ce8=%s'
		      % (sc, dt_full, st, sh, pnl_pct, px, ac, em))
		return
	gap = px - stop
	gap_pct = (gap / stop * 100.0) if stop is not None and stop > 0 else 0.0
	near = bool(px <= stop)
	buf_atr = None
	if atr_v is not None and atr_v > 0 and stop is not None:
		buf_atr = (px - float(stop)) / float(atr_v)
	profit_atr = None
	if atr_v is not None and atr_v > 0:
		profit_atr = (px - ac) / float(atr_v)
	note = '\u4ef7>\u6210\u672c\u53ef\u6bd4'
	try:
		hlim = float(g.hard_stop_pct)
		hline = ac * (1.0 + hlim)
		note = '\u786c\u6b62\u9608\u7ebf%.3f(%.1f%%)\u6d6e\u76c8%+.2f%%' % (hline, hlim * 100.0, pnl_pct)
	except Exception:
		pass
	if hh_bar is not None and highest_high is not None and float(highest_high) > float(hh_bar) + 1e-6:
		note = (note + '|\u65e5\u7ebfHH=%.3f\u2192\u6709\u6548HH=%.3f' % (float(hh_bar), float(highest_high)))[:120]
	print('[ATR-MON] \u8303\u56f4=%s|\u65f6\u95f4=%s|\u4ee3\u7801=%s|\u80a1=%d|\u6d6e\u76c8\u4e8f%%=%+.2f%%|\u73b0=%.3f|\u6210\u672c=%.3f|\u6b62\u76c8\u7ebf=%.3f|\u8ddd\u7ebf=%.3f|\u8ddd\u7ebf%%=%.2f%%|ATR=%.4f|HH=%.3f|\u8d85\u7ebfATR=%s|\u76c8ATR\u500d=%s|\u672c\u6839\u89e6\u53d1=%s|\u5907\u6ce8=%s'
	      % (sc, dt_full, st, sh, pnl_pct, px, ac, stop, gap, gap_pct,
	         atr_v if atr_v is not None else 0.0,
	         highest_high if highest_high is not None else 0.0,
	         ('%.2f' % buf_atr) if buf_atr is not None else '--',
	         ('%.2f' % profit_atr) if profit_atr is not None else '--',
	         '\u662f' if near else '\u5426', note))


def _check_atr_take_profit_only(days_held_effective, highs, lows, closes, current_close, avg_cost, ref_high=None):
	if avg_cost is None or current_close <= avg_cost:
		return False, 'ATR\u6b62\u76c8\u4ec5\u6d6e\u76c8'
	stop, atr_v, hh, err, _hh_bar = _atr_trailing_stop_numbers(
		days_held_effective, highs, lows, closes, ref_high=ref_high)
	if err == 'talib':
		return False, 'talib \u672a\u5b89\u88c5'
	if err == 'bar':
		return False, 'K\u7ebf\u4e0d\u8db3'
	if err == 'hold':
		return False, '\u6301\u4ed3\u4e0d\u8db31\u65e5'
	if err == 'hh':
		return False, '\u6700\u9ad8\u4ef7\u5931\u8d25'
	if err in ('atr_x', 'atr0'):
		return False, 'ATR\u65e0\u6548'
	if stop is None:
		return False, 'ATR\u65e0\u6548'
	if current_close <= stop:
		return True, 'ATR\u6b62\u76c8 \u7ebf=%.3f' % stop
	return False, 'ATR\u672a\u89e6\u53d1'


def _emit_atr_non_watchlist_account_positions(C, dt_full, d_str, tick_map, wl):
	"""\u8d26\u6237\u4e2d\u5b58\u5728\u4f46\u4e0d\u5728\u81ea\u9009\u6c60\u7684\u6301\u4ed3\uff1a\u4ec5\u8f93\u51fa [ATR-MON]\uff0c\u4e0d\u8d70\u672c\u7b56\u7565\u5356\u51fa\uff08\u4e0e\u98ce\u63a7\u5faa\u73af\u63a5\u89e6\uff0c\u6bcf\u5206\u949f\u4e00\u6761\uff09\u3002"""
	if not getattr(g, 'atr_intraday_log', True):
		return
	if not bool(getattr(g, 'atr_log_account_non_watchlist', True)):
		return
	if not (getattr(g, 'accid', '') or '').strip():
		return
	_gtd = _get_trade_detail_data_fn()
	if not _gtd:
		return
	try:
		pos = _gtd(g.accid, _account_type(), 'position')
	except Exception:
		pos = []
	cur_key = dt_full[:12]
	if not hasattr(g, '_atr_last_minute_log'):
		g._atr_last_minute_log = {}
	wl_set = wl if isinstance(wl, (set, frozenset)) else frozenset(wl or [])
	for p in pos or []:
		try:
			st = _normalize_position_code(p)
			st = _canonical_stock_code(st) or st
			vol = int(getattr(p, 'm_nVolume', 0) or 0)
			if not st or vol <= 0:
				continue
			if st in wl_set:
				continue
			if g._atr_last_minute_log.get(st) == cur_key:
				continue
			avg_c = float(getattr(p, 'm_dOpenPrice', 0) or 0)
			if avg_c <= 0:
				continue
			data_d = C.get_market_data_ex(
				['close', 'high', 'low', 'open'], [st],
				end_time=dt_full, period='1d', count=int(g.bar_count), subscribe=False
			)
			if st not in data_d:
				continue
			highs = _ohlc_to_list(data_d[st].get('high'))
			lows = _ohlc_to_list(data_d[st].get('low'))
			closes = _ohlc_to_list(data_d[st].get('close'))
			if len(closes) < 2:
				continue
			fb = float(closes[-1])
			px = _get_current_price(C, st, dt_full, fb, tick_map)
			if px is None or px <= 0:
				continue
			px_mx = _live_px_max_for_atr(C, st, dt_full, tick_map, px)
			if px_mx is not None and px_mx > 0:
				px = float(px_mx)
			highs, lows, closes = _align_daily_ohlc_chronological(data_d, st, highs, lows, closes, ref_px=px)
			bdate = _effective_buy_date(st, d_str)
			try:
				dh = max(0, (datetime.datetime.strptime(d_str, '%Y%m%d') - datetime.datetime.strptime(bdate, '%Y%m%d')).days) if bdate else 1
			except Exception:
				dh = 1
			if not bdate:
				dh_eff = 1
			elif bdate == d_str:
				dh_eff = 1 if bool(g.allow_atr_same_day) else 0
			else:
				dh_eff = max(1, dh)
			ref_h = float(px)
			if bool(getattr(g, 'atr_ref_high_use_intraday', True)):
				m1h = _intraday_high_since_open(C, st, dt_full, d_str)
				m1x = _m1_last_high(C, st, dt_full)
				for u in (m1h, m1x):
					if u is not None and float(u) > 0:
						ref_h = max(ref_h, float(u))
			_emit_atr_mon_line(dt_full, st, px, avg_c, dh_eff, highs, lows, closes,
				   hold_shares=vol, scope_tag='\u975e\u81ea\u9009', ref_high=ref_h)
		except Exception:
			continue


def _clear_sim_stock(stock):
	for d in (
		g.holding, g.buy_price, g.buy_shares, g.buy_date, g.total_cost,
		g.anchor_buy, g.gap_bracket, g.open_px, g.prev_close_ref, g.leg_done, g.touch_neg8,
	):
		if isinstance(d, dict):
			d.pop(stock, None)
	if hasattr(g, '_day_low_marker'):
		g._day_low_marker.pop(stock, None)
	if hasattr(g, '_day_low_val'):
		g._day_low_val.pop(stock, None)


def init(C):
	g.accid = getattr(C, 'accountid', '') or getattr(C, 'account_id', '') or '30262698'
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'

	g.watchlist_sector_name = getattr(C, 'watchlist_sector_name', '\u6211\u7684\u81ea\u9009')
	g.per_stock_amount = float(getattr(C, 'per_stock_amount', 100000))
	g.min_order_shares = int(getattr(C, 'min_order_shares', 100))
	g.max_hold_count = int(getattr(C, 'max_hold_count', 1))
	g.require_sse_above_ma5_for_new = bool(getattr(C, 'require_sse_above_ma5_for_new', True))
	g.ma_index_period_short = int(getattr(C, 'ma_index_period_short', 5))
	g.ma_index_period_long = int(getattr(C, 'ma_index_period_long', 10))
	g.atr_period = int(getattr(C, 'atr_period', 14))
	g.atr_stop_mult = float(getattr(C, 'atr_stop_mult', 2.0))
	g.atr_ref_high_use_intraday = bool(getattr(C, 'atr_ref_high_use_intraday', True))
	g.bar_count = int(getattr(C, 'bar_count', 80))
	g.verbose_log = bool(getattr(C, 'verbose_log', True))
	g.allow_atr_same_day = bool(getattr(C, 'allow_atr_same_day', True))
	g.hard_stop_pct = float(getattr(C, 'hard_stop_pct', -0.08))
	g.intraday_touch_pct = float(getattr(C, 'intraday_touch_pct', -0.08))
	g.intraday_fail_recover_pct = float(getattr(C, 'intraday_fail_recover_pct', -0.06))
	g.tail_clear_start_hhmmss = int(getattr(C, 'tail_clear_start_hhmmss', 145000))
	g.non_atr_sell_start_hhmmss = int(getattr(C, 'non_atr_sell_start_hhmmss', 145400))
	g.tail_intraday_log = bool(getattr(C, 'tail_intraday_log', True))
	g.atr_intraday_log = bool(getattr(C, 'atr_intraday_log', True))
	g.atr_log_account_non_watchlist = bool(getattr(C, 'atr_log_account_non_watchlist', True))
	g.use_tick_first = bool(getattr(C, 'use_tick_first', True))
	g.signal_trace_log = bool(getattr(C, 'signal_trace_log', True))
	g.minute_summary_log = bool(getattr(C, 'minute_summary_log', True))
	g.position_summary_log = bool(getattr(C, 'position_summary_log', True))
	g.sell_monitor_summary_log = bool(getattr(C, 'sell_monitor_summary_log', True))
	g.monitor_account_risk_sells = bool(getattr(C, 'monitor_account_risk_sells', True))
	# \u5b9e\u76d8\u4fdd\u7559 is_last_bar \u95e8\u95f2\uff1b\u56de\u6d4b\u82e5\u672a\u8bc6\u522b\u5230 do_back_test\uff0c\u53ef\u5728 QMT \u91cc\u8bbe C.handlebar_each_bar=True \u5f3a\u5236\u6bcf\u6839 K \u6267\u884c
	g.handlebar_each_bar = bool(getattr(C, 'handlebar_each_bar', False))
	g.live_orders = bool(getattr(C, 'live_orders', True))
	g.strategy_order_name = (getattr(C, 'strategy_order_name', None) or '\u81ea\u9009\u5206\u6863').strip()[:20]
	g.quick_trade = int(getattr(C, 'quick_trade', 2))
	g.buy_code = 23 if str(g.account_type).upper() == 'STOCK' else 33
	g.sell_code = 24 if str(g.account_type).upper() == 'STOCK' else 34

	g.holding = {}
	g.buy_price = {}
	g.buy_shares = {}
	g.buy_date = {}
	g.total_cost = {}
	g.anchor_buy = {}
	g.gap_bracket = {}
	g.open_px = {}
	g.prev_close_ref = {}
	g.leg_done = {}
	g.touch_neg8 = {}
	g._day_low_marker = {}
	g._day_low_val = {}
	g._last_handlebar_barpos = None
	g._warned_no_account = False
	g._ma10_signal_latched = False
	g._trade_day = ''
	g._opc_day = ''
	g._opc_map = {}
	g._tail_last_minute_log = {}
	g._atr_last_minute_log = {}
	g._hold_days_dbg_marker = {}
	_hydrate_buy_date_from_trades()

	print('=' * 60)
	print('%s \u521d\u59cb\u5316 accid=%s \u677f\u5757=%s \u5355\u7968\u9884\u7b97=%.0f MA5\u95e8\u63a7\u5f00\u65b0=%s live_orders=%s quick_trade=%d \u7b56\u7565\u540d=%s'
	      % (STRATEGY_TAG, g.accid, g.watchlist_sector_name, g.per_stock_amount,
	         getattr(g, 'require_sse_above_ma5_for_new', True), g.live_orders, g.quick_trade, g.strategy_order_name))
	print('\u56de\u6d4b\u4e0d\u4e0b\u5355\uff1b\u5b9e\u76d8 passorder \u4e70=%d \u5356=%d' % (g.buy_code, g.sell_code))
	print('signal_trace_log=%s minute_summary_log=%s position_summary_log=%s sell_monitor_summary_log=%s monitor_account_risk_sells=%s'
	      % (g.signal_trace_log, g.minute_summary_log, g.position_summary_log, g.sell_monitor_summary_log, g.monitor_account_risk_sells))
	print('non_atr_sell_start_hhmmss=%d tail_intraday_log=%s atr_intraday_log=%s atr_log_non_wl=%s'
	      % (g.non_atr_sell_start_hhmmss, g.tail_intraday_log, g.atr_intraday_log,
	         getattr(g, 'atr_log_account_non_watchlist', True)))
	if bool(getattr(C, 'do_back_test', False)) or bool(getattr(C, 'isDoBackTest', False)) or g.handlebar_each_bar:
		print('%s \u56de\u6d4b/handlebar_each_bar: \u6bcf\u6839 1m K \u6267\u884c handlebar\uff08\u4e0d\u4ec5 is_last_bar\uff09\u2192\u6709 [MIN]' % STRATEGY_TAG)
	print('=' * 60)


def _sim_hold_keys():
	out = set()
	for k, v in g.holding.items():
		if v and int(g.buy_shares.get(k, 0) or 0) > 0:
			out.add(_canonical_stock_code(k) or k)
	return out


def _primary_holding_stock():
	for k, v in g.holding.items():
		if v and int(g.buy_shares.get(k, 0) or 0) > 0:
			return k
	return None


def _should_passorder(C):
	"""\u5b9e\u76d8\u4e14\u975e\u56de\u6d4b\u65f6\u624d\u53d1\u8d77 passorder\uff08\u56de\u6d4b\u5224\u65ad\u4e0e _is_qmt_backtest_context \u5171\u7528\uff09\u3002"""
	if not bool(getattr(g, 'live_orders', True)):
		return False
	if not (getattr(g, 'accid', '') or '').strip():
		return False
	return not _is_qmt_backtest_context(C)


def _passorder_go(C, op_code, stock, volume, user_note):
	"""op_code: \u4e70 23/\u5356 24\uff08STOCK\uff09\u3002\u6309\u80a1\u6570 1101 + \u6700\u65b0\u4ef7 5\u3002"""
	try:
		vol = int(volume)
	except Exception:
		return False
	mos = int(g.min_order_shares)
	vol = (vol // mos) * mos
	if vol < mos:
		return False
	note = str(user_note or '')[:36].replace('|', '_')
	po = _passorder_fn()
	if po is None:
		print('%s passorder \u672a\u627e\u5230\uff08\u975e QMT \u73af\u5883\uff09' % STRATEGY_TAG)
		return False
	try:
		po(
			int(op_code), 1101, g.accid, str(stock),
			5, 0, vol,
			str(g.strategy_order_name),
			int(g.quick_trade),
			note,
			C,
		)
	except Exception as e:
		print('%s passorder ERR %s vol=%s %r' % (STRATEGY_TAG, stock, vol, e))
		return False
	return True


def _signal_buy_leg(C, stock, cash_yuan, price_now, dt_full, d_str, mos, tag, tick_map):
	sh = _shares_for_cash(cash_yuan, price_now, mos)
	if sh < mos:
		_mr_set('\u4e70\u4fe1\u53f7\u80a1\u6570\u4e0d\u8db3\u6700\u5c0f\u624b %s' % tag, 0, price_now)
		return False
	placed = False
	if _should_passorder(C):
		placed = _passorder_go(C, g.buy_code, stock, sh, tag)
		if not placed:
			return False
	src = 'tick/1m'
	if tick_map and stock in tick_map:
		src = 'tick_map'
	_mr_set('\u4fe1\u53f7\u4e70 %s' % tag, sh, price_now)
	g._mr_trade_stock = stock
	mark = '[ORDER]' if placed else '[SIGNAL]'
	print('%s %s[\u4e70] %s %d\u80a1 @%.3f \u7ea6%.0f\u5143 \u5206\u6863\u89c4\u5219=%s \u6765\u6e90=%s'
	      % (dt_full, mark, stock, sh, price_now, sh * price_now, tag, src))
	prev_sh = int(g.buy_shares.get(stock, 0) or 0)
	prev_tc = float(g.total_cost.get(stock, 0) or 0)
	g.buy_shares[stock] = prev_sh + sh
	g.total_cost[stock] = prev_tc + sh * float(price_now)
	g.holding[stock] = True
	g.buy_date[stock] = d_str
	g.buy_price[stock] = g.total_cost[stock] / float(g.buy_shares[stock])
	return True


def _print_sell_signal(C, dt_full, stock, sh, px, reason, tick_map=None):
	mos = int(g.min_order_shares)
	try:
		sh = int(sh)
	except Exception:
		return False
	sh = (sh // mos) * mos
	if sh < mos:
		return False
	tot_vol, avg_c = _position_volume_and_avg(stock)
	cur_px = float(px) if px is not None and float(px) > 0 else None
	try:
		cur = _get_current_price(C, stock, dt_full, cur_px, tick_map)
		if cur is not None and float(cur) > 0:
			cur_px = float(cur)
	except Exception:
		pass
	if cur_px is None or cur_px <= 0:
		cur_px = float(px) if px is not None and float(px) > 0 else 0.0
	pnl = _pnl_pct_vs_cost(avg_c, cur_px)
	avg_s = ('%.3f' % float(avg_c)) if avg_c is not None and float(avg_c) > 0 else '--'
	tot_s = int(tot_vol) if tot_vol and int(tot_vol) > 0 else 0
	pnl_s = ('%.2f%%' % pnl) if pnl is not None else '--'
	can_s = _canonical_stock_code(stock) or stock
	in_wl = can_s in getattr(g, '_mon_pool_codes', frozenset())
	wl_tag = '\u662f' if in_wl else '\u5426'
	ledger = '\u7b56\u7565\u8bb0\u8d26' if g.holding.get(stock) else '\u4ec5\u8d26\u6237(\u4e3b\u89c2/\u5176\u4ed6)'
	print('[SELL] \u65f6\u95f4=%s|\u4ee3\u7801=%s|\u5356\u51fa\u6570=%d|\u5356\u524d\u6301\u4ed3=%d|\u6210\u672c=%s|\u73b0\u4ef7=%.3f|\u6301\u4ed3\u76c8\u4e8f=%s|\u81ea\u9009=%s|\u8bb0\u8d26=%s|\u539f\u56e0=%s'
	      % (dt_full, stock, sh, tot_s, avg_s, float(cur_px), pnl_s, wl_tag, ledger, reason))
	placed = False
	if _should_passorder(C):
		placed = _passorder_go(C, g.sell_code, stock, sh, reason)
		if not placed:
			print('%s \u5355\u8fb9\u5931\u8d25 %s \u539f\u56e0=%s' % (dt_full, stock, reason))
			return False
	_mr_set('\u4fe1\u53f7\u5356 %s' % reason, sh, px)
	g._mr_trade_stock = stock
	mark = '[ORDER]' if placed else '[SIGNAL]'
	print('%s %s[\u5356] %s %d\u80a1 px=%.3f \u539f\u56e0:%s' % (dt_full, mark, stock, sh, px, reason))
	return True


def _signal_sell_sim(C, stock, reason, dt_full, sh, px, tick_map=None):
	if _print_sell_signal(C, dt_full, stock, sh, px, reason, tick_map):
		if g.holding.get(stock):
			_clear_sim_stock(stock)


def _in_session_trade(hms):
	if hms is None:
		return False
	if 93000 <= hms <= 113000:
		return True
	if 130000 <= hms <= 150000:
		return True
	return False


def _non_atr_sell_time_ok(hhmmss):
	"""\u975e ATR \u5356\u51fa\uff1a\u786c\u6b62\u635f\u3001\u5c3e\u76d8\u56de\u6536\u3001\u4e0a\u8bc1MA10\u6e05\u4ed3\uff0c\u4ec5\u5728\u8be5\u65f6\u523b\u540e\u8bc4\u4f30\u3002"""
	if hhmmss is None:
		return False
	return hhmmss >= int(getattr(g, 'non_atr_sell_start_hhmmss', 145400))


def _fmt_non_atr_sell_start():
	t = int(getattr(g, 'non_atr_sell_start_hhmmss', 145400))
	s = '%06d' % t
	return '%s:%s' % (s[:2], s[2:4])


def _is_qmt_backtest_context(C):
	"""\u5224\u65ad\u662f\u5426\u56de\u6d4b\uff08\u56de\u6d4b\u4e2d is_last_bar \u5bf9\u5386\u53f2 K \u591a\u4e3a False\uff0c\u4e0d\u80fd\u7528\u5176\u62e6\u6224\u6574\u6bb5 handlebar\uff09\u3002"""
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
	"""\u5b9e\u76d8\uff1a\u4ec5 is_last_bar \u4e3a True \u65f6\u8dd1\uff08\u672c\u6839 K \u5df2\u5b9a\u578b\uff09\u3002\u56de\u6d4b\uff1a\u6bcf\u6839\u5386\u53f2 K \u90fd\u8dd1\u3002"""
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


def handlebar(C):
	if not _handlebar_should_run(C):
		return
	bp = getattr(C, 'barpos', None)
	if bp is not None and bp == getattr(g, '_last_handlebar_barpos', None):
		return
	g._last_handlebar_barpos = bp

	dt_full = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	d_str = dt_full[:8]
	try:
		hhmmss = int(dt_full[8:14])
	except Exception:
		hhmmss = None

	pool = []
	tick_map = {}
	ph0 = None
	g._mr_sh = 0
	g._mr_px = None
	g._mr_op = '\u76d1\u63a7\u4e2d'
	g._mr_trade_stock = None
	g._mr_focus = None

	now = datetime.datetime.now()
	now_time = now.strftime('%H%M%S')

	if now_time < '093000' or now_time > '150000':
		if getattr(g, 'signal_trace_log', True):
			print('[TRACE] \u5e02\u533a\u65f6\u95f4\u5916 now_wall=%s bar\u65e5=%s \u8df3\u8fc7(\u5b9e\u76d8\u7528\u5899\u949f)\u3002'
			      '\u63d0\u793a:[MIN]\u4eca\u5f00/\u6628\u6536\u6309K\u7ebf\u65f6\u95f4=%s\u7684\u4ea4\u6613\u65e5\u8ba1\u7b97\uff0c\u4e0e\u5899\u949f\u201c\u4eca\u5929\u201d\u672a\u5fc5\u4e00\u81f4\u3002'
			      % (now_time, d_str, dt_full))
		_mr_set('\u975e\u4ea4\u6613\u65f6\u6bb5(\u5899\u949f%s)' % now_time)
		pool_early = _pool_from_sector(C)
		g._mon_pool_codes = frozenset((_canonical_stock_code(x) or x) for x in pool_early)
		pos_early = _position_codes_from_account()
		_emit_minute_summary(C, dt_full, d_str, hhmmss, tick_map, pool_early, None, set(), True)
		_emit_monitor_unified_summary(dt_full, pos_early, g._mon_pool_codes)
		_emit_position_holdings(C, dt_full, d_str, tick_map)
		return

	if getattr(g, '_trade_day', '') != d_str:
		g._trade_day = d_str
		g._ma10_signal_latched = False
		g._tail_last_minute_log = {}
		g._atr_last_minute_log = {}
		g._hold_days_dbg_marker = {}
		_hydrate_buy_date_from_trades()

	if not g.accid:
		if not g._warned_no_account:
			g._warned_no_account = True
			print('%s \u8b66\u544a: accid \u4e3a\u7a7a' % STRATEGY_TAG)

	pos_codes = _position_codes_from_account()
	pool = _pool_from_sector(C)
	g._mon_pool_codes = frozenset((_canonical_stock_code(x) or x) for x in pool)
	if not hasattr(g, '_day_low_marker'):
		g._day_low_marker = {}
	if not hasattr(g, '_day_low_val'):
		g._day_low_val = {}

	sim_keys = _sim_hold_keys()
	already = pos_codes | sim_keys
	mos = int(g.min_order_shares)
	notional = float(g.per_stock_amount)
	mhc = int(g.max_hold_count)

	if g.use_tick_first and pool:
		codes = list(pool)[:50]
		ph = _primary_holding_stock()
		if ph and ph not in codes:
			codes.append(ph)
		try:
			if hasattr(C, 'get_full_tick') and codes:
				ticks = C.get_full_tick(codes)
				if ticks:
					for code, t in ticks.items():
						p = _parse_tick_price(t)
						if p and p > 0:
							tick_map[_canonical_stock_code(code) or code] = float(p)
		except Exception:
			pass

	idx_close, idx_ma5, idx_ma10, index_allow_new, index_liquidate_all = _sse_ma_state(C, dt_full)
	if not bool(getattr(g, 'require_sse_above_ma5_for_new', True)):
		index_allow_new = True
	if _vb() and idx_close is not None:
		print('%s \u4e0a\u8bc1 \u6536=%.2f MA5=%.2f MA10=%.2f \u5f00\u65b0\u95e8\u63a7=%s \u6e05\u5168MA10=%s'
		      % (d_str, idx_close, idx_ma5 or 0, idx_ma10 or 0, index_allow_new, index_liquidate_all))

	ph0 = _primary_holding_stock()
	g._mr_focus = ph0 or (pool[0] if pool else None)
	in_sess = _in_session_trade(hhmmss) if hhmmss is not None else False
	pool_head = (pool[0] if pool else '')
	_trace(dt_full, 'barpos=%s now_wall=%s hhmmss=%s \u8fde\u7eed\u7ade\u4ef7=%s pool=%d acc=%d sim_ph=%s tick_n=%d'
	       % (bp, now_time, hhmmss, in_sess, len(pool), len(pos_codes), ph0 or '-', len(tick_map)))
	if pool_head:
		ot, pc = _daily_open_prevclose(C, pool_head, dt_full, d_str)
		if ot and pc:
			gapv = ot / pc - 1.0
			br0 = _gap_bracket(gapv)
			px0 = _get_current_price(C, pool_head, dt_full, None, tick_map)
			_trace(dt_full, '\u5019\u9009[%s] \u4eca\u5f00=%.3f \u6628\u653f=%.3f gap=%.2f%% \u6863=%s \u5f53\u524d\u4ef7=%s'
			       % (pool_head, ot, pc, gapv * 100, br0, ('%.3f' % px0) if px0 else '\u65e0'))
		else:
			_trace(dt_full, '\u5019\u9009[%s] \u65e5\u7ebf\u4eca\u5f00/\u6628\u6536\u62c9\u53d6\u5931\u8d25' % pool_head)
	else:
		_trace(dt_full, '\u81ea\u9009\u6c60\u4e3a\u7a7a')

	if not _in_session_trade(hhmmss):
		_mr_set('\u975e\u8fde\u7eed\u7ade\u4ef7\u65f6\u6bb5(K\u7ebfhhmmss=%s)' % hhmmss)
	elif not pool:
		_mr_set('\u81ea\u9009\u6c60\u7a7a')
	elif not index_allow_new:
		_mr_set('\u4e0a\u8bc1\u5728MA5\u4e0b\u4e0d\u5f00\u65b0\u4ed3')
	elif len(already) >= mhc:
		_mr_set('\u5df2\u6ee1\u4ed3(%d>=%d)' % (len(already), mhc))
	elif ph0:
		br_l = g.gap_bracket.get(ph0)
		_mr_set('\u91d1\u5b57\u5854/\u6301\u4ed3 %s \u6863=%s' % (ph0, br_l or '-'))
	else:
		stx = _canonical_stock_code(pool[0]) or pool[0]
		if stx in already:
			_mr_set('\u5df2\u6301\u4ed3\u8df3\u8fc7 %s' % stx)
		else:
			otx, pcx = _daily_open_prevclose(C, stx, dt_full, d_str)
			if otx and pcx:
				brx = _gap_bracket(otx / pcx - 1.0)
				_mr_set('\u7b49\u5f85\u5f00\u4ed3 %s \u6863=%s' % (stx, brx))
			else:
				_mr_set('\u7b49\u5f00\u4ed3 %s(\u65e5\u7ebf\u7f3a\u5931\u8d25)' % stx)

	def run_index_liquidate_signal():
		if not index_liquidate_all:
			g._ma10_signal_latched = False
			return
		if not _non_atr_sell_time_ok(hhmmss):
			return
		if g._ma10_signal_latched:
			return
		g._ma10_signal_latched = True
		wl = getattr(g, '_mon_pool_codes', frozenset())
		print('%s [SIGNAL] \u4e0a\u8bc1\u6536\u76d8<\u7ebfMA10 \u4ec5\u6e05\u201c\u81ea\u9009\u6c60\u201d\u5185\u6301\u4ed3\uff08\u672c\u8f6e\u4e00\u6b21\uff0c\u5b9e\u76d8\u4e0b\u5356\uff09' % dt_full)
		pos = []
		_gtd = _get_trade_detail_data_fn()
		if g.accid and _gtd:
			try:
				pos = _gtd(g.accid, _account_type(), 'position') or []
			except Exception:
				pos = []
		for p in pos or []:
			try:
				if int(getattr(p, 'm_nVolume', 0) or 0) <= 0:
					continue
				st = _normalize_position_code(p)
				if not st:
					continue
				st_can = _canonical_stock_code(st) or st
				if not wl or st_can not in wl:
					continue
				sh = int(getattr(p, 'm_nVolume', 0) or 0)
				sh = (sh // mos) * mos
				px = float(getattr(p, 'm_dLastPrice', 0) or 0)
				_print_sell_signal(C, dt_full, st, sh, px, '\u4e0a\u8bc1\u7834MA10(\u8d26\u6237\u6301\u4ed3\u53c2\u8003)', tick_map)
			except Exception:
				continue
		for st in list(g.holding.keys()):
			if g.holding.get(st):
				st_can = _canonical_stock_code(st) or st
				if not wl or st_can not in wl:
					continue
				sh = int(g.buy_shares.get(st, 0) or 0)
				if sh >= mos:
					fb = None
					try:
						m1 = C.get_market_data_ex(['close'], [st], end_time=dt_full, period='1m', count=1, subscribe=False)
						if st in m1:
							cm = _ohlc_to_list(m1[st].get('close'))
							if cm:
								fb = float(cm[-1])
					except Exception:
						pass
					px = _get_current_price(C, st, dt_full, fb, tick_map) or fb or 0.0
					_signal_sell_sim(C, st, '\u4e0a\u8bc1\u7834MA10(\u6a21\u62df\u6301\u4ed3\u6e05\u7a7a)', dt_full, sh, px, tick_map)

	def run_risk_sell_signal():
		wl = getattr(g, '_mon_pool_codes', frozenset())
		cand = set()
		for k, v in list(g.holding.items()):
			if not v or int(g.buy_shares.get(k, 0) or 0) <= 0:
				continue
			ck = _canonical_stock_code(k) or k
			if ck in wl:
				cand.add(ck)
		if getattr(g, 'monitor_account_risk_sells', True):
			cand |= (set(pos_codes) & wl)
		for stock in sorted(cand):
			if not stock:
				continue
			st = _canonical_stock_code(stock) or stock
			try:
				data_d = C.get_market_data_ex(
					['close', 'high', 'low', 'open'], [st],
					end_time=dt_full, period='1d', count=int(g.bar_count), subscribe=False
				)
				if st not in data_d:
					continue
				highs = _ohlc_to_list(data_d[st].get('high'))
				lows = _ohlc_to_list(data_d[st].get('low'))
				closes = _ohlc_to_list(data_d[st].get('close'))
				if len(closes) < 2:
					continue
				fb = float(closes[-1])
				px = _get_current_price(C, st, dt_full, fb, tick_map)
				if px is None or px <= 0:
					continue
				px_mx = _live_px_max_for_atr(C, st, dt_full, tick_map, px)
				if px_mx is not None and px_mx > 0:
					px = float(px_mx)
				highs, lows, closes = _align_daily_ohlc_chronological(data_d, st, highs, lows, closes, ref_px=px)
				bar_low = px
				try:
					m1 = C.get_market_data_ex(
						['close', 'low'], [st], end_time=dt_full, period='1m', count=1, subscribe=False
					)
					if st in m1:
						lm = _ohlc_to_list(m1[st].get('low'))
						if lm:
							bar_low = min(float(lm[-1]), px)
				except Exception:
					pass

				prev_ref = float(g.prev_close_ref.get(st, closes[-2]))
				if prev_ref <= 0:
					prev_ref = float(closes[-2])

				if g._day_low_marker.get(st) != d_str:
					g._day_low_marker[st] = d_str
					g._day_low_val[st] = bar_low
				else:
					g._day_low_val[st] = min(float(g._day_low_val.get(st, bar_low)), bar_low)
				dv = float(g._day_low_val[st])
				touch_hit = dv / prev_ref - 1.0 <= float(g.intraday_touch_pct)
				if touch_hit:
					prev_touch_day = g.touch_neg8.get(st)
					g.touch_neg8[st] = d_str
					if getattr(g, 'tail_intraday_log', True) and prev_touch_day != d_str:
						print('[TAIL-ARM] \u65f6\u95f4=%s|\u4ee3\u7801=%s|\u53c2\u8003\u6628\u6536=%.3f|\u65e5\u5185\u6700\u4f4e=%.3f|\u4ece\u6628\u6536\u8dcc\u5e45=%.2f%%|\u8bf4\u660e=\u5df2\u8bb0\u5f55\u66fe\u89e6\u9608(\u5c3e\u76d8%s\u540e\u672a\u6536\u56de\u5219\u5356)'
						      % (dt_full, st, prev_ref, dv, (dv / prev_ref - 1.0) * 100.0, _fmt_non_atr_sell_start()))

				if getattr(g, 'tail_intraday_log', True) and g.touch_neg8.get(st) == d_str and hhmmss is not None and (not _non_atr_sell_time_ok(hhmmss)):
					cur_key = dt_full[:12]
					if not hasattr(g, '_tail_last_minute_log'):
						g._tail_last_minute_log = {}
					if g._tail_last_minute_log.get(st) != cur_key:
						g._tail_last_minute_log[st] = cur_key
						ch = px / prev_ref - 1.0
						th = float(g.intraday_fail_recover_pct)
						ok_tail = ch < th
						print('[TAIL-PEND] \u65f6\u95f4=%s|\u4ee3\u7801=%s|\u73b0/\u6628\u6536=%.2f%%|\u672a\u56de\u95f8=%.2f%%|\u5c3e\u76d8\u53ef\u5356=%s|\u8bf4\u660e=\u76d8\u4e2d\u76d1\u63a7\u7b49%s'
						      % (dt_full, st, ch * 100.0, th * 100.0, '\u662f' if ok_tail else '\u5426', _fmt_non_atr_sell_start()))

				acc_v, acc_a = _account_position_detail(st)
				sim_v = int(g.buy_shares.get(st, 0) or 0)
				has_sim = bool(g.holding.get(st)) and sim_v > 0
				if acc_v and int(acc_v) > 0:
					sh_raw = int(acc_v)
					if acc_a is not None and float(acc_a) > 0:
						avg_c = float(acc_a)
					elif has_sim:
						ac = _avg_cost(st)
						avg_c = float(ac) if ac is not None else None
					else:
						avg_c = float(acc_a) if acc_a is not None else None
				elif has_sim:
					sh_raw = sim_v
					avg_c = _avg_cost(st)
				else:
					continue
				sh = (sh_raw // mos) * mos
				if sh < mos:
					continue

				if st not in g.buy_date:
					g.buy_date[st] = _effective_buy_date(st, d_str) or d_str

				if _non_atr_sell_time_ok(hhmmss) and avg_c is not None and avg_c > 0 and px / avg_c - 1.0 <= float(g.hard_stop_pct):
					_signal_sell_sim(C, st, '\u786c\u6b62\u635f-8%', dt_full, sh, px, tick_map)
					continue

				if _non_atr_sell_time_ok(hhmmss):
					if g.touch_neg8.get(st) == d_str and (px / prev_ref - 1.0) < float(g.intraday_fail_recover_pct):
						_signal_sell_sim(C, st, '\u5c3e\u76d8\u66fe\u89e6-8%\u672a\u56de-6%', dt_full, sh, px, tick_map)
						continue

				if avg_c is None or avg_c <= 0:
					continue

				bdate = _effective_buy_date(st, d_str)
				try:
					dh = max(0, (datetime.datetime.strptime(d_str, '%Y%m%d') - datetime.datetime.strptime(bdate, '%Y%m%d')).days) if bdate else 1
				except Exception:
					dh = 1
				if not bdate:
					dh_eff = 1
				elif bdate == d_str:
					dh_eff = 1 if bool(g.allow_atr_same_day) else 0
				else:
					dh_eff = max(1, dh)
				ref_h = float(px)
				if bool(getattr(g, 'atr_ref_high_use_intraday', True)):
					m1h = _intraday_high_since_open(C, st, dt_full, d_str)
					m1x = _m1_last_high(C, st, dt_full)
					for u in (m1h, m1x):
						if u is not None and float(u) > 0:
							ref_h = max(ref_h, float(u))
				_emit_atr_mon_line(dt_full, st, px, avg_c, dh_eff, highs, lows, closes,
						   hold_shares=sh_raw, scope_tag='\u81ea\u9009', ref_high=ref_h)
				should_tp, note = _check_atr_take_profit_only(dh_eff, highs, lows, closes, px, avg_c, ref_high=ref_h)
				if _vb():
					print('%s [\u6b62\u76c8\u68c0\u67e5] %s %s' % (dt_full, st, note))
				if should_tp:
					_signal_sell_sim(C, st, note, dt_full, sh, px, tick_map)
			except Exception as e:
				print('%s [\u98ce\u63a7\u5356\u5f02\u5e38] %s %s' % (dt_full, st, e))

	def run_pyramid_and_entry_signal():
		if not _in_session_trade(hhmmss):
			_trace(dt_full, '\u975e\u8fde\u7eed\u7ade\u4ef7\u65f6\u6bb5(\u5348\u4f11/76\u524d) \u8df3\u8fc7\u5f00\u4ed3\u91d1\u5b57\u5854 hhmmss=%s' % hhmmss)
			return
		ph = _primary_holding_stock()
		if ph:
			stock = ph
			bracket = g.gap_bracket.get(stock)
			anchor = g.anchor_buy.get(stock)
			if bracket == 'D' or anchor is None:
				_trace(dt_full, '\u91d1\u5b57\u5854\u8df3\u8fc7 ph=%s \u6863=%s anchor=%s (D\u6863\u6216\u65e0\u951a\u5b9a)' % (stock, bracket, anchor))
				return
			legs = list(g.leg_done.get(stock, [True, False, False]))
			if len(legs) != 3:
				legs = [True, False, False]
			fb = None
			try:
				m1 = C.get_market_data_ex(['close'], [stock], end_time=dt_full, period='1m', count=1, subscribe=False)
				if stock in m1:
					cm = _ohlc_to_list(m1[stock].get('close'))
					if cm:
						fb = float(cm[-1])
			except Exception:
				pass
			price_now = _get_current_price(C, stock, dt_full, fb, tick_map)
			if price_now is None or price_now <= 0:
				_trace(dt_full, '\u91d1\u5b57\u5854 %s \u65e0\u6cd5\u53d6\u5f53\u524d\u4ef7' % stock)
				return
			_trace(dt_full, '\u91d1\u5b57\u5854 %s \u6863=%s \u951a=%.3f \u4ef7=%.3f legs=%s' % (stock, bracket, anchor, price_now, legs))
			if bracket == 'A':
				if not legs[1] and price_now <= anchor * 0.95:
					if _signal_buy_leg(C, stock, notional * 0.30, price_now, dt_full, d_str, mos,
							   '\u3010A\u6863\u3011\u52a0\u4ed330%%\u951ax0.95', tick_map):
						legs[1] = True
				if not legs[2] and price_now <= anchor * 0.92:
					if _signal_buy_leg(C, stock, notional * 0.20, price_now, dt_full, d_str, mos,
							   '\u3010A\u6863\u3011\u52a0\u4ed320%%\u951ax0.92', tick_map):
						legs[2] = True
			elif bracket in ('B', 'C'):
				if not legs[1] and price_now <= anchor * 0.97:
					if _signal_buy_leg(C, stock, notional * 0.20, price_now, dt_full, d_str, mos,
							   ('\u3010%s\u6863\u3011\u52a0\u4ed320%%\u951ax0.97' % bracket), tick_map):
						legs[1] = True
				if not legs[2] and price_now <= anchor * 0.95:
					if _signal_buy_leg(C, stock, notional * 0.30, price_now, dt_full, d_str, mos,
							   ('\u3010%s\u6863\u3011\u52a0\u4ed330%%\u951ax0.95' % bracket), tick_map):
						legs[2] = True
			g.leg_done[stock] = legs
			return

		if not pool:
			_trace(dt_full, '\u65e0\u5f00\u4ed3\u5019\u9009(\u81ea\u9009\u6c60\u7a7a)')
			return
		if not index_allow_new:
			_trace(dt_full, '\u4e0d\u5f00\u65b0\u4ed3: \u4e0a\u8bc1\u5728MA5\u4e0b')
			if _vb():
				print('%s [\u4e0d\u5f00\u65b0\u4ed3] \u4e0a\u8bc1\u5728MA5\u4e0b' % dt_full)
			return
		if len(already) >= mhc:
			_trace(dt_full, '\u5df2\u6ee1\u4ed3\u6570 already=%d >= max_hold=%d' % (len(already), mhc))
			if _vb():
				print('%s [\u8df3\u8fc7\u5f00\u4ed3] \u8d26\u6237/\u7b56\u7565\u5df2\u6301\u4ed3\u6570=%d \u5df2\u8fbe\u4e0a\u9650=%d' % (dt_full, len(already), mhc))
			return

		cands = []
		held_cnt = 0
		for s in pool:
			can = _canonical_stock_code(s) or s
			if can in already:
				held_cnt += 1
				continue
			cands.append(can)
		if not cands:
			_trace(dt_full, '\u81ea\u9009\u5168\u90e8\u5df2\u6301\u4ed3 held=%d pool=%d' % (held_cnt, len(pool)))
			if _vb():
				print('%s [\u8df3\u8fc7\u5f00\u4ed3] \u81ea\u9009\u5168\u90e8\u5df2\u6301\u4ed3 held=%d pool=%d' % (dt_full, held_cnt, len(pool)))
			return
		stock = cands[0]
		o_today, prev_c = _daily_open_prevclose(C, stock, dt_full, d_str)
		if o_today is None:
			_trace(dt_full, '\u65e5\u7ebf\u7f3a\u5931\u8d25 %s \u4eca\u5f00/\u6628\u6536' % stock)
			return
		gap = o_today / prev_c - 1.0
		br = _gap_bracket(gap)
		g.open_px[stock] = o_today
		g.prev_close_ref[stock] = prev_c
		g.gap_bracket[stock] = br
		fb = None
		try:
			m1 = C.get_market_data_ex(['close'], [stock], end_time=dt_full, period='1m', count=1, subscribe=False)
			if stock in m1:
				cm = _ohlc_to_list(m1[stock].get('close'))
				if cm:
					fb = float(cm[-1])
		except Exception:
			pass
		price_now = _get_current_price(C, stock, dt_full, fb, tick_map)
		if price_now is None or price_now <= 0:
			_trace(dt_full, '\u9996\u4e70\u524d\u65e0\u6cd5\u53d6\u4ef7 %s' % stock)
			return
		legs = [False, False, False]
		if br == 'D':
			sh_t = _shares_for_cash(notional * 0.50, price_now, mos)
			_trace(dt_full, 'D\u6863\u9996\u4e7050%% \u4ef7=%.3f \u8ba1\u7b97\u80a1\u6570=%d(\u9700>=%d\u624d\u53d1\u4fe1\u53f7)' % (price_now, sh_t, mos))
			if _signal_buy_leg(C, stock, notional * 0.50, price_now, dt_full, d_str, mos,
					   '\u3010D\u6863\u3011\u9996\u4e7050%%\u5355\u7b14\u65e0\u52a0\u4ed3', tick_map):
				legs[0] = True
				g.anchor_buy[stock] = price_now
				g.leg_done[stock] = legs
			return
		if br == 'A':
			if hhmmss is None or not (93000 <= hhmmss <= 93559):
				_trace(dt_full, 'A\u6863\u9996\u4e70\u9700 9:30-9:35 \u5f53\u524dhhmmss=%s \u7b49\u5f85/\u8df3\u8fc7' % hhmmss)
				return
			sh_t = _shares_for_cash(notional * 0.50, price_now, mos)
			_trace(dt_full, 'A\u6863\u9996\u4e7050%% hhmmss=%s \u4ef7=%.3f \u8ba1\u7b97\u80a1=%d' % (hhmmss, price_now, sh_t))
			if _signal_buy_leg(C, stock, notional * 0.50, price_now, dt_full, d_str, mos,
					   '\u3010A\u6863\u3011\u9996\u4e7050%%|0930-0935', tick_map):
				legs[0] = True
				g.anchor_buy[stock] = price_now
				g.leg_done[stock] = legs
			return
		if br == 'B':
			thr_b = g.open_px[stock] * 0.97
			if price_now > thr_b:
				_trace(dt_full, 'B\u6863\u7b49\u5f85\u4ef7<=%.3f(\u5f00-3%%) \u5f53\u524d%.3f \u672a\u8fbe\u6761\u4ef6' % (thr_b, price_now))
				return
			_trace(dt_full, 'B\u6863\u89e6\u53d1\u9996\u4e70\u9608\u503c \u4ef7=%.3f' % price_now)
			if _signal_buy_leg(C, stock, notional * 0.50, price_now, dt_full, d_str, mos,
					   '\u3010B\u6863\u3011\u9996\u4e7050%%|\u4eca\u5f00x0.97', tick_map):
				legs[0] = True
				g.anchor_buy[stock] = price_now
				g.leg_done[stock] = legs
			return
		if br == 'C':
			thr_c = g.open_px[stock] * 0.96
			if price_now > thr_c:
				_trace(dt_full, 'C\u6863\u7b49\u5f85\u4ef7<=%.3f(\u5f00-4%%) \u5f53\u524d%.3f' % (thr_c, price_now))
				return
			_trace(dt_full, 'C\u6863\u89e6\u53d1\u9996\u4e70\u9608\u503c \u4ef7=%.3f' % price_now)
			if _signal_buy_leg(C, stock, notional * 0.50, price_now, dt_full, d_str, mos,
					   '\u3010C\u6863\u3011\u9996\u4e7050%%|\u4eca\u5f00x0.96', tick_map):
				legs[0] = True
				g.anchor_buy[stock] = price_now
				g.leg_done[stock] = legs

	try:
		run_index_liquidate_signal()
		run_risk_sell_signal()
		_emit_atr_non_watchlist_account_positions(C, dt_full, d_str, tick_map, getattr(g, '_mon_pool_codes', frozenset()))
		if index_liquidate_all:
			_mr_set('\u4e0a\u8bc1\u7834MA10\u672c\u6839\u5df2\u6267\u884c\u6e05\u4ed3\u5206\u652f(\u65e0\u65b0\u5f00/\u91d1\u5b57\u5854)')
			_trace(dt_full, '\u672c\u6839\u5df2\u6309MA10\u6e05\u4ed3\u903b\u8f91\u5904\u7406\u5b8c \u8df3\u8fc7\u5f00\u65b0/\u91d1\u5b57\u5854')
			return
		run_pyramid_and_entry_signal()
	except Exception as e:
		_mr_set('\u6267\u884c\u5f02\u5e38: %s' % str(e)[:40])
		print('%s handlebar ERR %r dt=%s' % (STRATEGY_TAG, e, dt_full))
	finally:
		_emit_minute_summary(C, dt_full, d_str, hhmmss, tick_map, pool, ph0, already, index_allow_new)
		_emit_monitor_unified_summary(dt_full, pos_codes, getattr(g, '_mon_pool_codes', frozenset()))
		_emit_position_holdings(C, dt_full, d_str, tick_map)


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
