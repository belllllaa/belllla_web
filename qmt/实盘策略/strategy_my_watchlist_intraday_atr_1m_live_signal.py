#coding:gbk
"""Live 1m watchlist strategy (passorder). Doc: strategy_my_watchlist_intraday_atr_1m_live_signal.md"""

import sys
import time
import datetime
import csv
import os


def _passorder_fn():
	fn = getattr(sys.modules.get('__main__'), 'passorder', None)
	if fn is None:
		fn = globals().get('passorder')
	return fn


def _cancel_fn():
	fn = getattr(sys.modules.get('__main__'), 'cancel', None)
	if fn is None:
		fn = globals().get('cancel')
	return fn


def _remove_stock_from_sector_fn():
	fn = getattr(sys.modules.get('__main__'), 'remove_stock_from_sector', None)
	if fn is None:
		fn = globals().get('remove_stock_from_sector')
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


def _snapshot_price_chg_open(C, stock, dt_full, d_str, tick_map, opc=None, acc_lp=None, hhmmss=None):
	"""(\u4eca\u5f00, \u6da8\u8dcc\u5e45%%, \u5f53\u524d\u4ef7) \u5931\u8d25\u7528 None; opc \u4e3a (\u4eca\u5f00,\u6628\u6536) \u65f6\u4e0d\u518d\u8bf7\u6c42\u65e5\u7ebf; acc_lp \u4e3a\u8d26\u6237\u6301\u4ed3 m_dLastPrice(\u4e0e[POS]\u4e00\u81f4)"""
	if not stock or stock == '-':
		return None, None, None
	if opc is not None:
		ot, pc = opc
	else:
		ot, pc = _opc_get(C, stock, dt_full, d_str, hhmmss)
	fb = None
	try:
		m1 = C.get_market_data_ex(['close'], [stock], end_time=dt_full, period='1m', count=1, subscribe=False)
		if stock in m1:
			cm = _ohlc_to_list(m1[stock].get('close'))
			if cm:
				fb = float(cm[-1])
	except Exception:
		pass
	px = _get_current_price(C, stock, dt_full, fb, tick_map, account_last=acc_lp)
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


def _opc_get(C, stock, dt_full, d_str, hhmmss=None):
	"""\u6309 K \u7ebf\u4ea4\u6613\u65e5 d_str \u7f13\u5b58\u65e5\u7ebf+1m \u63a8\u7b97\u7ed3\u679c\uff1b\u5b9e\u76d8 tick \u7684\u6628\u6536/\u4eca\u5f00\u8986\u76d6\u4f18\u5148\u3002
	\u5728 gap_bracket_min_hhmmss \u4e4b\u524d\u82e5 tick \u672a\u7ed9\u6709\u6548\u4eca\u5f00\uff0c\u4e0d\u91c7\u7528\u65e5\u7ebf/\u7f13\u5b58\u63a8\u51fa\u7684\u4eca\u5f00\uff08\u907f\u514d\u96c6\u5408\u7ade\u4ef7\u672a\u5b9a\u524d\u8bef\u5206\u6863\uff09\u3002"""
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
		try:
			o = float(top)
		except (TypeError, ValueError):
			pass
	elif hhmmss is not None:
		try:
			lim = int(getattr(g, 'gap_bracket_min_hhmmss', getattr(g, 'session_gate_start_hhmmss', 92500)))
			if int(hhmmss) < lim:
				o = None
		except (TypeError, ValueError):
			pass
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


def _account_last_price_map(C):
	"""\u8d26\u6237\u6301\u4ed3 m_dLastPrice \u2192 \u89c4\u8303\u4ee3\u7801\u6620\u5c04\uff08\u4e0e[POS]\u73b0\u4ef7\u540c\u6e90\uff09\u3002"""
	out = {}
	if not (g.accid or '').strip():
		return out
	_gtd = _get_trade_detail_data_fn()
	if not _gtd:
		return out
	try:
		pos = _gtd(g.accid, _account_type(), 'position') or []
	except Exception:
		return out
	for p in pos:
		try:
			st = _normalize_position_code(p)
			st = _canonical_stock_code(st) or st
			if not st or int(getattr(p, 'm_nVolume', 0) or 0) <= 0:
				continue
			lp = float(getattr(p, 'm_dLastPrice', 0) or 0)
			if lp > 0:
				out[st] = lp
		except Exception:
			continue
	return out


def _emit_minute_summary(C, dt_full, d_str, hhmmss, tick_map, pool, ph0, already, index_allow_new, acc_lp_map=None):
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
	am = acc_lp_map or {}
	stale_bar = _live_bar_before_calendar_today(d_str, C)
	stale_op = '\u7b49\u5f85\u5f53\u65e5K\u7ebf(\u5f53\u524dbar\u65e5\u671f=%s\u975e\u4eca\u65e5\u65e0\u5206\u6863)' % d_str
	for st in lines:
		opc = _opc_get(C, st, dt_full, d_str, hhmmss) if st else (None, None)
		can = _canonical_stock_code(st) or st
		alc = am.get(can) or am.get(st)
		ot, chg, px = _snapshot_price_chg_open(C, st, dt_full, d_str, tick_map, opc=opc, acc_lp=alc, hhmmss=hhmmss) if st else (None, None, None)
		if stale_bar:
			op = stale_op
			sh = 0
			out_px = getattr(g, '_mr_px', None)
		elif focus and st == focus:
			op = getattr(g, '_mr_op', '-')
			sh = int(getattr(g, '_mr_sh', 0) or 0)
			out_px = getattr(g, '_mr_px', None)
			# \u5df2\u6301\u4ed3\u884c\uff1a_mr_sh \u5e38\u4e3a 0\uff08\u672c\u5206\u949f\u672a\u4e0b\u5355\uff09\uff0c\u4e0e [POS] \u5bf9\u9f50\u7528\u5b9e\u9645\u6301\u4ed3\u91cf
			al0 = already if already is not None else frozenset()
			if can in al0:
				vh0, _ = _position_volume_and_avg(st)
				if vh0 and int(vh0) > 0:
					sh = int(vh0)
		else:
			op = _per_stock_watch_hint(C, st, dt_full, d_str, hhmmss, tick_map, already, index_allow_new, opc=opc)
			tr_can = (_canonical_stock_code(tr_st) or tr_st) if tr_st else None
			sh = int(getattr(g, '_mr_sh', 0) or 0) if (tr_can and can == tr_can) else 0
			out_px = getattr(g, '_mr_px', None) if (tr_can and can == tr_can) else None
			# \u975e\u672c bar \u6210\u4ea4\u7968\uff1a\u539f\u903b\u8f91\u80a1\u6570\u56fa\u5b9a\u4e3a 0\uff1b\u5df2\u6301\u4ed3\u5e94\u663e\u793a\u5b9e\u9645\u6301\u4ed3\uff08\u4e0e [POS] \u4e00\u81f4\uff09
			al1 = already if already is not None else frozenset()
			if can in al1:
				vh1, _ = _position_volume_and_avg(st)
				if vh1 and int(vh1) > 0:
					sh = int(vh1)
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
	if _live_bar_before_calendar_today(d_str, C):
		return '\u7b49\u5f85\u5f53\u65e5K\u7ebf(\u5f53\u524dbar\u975e\u4eca\u65e5\u65e0\u5206\u6863)'
	if not (_in_session_trade(hhmmss) or _a_preopen_for_first_buy(hhmmss)):
		return '\u975e\u4ea4\u6613\u53ef\u64cd\u4f5c\u65f6\u6bb5'
	if not index_allow_new:
		return '\u4e0a\u8bc1T-1\u6536<T-1MA5(\u672c\u7968\u4ec5\u76d1\u63a7)'
	if stock in already:
		return '\u5df2\u6301\u4ed3'
	if opc is not None:
		o, pc = opc
	else:
		o, pc = _opc_get(C, stock, dt_full, d_str, hhmmss)
	if pc is None or pc <= 0:
		return '\u65e5\u7ebf\u7f3a\u5931\u8d25'
	if o is None or o <= 0:
		try:
			gbm = int(getattr(g, 'gap_bracket_min_hhmmss', getattr(g, 'session_gate_start_hhmmss', 92500)))
			if hhmmss is not None and int(hhmmss) < gbm:
				return '\u96c6\u5408\u7ade\u4ef7\u672a\u786e\u5b9a(\u6863\u5f85\u786e\u8ba4)'
		except (TypeError, ValueError):
			pass
		return '\u4eca\u5f00\u62c9\u53d6\u5931\u8d25'
	br = _gap_bracket(o / pc - 1.0)
	px = _get_current_price(C, stock, dt_full, None, tick_map)
	if br == 'A' and not _a_first_buy_window_ok(hhmmss):
		a0, a1 = int(getattr(g, 'a_first_buy_start_hhmmss', 92500)), int(getattr(g, 'a_first_buy_end_hhmmss', 102559))
		try:
			h = int(hhmmss)
			if h > a1:
				return ('A\u6863\u9996\u4e70\u7a97\u53e3\u5df2\u8fc7(%s-%s)\u672c\u65e5\u4e0d\u518d\u81ea\u52a8\u9996\u4e70 '
				        '\u53ef\u5728\u7b56\u7565\u91cc\u8c03\u5927 a_first_buy_end_hhmmss') % (_fmt_hhmmss_colon(a0), _fmt_hhmmss_colon(a1))
			if h < a0:
				return '\u7b49\u5f85A\u6863\u9996\u4e70(%s-%s) \u6863=%s' % (_fmt_hhmmss_colon(a0), _fmt_hhmmss_colon(a1), br)
		except (TypeError, ValueError):
			pass
		return '\u7b49\u5f85A\u6863\u9996\u4e70(%s-%s) \u6863=%s' % (_fmt_hhmmss_colon(a0), _fmt_hhmmss_colon(a1), br)
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


def _get_current_price(C, stock, bar_date_str, fallback_close, tick_snapshot=None, account_last=None):
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
		if account_last is not None and float(account_last) > 0:
			return float(account_last)
	except (TypeError, ValueError):
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


# ---------- manual_open_date CSV: calendar hold days (\u540c strategy_manual_hold_days_live) ----------
_MANUAL_HOLD_OPEN_CSV_NAME = 'manual_open_date_my_holdings.csv'


def _strategy_script_base_dir():
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
	try:
		return os.path.abspath(os.getcwd())
	except Exception:
		return ''


def default_manual_hold_open_csv_path():
	base = _strategy_script_base_dir()
	if not base:
		return ''
	return os.path.normpath(os.path.join(base, _MANUAL_HOLD_OPEN_CSV_NAME))


def _manual_abs_if_file(path_str):
	if not path_str:
		return None
	p = os.path.normpath(os.path.abspath(str(path_str).strip()))
	return p if os.path.isfile(p) else None


def _iter_manual_hold_csv_candidates():
	seen = set()
	for p in (
		default_manual_hold_open_csv_path(),
		os.path.join(
			os.environ.get('USERPROFILE', '') or '',
			'Documents',
			'belllla_web',
			'qmt',
			'\u5b9e\u76d8\u7b56\u7565',
			_MANUAL_HOLD_OPEN_CSV_NAME,
		),
		os.path.join(
			r'c:\Users\admin\Documents\belllla_web',
			'qmt',
			'\u5b9e\u76d8\u7b56\u7565',
			_MANUAL_HOLD_OPEN_CSV_NAME,
		),
	):
		if not p:
			continue
		n = os.path.normpath(p)
		if n in seen:
			continue
		seen.add(n)
		yield n


def resolve_manual_hold_open_csv_path(context_raw):
	cr = (context_raw or '').strip()
	if cr:
		ap = os.path.normpath(os.path.abspath(cr))
		if os.path.isfile(ap):
			return ap, 'context'
	for ev in ('MANUAL_OPEN_DATE_CSV', 'BELLLLA_MANUAL_OPEN_CSV'):
		got = _manual_abs_if_file(os.environ.get(ev))
		if got:
			return got, ev
	for cand in _iter_manual_hold_csv_candidates():
		if cand and os.path.isfile(cand):
			return os.path.normpath(os.path.abspath(cand)), 'auto_found'
	if cr:
		return os.path.normpath(os.path.abspath(cr)), 'context_missing_file'
	base = default_manual_hold_open_csv_path()
	return base, 'fallback_default'


def _load_manual_hold_open_dates_csv(path_str):
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


def _manual_hold_csv_reload(asof_trade_day=None):
	"""\u624b\u5de5\u5f00\u4ed3 CSV\uff1a\u540c\u4e00\u4ea4\u6613\u65e5 d_str \u4ec5\u8bfb\u76d8\u4e00\u6b21\uff08\u65e0 mtime \u8f6e\u8be2\uff09\u3002
	init \u65e0 d_str \u65f6\u9884\u8bfb\u4e00\u6b21\u6807 __PREBAR__\uff1b\u9996\u6b21\u4f20\u5165\u5f53\u65e5 d_str \u65f6\u518d\u8bfb\u4e00\u6b21\u4ee5\u7eb3\u5165\u9694\u591c\u4fee\u6539 CSV\u3002"""
	if not getattr(g, 'use_manual_hold_days_csv', True):
		g._manual_open_dates = {}
		g._manual_csv_loaded_trade_day = None
		return
	path = str(getattr(g, 'open_date_csv_path', '') or '').strip()
	if not path:
		g._manual_open_dates = {}
		g._manual_csv_mtime = None
		g._manual_csv_load_err = 'no_path'
		g._manual_csv_loaded_trade_day = None
		return
	sd = (asof_trade_day or '').strip()
	if sd and getattr(g, '_manual_csv_loaded_trade_day', None) == sd:
		return
	try:
		mt = os.path.getmtime(path)
	except Exception as e:
		g._manual_open_dates = {}
		g._manual_csv_mtime = None
		g._manual_csv_load_err = str(e)[:80]
		g._manual_csv_loaded_trade_day = None
		return
	mp, err = _load_manual_hold_open_dates_csv(path)
	g._manual_open_dates = mp
	g._manual_csv_mtime = mt
	g._manual_csv_load_err = err or ''
	if sd:
		g._manual_csv_loaded_trade_day = sd
	else:
		g._manual_csv_loaded_trade_day = '__PREBAR__'


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


