#coding:gbk
"""
\u81ea\u9009\u6c60 ATR \u6b62\u76c8\u8bd5\u7b97\uff08\u5355\u6587\u4ef6\u72ec\u7acb\u7248\uff0c\u4e0d\u5f15\u5165\u4efb\u4f55\u5b9e\u76d8 .py \u8def\u5f84\uff09\u3002
\u53e3\u5f84\u4e0e\u5b9e\u76d8 strategy_my_watchlist_intraday_atr_1m_live_signal \u4e2d ATR \u6b62\u76c8\u8ba1\u7b97\u4fdd\u6301\u4e00\u81f4\uff1a
  HH_eff = max(\u65e5\u7ebf\u7a97\u53e3\u6700\u9ad8, ref_high)\uff0c\u6b62\u76c8 = HH_eff - ATR * mult\uff1bref_high \u53e0\u73b0\u4ef7/\u5206\u65f6\u9ad8\u3002

\u8fd0\u884c\uff1aQMT 1m \u7b56\u7565\u9644\u52a0\u672c\u6587\u4ef6\u3002
  - \u76d8\u540e/\u975e\u4ea4\u6613\u65e5\uff1a\u5ba2\u6237\u7aef\u4e0d\u518d\u8c03 handlebar\uff0c\u539f\u5148\u4ec5\u7b49 is_last_bar \u4f1a\u6ca1\u8f93\u51fa\u3002\u9ed8\u8ba4\u5728 init \u65f6\u4e5f\u8dd1\u4e00\u6b21\u8bd5\u7b97\uff08atr_test_on_init=True\uff09\u3002
  - \u53ef\u9009 C.atr_test_end_time\uff1aYYYYMMDD \u621614\u4f4d\u5168\u65f6\u5206 YYYYMMDDhhmmss\uff08\u4ec514\u4f4d\u65e5\u671f\u5219\u81ea\u52a8\u62fc 150000 \u4f5c\u4e3a\u5f53\u65e5\u6536\u76d8\u53c2\u8003\u65f6\u523b\uff09\u3002
\u76d8\u4e2d\uff1a\u4ecd\u53ef\u5728\u6bcf\u6839\u6700\u540e\u4e00\u6839 1m is_last_bar \u6253\u5370\u4e00\u6b21\uff08\u56de\u6d4b\u6bcf\u6839\u53ef\u6253\u5370\uff09\u3002
\u53c2\u6570\uff1aC.watchlist_sector_name\u3001C.atr_period(14)\u3001C.atr_stop_mult(2)\u3001C.bar_count(80)\u3001
C.allow_atr_same_day(True)\u3001C.atr_ref_high_use_intraday(True)\u3001C.test_atr_dh_eff(1)\u3001C.test_atr_max_stocks(500,0=\u5168\u90e8)\u3001
C.accountid / C.account_type\uff08\u53ef\u9009\uff09\u3001C.atr_test_on_init(True)\u3001C.atr_test_end_time(\u53ef\u9009)\u3002
"""

from __future__ import print_function

import time
import sys

import numpy as np

try:
	import talib
except Exception:
	talib = None


class _Cfg(object):
	pass


cfg = _Cfg()


def timetag_to_datetime(timetag, format_str='%Y%m%d%H%M%S'):
	try:
		return time.strftime(format_str, time.localtime(float(timetag) / 1000.0))
	except Exception:
		try:
			return time.strftime(format_str, time.localtime(float(timetag)))
		except Exception:
			return str(timetag)


def _account_type():
	t = getattr(cfg, 'account_type', None) or 'STOCK'
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


def _daily_bars_need_reverse(data_d, stock, closes, ref_px=None):
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


def _pool_from_sector(C):
	name = (getattr(cfg, 'watchlist_sector_name', None) or '\u6211\u7684\u81ea\u9009').strip()
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


def _account_last_price(stock):
	if not (getattr(cfg, 'accid', '') or '').strip():
		return None
	gtd = getattr(sys.modules.get('__main__'), 'get_trade_detail_data', None) or globals().get('get_trade_detail_data')
	if not gtd:
		return None
	try:
		pos = gtd(cfg.accid, _account_type(), 'position')
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


def _atr_trailing_stop_numbers(days_held_effective, highs, lows, closes, ref_high=None):
	if talib is None:
		return None, None, None, 'talib', None
	if not highs or not lows or not closes or len(closes) < 2:
		return None, None, None, 'bar', None
	if days_held_effective < 1 and not bool(getattr(cfg, 'allow_atr_same_day', True)):
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
			int(cfg.atr_period),
		)
		atr_v = float(atr_arr[-1]) if len(atr_arr) and not np.isnan(atr_arr[-1]) else None
	except Exception:
		return None, None, None, 'atr_x', float(hh_daily)
	mult = float(cfg.atr_stop_mult)
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


def _should_run_bar(C):
	try:
		if C.is_last_bar():
			return True
	except Exception:
		pass
	try:
		if bool(getattr(C, 'do_back_test', False)) or bool(getattr(C, 'isDoBackTest', False)):
			return True
	except Exception:
		pass
	return False


def _apply_cfg_from_C(C):
	cfg.accid = getattr(C, 'accountid', '') or getattr(C, 'account_id', '') or ''
	cfg.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'
	cfg.watchlist_sector_name = getattr(C, 'watchlist_sector_name', '\u6211\u7684\u81ea\u9009')
	cfg.atr_period = int(getattr(C, 'atr_period', 14))
	cfg.atr_stop_mult = float(getattr(C, 'atr_stop_mult', 2.0))
	cfg.bar_count = int(getattr(C, 'bar_count', 80))
	cfg.allow_atr_same_day = bool(getattr(C, 'allow_atr_same_day', True))
	cfg.atr_ref_high_use_intraday = bool(getattr(C, 'atr_ref_high_use_intraday', True))


