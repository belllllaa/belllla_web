# -*- coding: utf-8 -*-
"""
自选报价探测：打印「我的自选」中每只股票的
  昨天收盘价、今天开盘价、现在价格、涨跌幅%%（相对昨收）。

用法（QMT）：
  - 周期选 1 分钟；与 strategy_my_watchlist_intraday_atr_1m_live_signal 一样依赖 get_stock_list_in_sector / get_market_data_ex / get_full_tick。
  - 板块名默认「我的自选」，可在 init 参数里设 C.watchlist_sector_name。
  - 回测下每根 K 执行；实盘仅 is_last_bar 时执行（与主策略门闸一致）。

仅 print，无下单。
"""

import time
import datetime

STRATEGY_TAG = '[QUOTE探测]'
INDEX_TAG = STRATEGY_TAG


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
	name = (getattr(g, 'watchlist_sector_name', None) or '\u6211\u7684\u81ea\u9009').strip()
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


def _daily_last_bar_date(data_d, stock, closes_d):
	tags = _ohlc_time_list(data_d, stock)
	if not tags or len(tags) != len(closes_d):
		return None
	return _tag_to_yyyymmdd(tags[-1])


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


def _prev_close_without_daily_time(C, stock, dt_full, closes_d, n):
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


def _first_open_today_from_1m(C, stock, dt_full, d_str):
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


def _opc_reset_day(d_str):
	if getattr(g, '_opc_day', '') != d_str:
		g._opc_day = d_str
		g._opc_map = {}


def _opc_get(C, stock, dt_full, d_str):
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


def _snapshot_chg(C, stock, dt_full, d_str, tick_map, opc):
	ot, pc = opc
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


def init(C):
	g.watchlist_sector_name = getattr(C, 'watchlist_sector_name', '\u6211\u7684\u81ea\u9009')
	g.bar_count = int(getattr(C, 'bar_count', 80))
	g.handlebar_each_bar = bool(getattr(C, 'handlebar_each_bar', False))
	g._opc_day = ''
	g._opc_map = {}
	g._last_handlebar_barpos = None
	print('=' * 60)
	print('%s init \u677f\u5757=%s bar_count=%d' % (INDEX_TAG, g.watchlist_sector_name, g.bar_count))
	print('\u6bcf\u6839\u53ef\u6253 [QUOTE] \u884c\uff1a\u6628\u6536|\u4eca\u5f00|\u73b0\u4ef7|\u6da8\u8dcc\u5e45%%')
	print('=' * 60)


def handlebar(C):
	if not _handlebar_should_run(C):
		return
	bp = getattr(C, 'barpos', None)
	if bp is not None and bp == getattr(g, '_last_handlebar_barpos', None):
		return
	g._last_handlebar_barpos = bp

	dt_full = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	d_str = dt_full[:8]

	pool = _pool_from_sector(C)
	if not pool:
		print('%s %s \u81ea\u9009\u6c60\u7a7a \u6771\u5757=%s' % (dt_full, INDEX_TAG, g.watchlist_sector_name))
		return

	tick_map = {}
	try:
		if hasattr(C, 'get_full_tick') and pool:
			codes = list(pool)[:80]
			ticks = C.get_full_tick(codes)
			if ticks:
				for code, t in ticks.items():
					p = _parse_tick_price(t)
					if p and p > 0:
						tick_map[_canonical_stock_code(code) or code] = float(p)
	except Exception:
		pass

	for st in pool:
		opc = _opc_get(C, st, dt_full, d_str)
		ot, chg, px = _snapshot_chg(C, st, dt_full, d_str, tick_map, opc)
		prev_s = ('%.3f' % float(opc[1])) if (opc and opc[1] is not None and float(opc[1]) > 0) else '--'
		open_s = ('%.3f' % float(ot)) if ot is not None and float(ot) > 0 else '--'
		cur_s = ('%.3f' % float(px)) if px is not None and float(px) > 0 else '--'
		chg_s = ('%.2f%%' % chg) if chg is not None else '--'
		print('%s [QUOTE] \u4ee3\u7801=%s|\u6628\u5929\u6536\u76d8=%s|\u4eca\u5929\u5f00\u76d8=%s|\u73b0\u5728\u4ef7\u683c=%s|\u6da8\u8dcc\u5e45=%s'
		      % (dt_full, st, prev_s, open_s, cur_s, chg_s))


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