def _try_remove_sold_stock_from_watchlist_sector(C, stock):
	"""\u5356\u6210\u4ea4\u786e\u8ba4\u540e\u4ece watchlist_sector_name \u5bf9\u5e94\u677f\u5757\u79fb\u9664\u6210\u4ea4\u4ee3\u7801\uff08\u9700 auto_remove_sold_from_watchlist=True\uff09\u3002"""
	if not bool(getattr(g, 'auto_remove_sold_from_watchlist', False)):
		return
	se = (getattr(g, 'watchlist_sector_name', None) or '').strip()
	if not se:
		return
	fn = _remove_stock_from_sector_fn()
	if fn is None:
		if not getattr(g, '_warned_no_remove_sector_fn', False):
			g._warned_no_remove_sector_fn = True
			print('%s \u81ea\u9009\u79fb\u9664: remove_stock_from_sector \u672a\u627e\u5230\uff08\u975e QMT \u6216\u7248\u672c\u672a\u66b4\u9732\uff09' % STRATEGY_TAG)
		return
	can = _canonical_stock_code(stock) or stock
	try:
		fn(se, can)
	except TypeError:
		try:
			fn(C, se, can)
		except Exception as e:
			print('%s [\u81ea\u9009\u79fb\u9664ERR] %s %s %r' % (STRATEGY_TAG, se, can, e))
	except Exception as e:
		print('%s [\u81ea\u9009\u79fb\u9664ERR] %s %s %r' % (STRATEGY_TAG, se, can, e))
		return
	print('%s [\u81ea\u9009\u79fb\u9664OK] \u677f\u5757=%s %s' % (STRATEGY_TAG, se, can))


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
	"""\u6309\u624b\u5de5 CSV \u5f00\u4ed3\u65e5\u4f30\u7b97\u6301\u4ed3\u5929\u6570\uff1b\u672a\u5339\u914d\u6309 1 \u5929\u3002"""
	if not stock or not d_str:
		return 1
	_emit_hold_days_debug_once(stock, d_str)
	bdate = _effective_buy_date(stock, d_str)
	if not bdate:
		return 1
	try:
		dh = (datetime.datetime.strptime(d_str, '%Y%m%d') - datetime.datetime.strptime(bdate, '%Y%m%d')).days
		# \u5f53\u65e5\u4e70\u5165\u65e5\u671f\u5dee\u4e3a 0\uff0c\u7edf\u4e00\u663e\u793a\u4e3a\u6301\u4ed3 1 \u5929\uff08\u4e0e\u884c\u60c5\u8f6f\u4ef6\u4e60\u60ef\u4e00\u81f4\uff09
		return max(1, int(dh))
	except Exception:
		return 1


def _emit_hold_days_debug_once(stock, d_str):
	"""\u6bcf\u7968\u6bcf\u5929\u6700\u591a\u4e00\u6761\uff1a\u4ec5\u624b\u5de5 CSV \u5f00\u4ed3\u65e5\u3002"""
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
	try:
		eff = _effective_buy_date(can, d_str)
		mc = (getattr(g, '_manual_open_dates', None) or {}).get(can)
		print('[TRACE] HOLD-DAYS code=%s d=%s manual_csv=%r csv_path=%r effective=%r'
		      % (can, d_str, mc, getattr(g, 'open_date_csv_path', None), eff))
	except Exception:
		pass


def _effective_buy_date(stock, d_str):
	"""\u4ec5\u624b\u5de5 CSV \u4e2d\u7684 open_date\uff08YYYYMMDD\uff09\uff1b\u5173\u95ed use_manual_hold_days_csv \u6216\u65e0\u884c\u5219 None\u3002"""
	if not getattr(g, 'use_manual_hold_days_csv', True):
		return None
	can = _canonical_stock_code(stock) or stock
	_manual_hold_csv_reload(d_str)
	return (getattr(g, '_manual_open_dates', None) or {}).get(can)


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


def _live_px_max_for_atr(C, stock, dt_full, tick_map, base_px, account_last=None):
	"""\u5408\u5e76\u591a\u8def\u5f84\u73b0\u4ef7\u53d6 max\uff1baccount_last \u4e3a\u8d26\u6237 m_dLastPrice\uff08\u7531\u8c03\u7528\u65b9\u4f20\u5165\uff0c\u907f\u514d\u518d\u626b\u6301\u4ed3\u8868\uff09\u3002"""
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
	try:
		if account_last is not None and float(account_last) > 0:
			vals.append(float(account_last))
	except (TypeError, ValueError):
		pass
	mh = _m1_last_high(C, stock, dt_full)
	if mh is not None and mh > 0:
		vals.append(float(mh))
	if not vals:
		return None
	return max(vals)


def _sse_t1_close_index(closes, data_d, d_str):
	"""\u4e0a\u8bc1\u65e5\u7ebf\u4e2d T-1 \u5b8c\u6210\u65e5\u6536\u7684\u7d22\u5f15\uff08\u5347\u5e8f closes\uff09\u3002\u82e5\u6700\u540e\u4e00\u6839\u4e3a\u5f53\u65e5 d_str\uff08\u672a\u6536\u76d8\uff09\u5219 T-1 \u4e3a\u5012\u6570\u7b2c\u4e8c\u6839\u3002"""
	n = len(closes)
	if n < 2 or not d_str:
		return None
	ld = _daily_last_bar_date(data_d, INDEX_SSE, closes)
	if ld:
		try:
			if int(ld) == int(d_str):
				return n - 2
		except Exception:
			pass
	return n - 1


def _sse_ma_state(C, dt_full, d_str=None, hhmmss=None):
	"""\u8fd4\u56de (\u4e0a\u8bc1 T-1 \u6536, T-1 \u65e5\u7ebf MA5, \u6700\u65b0\u65e5\u7ebf MA10, \u5141\u8bb8\u5f00\u65b0\u4ed3, \u662f\u5426\u6e05\u5168\u4ed3)\u3002
	\u5141\u8bb8\u5f00\u65b0\u4ed3\uff1a T-1 \u6536 >= T-1 \u7684 MA5\uff08\u4e0d\u542b\u5f53\u65e5\u672a\u5b8c\u6210 K\uff09\u3002\u9996\u6b21 bar \u65f6\u523b >= sse_ma5_gate_latch_hhmmss\uff08\u9ed8\u8ba4 93000\uff09\u65f6\u5c06\u8be5\u7ed3\u679c\u51bb\u7ed3\u81f3\u6362\u65e5\uff08\u76d8\u4e2d\u4e0d\u518d\u91cd\u7b97\u95e8\u63a7\uff09\u3002
	\u6e05\u5168\u4ed3\uff1a\u4ecd\u7528\u6700\u65b0\u4e00\u6839\u65e5\u7ebf\u6536 vs \u5176 MA10\uff08\u53ef\u542b\u5f53\u65e5\u672a\u5b8c\u6210 K\uff0c\u4e0e\u539f\u903b\u8f91\u4e00\u81f4\uff09\u3002"""
	if d_str is None and dt_full and len(str(dt_full)) >= 8:
		d_str = str(dt_full)[:8]
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
		last_raw = float(closes[-1])
		p5, p10 = int(g.ma_index_period_short), int(g.ma_index_period_long)
		ma10 = sum(float(x) for x in closes[-p10:]) / float(p10)
		index_liquidate_all = bool(last_raw < ma10)
		i1 = _sse_t1_close_index(closes, data_d, d_str)
		if i1 is None or i1 < p5 - 1:
			t1_close = t1_ma5 = None
			t1_allow = True
		else:
			t1_close = float(closes[i1])
			t1_ma5 = sum(float(closes[i1 - p5 + 1:i1 + 1])) / float(p5)
			t1_allow = bool(t1_close >= t1_ma5)
		latch_h = int(getattr(g, 'sse_ma5_gate_latch_hhmmss', 93000))
		if hhmmss is None:
			allow_new = bool(t1_allow)
		else:
			try:
				hv = int(hhmmss)
			except Exception:
				hv = 0
			if (not getattr(g, '_sse_ma5_gate_latched', False)) and hv >= latch_h:
				g._sse_ma5_gate_latched = True
				g._sse_ma5_gate_frozen_allow = bool(t1_allow)
			if getattr(g, '_sse_ma5_gate_latched', False):
				allow_new = bool(getattr(g, '_sse_ma5_gate_frozen_allow', t1_allow))
			else:
				allow_new = bool(t1_allow)
		if t1_close is None:
			return None, None, ma10, allow_new, index_liquidate_all
		return t1_close, t1_ma5, ma10, allow_new, index_liquidate_all
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


def _calendar_hold_days_bdate_to_asof(bdate, d_str):
	"""\u5f00\u4ed3\u65e5 bdate \u2192 asof d_str \u7684\u65e5\u5386\u5929\u6570\uff08\u540c\u65e5=1\uff09\u3002"""
	if not bdate or not d_str:
		return 1
	try:
		return max(1, int((datetime.datetime.strptime(d_str, '%Y%m%d') - datetime.datetime.strptime(bdate, '%Y%m%d')).days))
	except Exception:
		return 1


def _daily_hh_peak_since_open(data_d, stock, highs, open_yyyymmdd, dh_cal_fallback):
	"""\u65e5\u7ebf high \u4ece\u5f00\u4ed3\u65e5\uff08\u542b\uff09\u8d77\u81f3\u5e8f\u5217\u672b\u7684\u6700\u9ad8\uff1b\u65e0\u65e5\u671f\u6807\u7b7e\u65f6\u6309\u6301\u4ed3\u5929\u6570\u56de\u9000\u7a97\u53e3\u3002"""
	if not highs or not open_yyyymmdd:
		return None
	i0 = None
	tags = _ohlc_time_list(data_d, stock) if data_d and stock in data_d else None
	if tags and len(tags) >= len(highs):
		try:
			op = int(open_yyyymmdd)
		except Exception:
			op = None
		if op is not None:
			for i in range(len(highs)):
				td = _tag_to_yyyymmdd(tags[i])
				if not td:
					continue
				try:
					if int(td) >= op:
						i0 = i
						break
				except Exception:
					continue
	if i0 is None:
		try:
			n = min(len(highs), max(3, int(dh_cal_fallback) + 8))
		except Exception:
			n = len(highs)
		i0 = max(0, len(highs) - n)
	try:
		return max(float(x) for x in highs[i0:] if x is not None and float(x) > 0)
	except Exception:
		return None


def _atr_dynamic_mult(dh_cal):
	"""\u52a8\u6001\u500d\u6570\u5728 [max,min] \u533a\u95f4\u5e73\u6ed1\u6536\u655b\uff0c\u907f\u514d\u957f\u671f\u88ab\u4e0a\u9650\u5361\u6b7b\u3002
	\u9ed8\u8ba4\u5728 half_life \u5929\u5185\u7531\u8d77\u70b9\u8870\u51cf\u5230\u4e0b\u9650\uff1am = start - (start-lo) * ratio\u3002"""
	h = float(getattr(g, 'atr_stop_half_life_days', 10.0))
	if h <= 1e-6:
		h = 10.0
	dh = max(1, int(dh_cal))
	lo = float(getattr(g, 'atr_stop_mult_min', 1.0))
	hi = float(getattr(g, 'atr_stop_mult_max', 3.0))
	if hi < lo:
		lo, hi = hi, lo
	init = float(getattr(g, 'atr_stop_mult_initial', hi))
	start = max(lo, min(hi, init))
	ratio = min(1.0, max(0.0, float(dh - 1) / float(h)))
	m = start - (start - lo) * ratio
	return max(lo, min(hi, m))


def _atr_profit_lock_floor_price(avg_cost, dh_cal, cur_px):
	"""\u76c8\u5229\u4fdd\u62a4\u5e95\u7ebf\uff1a\u6301\u4ed3\u5929\u6570>=atr_lock_floor_min_days \u4e14\u6d6e\u76c8>=atr_lock_min_profit_dec\u65f6\u751f\u6548\u3002"""
	if avg_cost is None or float(avg_cost) <= 0 or cur_px is None or float(cur_px) <= 0:
		return None
	need_d = int(getattr(g, 'atr_lock_floor_min_days', 7))
	if int(dh_cal) < need_d:
		return None
	pf = float(cur_px) / float(avg_cost) - 1.0
	thr_pf = float(getattr(g, 'atr_lock_min_profit_dec', 0.15))
	if pf < thr_pf:
		return None
	base = float(getattr(g, 'atr_lock_ratio_base', 0.60))
	slope = float(getattr(g, 'atr_lock_ratio_slope', 0.025))
	cap = float(getattr(g, 'atr_lock_ratio_cap', 0.97))
	lock_ratio = min(cap, base + float(dh_cal) * slope)
	min_profit = pf * lock_ratio
	return float(avg_cost) * (1.0 + min_profit)


def _atr_ref_high_merged(C, st, dt_full, d_str, px):
	ref_h = float(px)
	if bool(getattr(g, 'atr_ref_high_use_intraday', True)):
		m1h = _intraday_high_since_open(C, st, dt_full, d_str)
		m1x = _m1_last_high(C, st, dt_full)
		for u in (m1h, m1x):
			if u is not None and float(u) > 0:
				ref_h = max(ref_h, float(u))
	return ref_h