def _resolve_probe_dt_full(C):
	"""\u8fd4\u56de (dt_full_14, source_tag)\uff1bsource \u4e3a param|bar|wall\u3002"""
	raw = getattr(C, 'atr_test_end_time', None)
	if raw is not None:
		s = str(raw).strip()
		if len(s) == 8 and s.isdigit():
			s = s + '150000'
		if len(s) >= 14 and s[:14].isdigit():
			return s[:14], 'param'
	try:
		bp = getattr(C, 'barpos', 0)
		tt = C.get_bar_timetag(bp)
		dt_full = timetag_to_datetime(tt, '%Y%m%d%H%M%S')
		if len(dt_full) >= 14 and dt_full[:14].isdigit():
			return dt_full[:14], 'bar'
	except Exception:
		pass
	return time.strftime('%Y%m%d%H%M%S'), 'wall'


def run_watchlist_atr_probe(C):
	_apply_cfg_from_C(C)
	if talib is None:
		print('[ERR] talib \u672a\u5b89\u88c5\uff0c\u65e0\u6cd5\u8ba1\u7b97 ATR')
		return
	dh_eff = int(getattr(C, 'test_atr_dh_eff', 1))
	max_stocks = int(getattr(C, 'test_atr_max_stocks', 500))
	dt_full, dt_src = _resolve_probe_dt_full(C)
	if dt_src != 'bar':
		print('[ATR-STANDALONE] end_time=%s (src=%s, \u975e\u4ea4\u6613\u6216\u65e0K\u65f6\u7528\u53c2\u6570/\u5899\u949f)' % (dt_full, dt_src))
	d_str = dt_full[:8]
	tick_map = {}
	pool = _pool_from_sector(C)
	if not pool:
		print('[WARN] \u7a7a\u6c60 sector=%r' % (cfg.watchlist_sector_name,))
		return
	print('=' * 72)
	print('[ATR-STANDALONE] dt=%s dh=%d atr=%s mult=%s bars=%s ref_hi=%s'
	      % (dt_full, dh_eff, cfg.atr_period, cfg.atr_stop_mult, cfg.bar_count, cfg.atr_ref_high_use_intraday))
	loop = sorted(pool)
	if max_stocks > 0:
		loop = loop[:max_stocks]
	print('[ATR-STANDALONE] n=%d calc=%d head=%s' % (len(pool), len(loop), pool[:10]))
	print('-' * 72)
	for st in loop:
		try:
			data_d = C.get_market_data_ex(
				['close', 'high', 'low', 'open'], [st],
				end_time=dt_full, period='1d', count=int(cfg.bar_count), subscribe=False
			)
			if st not in data_d:
				print('%s no daily' % st)
				continue
			highs = _ohlc_to_list(data_d[st].get('high'))
			lows = _ohlc_to_list(data_d[st].get('low'))
			closes = _ohlc_to_list(data_d[st].get('close'))
			if len(closes) < 2:
				print('%s bars<2' % st)
				continue
			fb = float(closes[-1])
			px0 = _get_current_price(C, st, dt_full, fb, tick_map)
			if px0 is None or px0 <= 0:
				print('%s no px' % st)
				continue
			px = _live_px_max_for_atr(C, st, dt_full, tick_map, px0)
			if px is None or px <= 0:
				px = float(px0)
			else:
				px = float(px)
			highs, lows, closes = _align_daily_ohlc_chronological(data_d, st, highs, lows, closes, ref_px=px)
			ref_h = float(px)
			if bool(cfg.atr_ref_high_use_intraday):
				m1h = _intraday_high_since_open(C, st, dt_full, d_str)
				m1x = _m1_last_high(C, st, dt_full)
				for u in (m1h, m1x):
					if u is not None and float(u) > 0:
						ref_h = max(ref_h, float(u))
			stop, atr_v, hh_eff, err, hh_daily = _atr_trailing_stop_numbers(
				dh_eff, highs, lows, closes, ref_high=ref_h)
			if err is not None:
				print('%s err=%s hh_d=%s' % (st, err, hh_daily))
				continue
			gap = px - stop
			gap_pct = (gap / stop * 100.0) if stop and stop > 0 else 0.0
			hd = ('%.3f' % hh_daily) if hh_daily is not None else '--'
			print(('%s px=%.3f ref_hi=%.3f HH_eff=%.3f HH_d=%s ATR=%.4f x=%.2f stop=%.3f d=%.3f(%.2f%%)')
			      % (st, px, ref_h, hh_eff, hd, atr_v, cfg.atr_stop_mult, stop, gap, gap_pct))
		except Exception as e:
			print('%s EXC %r' % (st, e))
	print('=' * 72)


_g_once = False


def init(C):
	global _g_once
	_g_once = False
	_apply_cfg_from_C(C)
	print('[ATR-STANDALONE] init ok 1m attach; handlebar still on is_last_bar')
	if bool(getattr(C, 'atr_test_on_init', True)):
		try:
			run_watchlist_atr_probe(C)
		except Exception as e:
			print('[ATR-STANDALONE] init probe EXC %r' % (e,))


def handlebar(C):
	global _g_once
	if _g_once:
		return
	if not _should_run_bar(C):
		return
	_g_once = True
	run_watchlist_atr_probe(C)


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)


if __name__ == '__main__':
	print(__doc__)