def _atr_pack_for_position(C, st, dt_full, d_str, data_d, highs, lows, closes, px, avg_c, dh_eff):
	"""mult, floor, hh_daily_override(\u4ec5\u65e5\u7ebf\u4ece\u5f00\u4ed3\u8d77), ref_high(\u62fc\u5f53\u65e5\u5206\u65f6), dh_cal\u3002"""
	bdate = _effective_buy_date(st, d_str)
	if bdate:
		dh_cal = _calendar_hold_days_bdate_to_asof(bdate, d_str)
	else:
		try:
			dh_cal = max(1, int(dh_eff))
		except Exception:
			dh_cal = 1
	hh_ov = _daily_hh_peak_since_open(data_d, st, highs, bdate, dh_cal) if bdate else None
	mult = _atr_dynamic_mult(dh_cal)
	floor = _atr_profit_lock_floor_price(avg_c, dh_cal, px)
	ref_h = _atr_ref_high_merged(C, st, dt_full, d_str, px)
	return mult, floor, hh_ov, ref_h, dh_cal


def _atr_trailing_stop_numbers(days_held_effective, highs, lows, closes, ref_high=None, mult=None, stop_floor=None, hh_daily_override=None):
	"""\u8ba1\u7b97 ATR\u6b62\u76c8\u7ebf\u3002HH \u4f18\u5148\u7528\u5f00\u4ed3\u65e5\u8d77\u65e5\u7ebf\u6700\u9ad8\uff08override\uff09\u518d\u4e0e ref_high \u62fc\uff1bstop=max(HH-ATR*mult, floor)\u3002"""
	if talib is None:
		return None, None, None, 'talib', None
	if not highs or not lows or not closes or len(closes) < 2:
		return None, None, None, 'bar', None
	if days_held_effective < 1 and not bool(g.allow_atr_same_day):
		return None, None, None, 'hold', None
	hh_daily = None
	if hh_daily_override is not None:
		try:
			hh_daily = float(hh_daily_override)
		except (TypeError, ValueError):
			hh_daily = None
	if hh_daily is None:
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
	mult_use = float(mult) if mult is not None else float(getattr(g, 'atr_stop_mult_initial', getattr(g, 'atr_stop_mult', 2.5)))
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
	stop = hh_eff - float(atr_v) * mult_use
	if stop_floor is not None:
		try:
			sf = float(stop_floor)
			if sf > 0:
				stop = max(stop, sf)
		except (TypeError, ValueError):
			pass
	return stop, atr_v, hh_eff, None, float(hh_daily)


def _emit_atr_mon_line(dt_full, st, px, avg_c, dh_eff, highs, lows, closes, hold_shares=0, scope_tag='', ref_high=None,
		       mult=None, stop_floor=None, hh_daily_override=None, dh_cal=None, px_display=None):
	"""\u6bcf\u5206\u949f\u6700\u591a\u4e00\u6761 [ATR-MON]\u3002
	px \u4e3a ATR/\u6b62\u76c8\u5224\u65ad\u7528\u4ef7\uff08\u53ef\u542b _live_px_max_for_atr \u5408\u5e76\u540e\u7684\u4ef7\uff09\u3002
	px_display \u82e5\u6709\u5219\u7528\u4e8e\u65e5\u5fd7\u4e2d\u300c\u73b0\u4ef7\u300d\u4e0e\u6d6e\u76c8\u4e8f%%\uff08\u4e0e\u884c\u60c5/\u8d26\u6237\u6700\u65b0\u4ef7\u4e00\u81f4\uff09\u3002"""
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
	try:
		px_atr = float(px)
	except (TypeError, ValueError):
		px_atr = 0.0
	try:
		px_show = float(px_display) if (px_display is not None and float(px_display) > 0) else px_atr
	except (TypeError, ValueError):
		px_show = px_atr
	if avg_c is None or float(avg_c) <= 0:
		print('[ATR-MON] \u8303\u56f4=%s|\u65f6\u95f4=%s|\u4ee3\u7801=%s|\u80a1=%d|\u6d6e\u76c8\u4e8f%%=--|\u73b0=%.3f|\u6210\u672c=--|\u6b62\u76c8\u7ebf=--|\u4fdd\u5e95\u7ebf=--|\u8ddd\u7ebf=--|\u8ddd\u7ebf%%=--|ATR=--|HH=--|\u8d85\u7ebfATR=--|\u76c8ATR\u500d=--|\u672c\u6839\u89e6\u53d1=--|\u5907\u6ce8=\u6210\u672c\u7f3a'
		      % (sc, dt_full, st, sh, px_show))
		return
	ac = float(avg_c)
	pnl_pct = (px_show / ac - 1.0) * 100.0
	underwater = px_show <= ac
	if mult is not None or stop_floor is not None or hh_daily_override is not None:
		stop, atr_v, highest_high, err, hh_bar = _atr_trailing_stop_numbers(
			dh_eff, highs, lows, closes, ref_high=ref_high, mult=mult, stop_floor=stop_floor, hh_daily_override=hh_daily_override)
	else:
		stop, atr_v, highest_high, err, hh_bar = _atr_trailing_stop_numbers(dh_eff, highs, lows, closes, ref_high=ref_high)
	if err is not None:
		em = {'talib': 'talib', 'bar': 'K\u7ebf', 'hold': '\u6301\u4ed31\u65e5', 'hh': 'HH', 'atr_x': 'ATR\u7b97', 'atr0': 'ATR\u65e0\u6548'}.get(err, err)
		print('[ATR-MON] \u8303\u56f4=%s|\u65f6\u95f4=%s|\u4ee3\u7801=%s|\u80a1=%d|\u6d6e\u76c8\u4e8f%%=%+.2f%%|\u73b0=%.3f|\u6210\u672c=%.3f|\u6b62\u76c8\u7ebf=--|\u4fdd\u5e95\u7ebf=%s|\u8ddd\u7ebf=--|\u8ddd\u7ebf%%=--|ATR=--|HH=--|\u8d85\u7ebfATR=--|\u76c8ATR\u500d=--|\u672c\u6839\u89e6\u53d1=--|\u5907\u6ce8=%s'
		      % (sc, dt_full, st, sh, pnl_pct, px_show, ac,
		         ('%.3f' % float(stop_floor)) if (stop_floor is not None and float(stop_floor) > 0) else '--', em))
		return
	gap = px_atr - stop
	gap_pct = (gap / stop * 100.0) if stop is not None and stop > 0 else 0.0
	near = bool(px_atr <= stop)
	buf_atr = None
	if atr_v is not None and atr_v > 0 and stop is not None:
		buf_atr = (px_atr - float(stop)) / float(atr_v)
	profit_atr = None
	if atr_v is not None and atr_v > 0:
		profit_atr = (px_atr - ac) / float(atr_v)
	note = '\u4ef7>\u6210\u672c\u53ef\u6bd4'
	if underwater:
		note = '\u975e\u6d6e\u76c8\u4ec5\u663e\u793a\u6b62\u76c8\u7ebf(\u672c\u6839\u4e0d\u6309\u6b62\u76c8\u5356\u51fa)'
	try:
		hlim = float(g.hard_stop_pct)
		hline = ac * (1.0 + hlim)
		hnote = '\u786c\u6b62\u9608\u7ebf%.3f(%.1f%%)\u6d6e\u76c8%+.2f%%' % (hline, hlim * 100.0, pnl_pct)
		note = (note + '|' + hnote)[:120]
	except Exception:
		pass
	if hh_bar is not None and highest_high is not None and float(highest_high) > float(hh_bar) + 1e-6:
		note = (note + '|\u65e5\u7ebfHH=%.3f\u2192\u6709\u6548HH=%.3f' % (float(hh_bar), float(highest_high)))[:120]
	if mult is not None:
		note = (note + '|m=%.3f' % float(mult))[:120]
	if dh_cal is not None:
		note = (note + '|dh=%d' % int(dh_cal))[:120]
	if stop_floor is not None:
		try:
			note = (note + '|floor=%.3f' % float(stop_floor))[:120]
		except Exception:
			pass
	print('[ATR-MON] \u8303\u56f4=%s|\u65f6\u95f4=%s|\u4ee3\u7801=%s|\u80a1=%d|\u6d6e\u76c8\u4e8f%%=%+.2f%%|\u73b0=%.3f|\u6210\u672c=%.3f|\u6b62\u76c8\u7ebf=%.3f|\u4fdd\u5e95\u7ebf=%s|\u8ddd\u7ebf=%.3f|\u8ddd\u7ebf%%=%.2f%%|ATR=%.4f|\u6301\u4ed3HH=%s|\u6709\u6548HH=%.3f|\u8d85\u7ebfATR=%s|\u76c8ATR\u500d=%s|\u672c\u6839\u89e6\u53d1=%s|\u5907\u6ce8=%s'
	      % (sc, dt_full, st, sh, pnl_pct, px_show, ac, stop,
	         ('%.3f' % float(stop_floor)) if (stop_floor is not None and float(stop_floor) > 0) else '--',
	         gap, gap_pct, atr_v if atr_v is not None else 0.0,
	         ('%.3f' % float(hh_bar)) if (hh_bar is not None and float(hh_bar) > 0) else '--',
	         highest_high if highest_high is not None else 0.0,
	         ('%.2f' % buf_atr) if buf_atr is not None else '--',
	         ('%.2f' % profit_atr) if profit_atr is not None else '--',
	         '\u662f' if near else '\u5426', note))


def _check_atr_take_profit_only(days_held_effective, highs, lows, closes, current_close, avg_cost, ref_high=None,
				mult=None, stop_floor=None, hh_daily_override=None):
	if avg_cost is None or current_close <= avg_cost:
		return False, 'ATR\u6b62\u76c8\u4ec5\u6d6e\u76c8'
	stop, atr_v, hh, err, _hh_bar = _atr_trailing_stop_numbers(
		days_held_effective, highs, lows, closes, ref_high=ref_high,
		mult=mult, stop_floor=stop_floor, hh_daily_override=hh_daily_override)
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
		m_s = (' m=%.3f' % float(mult)) if mult is not None else ''
		f_s = (' floor=%.3f' % float(stop_floor)) if stop_floor is not None else ''
		return True, ('ATR\u6b62\u76c8 \u7ebf=%.3f' % stop) + m_s + f_s
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
			acc_lp = float(getattr(p, 'm_dLastPrice', 0) or 0)
			px_live = _get_current_price(C, st, dt_full, None, tick_map, account_last=acc_lp if acc_lp > 0 else None)
			if px_live is None or float(px_live) <= 0:
				continue
			px_mx = _live_px_max_for_atr(
				C, st, dt_full, tick_map, float(px_live), account_last=acc_lp if acc_lp > 0 else None)
			px = float(px_mx) if (px_mx is not None and float(px_mx) > 0) else float(px_live)
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
			m_atr, fl_atr, hh_ov, ref_h, dh_cal = _atr_pack_for_position(
				C, st, dt_full, d_str, data_d, highs, lows, closes, px_live, avg_c, dh_eff)
			_emit_atr_mon_line(dt_full, st, px, avg_c, dh_eff, highs, lows, closes,
				   hold_shares=vol, scope_tag='\u975e\u81ea\u9009', ref_high=ref_h,
				   mult=m_atr, stop_floor=fl_atr, hh_daily_override=hh_ov, dh_cal=dh_cal,
				   px_display=float(px_live))
		except Exception:
			continue


def _clear_sim_stock(stock):
	for d in (
		g.holding, g.buy_price, g.buy_shares, g.buy_date, g.total_cost,
		g.anchor_buy, g.gap_bracket, g.open_px, g.prev_close_ref, g.leg_done, g.prev_close_stop_touch_day,
		getattr(g, 'pyramid_anchor_day', None),
	):
		if isinstance(d, dict):
			d.pop(stock, None)
	if hasattr(g, '_day_low_marker'):
		g._day_low_marker.pop(stock, None)
	if hasattr(g, '_day_low_val'):
		g._day_low_val.pop(stock, None)


def _finish_daily_entry_defer(prev_day, pos_codes):
	"""\u6362\u65e5\u56de\u8c03\uff1a\u6628\u65e5\u5c1d\u8bd5\u9996\u4e70\u4e14\u672a\u6210\u4ed3\u7684\u7968\u6392\u5230\u4eca\u65e5\u672b\u5c3e\u3002"""
	heads_dict = getattr(g, '_daily_entry_heads', None)
	if heads_dict:
		items = list(heads_dict.items())
	elif getattr(g, '_daily_entry_head', None):
		try:
			st, day = g._daily_entry_head[0], g._daily_entry_head[1]
			items = [((_canonical_stock_code(st) or st), day)]
		except (TypeError, ValueError, IndexError):
			items = []
	else:
		items = []
	if not items:
		g._daily_entry_heads = {}
		g._daily_entry_head = None
		return
	if not hasattr(g, '_defer_first_buy_tail'):
		g._defer_first_buy_tail = set()
	for can, day in items:
		if day != prev_day:
			continue
		in_acc = can in (pos_codes or set())
		sim_ok = bool(g.holding.get(can)) and int(g.buy_shares.get(can, 0) or 0) > 0
		legs = list(g.leg_done.get(can, [False, False, False]))
		first_ok = bool(legs and legs[0])
		if (not in_acc) and (not sim_ok) and (not first_ok):
			g._defer_first_buy_tail.add(can)
	g._daily_entry_heads = {}
	g._daily_entry_head = None


def _reset_pyramid_session_on_roll_day():
	"""\u6362\u65e5\uff1a\u52a0\u817f\u4ec5\u5f53\u65e5\u6709\u6548\uff1b\u6e05\u7a7a\u91d1\u5b57\u5854\u951a\u65e5\u5e76\u590d\u4f4d B/C \u817f\u6807\u8bb0\uff08\u9996\u817f\u5df2\u6210\u4ed3\u5219\u4ecd\u4e3a True\uff09\u3002"""
	if not hasattr(g, 'pyramid_anchor_day') or not isinstance(getattr(g, 'pyramid_anchor_day', None), dict):
		g.pyramid_anchor_day = {}
	for st in list(g.holding.keys()):
		if not g.holding.get(st):
			continue
		try:
			sh = int(g.buy_shares.get(st, 0) or 0)
		except Exception:
			sh = 0
		if sh <= 0:
			continue
		g.pyramid_anchor_day.pop(st, None)
		legs = list(g.leg_done.get(st, [True, False, False]))
		if len(legs) != 3:
			legs = [True, False, False]
		if legs[0]:
			g.leg_done[st] = [True, False, False]


def init(C):
	g.accid = getattr(C, 'accountid', '') or getattr(C, 'account_id', '') or '30262698'
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'

	g.watchlist_sector_name = getattr(C, 'watchlist_sector_name', '\u6211\u7684\u81ea\u9009')
	g.per_stock_amount = float(getattr(C, 'per_stock_amount', 100000))
	g.min_order_shares = int(getattr(C, 'min_order_shares', 100))
	# \u6700\u5927\u540c\u65f6\u6301\u4ed3\u53ea\u6570\uff1a\u6052\u4e3a 0=\u4e0d\u9650\u5236\uff08\u5b9e\u76d8\u9700\u6c42\u65e0\u4e0a\u9650\uff0c\u4e0d\u8bfb C.max_hold_count\uff09
	g.max_hold_count = 0
	g.require_sse_above_ma5_for_new = bool(getattr(C, 'require_sse_above_ma5_for_new', True))
	g.ma_index_period_short = int(getattr(C, 'ma_index_period_short', 5))
	g.ma_index_period_long = int(getattr(C, 'ma_index_period_long', 10))
	# \u4e0a\u8bc1 MA5 \u5f00\u65b0\u95e8\u63a7\uff1a\u9996\u6b21 bar \u65f6\u523b >= \u6b64\u503c\u65f6\u51bb\u7ed3\u5f53\u65e5 T-1 vs MA5 \u5224\u65ad\uff08\u9ed8\u8ba4 93000=\u8fde\u7eed\u7ade\u4ef7\u5f00\u76d8\uff09
	g.sse_ma5_gate_latch_hhmmss = int(getattr(C, 'sse_ma5_gate_latch_hhmmss', 93000))
	g.atr_period = int(getattr(C, 'atr_period', 14))
	# \u5168\u5e02\u573a\u903b\u8f91\u9ed8\u8ba4\u4ece 09:25 (92500) \u8d77\u7b97\uff08\u4e0e\u96c6\u5408\u7ade\u4ef7\u636e\u5408\u540e\u5bf9\u9f50\uff09
	g.session_gate_start_hhmmss = int(getattr(C, 'session_gate_start_hhmmss', 92500))
	# \u7f3a\u53e3\u5206\u6863\uff1a\u9ed8\u8ba4\u4e0e session_gate_start \u540c\u6b65\uff08\u665a\u4e8e\u6b64\u65f6\u95f4\u4e14 tick \u65e0\u4eca\u5f00\u5219\u4e0d\u63a8\u5f00\u76d8\uff09
	g.gap_bracket_min_hhmmss = int(getattr(C, 'gap_bracket_min_hhmmss', g.session_gate_start_hhmmss))
	_atr_ini = getattr(C, 'atr_stop_mult_initial', None)
	if _atr_ini is None:
		_atr_ini = getattr(C, 'atr_stop_mult', 2.5)
	g.atr_stop_mult_initial = float(_atr_ini)
	g.atr_stop_mult = float(_atr_ini)
	g.atr_stop_half_life_days = float(getattr(C, 'atr_stop_half_life_days', 10.0))
	g.atr_stop_mult_min = float(getattr(C, 'atr_stop_mult_min', 1.0))
	g.atr_stop_mult_max = float(getattr(C, 'atr_stop_mult_max', 3.0))
	_lo, _hi = float(g.atr_stop_mult_min), float(g.atr_stop_mult_max)
	if _hi < _lo:
		_lo, _hi = _hi, _lo
	g._atr_start_eff = max(_lo, min(_hi, float(g.atr_stop_mult_initial)))
	g.atr_lock_floor_min_days = int(getattr(C, 'atr_lock_floor_min_days', 7))
	g.atr_lock_min_profit_dec = float(getattr(C, 'atr_lock_min_profit_dec', 0.15))
	g.atr_lock_ratio_base = float(getattr(C, 'atr_lock_ratio_base', 0.60))
	g.atr_lock_ratio_slope = float(getattr(C, 'atr_lock_ratio_slope', 0.025))
	g.atr_lock_ratio_cap = float(getattr(C, 'atr_lock_ratio_cap', 0.97))
	g.atr_ref_high_use_intraday = bool(getattr(C, 'atr_ref_high_use_intraday', True))
	g.bar_count = int(getattr(C, 'bar_count', 80))
	g.verbose_log = bool(getattr(C, 'verbose_log', True))
	g.allow_atr_same_day = bool(getattr(C, 'allow_atr_same_day', True))
	# hard_stop_pct / tail_cost_stop_pct: \u5c3e\u76d8\u81ea\u9009\uff0c\u5224\u522b\u5f0f\u4e3a \u73b0\u4ef7/\u6301\u4ed3\u6210\u672c-1\uff08\u6301\u4ed3\u76c8\u4e8f\uff09\uff0c\u4e0e\u6628\u6536\u65e0\u5173\u3002
	g.hard_stop_pct = float(getattr(C, 'hard_stop_pct', -0.08))
	g.tail_cost_stop_pct = float(getattr(C, 'tail_cost_stop_pct', g.hard_stop_pct))
	# intraday_touch_pct: \u5168\u5929\u8fde\u7eed\u7ade\u4ef7\uff0c\u5224\u522b\u5f0f\u4e3a \u73b0\u4ef7/\u6628\u6536-1\uff08\u5f53\u65e5\u8dcc\u5e45\u76f8\u5bf9\u6628\u6536\uff09\uff0c\u4e0e\u6210\u672c\u65e0\u5173\uff08\u9ed8\u8ba4-9%\u4fbf\u4e8e\u8dcc\u505c\u524d\u6392\u5355\uff09\u3002
	g.intraday_touch_pct = float(getattr(C, 'intraday_touch_pct', -0.09))
	g.intraday_fail_recover_pct = float(getattr(C, 'intraday_fail_recover_pct', -0.06))
	g.tail_clear_start_hhmmss = int(getattr(C, 'tail_clear_start_hhmmss', 145000))
	# \u5c3e\u76d8\u76d1\u63a7\uff1a\u73b0\u4ef7<\u5f53\u524d MA5\uff08\u4e0e\u5c3e\u76d8\u6210\u672c\u6b62\u635f\u540c\u4e00\u65f6\u6bb5 tail_clear_start_hhmmss\uff09
	g.tail_sell_below_ma5 = bool(getattr(C, 'tail_sell_below_ma5', True))
	g.tail_ma5_period = max(2, int(getattr(C, 'tail_ma5_period', 5)))
	g.non_atr_sell_start_hhmmss = int(getattr(C, 'non_atr_sell_start_hhmmss', 145400))
	g.sell_unfilled_timeout_sec = float(getattr(C, 'sell_unfilled_timeout_sec', 60))
	# 卖出必须成交：失败后持续撤单重挂，不设重试上限
	g.sell_unfilled_max_retry = 0
	g.tail_intraday_log = bool(getattr(C, 'tail_intraday_log', True))
	g.atr_intraday_log = bool(getattr(C, 'atr_intraday_log', True))
	g.atr_log_account_non_watchlist = bool(getattr(C, 'atr_log_account_non_watchlist', True))
	g.use_tick_first = bool(getattr(C, 'use_tick_first', True))
	g.signal_trace_log = bool(getattr(C, 'signal_trace_log', True))
	g.minute_summary_log = bool(getattr(C, 'minute_summary_log', True))
	g.position_summary_log = bool(getattr(C, 'position_summary_log', True))
	g.sell_monitor_summary_log = bool(getattr(C, 'sell_monitor_summary_log', True))
	g.monitor_account_risk_sells = bool(getattr(C, 'monitor_account_risk_sells', True))
	# \u672c\u65e5\u7b56\u7565\u5356\u51fa\u6210\u529f\u540e\u7981\u6b62\u518d\u9996\u4e70\u8be5\u7968\uff08\u907f\u514d\u5356\u540e\u51e0\u5206\u949f\u53c8\u88ab\u9996\u4e70\u903b\u8f91\u63a5\u56de\uff09
	g.block_same_day_rebuy_after_sell = bool(getattr(C, 'block_same_day_rebuy_after_sell', True))
	g.auto_remove_sold_from_watchlist = bool(getattr(C, 'auto_remove_sold_from_watchlist', False))
	g.session_gate_prefer_bar_time = bool(getattr(C, 'session_gate_prefer_bar_time', True))
	# A \u6863\u9996\u4e70\u9ed8\u8ba4 09:25-10:25\uff08\u53ef\u7528 C.a_first_buy_* \u8986\u76d6\uff09
	g.a_first_buy_start_hhmmss = int(getattr(C, 'a_first_buy_start_hhmmss', g.session_gate_start_hhmmss))
	g.a_first_buy_end_hhmmss = int(getattr(C, 'a_first_buy_end_hhmmss', 102559))
	# \u5b9e\u76d8\u4fdd\u7559 is_last_bar \u95e8\u95f2\uff1b\u56de\u6d4b\u82e5\u672a\u8bc6\u522b\u5230 do_back_test\uff0c\u53ef\u5728 QMT \u91cc\u8bbe C.handlebar_each_bar=True \u5f3a\u5236\u6bcf\u6839 K \u6267\u884c
	g.handlebar_each_bar = bool(getattr(C, 'handlebar_each_bar', False))
	g.live_orders = bool(getattr(C, 'live_orders', True))
	g.strategy_order_name = (getattr(C, 'strategy_order_name', None) or '\u81ea\u9009\u5206\u6863').strip()[:20]
	g.quick_trade = int(getattr(C, 'quick_trade', 2))
	g.buy_code = 23 if str(g.account_type).upper() == 'STOCK' else 33
	g.sell_code = 24 if str(g.account_type).upper() == 'STOCK' else 34

	g.use_manual_hold_days_csv = bool(getattr(C, 'use_manual_hold_days_csv', True))
	ctx_hold_csv = getattr(C, 'open_date_csv_path', None) or getattr(C, 'manual_open_date_csv', None)
	picked_csv, csv_how = resolve_manual_hold_open_csv_path(ctx_hold_csv)
	g.open_date_csv_path = str(picked_csv or '').strip()
	g._manual_hold_csv_resolve = csv_how
	g._manual_open_dates = {}
	g._manual_csv_mtime = None
	g._manual_csv_load_err = ''
	g._manual_csv_loaded_trade_day = None
	if g.use_manual_hold_days_csv:
		_manual_hold_csv_reload()

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
	g.pyramid_anchor_day = {}
	g.prev_close_stop_touch_day = {}
	g._day_low_marker = {}
	g._day_low_val = {}
	g._last_handlebar_barpos = None
	g._warned_no_account = False
	g._ma10_signal_latched = False
	g._sse_ma5_gate_latched = False
	g._sse_ma5_gate_frozen_allow = None
	g._trade_day = ''
	g._opc_day = ''
	g._opc_map = {}
	g._tail_last_minute_log = {}
	g._atr_last_minute_log = {}
	g._hold_days_dbg_marker = {}
	# \u6362\u65e5\u5c06\u6628\u65e5\u9996\u4e70\u5019\u9009\u4e14\u672a\u6210\u4ed3\u7684\u7968\u6392\u5230\u672b\u5c3e\uff0c\u6b21\u65e5\u91cd\u65b0\u7b5b\u9009
	g._defer_first_buy_tail = set()
	g._daily_entry_head = None
	g._daily_entry_heads = {}
	g._needs_entry_defer_check = None
	g._sell_order_pending = {}
	g._sell_order_seq = 0
	g._intraday_prev_ref_stop_done = set()
	g._tail_cost_stop_sold = set()
	g._same_day_sold_canon = set()

	print('=' * 60)
	print('%s \u521d\u59cb\u5316 accid=%s \u677f\u5757=%s \u5355\u7968\u9884\u7b97=%.0f MA5\u95e8\u63a7(T-1/\u51bb\u7ed3>=%06d)=%s live_orders=%s quick_trade=%d \u7b56\u7565\u540d=%s'
	      % (STRATEGY_TAG, g.accid, g.watchlist_sector_name, g.per_stock_amount,
	         int(getattr(g, 'sse_ma5_gate_latch_hhmmss', 93000)),
	         getattr(g, 'require_sse_above_ma5_for_new', True), g.live_orders, g.quick_trade, g.strategy_order_name))
	print('manual_hold_days_csv=%s csv=%r resolve=%s rows=%d err=%r env=MANUAL_OPEN_DATE_CSV'
	      % (getattr(g, 'use_manual_hold_days_csv', True), getattr(g, 'open_date_csv_path', ''),
	         getattr(g, '_manual_hold_csv_resolve', ''),
	         len(getattr(g, '_manual_open_dates', {}) or {}), getattr(g, '_manual_csv_load_err', '')))
	print('atr_tp: init_mult=%.2f start_eff@dh1=%.3f half_life=%.1fd mult_clamp=[%.2f,%.2f] lock_days>=%d lock_profit>=%.1f%% lock_ratio=base%.2f+slope%.3f*dh cap%.2f atr_period=%d'
	      % (g.atr_stop_mult_initial, float(getattr(g, '_atr_start_eff', g.atr_stop_mult_initial)), g.atr_stop_half_life_days, g.atr_stop_mult_min, g.atr_stop_mult_max,
	         g.atr_lock_floor_min_days, g.atr_lock_min_profit_dec * 100.0,
	         g.atr_lock_ratio_base, g.atr_lock_ratio_slope, g.atr_lock_ratio_cap, g.atr_period))
	if float(getattr(g, '_atr_start_eff', 2.0)) <= 1.01:
		print('\u26a0\ufe0f ATR: start_eff<=1.01 \u2192 \u65e5\u5fd7\u4e2d m \u5e38\u663e\u793a\u4e3a ~1.0\uff1b\u82e5\u5e0c\u671b\u5bbd\u4e0a\u9650 \u8bf7\u68c0\u67e5 QMT: atr_stop_mult/atr_stop_mult_initial \u4e0d\u8981\u4e3a1\uff0c\u9ed8\u8ba4 mult_clamp \u4e0a\u4e0b\u9650 1~3\uff0c\u534a\u8870\u671f 10d')
	print('\u56de\u6d4b\u4e0d\u4e0b\u5355\uff1b\u5b9e\u76d8 passorder \u4e70=%d \u5356=%d' % (g.buy_code, g.sell_code))
	print('signal_trace_log=%s minute_summary_log=%s position_summary_log=%s sell_monitor_summary_log=%s monitor_account_risk_sells=%s block_same_day_rebuy_after_sell=%s auto_remove_sold_from_watchlist=%s'
	      % (g.signal_trace_log, g.minute_summary_log, g.position_summary_log, g.sell_monitor_summary_log, g.monitor_account_risk_sells, getattr(g, 'block_same_day_rebuy_after_sell', True), getattr(g, 'auto_remove_sold_from_watchlist', False)))
	print('non_atr_sell_start_hhmmss=%d tail_clear_start=%06d tail_below_ma5=%s tail_ma5_period=%d tail_cost_stop_pct=%.4f sell_unfilled=%.0fs max_retry=%s tail_intraday_log=%s atr_intraday_log=%s atr_log_non_wl=%s'
	      % (g.non_atr_sell_start_hhmmss, int(g.tail_clear_start_hhmmss), getattr(g, 'tail_sell_below_ma5', True), int(getattr(g, 'tail_ma5_period', 5)), float(g.tail_cost_stop_pct), float(g.sell_unfilled_timeout_sec),
	         ('\u65e0\u9650' if int(g.sell_unfilled_max_retry) <= 0 else int(g.sell_unfilled_max_retry)),
	         g.tail_intraday_log, g.atr_intraday_log,
	         getattr(g, 'atr_log_account_non_watchlist', True)))
	print('session_gate_start=%06d session_gate_prefer_bar_time=%s gap_bracket_min=%06d A\u6863\u9996\u4e70=%06d-%06d(\u52a0\u4ed3\u817f\u5168\u5929...)'
	      % (int(g.session_gate_start_hhmmss), g.session_gate_prefer_bar_time, int(g.gap_bracket_min_hhmmss),
	         int(g.a_first_buy_start_hhmmss), int(g.a_first_buy_end_hhmmss)))
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


def _held_sim_keys_in_pool(pool):
	"""\u6a21\u62df\u6301\u4ed3\u4e14\u5728\u81ea\u9009\u6c60\u5185\u7684\u4ee3\u7801\u5217\u8868\uff08\u591a\u7968\u91d1\u5b57\u5854\u7528\uff09\u3002"""
	if not pool:
		return []
	pool_set = frozenset((_canonical_stock_code(x) or x) for x in pool)
	out = []
	for k, v in list(g.holding.items()):
		if not v or int(g.buy_shares.get(k, 0) or 0) <= 0:
			continue
		can = _canonical_stock_code(k) or k
		if can in pool_set:
			out.append(k)
	return sorted(out, key=lambda x: (_canonical_stock_code(x) or x))


def _run_pyramid_for_stock(C, stock, dt_full, d_str, hhmmss, tick_map, notional, mos):
	"""\u5355\u7968\u91d1\u5b57\u5854\u52a0\u4ed3\uff08A/B/C\u6863\uff09\u3002"""
	if not _in_session_trade(hhmmss):
		br_ph = g.gap_bracket.get(stock)
		if not (br_ph == 'A' and _a_preopen_for_first_buy(hhmmss)):
			_trace(dt_full, '\u91d1\u5b57\u5854\u8df3\u8fc7(\u975e\u8fde\u7eed\u7adf\u4ef7\u4e14\u975e\u6301A\u96c6\u5408\u672b\u6bb5) stock=%s hhmmss=%s' % (stock, hhmmss))
			return
	bracket = g.gap_bracket.get(stock)
	anchor = g.anchor_buy.get(stock)
	if bracket == 'D' or anchor is None:
		_trace(dt_full, '\u91d1\u5b57\u5854\u8df3\u8fc7 stock=%s \u6863=%s anchor=%s (D\u6863\u6216\u65e0\u951a\u5b9a)' % (stock, bracket, anchor))
		return
	sess = (getattr(g, 'pyramid_anchor_day', None) or {}).get(stock)
	if sess != d_str:
		_trace(dt_full, '\u91d1\u5b57\u5854\u8df3\u8fc7 stock=%s \u52a0\u817f\u4ec5\u5f53\u65e5(\u951a\u65e5=%s \u672c\u65e5=%s)' % (stock, sess, d_str))
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
		o_a = g.open_px.get(stock)
		if o_a is None or o_a <= 0:
			_trace(dt_full, '\u91d1\u5b57\u5854 %s A\u6863\u7f3a\u4eca\u5f00 \u8df3\u8fc7\u52a0\u4ed3\u817f' % stock)
		else:
			if not legs[1] and price_now <= o_a * 0.95:
				if _signal_buy_leg(C, stock, notional * 0.30, price_now, dt_full, d_str, mos,
						   '\u3010A\u6863\u3011\u52a0\u4ed330%%|\u4eca\u5f00x0.95(-5%)', tick_map):
					legs[1] = True
			if not legs[2] and price_now <= o_a * 0.92:
				if _signal_buy_leg(C, stock, notional * 0.20, price_now, dt_full, d_str, mos,
						   '\u3010A\u6863\u3011\u52a0\u4ed320%%|\u4eca\u5f00x0.92(-8%)', tick_map):
					legs[2] = True
	elif bracket == 'B':
		o_b = g.open_px.get(stock)
		if o_b is None or o_b <= 0:
			_trace(dt_full, '\u91d1\u5b57\u5854 %s B\u6863\u7f3a\u4eca\u5f00 \u8df3\u8fc7\u52a0\u4ed3\u817f' % stock)
		else:
			if not legs[1] and price_now <= o_b * 0.95:
				if _signal_buy_leg(C, stock, notional * 0.30, price_now, dt_full, d_str, mos,
						   '\u3010B\u6863\u3011\u52a0\u4ed330%%|\u4eca\u5f00x0.95(-5%)', tick_map):
					legs[1] = True
			if not legs[2] and price_now <= o_b * 0.92:
				if _signal_buy_leg(C, stock, notional * 0.20, price_now, dt_full, d_str, mos,
						   '\u3010B\u6863\u3011\u52a0\u4ed320%%|\u4eca\u5f00x0.92(-8%)', tick_map):
					legs[2] = True
	elif bracket == 'C':
		o_c = g.open_px.get(stock)
		if o_c is None or o_c <= 0:
			_trace(dt_full, '\u91d1\u5b57\u5854 %s C\u6863\u7f3a\u4eca\u5f00 \u8df3\u8fc7\u52a0\u4ed3\u817f' % stock)
		else:
			if not legs[1] and price_now <= o_c * 0.91:
				if _signal_buy_leg(C, stock, notional * 0.30, price_now, dt_full, d_str, mos,
						   '\u3010C\u6863\u3011\u52a0\u4ed330%%|\u4eca\u5f00x0.91(-9%)', tick_map):
					legs[1] = True
			if not legs[2] and price_now <= o_c * 0.88:
				if _signal_buy_leg(C, stock, notional * 0.20, price_now, dt_full, d_str, mos,
						   '\u3010C\u6863\u3011\u52a0\u4ed320%%|\u4eca\u5f00x0.88(-12%)', tick_map):
					legs[2] = True
	g.leg_done[stock] = legs


def _try_first_buy_watchlist_stock(C, stock, dt_full, d_str, hhmmss, tick_map, notional, mos):
	"""\u5355\u7968\u9996\u4e70\u9996\u817f\uff1b\u6210\u529f\u5219 True\u3002"""
	can0 = _canonical_stock_code(stock) or stock
	if bool(getattr(g, 'block_same_day_rebuy_after_sell', True)) and can0 in getattr(g, '_same_day_sold_canon', set()):
		_trace(dt_full, '\u5f53\u65e5\u5df2\u7b56\u7565\u5356\u51fa\u7981\u518d\u9996\u4e70 stock=%s' % stock)
		return False
	if not hasattr(g, '_daily_entry_heads'):
		g._daily_entry_heads = {}
	g._daily_entry_heads[can0] = d_str
	o_today, prev_c = _opc_get(C, stock, dt_full, d_str, hhmmss)
	if o_today is None:
		_trace(dt_full, '\u65e5\u7ebf\u7f3a\u5931\u8d25 %s \u4eca\u5f00/\u6628\u6536' % stock)
		return False
	gap = o_today / prev_c - 1.0
	br = _gap_bracket(gap)
	g.open_px[stock] = o_today
	g.prev_close_ref[stock] = prev_c
	g.gap_bracket[stock] = br
	if _a_preopen_for_first_buy(hhmmss) and (not _in_session_trade(hhmmss)) and br != 'A':
		_trace(dt_full, '\u96c6\u5408\u7ade\u4ef7\u672b\u6bb5\u4ec5A\u6863\u9996\u4e70 stock=%s \u6863=%s \u8df3\u8fc7' % (stock, br))
		return False
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
		return False
	legs = [False, False, False]
	if br == 'D':
		sh_t = _shares_for_cash(notional * 0.50, price_now, mos)
		_trace(dt_full, 'D\u6863\u9996\u4e7050%% stock=%s \u4ef7=%.3f \u8ba1\u7b97\u80a1\u6570=%d(\u9700>=%d\u624d\u53d1\u4fe1\u53f7)' % (stock, price_now, sh_t, mos))
		if _signal_buy_leg(C, stock, notional * 0.50, price_now, dt_full, d_str, mos,
				   '\u3010D\u6863\u3011\u9996\u4e7050%%\u5355\u7b14\u65e0\u52a0\u4ed3', tick_map):
			legs[0] = True
			g.anchor_buy[stock] = price_now
			g.leg_done[stock] = legs
			g.pyramid_anchor_day[stock] = d_str
			return True
		return False
	if br == 'A':
		a0, a1 = int(getattr(g, 'a_first_buy_start_hhmmss', 92500)), int(getattr(g, 'a_first_buy_end_hhmmss', 102559))
		if not _a_first_buy_window_ok(hhmmss):
			_trace(dt_full, 'A\u6863\u9996\u4e70\u9700 %06d-%06d stock=%s hhmmss=%s' % (a0, a1, stock, hhmmss))
			return False
		sh_t = _shares_for_cash(notional * 0.50, price_now, mos)
		_trace(dt_full, 'A\u6863\u9996\u4e7050%% stock=%s \u7a97\u53e3%06d-%06d hhmmss=%s \u4ef7=%.3f \u8ba1\u7b97\u80a1=%d' % (stock, a0, a1, hhmmss, price_now, sh_t))
		tag_a = '\u3010A\u6863\u3011\u9996\u4e7050%%|%06d-%06d' % (a0, a1)
		if _signal_buy_leg(C, stock, notional * 0.50, price_now, dt_full, d_str, mos,
				   tag_a, tick_map):
			legs[0] = True
			g.anchor_buy[stock] = price_now
			g.leg_done[stock] = legs
			g.pyramid_anchor_day[stock] = d_str
			return True
		want_po = _should_passorder(C)
		_trace(dt_full, 'A\u6863\u9996\u4e70\u672a\u6210\u4ea4 stock=%s sh_t=%d mos=%d \u9700passorder=%s'
		      % (stock, sh_t, mos, want_po))
		return False
	if br == 'B':
		thr_b = g.open_px[stock] * 0.97
		if price_now > thr_b:
			_trace(dt_full, 'B\u6863\u672a\u8fbe stock=%s \u9608\u503c<=%.3f \u73b0%.3f' % (stock, thr_b, price_now))
			return False
		_trace(dt_full, 'B\u6863\u89e6\u53d1\u9996\u4e70 stock=%s \u4ef7=%.3f' % (stock, price_now))
		if _signal_buy_leg(C, stock, notional * 0.50, price_now, dt_full, d_str, mos,
				   '\u3010B\u6863\u3011\u9996\u4e7050%%|\u4eca\u5f00x0.97', tick_map):
			legs[0] = True
			g.anchor_buy[stock] = price_now
			g.leg_done[stock] = legs
			g.pyramid_anchor_day[stock] = d_str
			return True
		return False
	if br == 'C':
		thr_c = g.open_px[stock] * 0.96
		if price_now > thr_c:
			_trace(dt_full, 'C\u6863\u672a\u8fbe stock=%s \u9608\u503c<=%.3f \u73b0%.3f' % (stock, thr_c, price_now))
			return False
		_trace(dt_full, 'C\u6863\u89e6\u53d1\u9996\u4e70 stock=%s \u4ef7=%.3f' % (stock, price_now))
		if _signal_buy_leg(C, stock, notional * 0.50, price_now, dt_full, d_str, mos,
				   '\u3010C\u6863\u3011\u9996\u4e7050%%|\u4eca\u5f00x0.96', tick_map):
			legs[0] = True
			g.anchor_buy[stock] = price_now
			g.leg_done[stock] = legs
			g.pyramid_anchor_day[stock] = d_str
			return True
		return False
	return False


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
		ret = po(
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
	# QMT \u6709\u65f6\u62d2\u5355\u4e0d\u629b\u5f02\u5e38\u800c\u8fd4\u56de False\uff08\u5982 T+1 \u4e0d\u53ef\u5356\u3001\u53ef\u5356\u91cf\u4e0d\u8db3\u7b49\uff09
	if ret is False:
		print('%s passorder \u62d2\u5355/ret=False op=%s %s vol=%d remark=%r \u53ef\u80fdT+1\u4e0d\u53ef\u5356/\u9650\u5236/\u8d44\u91d1'
		      % (STRATEGY_TAG, op_code, stock, vol, note))
		return False
	return True


def _signal_buy_leg(C, stock, cash_yuan, price_now, dt_full, d_str, mos, tag, tick_map):
	can = _canonical_stock_code(stock) or stock
	if bool(getattr(g, 'block_same_day_rebuy_after_sell', True)) and can in getattr(g, '_same_day_sold_canon', set()):
		_trace(dt_full, '当日已卖不再买入 stock=%s tag=%s' % (stock, tag))
		_mr_set('当日已卖不回补 %s' % stock, 0, price_now)
		return False
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
	if getattr(g, '_defer_first_buy_tail', None):
		g._defer_first_buy_tail.discard(_canonical_stock_code(stock) or stock)
	return True


def _compact_sell_order_remark(stock):
	g._sell_order_seq = int(getattr(g, '_sell_order_seq', 0)) + 1
	s = (_canonical_stock_code(stock) or stock).replace('.', '')
	sfx = s[-12:] if len(s) > 12 else s
	return ('SL%d_%s' % (g._sell_order_seq % 1000000, sfx))[:36]


def _stock_has_pending_sell(stock):
	pd = getattr(g, '_sell_order_pending', None)
	if not pd:
		return False
	can = _canonical_stock_code(stock) or stock
	for v in pd.values():
		st0 = v.get('stock')
		sc = _canonical_stock_code(st0) or st0
		if sc == can:
			return True
	return False


def _sell_refresh_shares(stock, mos):
	tot_vol, _ = _position_volume_and_avg(stock)
	if tot_vol and int(tot_vol) > 0:
		sh = (int(tot_vol) // mos) * mos
		return sh if sh >= mos else 0
	if g.holding.get(stock):
		sv = int(g.buy_shares.get(stock, 0) or 0)
		sh = (sv // mos) * mos
		return sh if sh >= mos else 0
	return 0


def _fmt_sell_rule(rule_bucket, rule_key, detail=''):
	"""\u7edf\u4e00\u5356\u51fa\u539f\u56e0\uff08\u4f9b [SELL]/[ORDER]/[SELL-OK] \u4e0e\u59d4\u6258\u5907\u6ce8\u8bfb\u53d6\uff09\u3002
	rule_bucket: \u6307\u6570 / \u98ce\u63a7 / \u5c3e\u76d8 / \u6b62\u76c8
	rule_key: \u77ed\u6807\u7b7e\uff1a\u4e0a\u8bc1MA10\u3001\u786c\u6b62\u635f\u3001\u6628\u6536\u6b62\u635f\u3001ATR\u540a\u706f\u3001\u5c3e\u76d8\u6210\u672c\u3001\u7834\u5747\u7ebf\u7b49"""
	b = (rule_bucket or '').strip() or '\u5176\u4ed6'
	k = (rule_key or '').strip() or '\u672a\u77e5'
	d = str(detail).strip() if detail is not None else ''
	if '|' in d:
		d = d.replace('|', ';')
	out = '\u89c4\u5219\u7c7b=%s|\u89c4\u5219\u9879=%s' % (b, k)
	if d:
		out += '|\u8be6\u60c5=%s' % d
	return out


def _sell_rule_parts(reason):
	"""\u4ece _fmt_sell_rule \u5b57\u7b26\u4e32\u89e3\u6790\u4e09\u5217\uff1b\u65e7\u683c\u5f0f\u65e0\u7ba1\u9053\u65f6\u5168\u90e8\u653e\u5165\u8be6\u60c5\u3002"""
	s = str(reason or '').strip()
	rb = rk = det = ''
	for part in s.split('|'):
		if '=' not in part:
			continue
		k, v = part.split('=', 1)
		k = k.strip()
		v = v.strip()
		if k == '\u89c4\u5219\u7c7b':
			rb = v
		elif k == '\u89c4\u5219\u9879':
			rk = v
		elif k == '\u8be6\u60c5':
			det = v
	if not rb and not rk and not det and s:
		det = s
	return rb, rk, det


def _emit_sell_fill_success(C, dt_full, stock, vol, px, avg_c, reason):
	try:
		v = int(vol)
	except Exception:
		v = 0
	try:
		p = float(px)
	except Exception:
		p = 0.0
	ac = float(avg_c) if avg_c is not None and float(avg_c) > 0 else None
	pnl_pct = (p / ac - 1.0) * 100.0 if ac and ac > 0 else None
	amt = float(v) * p
	ps = ('%.2f%%' % pnl_pct) if pnl_pct is not None else '--'
	ac_s = ('%.3f' % ac) if ac is not None else '--'
	rb, rk, det = _sell_rule_parts(reason)
	print('[SELL-OK] \u65f6\u95f4=%s|\u4ee3\u7801=%s|\u6210\u4ea4\u4ef7=%.3f|\u6210\u4ea4\u80a1\u6570=%d|\u6301\u4ed3\u6210\u672c=%s|\u76c8\u4e8f\u6bd4=%s|\u6210\u4ea4\u91d1\u989d\u2248%.0f|\u89c4\u5219\u7c7b=%s|\u89c4\u5219\u9879=%s|\u8be6\u60c5=%s'
	      % (dt_full, stock, p, v, ac_s, ps, amt, rb or '--', rk or '--', (det or '--')[:100]))
	try:
		_try_remove_sold_stock_from_watchlist_sector(C, stock)
	except Exception as e:
		print('%s [\u81ea\u9009\u79fb\u9664\u5f02\u5e38] %s %r' % (STRATEGY_TAG, stock, e))


def _auction_cancel_block_wall(wall_int):
	try:
		w = int(wall_int)
	except Exception:
		return False
	return 92000 <= w <= 92559


def _process_sell_unfilled_cancel_retry(C, dt_full, d_str, hhmmss, tick_map, wall_now_int):
	pending = getattr(g, '_sell_order_pending', None)
	if not pending:
		return
	if not _should_passorder(C) or not (g.accid or '').strip():
		return
	_gtd = _get_trade_detail_data_fn()
	if not _gtd:
		return
	mos = int(g.min_order_shares)
	timeout = float(getattr(g, 'sell_unfilled_timeout_sec', 60))
	ORDER_DONE = 56
	ORDER_CANCEL_STATES = (53, 54, 57)
	now_ts = time.time()
	try:
		orders = _gtd(g.accid, _account_type(), 'order') or []
	except Exception:
		orders = []
	try:
		deals = _gtd(g.accid, _account_type(), 'deal') or []
	except Exception:
		deals = []
	cancel_fn = _cancel_fn()

	def _repost_sell_after_fail(st, pinfo):
		"""卖单未成后的统一重挂：持续重试直到成交或无可卖股数。"""
		sh_new = _sell_refresh_shares(st, mos)
		if sh_new < mos:
			print('%s [卖重挂]无可卖数 %s' % (dt_full, st))
			return
		new_r = _compact_sell_order_remark(st)
		cur_px = float(pinfo.get('px_quote', 0) or 0)
		try:
			cur = _get_current_price(C, st, dt_full, cur_px if cur_px > 0 else None, tick_map)
			if cur is not None and float(cur) > 0:
				cur_px = float(cur)
		except Exception:
			pass
		if not _passorder_go(C, g.sell_code, st, sh_new, new_r):
			print('%s [卖重挂]passorder失败 %s' % (dt_full, st))
			return
		pending[new_r] = {
			't': time.time(),
			'stock': st,
			'sh': sh_new,
			'px_quote': cur_px,
			'reason': pinfo.get('reason', ''),
			'avg_c': pinfo.get('avg_c'),
			'retry': int(pinfo.get('retry', 0)) + 1,
		}
		print('%s [ORDER][卖重挂] %s %d股 retry=%d' % (dt_full, st, sh_new, pending[new_r]['retry']))

	for remark in list(pending.keys()):
		pinfo = pending.get(remark)
		if not pinfo:
			continue
		st = pinfo['stock']
		got_deal = False
		for d in deals:
			if (getattr(d, 'm_strRemark', '') or '') != remark:
				continue
			try:
				vol_d = int(getattr(d, 'm_nVolume', 0) or 0)
			except Exception:
				vol_d = 0
			if vol_d <= 0:
				continue
			px_d = float(getattr(d, 'm_dPrice', 0) or getattr(d, 'm_dTradePrice', 0) or 0)
			if px_d <= 0:
				px_d = float(pinfo.get('px_quote', 0) or 0)
			_emit_sell_fill_success(C, dt_full, st, vol_d, px_d, pinfo.get('avg_c'), pinfo.get('reason', ''))
			pending.pop(remark, None)
			if g.holding.get(st):
				_clear_sim_stock(st)
			got_deal = True
			break
		if got_deal:
			continue

		om = None
		for o in orders:
			if (getattr(o, 'm_strRemark', '') or '') == remark:
				om = o
				break
		if om:
			st_ord = int(getattr(om, 'm_nOrderStatus', 0) or 0)
			if st_ord in ORDER_CANCEL_STATES:
				pending.pop(remark, None)
				_repost_sell_after_fail(st, pinfo)
				continue
			if st_ord == ORDER_DONE:
				try:
					sh_f = int(getattr(om, 'm_nVolumeTotalOriginal', 0) or pinfo.get('sh', 0) or 0)
				except Exception:
					sh_f = int(pinfo.get('sh', 0) or 0)
				px_f = float(getattr(om, 'm_dLimitPrice', 0) or getattr(om, 'm_dPrice', 0) or 0)
				if px_f <= 0:
					px_f = float(pinfo.get('px_quote', 0) or 0)
				_emit_sell_fill_success(C, dt_full, st, sh_f, px_f, pinfo.get('avg_c'), pinfo.get('reason', ''))
				pending.pop(remark, None)
				if g.holding.get(st):
					_clear_sim_stock(st)
				continue

		elapsed = now_ts - float(pinfo.get('t', 0))
		if elapsed < timeout:
			continue
		if not om:
			if elapsed > timeout * 3:
				print('%s [\u5356\u5355\u8ddf\u8e2a]\u59d4\u6258\u672a\u540c\u6b65\u8d85\u65f6\uff0c\u76f4\u63a5\u91cd\u6302 %s' % (dt_full, st))
				pending.pop(remark, None)
				_repost_sell_after_fail(st, pinfo)
			continue
		if _auction_cancel_block_wall(wall_now_int):
			continue
		oid = getattr(om, 'm_strOrderSysID', '') or ''
		if not oid or cancel_fn is None:
			continue
		try:
			cancel_fn(oid, g.accid, _account_type(), C)
		except Exception as e:
			print('%s [\u5356\u5355\u64a4\u5355\u5931\u8d25] %s %r' % (STRATEGY_TAG, oid, e))
			continue
		pending.pop(remark, None)
		_repost_sell_after_fail(st, pinfo)


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
	rb, rk, det = _sell_rule_parts(reason)
	print('[SELL] \u65f6\u95f4=%s|\u4ee3\u7801=%s|\u5356\u51fa\u6570=%d|\u5356\u524d\u6301\u4ed3=%d|\u6210\u672c=%s|\u73b0\u4ef7=%.3f|\u6301\u4ed3\u76c8\u4e8f=%s|\u81ea\u9009=%s|\u8bb0\u8d26=%s|\u89c4\u5219\u7c7b=%s|\u89c4\u5219\u9879=%s|\u8be6\u60c5=%s'
	      % (dt_full, stock, sh, tot_s, avg_s, float(cur_px), pnl_s, wl_tag, ledger, rb or '--', rk or '--', (det or '--')[:160]))
	live = _should_passorder(C)
	remark = _compact_sell_order_remark(stock) if live else str(reason or '')[:36].replace('|', '_')
	placed = False
	if live:
		placed = _passorder_go(C, g.sell_code, stock, sh, remark)
		if not placed:
			print('%s \u5355\u8fb9\u5931\u8d25 %s |\u89c4\u5219\u9879=%s|\u8be6\u60c5=%s' % (dt_full, stock, rk or '--', (det or str(reason))[:120]))
			return False
		g._sell_order_pending[remark] = {
			't': time.time(),
			'stock': stock,
			'sh': sh,
			'px_quote': float(cur_px),
			'reason': str(reason or '')[:120],
			'avg_c': avg_c,
			'retry': 0,
		}
	_mr_set('\u4fe1\u53f7\u5356 %s' % reason, sh, px)
	g._mr_trade_stock = stock
	mark = '[ORDER]' if (live and placed) else '[SIGNAL]'
	print('%s %s[\u5356] %s %d\u80a1 px=%.3f |\u89c4\u5219\u7c7b=%s|\u89c4\u5219\u9879=%s|\u8be6\u60c5=%s'
	      % (dt_full, mark, stock, sh, px, rb or '--', rk or '--', (det or '--')[:120]))
	return True


def _signal_sell_sim(C, stock, reason, dt_full, sh, px, tick_map=None):
	if _should_passorder(C) and _stock_has_pending_sell(stock):
		return False
	if not _print_sell_signal(C, dt_full, stock, sh, px, reason, tick_map):
		return False
	if not _should_passorder(C):
		if g.holding.get(stock):
			_clear_sim_stock(stock)
	if bool(getattr(g, 'block_same_day_rebuy_after_sell', True)):
		if not hasattr(g, '_same_day_sold_canon'):
			g._same_day_sold_canon = set()
		g._same_day_sold_canon.add(_canonical_stock_code(stock) or stock)
	return True


def _in_session_trade(hms):
	if hms is None:
		return False
	if 93000 <= hms <= 113000:
		return True
	if 130000 <= hms <= 150000:
		return True
	return False


def _a_preopen_for_first_buy(hhmmss):
	"""A \u9996\u4e70\u8d77\u70b9 < 93000 \u65f6\uff1a9:25\u20149:30 \u672b\u53ef\u8d70\u9996\u4e70/\u6301\u4ed3 A \u91d1\u5b57\u5854\uff08\u4e0e _session_gate_pass \u4e0b\u9650\u5bf9\u9f50\uff09\u3002"""
	if hhmmss is None:
		return False
	try:
		h = int(hhmmss)
	except Exception:
		return False
	a0 = int(getattr(g, 'a_first_buy_start_hhmmss', 92500))
	if a0 >= 93000:
		return False
	return a0 <= h < 93000


def _a_first_buy_window_ok(hhmmss):
	"""A \u6863\u9996\u4e70\u5fc5\u987b\u843d\u5728\u6b64\u7a97\u53e3\uff1b\u52a0\u4ed3\u817f\u4e0d\u9650\u6b64\u7a97\u53e3\u3002"""
	if hhmmss is None:
		return False
	a0 = int(getattr(g, 'a_first_buy_start_hhmmss', 92500))
	a1 = int(getattr(g, 'a_first_buy_end_hhmmss', 102559))
	try:
		h = int(hhmmss)
	except Exception:
		return False
	return a0 <= h <= a1


def _fmt_hhmmss_colon(hms):
	hms = int(hms)
	return '%02d:%02d:%02d' % (hms // 10000, (hms // 100) % 100, hms % 100)


def _non_atr_sell_time_ok(hhmmss):
	"""\u975e ATR \u5356\u51fa\uff08\u5982\u4e0a\u8bc1MA10\u6e05\u4ed3\uff09\uff1a\u4ec5\u5728 non_atr_sell_start_hhmmss \u4e4b\u540e\u8bc4\u4f30\u3002\u5c3e\u76d8\u6210\u672c\u6b62\u635f\u5355\u72ec\u7528 tail_clear_start_hhmmss\u3002"""
	if hhmmss is None:
		return False
	return hhmmss >= int(getattr(g, 'non_atr_sell_start_hhmmss', 145400))


def _fmt_non_atr_sell_start():
	t = int(getattr(g, 'non_atr_sell_start_hhmmss', 145400))
	s = '%06d' % t
	return '%s:%s' % (s[:2], s[2:4])


def _stock_ma_tail_live(C, stock, dt_full, d_str, px_live, period):
	"""\u76d8\u4e2d\u4f30\u8ba1\u7684\u65e5\u7ebf MA(\u5468\u671f)\uff1a\u6700\u8fd1 period \u4e2a\u4ea4\u6613\u65e5\u6536\u76d8\u5747\u503c\uff1b\u672b\u6839\u4e3a\u5f53\u65e5\u5219\u7528 px \u66ff\u6362\u8be5\u6839\u6536\u76d8\uff1b\u82e5\u65e5\u7ebf\u672a\u66f4\u65b0\u5230\u4eca\u65e5\u5219\u7528\u8fd1 period-1 \u65e5\u6536\u76d8 + px\u3002"""
	try:
		px = float(px_live)
		if px <= 0:
			return None
	except (TypeError, ValueError):
		return None
	p = max(2, int(period))
	cnt = max(p + 5, int(getattr(g, 'bar_count', 80)))
	try:
		data_d = C.get_market_data_ex(
			['close', 'high', 'low'], [stock],
			end_time=dt_full, period='1d', count=cnt, subscribe=False
		)
		if stock not in data_d:
			return None
		highs = _ohlc_to_list(data_d[stock].get('high'))
		lows = _ohlc_to_list(data_d[stock].get('low'))
		closes = _ohlc_to_list(data_d[stock].get('close'))
		if not highs or not lows or not closes:
			return None
		n = min(len(highs), len(lows), len(closes))
		highs, lows, closes = highs[:n], lows[:n], closes[:n]
		tags = _ohlc_time_list(data_d, stock)
		last_d = None
		if tags and len(tags) >= n:
			pairs = []
			for i in range(n):
				td = _tag_to_yyyymmdd(tags[i])
				if td:
					try:
						pairs.append((int(td), i))
					except Exception:
						pass
			if len(pairs) >= n:
				pairs.sort(key=lambda x: x[0])
				last_i = pairs[-1][1]
				last_d = _tag_to_yyyymmdd(tags[last_i])
		highs, lows, closes = _align_daily_ohlc_chronological(data_d, stock, highs, lows, closes, ref_px=px)
	except Exception:
		return None
	if len(closes) < p:
		return None
	ds = (d_str or '').strip()
	if last_d == ds or last_d is None:
		w = list(closes[-p:])
		w[-1] = px
	else:
		if len(closes) < p - 1:
			return None
		w = list(closes[-(p - 1):]) + [px]
	try:
		return sum(float(x) for x in w) / float(len(w))
	except Exception:
		return None


def _run_tail_watchlist_cost_stop(C, dt_full, d_str, hhmmss, tick_map, mos):
	"""\u5c3e\u76d8\uff08>=tail_clear_start\uff09\uff1a(1)\u73b0\u4ef7/\u6210\u672c-1<=tail_cost_stop_pct\u5356\uff1b(2)\u82e5\u5f00\u542f tail_sell_below_ma5 \u4e14\u73b0\u4ef7<\u5f53\u524d\u65e5\u7ebfMA5\u4f30\u8ba1\u503c\u5219\u5356\u3002\u4e0e\u6628\u6536\u65e0\u5173\u3002"""
	if not _in_session_trade(hhmmss):
		return
	if hhmmss is None:
		return
	try:
		h = int(hhmmss)
	except (TypeError, ValueError):
		return
	if h < int(getattr(g, 'tail_clear_start_hhmmss', 145000)):
		return
	wl = getattr(g, '_mon_pool_codes', frozenset())
	if not wl:
		return
	thr = float(getattr(g, 'tail_cost_stop_pct', getattr(g, 'hard_stop_pct', -0.08)))
	acc_lp_map = _account_last_price_map(C)
	for st0 in sorted(wl):
		st = _canonical_stock_code(st0) or st0
		can_k = (st, d_str)
		if can_k in getattr(g, '_tail_cost_stop_sold', set()):
			continue
		try:
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
					avg_c = float(acc_a) if (acc_a is not None and float(acc_a) > 0) else None
			elif has_sim:
				sh_raw = sim_v
				avg_c = _avg_cost(st)
			else:
				continue
			sh = (int(sh_raw) // mos) * mos
			if sh < mos:
				continue
			if avg_c is None or float(avg_c) <= 0:
				_, ac2 = _position_volume_and_avg(st)
				if ac2 is not None and float(ac2) > 0:
					avg_c = float(ac2)
			if avg_c is None or float(avg_c) <= 0:
				continue
			alp = acc_lp_map.get(st) if acc_lp_map else None
			try:
				alp_ok = alp is not None and float(alp) > 0
			except (TypeError, ValueError):
				alp_ok = False
			px_live = _get_current_price(C, st, dt_full, None, tick_map, account_last=float(alp) if alp_ok else None)
			if px_live is None or float(px_live) <= 0:
				continue
			# \u5c3e\u76d8\u6301\u4ed3\u76c8\u4e8f\uff1a\u73b0\u4ef7/\u6210\u672c-1 <= thr\uff08\u9ed8\u8ba4-8%\uff09\uff1b\u4e0e\u6628\u6536\u65e0\u5173\u3002
			px_mx = _live_px_max_for_atr(
				C, st, dt_full, tick_map, float(px_live), account_last=float(alp) if alp_ok else None)
			px = float(px_mx) if (px_mx is not None and float(px_mx) > 0) else float(px_live)
			reason = None
			if float(px_live) / float(avg_c) - 1.0 <= thr:
				reason = _fmt_sell_rule('\u5c3e\u76d8', '\u6210\u672c\u6b62\u635f', '\u76c8\u4e8f\u2264%.1f%%(\u76f8\u5bf9\u6210\u672c,\u95e8\u63a7>=tail_clear)' % (thr * 100.0))
			elif bool(getattr(g, 'tail_sell_below_ma5', True)):
				mp = int(getattr(g, 'tail_ma5_period', 5))
				ma_line = _stock_ma_tail_live(C, st, dt_full, d_str, float(px_live), mp)
				if ma_line is not None and float(ma_line) > 0 and float(px_live) < float(ma_line):
					reason = _fmt_sell_rule('\u5c3e\u76d8', '\u7834\u5747\u7ebfMA%d' % mp, '\u73b0=%.3f MA=%.3f(\u4ef7<\u5747\u7ebf)' % (float(px_live), float(ma_line)))
			if reason is None:
				continue
			if _signal_sell_sim(C, st, reason, dt_full, sh, px, tick_map):
				if not hasattr(g, '_tail_cost_stop_sold'):
					g._tail_cost_stop_sold = set()
				g._tail_cost_stop_sold.add(can_k)
		except Exception as e:
			print('%s [\u5c3e\u76d8\u6210\u672c\u6b62\u635f\u5f02\u5e38] %s %s' % (dt_full, st, e))


def _live_bar_before_calendar_today(d_str, C):
	"""\u5b9e\u76d8\u4e14\u5f53\u524d K \u7684\u4ea4\u6613\u65e5\u65e9\u4e8e\u672c\u673a\u65e5\u5386\u201c\u4eca\u5929\u201d\u65f6\u4e3a True\uff08\u5982\u76d8\u524d\u4ecd\u5728\u6628\u65e5\u6536\u76d8 1m\uff09\u3002\u56de\u6d4b\u59cb\u7ec8 False\u3002"""
	if not d_str or C is None:
		return False
	if _is_qmt_backtest_context(C):
		return False
	try:
		if len(d_str) != 8 or not d_str.isdigit():
			return False
		today = datetime.datetime.now().strftime('%Y%m%d')
		return int(d_str) < int(today)
	except Exception:
		return False


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


def _session_gate_pass(C, hhmmss, d_str=None):
	"""\u7c97\u7565\u95e8\u63a7\uff1a\u5b9e\u76d8\u8981\u6c42 K \u7ebf\u65e5\u671f\u4e3a\u201c\u4eca\u5929\u201d\uff0c\u4e14\u65f6\u523b\u5728 session_gate_start~15:00\u3002
	\u907f\u514d\u76d8\u524d\u4ecd\u5360\u7528\u6628\u65e5\u6536\u76d8 1m\uff08hhmmss=150000\uff09\u65f6\u88ab\u8bef\u5224\u4e3a\u201c\u4e0b\u5348\u5e02\u573a\u201d\u800c\u8d70\u5206\u6863/\u9996\u4e70\u903b\u8f91\u3002"""
	if d_str and _live_bar_before_calendar_today(d_str, C):
		return False
	try:
		wall_hms = int(datetime.datetime.now().strftime('%H%M%S'))
	except Exception:
		wall_hms = None
	prefer_bar = bool(getattr(g, 'session_gate_prefer_bar_time', True))
	gate = hhmmss if (prefer_bar and hhmmss is not None) else wall_hms
	if gate is None:
		return True
	try:
		gi = int(gate)
	except Exception:
		return True
	g0 = int(getattr(g, 'session_gate_start_hhmmss', 92500))
	return g0 <= gi <= 150000


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

	if not _session_gate_pass(C, hhmmss, d_str):
		if getattr(g, 'signal_trace_log', True):
			try:
				wi = int(now_time)
			except Exception:
				wi = None
			gate_used = hhmmss if (bool(getattr(g, 'session_gate_prefer_bar_time', True)) and hhmmss is not None) else wi
			stale = _live_bar_before_calendar_today(d_str, C)
			print('[TRACE] \u5e02\u533a\u95e8\u63a7\u672a\u901a\u8fc7 now_wall=%s bar_hhmmss=%s gate_used=%s bar\u65e5=%s stale_hist_bar=%s\u3002'
			      '%s'
			      % (now_time, hhmmss, gate_used, dt_full, stale,
			         '' if stale else '\u591c\u95f4\u56de\u653e\u8bf7\u4fdd\u7559 session_gate_prefer_bar_time=True(\u9ed8\u8ba4)\u6216\u68c0\u67e5K\u7ebf\u65f6\u95f4\u3002'))
		_mr_set('\u975e\u4ea4\u6613\u65f6\u6bb5(\u5899\u949f%s/bar%s)' % (now_time, hhmmss if hhmmss is not None else '-'))
		try:
			pool_early = _pool_from_sector(C)
			g._mon_pool_codes = frozenset((_canonical_stock_code(x) or x) for x in pool_early)
			pos_early = _position_codes_from_account()
		except Exception as e:
			print('%s [gate-early] pool/pos %r' % (STRATEGY_TAG, e))
			pool_early = []
			g._mon_pool_codes = frozenset()
			pos_early = set()
		try:
			_emit_minute_summary(C, dt_full, d_str, hhmmss, tick_map, pool_early, None, set(), True, _account_last_price_map(C))
		except Exception as e:
			print('%s [emit MIN gate] %r' % (STRATEGY_TAG, e))
		try:
			_emit_monitor_unified_summary(dt_full, pos_early, g._mon_pool_codes)
		except Exception as e:
			print('%s [emit MON gate] %r' % (STRATEGY_TAG, e))
		try:
			_emit_position_holdings(C, dt_full, d_str, tick_map)
		except Exception as e:
			print('%s [emit POS gate] %r' % (STRATEGY_TAG, e))
		return

	pos_codes = set()
	already = set()
	index_allow_new = True
	index_liquidate_all = False

	if getattr(g, '_trade_day', '') != d_str:
		prev_td = getattr(g, '_trade_day', '') or ''
		if prev_td:
			g._needs_entry_defer_check = prev_td
		try:
			_reset_pyramid_session_on_roll_day()
		except Exception as e:
			print('%s [roll_day] %r' % (STRATEGY_TAG, e))
		g._trade_day = d_str
		g._ma10_signal_latched = False
		g._sse_ma5_gate_latched = False
		g._sse_ma5_gate_frozen_allow = None
		g._tail_last_minute_log = {}
		g._atr_last_minute_log = {}
		g._hold_days_dbg_marker = {}
		g._intraday_prev_ref_stop_done = set()
		g._tail_cost_stop_sold = set()
		g._same_day_sold_canon = set()

	if not g.accid:
		if not g._warned_no_account:
			g._warned_no_account = True
			print('%s \u8b66\u544a: accid \u4e3a\u7a7a' % STRATEGY_TAG)

	try:
		pos_codes = _position_codes_from_account()
	except Exception as e:
		print('%s [pos_codes] %r' % (STRATEGY_TAG, e))
		pos_codes = set()
	pending_defer = getattr(g, '_needs_entry_defer_check', None)
	if pending_defer:
		try:
			_finish_daily_entry_defer(pending_defer, pos_codes)
		except Exception as e:
			print('%s [entry_defer] %r' % (STRATEGY_TAG, e))
		g._needs_entry_defer_check = None
	try:
		pool = _pool_from_sector(C)
	except Exception as e:
		print('%s [pool] %r' % (STRATEGY_TAG, e))
		pool = []
	g._mon_pool_codes = frozenset((_canonical_stock_code(x) or x) for x in pool)
	if not hasattr(g, '_day_low_marker'):
		g._day_low_marker = {}
	if not hasattr(g, '_day_low_val'):
		g._day_low_val = {}

	try:
		sim_keys = _sim_hold_keys()
	except Exception as e:
		print('%s [sim_keys] %r' % (STRATEGY_TAG, e))
		sim_keys = set()
	already = pos_codes | sim_keys
	if getattr(g, '_defer_first_buy_tail', None):
		for ac in list(already):
			g._defer_first_buy_tail.discard(_canonical_stock_code(ac) or ac)

	mos = int(g.min_order_shares)
	notional = float(g.per_stock_amount)

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

	try:
		wall_now = int(now_time)
	except Exception:
		wall_now = 0
	try:
		_process_sell_unfilled_cancel_retry(C, dt_full, d_str, hhmmss, tick_map, wall_now)
	except Exception as e:
		print('%s [sell_unfilled_retry] %r' % (STRATEGY_TAG, e))

	try:
		idx_close, idx_ma5, idx_ma10, index_allow_new, index_liquidate_all = _sse_ma_state(C, dt_full, d_str, hhmmss)
	except Exception as e:
		print('%s [sse_ma_state] %r' % (STRATEGY_TAG, e))
		idx_close = idx_ma5 = idx_ma10 = None
		index_allow_new = True
		index_liquidate_all = False
	if not bool(getattr(g, 'require_sse_above_ma5_for_new', True)):
		index_allow_new = True
	if _vb() and idx_close is not None:
		print('%s \u4e0a\u8bc1 T-1\u6536=%.2f T-1MA5=%.2f MA10=%.2f \u5f00\u65b0\u95e8\u63a7=%s \u6e05\u5168MA10=%s'
		      % (d_str, idx_close, idx_ma5 or 0, idx_ma10 or 0, index_allow_new, index_liquidate_all))

	try:
		ph0 = _primary_holding_stock()
	except Exception as e:
		print('%s [primary_hold] %r' % (STRATEGY_TAG, e))
		ph0 = None
	g._mr_focus = ph0 or (pool[0] if pool else None)
	in_sess = _in_session_trade(hhmmss) if hhmmss is not None else False
	pool_head = (pool[0] if pool else '')
	_trace(dt_full, 'barpos=%s now_wall=%s hhmmss=%s \u8fde\u7eed\u7ade\u4ef7=%s pool=%d acc=%d sim_ph=%s tick_n=%d'
	       % (bp, now_time, hhmmss, in_sess, len(pool), len(pos_codes), ph0 or '-', len(tick_map)))
	if pool_head:
		ot, pc = _opc_get(C, pool_head, dt_full, d_str, hhmmss)
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

	if not (_in_session_trade(hhmmss) or _a_preopen_for_first_buy(hhmmss)):
		_mr_set('\u975e\u4ea4\u6613\u53ef\u64cd\u4f5c\u65f6\u6bb5(K\u7ebfhhmmss=%s)' % hhmmss)
	elif not pool:
		_mr_set('\u81ea\u9009\u6c60\u7a7a')
	elif not index_allow_new:
		_mr_set('T-1\u4e0a\u8bc1\u6536<MA5\u4e0d\u5f00\u65b0')
	elif ph0:
		br_l = g.gap_bracket.get(ph0)
		_mr_set('\u91d1\u5b57\u5854/\u6301\u4ed3 %s \u6863=%s' % (ph0, br_l or '-'))
	else:
		stx = _canonical_stock_code(pool[0]) or pool[0]
		if stx in already:
			_mr_set('\u5df2\u6301\u4ed3\u8df3\u8fc7 %s' % stx)
		else:
			otx, pcx = _opc_get(C, stx, dt_full, d_str, hhmmss)
			if otx and pcx:
				brx = _gap_bracket(otx / pcx - 1.0)
				_mr_set('\u7b49\u5f85\u5f00\u4ed3 %s \u6863=%s' % (stx, brx))
			else:
				_mr_set('\u7b49\u5f00\u4ed3 %s(\u65e5\u7ebf\u7f3a\u5931\u8d25)' % stx)

	def run_index_liquidate_signal():
		if not index_liquidate_all:
			g._ma10_signal_latched = False
			return
		if not _in_session_trade(hhmmss):
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
				_signal_sell_sim(C, st, _fmt_sell_rule('\u6307\u6570', '\u4e0a\u8bc1MA10\u6e05\u4ed3', '\u8d26\u6237\u6301\u4ed3\u53c2\u8003'), dt_full, sh, px, tick_map)
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
					_signal_sell_sim(C, st, _fmt_sell_rule('\u6307\u6570', '\u4e0a\u8bc1MA10\u6e05\u4ed3', '\u6a21\u62df\u6301\u4ed3\u6e05\u7a7a'), dt_full, sh, px, tick_map)

	def run_risk_sell_signal():
		if not _in_session_trade(hhmmss):
			return
		wl = getattr(g, '_mon_pool_codes', frozenset())
		acc_lp_map = _account_last_price_map(C)
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
				alp = acc_lp_map.get(st) if acc_lp_map else None
				try:
					alp_ok = alp is not None and float(alp) > 0
				except (TypeError, ValueError):
					alp_ok = False
				px_live = _get_current_price(C, st, dt_full, None, tick_map, account_last=float(alp) if alp_ok else None)
				if px_live is None or float(px_live) <= 0:
					continue
				px_mx = _live_px_max_for_atr(
					C, st, dt_full, tick_map, float(px_live), account_last=float(alp) if alp_ok else None)
				px = float(px_mx) if (px_mx is not None and float(px_mx) > 0) else float(px_live)
				highs, lows, closes = _align_daily_ohlc_chronological(data_d, st, highs, lows, closes, ref_px=px)

				prev_ref = float(g.prev_close_ref.get(st, closes[-2]))
				if prev_ref <= 0:
					prev_ref = float(closes[-2])
				touch_pct = float(g.intraday_touch_pct)
				# \u5168\u5929\uff1a\u73b0\u4ef7/\u6628\u6536-1 <= intraday_touch_pct\uff08\u5f53\u65e5\u8dcc\u5e45\uff09\uff1b\u4e0e\u6301\u4ed3\u6210\u672c\u65e0\u5173\u3002
				touch_hit = (prev_ref > 0) and (float(px_live) / float(prev_ref) - 1.0 <= touch_pct)
				if touch_hit:
					prev_touch_day = g.prev_close_stop_touch_day.get(st)
					g.prev_close_stop_touch_day[st] = d_str
					if getattr(g, 'tail_intraday_log', True) and prev_touch_day != d_str:
						print('[\u6628\u6536\u6b62\u635f] \u65f6\u95f4=%s|\u4ee3\u7801=%s|\u9608\u503c=%.2f%%(\u73b0/\u6628\u6536-1)|\u6628\u6536=%.3f|\u73b0\u4ef7=%.3f|\u5f53\u524d=%.2f%%'
						      % (dt_full, st, touch_pct * 100.0, prev_ref, float(px_live), (float(px_live) / float(prev_ref) - 1.0) * 100.0))

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

				if avg_c is None or float(avg_c) <= 0:
					_, ac2 = _position_volume_and_avg(st)
					if ac2 is not None and float(ac2) > 0:
						avg_c = float(ac2)

				if avg_c is not None and float(avg_c) > 0 and _in_session_trade(hhmmss):
					try:
						cost_pnl = float(px_live) / float(avg_c) - 1.0
					except (TypeError, ValueError, ZeroDivisionError):
						cost_pnl = None
					if cost_pnl is not None and cost_pnl <= float(g.hard_stop_pct):
						if _signal_sell_sim(C, st, _fmt_sell_rule('\u98ce\u63a7', '\u6210\u672c\u786c\u6b62\u635f', '\u9608\u503c%.1f%%(\u5168\u5929\u8fde\u7eed\u7ade\u4ef7)' % (float(g.hard_stop_pct) * 100.0)), dt_full, sh, px_live, tick_map):
							continue

				if touch_hit and _in_session_trade(hhmmss):
					can_k = (_canonical_stock_code(st) or st, d_str)
					if can_k not in g._intraday_prev_ref_stop_done:
						if _signal_sell_sim(C, st, _fmt_sell_rule('\u98ce\u63a7', '\u6628\u6536\u6b62\u635f', '\u9608\u503c%.1f%%(\u5168\u5929\u76f8\u5bf9\u6628\u6536)' % (touch_pct * 100.0)), dt_full, sh, px_live, tick_map):
							g._intraday_prev_ref_stop_done.add(can_k)
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
				m_atr, fl_atr, hh_ov, ref_h, dh_cal = _atr_pack_for_position(
					C, st, dt_full, d_str, data_d, highs, lows, closes, px_live, avg_c, dh_eff)
				_emit_atr_mon_line(dt_full, st, px, avg_c, dh_eff, highs, lows, closes,
						   hold_shares=sh_raw, scope_tag='\u81ea\u9009', ref_high=ref_h,
						   mult=m_atr, stop_floor=fl_atr, hh_daily_override=hh_ov, dh_cal=dh_cal,
						   px_display=float(px_live))
				should_tp, note = _check_atr_take_profit_only(
					dh_eff, highs, lows, closes, px_live, avg_c, ref_high=ref_h,
					mult=m_atr, stop_floor=fl_atr, hh_daily_override=hh_ov)
				if _vb():
					print('%s [\u6b62\u76c8\u68c0\u67e5] %s %s' % (dt_full, st, note))
				if should_tp:
					_signal_sell_sim(C, st, _fmt_sell_rule('\u6b62\u76c8', 'ATR\u540a\u706f', note), dt_full, sh, px_live, tick_map)
			except Exception as e:
				print('%s [\u98ce\u63a7\u5356\u5f02\u5e38] %s %s' % (dt_full, st, e))
		_run_tail_watchlist_cost_stop(C, dt_full, d_str, hhmmss, tick_map, mos)

	def run_pyramid_and_entry_signal():
		mhc = int(getattr(g, 'max_hold_count', 0) or 0)
		for stock in _held_sim_keys_in_pool(pool):
			_run_pyramid_for_stock(C, stock, dt_full, d_str, hhmmss, tick_map, notional, mos)

		if not (_in_session_trade(hhmmss) or _a_preopen_for_first_buy(hhmmss)):
			_trace(dt_full, '\u975e\u8fde\u7eed\u7adf\u4ef7\u4e14\u975eA\u96c6\u5408\u672b\u6bb5 \u8df3\u8fc7\u9996\u4e70 hhmmss=%s' % hhmmss)
			return

		if not pool:
			_trace(dt_full, '\u65e0\u5f00\u4ed3\u5019\u9009(\u81ea\u9009\u6c60\u7a7a)')
			return
		if not index_allow_new:
			_trace(dt_full, '\u4e0d\u5f00\u65b0\u4ed3: T-1\u4e0a\u8bc1\u6536< T-1MA5')
			if _vb():
				print('%s [\u4e0d\u5f00\u65b0\u4ed3] T-1\u4e0a\u8bc1\u6536< T-1MA5' % dt_full)
			return
		if mhc > 0 and len(already) >= mhc:
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
		defer = set(getattr(g, '_defer_first_buy_tail', set())) & set(cands)
		if defer:
			cands.sort(key=lambda x: (0 if x not in defer else 1, x))
		if not cands:
			_trace(dt_full, '\u81ea\u9009\u5168\u90e8\u5df2\u6301\u4ed3 held=%d pool=%d' % (held_cnt, len(pool)))
			if _vb():
				print('%s [\u8df3\u8fc7\u5f00\u4ed3] \u81ea\u9009\u5168\u90e8\u5df2\u6301\u4ed3 held=%d pool=%d' % (dt_full, held_cnt, len(pool)))
			return

		already_dyn = set(already)
		for stock in list(cands):
			can0 = _canonical_stock_code(stock) or stock
			if can0 in already_dyn:
				continue
			if mhc > 0 and len(already_dyn) >= mhc:
				_trace(dt_full, '\u591a\u7968\u9996\u4e70\u5df2\u8fbe\u6301\u4ed3\u4e0a\u9650 max_hold=%d \u672c\u6839\u4f59\u4e0b\u505c' % mhc)
				break
			if _try_first_buy_watchlist_stock(C, stock, dt_full, d_str, hhmmss, tick_map, notional, mos):
				already_dyn.add(can0)

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
		try:
			_emit_minute_summary(C, dt_full, d_str, hhmmss, tick_map, pool, ph0, already, index_allow_new, _account_last_price_map(C))
		except Exception as e:
			print('%s [emit MIN] %r' % (STRATEGY_TAG, e))
		try:
			_emit_monitor_unified_summary(dt_full, pos_codes, getattr(g, '_mon_pool_codes', frozenset()))
		except Exception as e:
			print('%s [emit MON] %r' % (STRATEGY_TAG, e))
		try:
			_emit_position_holdings(C, dt_full, d_str, tick_map)
		except Exception as e:
			print('%s [emit POS] %r' % (STRATEGY_TAG, e))


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
