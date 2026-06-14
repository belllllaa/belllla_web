#coding:gbk
import datetime
import sys
import time


def fn_main(name):
	mod = sys.modules.get('__main__')
	fn = getattr(mod, name, None) if mod else None
	if fn is None:
		fn = globals().get(name)
	return fn


def timetag_to_datetime(timetag, format_str='%Y%m%d%H%M%S'):
	try:
		return time.strftime(format_str, time.localtime(float(timetag) / 1000.0))
	except Exception:
		try:
			return time.strftime(format_str, time.localtime(float(timetag)))
		except Exception:
			return str(timetag)


STRATEGY_TAG = '[\u5361\u5f02\u52a8\u5c3e\u76d8\u4e70]'
DEFAULT_SECTOR = '\u5361\u5f02\u52a8\u5c3e\u76d8\u4e70\u5165\u6c60'
SESSION_AM_START, SESSION_AM_END = 92500, 113000
SESSION_PM_START, SESSION_PM_END = 130000, 150000
BUY_WINDOW_START, BUY_WINDOW_END = 145500, 150000
DEFAULT_ACCID = '30262698'
DEFAULT_MAX_AMOUNT_PER_STOCK = 100000.0
DEFAULT_MIN_SHARES = 100
DEFAULT_WITHDRAW_SECS = 15
DEFAULT_BUY_PREMIUM_PCT = 0.005
DEFAULT_PREMIUM_RETRY_STEP = 0.005


class G(object):
	pass


g = G()


def canonical_stock_code(s):
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
	if len(t) == 6 and t.isdigit():
		if t.startswith(('60', '68', '51')):
			return t + '.SH'
		return t + '.SZ'
	return t


def code6_from_symbol(sym):
	c = canonical_stock_code(sym)
	return c.split('.', 1)[0] if c else ''


def normalize_position_code(pos):
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
		return canonical_stock_code(ins)
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


def parse_tick_price(t):
	if t is None:
		return None
	p = (getattr(t, 'lastPrice', None) or getattr(t, 'last_price', None) or
	     getattr(t, 'm_nLastPrice', None) or getattr(t, 'nLast', None))
	if p is None and isinstance(t, dict):
		p = t.get('lastPrice') or t.get('last_price') or t.get('m_nLastPrice') or t.get('nLast')
	if p is not None:
		try:
			v = float(p)
			return v if v > 0 else None
		except Exception:
			pass
	return None


def parse_tick_pre_close(t):
	if t is None:
		return None
	for k in ('preClose', 'preclose', 'm_dPreClose', 'm_dPreClosePrice',
	          'lastClose', 'yesterdayClose', 'YesterdayClose'):
		v = getattr(t, k, None)
		if v is None and isinstance(t, dict):
			v = t.get(k)
		if v is not None:
			try:
				x = float(v)
				if x > 0:
					return x
			except Exception:
				pass
	return None


def build_full_tick_prices(C, stock_list):
	out = {}
	if not stock_list or not hasattr(C, 'get_full_tick'):
		return out
	try:
		ticks = C.get_full_tick(stock_list)
		if not ticks:
			return out
		for code, t in ticks.items():
			p = parse_tick_price(t)
			if p is not None:
				out[code] = p
	except Exception:
		pass
	return out


def build_full_tick_map(C, stock_list):
	out = {}
	if not stock_list or not hasattr(C, 'get_full_tick'):
		return out
	try:
		ticks = C.get_full_tick(stock_list)
		if ticks:
			out.update(ticks)
	except Exception:
		pass
	return out


def prev_close_for_stock(C, stock, tick_obj=None, end_time_str=None):
	pc = parse_tick_pre_close(tick_obj)
	if pc is not None and pc > 0:
		return pc
	if not hasattr(C, 'get_market_data_ex'):
		return None
	try:
		kw = dict(period='1d', count=3, subscribe=False)
		if end_time_str:
			kw['end_time'] = end_time_str
		data = C.get_market_data_ex(['close'], [stock], **kw)
		if not data or stock not in data:
			for k in (stock, canonical_stock_code(stock)):
				if k in data:
					stock = k
					break
		stk = data.get(stock) if data else None
		cl = []
		if isinstance(stk, dict):
			cl = list(stk.get('close') or [])
		else:
			try:
				cl = list(getattr(stk, 'close', []) or [])
			except Exception:
				cl = []
		if len(cl) >= 2:
			v = float(cl[-2])
			return v if v > 0 else None
		if len(cl) == 1:
			v = float(cl[-1])
			return v if v > 0 else None
	except Exception:
		pass
	return None


def pct_vs_prev_close(last_px, prev_close):
	if last_px is None or prev_close is None:
		return None
	try:
		lp, pc = float(last_px), float(prev_close)
	except (TypeError, ValueError):
		return None
	if pc <= 0:
		return None
	return (lp / pc - 1.0) * 100.0


def limit_down_band(code6):
	if code6.startswith(('68', '30')):
		return -30.0, -15.0
	return -10.0, -8.0


def buy_pct_threshold(code6):
	if code6.startswith(('68', '30')):
		return 15.0
	return 8.0


def is_buy_blocked_by_pct(sym, last_px, prev_close):
	pct = pct_vs_prev_close(last_px, prev_close)
	if pct is None:
		return False, '\u65e0\u6da8\u8dcc\u5e45'
	code6 = code6_from_symbol(sym)
	floor, ceil = limit_down_band(code6)
	if pct <= ceil + 1e-6 and pct >= floor - 1e-6:
		return True, '\u8dcc\u5e45\u5e26[%.0f%%,%.0f%%]' % (floor, ceil)
	thr = buy_pct_threshold(code6)
	if pct > thr + 1e-6:
		return True, '\u6da8\u5e45>%.0f%%' % thr
	return False, 'OK'


def shares_for_amount(amount_yuan, price, min_shares=100):
	try:
		amt = float(amount_yuan)
		px = float(price)
	except (TypeError, ValueError):
		return 0
	if amt <= 0 or px <= 0:
		return 0
	sh = int(amt / px / min_shares) * min_shares
	return sh if sh >= min_shares else 0


def effective_buy_premium(gobj, retry=0):
	step = float(getattr(gobj, 'buy_premium_retry_step', DEFAULT_PREMIUM_RETRY_STEP) or 0)
	return float(gobj.buy_premium_pct) + step * int(retry or 0)


def limit_buy_price(last_px, premium_pct):
	try:
		px = float(last_px) * (1.0 + float(premium_pct))
	except Exception:
		return None
	if px <= 0:
		return None
	return max(0.01, round(px, 3))


def order_remark(prefix, stock, shares, retry=0):
	base = '%s_%s_%d' % (prefix, stock.replace('.', '_'), int(shares))
	if retry:
		base = (base + '_R%d' % retry)[:23]
	return base[:23]


def in_time_window(hhmmss, start_hms, end_hms):
	try:
		w = int(hhmmss)
		return int(start_hms) <= w <= int(end_hms)
	except (TypeError, ValueError):
		return False


def in_handlebar_session(hhmmss):
	if hhmmss is None:
		return False
	try:
		h = int(hhmmss)
	except (TypeError, ValueError):
		return False
	return (SESSION_AM_START <= h <= SESSION_AM_END) or (SESSION_PM_START <= h <= SESSION_PM_END)


def in_buy_window(hhmmss):
	return in_time_window(hhmmss, BUY_WINDOW_START, BUY_WINDOW_END)


def stock_display_name(C, code):
	try:
		if hasattr(C, 'get_stock_name'):
			n = C.get_stock_name(code)
			if n:
				return str(n).strip()
	except Exception:
		pass
	try:
		fn = getattr(C, 'get_instrumentdetail', None) or getattr(C, 'get_instrumentDetail', None)
		if fn:
			d = fn(code)
			if isinstance(d, dict):
				for k in ('InstrumentName', 'm_strInstrumentName', 'name'):
					if d.get(k):
						return str(d[k]).strip()
	except Exception:
		pass
	return ''


def log_today_buy_pool(C, gobj, bar_date_str, pool):
	d_str = bar_date_str[:8]
	items = []
	for code in sorted(pool or []):
		nm = stock_display_name(C, code)
		items.append('%s(%s)' % (nm, code) if nm else str(code))
	sector = (getattr(gobj, 'sector_name', None) or DEFAULT_SECTOR).strip()
	print('%s [\u4eca\u65e5\u5f85\u4e70\u6c60] \u65e5\u671f=%s \u677f\u5757=%r \u6570\u91cf=%d' % (
		gobj.strategy_tag, d_str, sector, len(pool or [])))
	print('%s [\u4eca\u65e5\u5f85\u4e70\u6c60] %s' % (
		gobj.strategy_tag, ' | '.join(items) if items else '\u65e0'))


def is_qmt_backtest_context(C):
	if bool(getattr(C, 'do_back_test', False)):
		return True
	if bool(getattr(C, 'doBackTest', False)) or bool(getattr(C, 'isDoBackTest', False)):
		return True
	rm = getattr(C, 'run_mode', None) or getattr(C, 'runMode', None)
	try:
		if rm is not None and int(rm) == 1:
			return True
	except (TypeError, ValueError):
		pass
	if isinstance(rm, str) and rm.strip().upper() in ('BACKTEST', 'TRUE', '1', 'T'):
		return True
	return False


def should_passorder(C):
	if is_qmt_backtest_context(C):
		return False
	if not bool(getattr(g, 'live_orders', True)):
		return False
	if not (getattr(g, 'accid', None) or '').strip():
		return False
	hhmmss = datetime.datetime.now().strftime('%H%M%S')
	return in_buy_window(hhmmss)


def rollover_session(gobj, current_date_str):
	if getattr(gobj, '_session_date', '') != current_date_str:
		gobj._session_date = current_date_str
		gobj._tried_stocks = set()
		gobj.waiting_list = []
		gobj.pending_orders = {}
		gobj._logged_fill_remarks = set()
		gobj._buy_pool_snapshot = []


def get_pool_stocks(C, sector_name):
	if not sector_name:
		return []
	stocks = []
	if hasattr(C, 'get_stock_list_in_sector'):
		try:
			raw = C.get_stock_list_in_sector(sector_name)
			if raw:
				stocks = list(raw)
		except Exception:
			pass
	if not stocks and hasattr(C, 'get_sector'):
		try:
			raw = C.get_sector(sector_name)
			if raw:
				stocks = list(raw)
		except Exception:
			pass
	out, seen = [], set()
	for s in stocks:
		c = canonical_stock_code(s)
		if c and c not in seen:
			seen.add(c)
			out.append(c)
	return out


def refresh_buy_pool(C, gobj):
	"""\u6bcf\u6b21\u4ece QMT \u677f\u5757\u91cd\u62c9\u80a1\u7968\u6c60\uff1b\u53d8\u5316\u65f6\u6e05\u7a7a\u5df2\u5c1d\u8bd5\u4e70\u5165\u3002"""
	pool = get_pool_stocks(C, gobj.sector_name)
	cur = tuple(sorted(pool or []))
	prev = tuple(getattr(gobj, '_buy_pool_snapshot', ()) or ())
	changed = (cur != prev)
	gobj._buy_pool_snapshot = list(cur)
	if changed:
		gobj._tried_stocks = set()
	return pool, changed


def monitor_buy_pool(C, gobj, bar_date_str):
	"""24h \u677f\u5757\u76d1\u63a7\uff1a\u6bcf\u6839 K \u7ebf\u62c9\u6c60\uff1b\u4ec5\u53d8\u5316\u65f6\u6253\u65e5\u5fd7\u3002"""
	pool, changed = refresh_buy_pool(C, gobj)
	if changed:
		print('%s [\u677f\u5757\u91cd\u8f7d] \u65f6\u95f4=%s \u6570\u91cf=%d \u677f\u5757=%r' % (
			gobj.strategy_tag, bar_date_str, len(pool or []), gobj.sector_name))
		log_today_buy_pool(C, gobj, bar_date_str, pool)
	return pool, changed


def get_account_cash(gobj):
	gtd = fn_main('get_trade_detail_data')
	if gtd is None or not (gobj.accid or '').strip():
		return 0.0
	try:
		accs = gtd(gobj.accid, gobj.account_type, 'account') or []
		if not accs:
			return 0.0
		return float(getattr(accs[0], 'm_dAvailable', 0) or 0)
	except Exception:
		return 0.0


def get_positions_map(gobj):
	gtd = fn_main('get_trade_detail_data')
	out = {}
	if gtd is None or not (gobj.accid or '').strip():
		return out
	try:
		for p in gtd(gobj.accid, gobj.account_type, 'position') or []:
			code = normalize_position_code(p)
			code = canonical_stock_code(code) or code
			if not code:
				continue
			vol = int(getattr(p, 'm_nVolume', 0) or 0)
			can = int(getattr(p, 'm_nCanUseVolume', 0) or 0)
			cost = float(getattr(p, 'm_dOpenPrice', 0) or getattr(p, 'cost_price', 0) or 0)
			out[code] = {'volume': vol, 'can_use': can, 'cost': cost}
	except Exception:
		pass
	return out


def _log_event(gobj, tag, stock, reason, **extra):
	parts = ['%s [%s] \u4ee3\u7801=%s \u539f\u56e0=%s' % (gobj.strategy_tag, tag, stock or '--', reason or '--')]
	for k, v in extra.items():
		if v is None:
			continue
		parts.append('%s=%s' % (k, v))
	print(' '.join(parts))


def _log_buy_submit(gobj, stock, shares, last_px, limit_px, prev_close, pct, amount_est, remark):
	pct_s = ('%.2f%%' % pct) if pct is not None else '--'
	prev_s = ('%.3f' % prev_close) if prev_close else '--'
	print('%s [\u4e70\u5165\u59d4\u6258] \u4ee3\u7801=%s \u80a1\u6570=%d \u73b0\u4ef7=%.3f \u9650\u4ef7=%.3f \u6628\u6536=%s \u6da8\u8dcc\u5e45=%s \u9884\u8ba1\u91d1\u989d=%.2f \u5907\u6ce8=%s' % (
		gobj.strategy_tag, stock, int(shares), float(last_px), float(limit_px),
		prev_s, pct_s, float(amount_est), remark))


def _deal_field(deal, *names):
	for n in names:
		v = getattr(deal, n, None)
		if v is None and isinstance(deal, dict):
			v = deal.get(n)
		if v is not None:
			return v
	return None


def _deal_remark(deal):
	return str(_deal_field(deal, 'm_strRemark', 'remark') or '')


def _deal_fill_price(deal):
	for n in ('m_dPrice', 'm_dTradedPrice', 'price', 'traded_price'):
		v = _deal_field(deal, n)
		if v is not None:
			try:
				x = float(v)
				if x > 0:
					return x
			except (TypeError, ValueError):
				pass
	return None


def _deal_fill_volume(deal):
	for n in ('m_nVolume', 'volume', 'traded_volume'):
		v = _deal_field(deal, n)
		if v is not None:
			try:
				return int(v)
			except (TypeError, ValueError):
				pass
	return None


def _log_buy_fill(gobj, remark, deal, pinfo):
	fill_px = _deal_fill_price(deal)
	fill_vol = _deal_fill_volume(deal)
	meta = pinfo.get('meta') or {}
	stock = pinfo.get('stock') or meta.get('stock') or ''
	sh = fill_vol if fill_vol is not None else int(pinfo.get('shares', 0) or 0)
	lp = meta.get('limit_px')
	last_px = meta.get('last_px')
	prev_close = meta.get('prev_close')
	pct = meta.get('pct')
	amount = (float(fill_px) * int(sh)) if fill_px and sh else meta.get('amount_est')
	pct_s = ('%.2f%%' % pct) if pct is not None else '--'
	prev_s = ('%.3f' % prev_close) if prev_close else '--'
	fill_s = ('%.3f' % fill_px) if fill_px else '--'
	amt_s = ('%.2f' % amount) if amount is not None else '--'
	print('%s [\u4e70\u5165\u6210\u4ea4] \u4ee3\u7801=%s \u80a1\u6570=%d \u6210\u4ea4\u4ef7=%s \u9650\u4ef7=%s \u73b0\u4ef7=%s \u6628\u6536=%s \u6da8\u8dcc\u5e45=%s \u6210\u4ea4\u91d1\u989d=%s \u5907\u6ce8=%s' % (
		gobj.strategy_tag, stock, sh, fill_s,
		('%.3f' % lp) if lp else '--',
		('%.3f' % last_px) if last_px else '--',
		prev_s, pct_s, amt_s, remark))


def _log_unfilled(gobj, pinfo, remark, reason):
	meta = pinfo.get('meta') or {}
	stock = pinfo.get('stock', '--')
	extra = {
		'\u80a1\u6570': pinfo.get('shares'),
		'\u9650\u4ef7': meta.get('limit_px'),
		'\u73b0\u4ef7': meta.get('last_px'),
		'\u91cd\u8bd5\u6b21\u6570': pinfo.get('retry', 0),
		'\u5907\u6ce8': remark,
		'\u6628\u6536': meta.get('prev_close'),
		'\u6da8\u8dcc\u5e45': (('%.2f%%' % meta['pct']) if meta.get('pct') is not None else None),
	}
	_log_event(gobj, '\u4e70\u5165\u672a\u6210\u4ea4', stock, reason, **extra)


def log_scan_summary(gobj, title, stats, extra=None):
	parts = ['%s [\u626b\u63cf\u6c47\u603b] %s' % (gobj.strategy_tag, title)]
	order = (
		'order_ok', 'fail_order', 'fail_no_price', 'fail_cap', 'fail_shares', 'fail_limit',
		'skip_filter', 'skip_pending', 'skip_tried', 'skip_backtest',
	)
	labels = {
		'order_ok': '\u59d4\u6258\u6210\u529f',
		'fail_order': '\u4e0b\u5355\u5931\u8d25',
		'fail_no_price': '\u65e0\u73b0\u4ef7',
		'fail_cap': '\u989d\u5ea6\u4e0d\u8db3',
		'fail_shares': '\u80a1\u6570\u4e0d\u8db3',
		'fail_limit': '\u9650\u4ef7\u5931\u8d25',
		'skip_filter': '\u6da8\u8dcc\u5e45\u8fc7\u6ee4',
		'skip_pending': '\u5728\u9014\u5355',
		'skip_tried': '\u5df2\u5904\u7406',
		'skip_backtest': '\u56de\u6d4b\u4e0d\u5355',
	}
	for k in order:
		if stats.get(k):
			parts.append('%s=%d' % (labels.get(k, k), stats[k]))
	for k, v in stats.items():
		if k not in order and v:
			parts.append('%s=%d' % (labels.get(k, k), v))
	if extra:
		parts.append(str(extra))
	print(' | '.join(parts))


def has_pending_side(gobj, stock, side):
	for p in gobj.pending_orders.values():
		if p.get('stock') == stock and p.get('side') == side:
			return True
	return False


def passorder_limit(C, gobj, stock, shares, limit_price, remark):
	po = fn_main('passorder')
	if po is None:
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u65e0passorder\u63a5\u53e3(\u975eQMT\u5b9e\u76d8)',
		           shares=shares, limit_px=limit_price, remark=remark)
		return False
	try:
		sh = int(shares)
		lp = max(0.01, round(float(limit_price), 3))
	except (TypeError, ValueError):
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u53c2\u6570\u65e0\u6548', shares=shares, limit_px=limit_price)
		return False
	if sh < gobj.min_shares:
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u80a1\u6570\u4e0d\u8db3100', shares=sh)
		return False
	try:
		ret = po(
			int(gobj.buy_code), 1101, gobj.accid, str(stock),
			11, float(lp), int(sh),
			str(gobj.strategy_order_name)[:20],
			int(gobj.quick_trade),
			str(remark)[:23],
			C,
		)
	except Exception as e:
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, 'passorder\u5f02\u5e38:%s' % e,
		           shares=sh, limit_px='%.3f' % lp, remark=remark)
		return False
	if ret is False:
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u5238\u5546\u62d2\u5355\u6216\u8fd4\u56deFalse',
		           shares=sh, limit_px='%.3f' % lp, remark=remark)
		return False
	return True


def register_pending(gobj, remark, stock, shares, retry=0, meta=None):
	gobj.waiting_list.append(remark)
	gobj.pending_orders[remark] = {
		'time': time.time(),
		'stock': stock,
		'side': 'buy',
		'shares': int(shares),
		'retry': int(retry),
		'meta': dict(meta or {}),
	}


def sync_done_from_deals(gobj):
	gtd = fn_main('get_trade_detail_data')
	if gtd is None or not gobj.waiting_list:
		return
	try:
		deals = gtd(gobj.accid, gobj.account_type, 'deal') or []
	except Exception:
		return
	deal_by_remark = {}
	for deal in deals:
		rmk = _deal_remark(deal)
		if rmk:
			deal_by_remark[rmk] = deal
	found = []
	for remark in list(gobj.waiting_list):
		if remark not in deal_by_remark:
			continue
		pinfo = gobj.pending_orders.get(remark)
		if pinfo and remark not in gobj._logged_fill_remarks:
			gobj._logged_fill_remarks.add(remark)
			_log_buy_fill(gobj, remark, deal_by_remark[remark], pinfo)
		found.append(remark)
	for r in found:
		if r in gobj.waiting_list:
			gobj.waiting_list.remove(r)
		gobj.pending_orders.pop(r, None)


def process_cancel_retry(C, gobj, tick_map_builder):
	if not gobj.waiting_list:
		return
	if not should_passorder(C):
		return
	gtd = fn_main('get_trade_detail_data')
	cancel = fn_main('cancel')
	if gtd is None:
		return
	now_ts = time.time()
	try:
		orders = gtd(gobj.accid, gobj.account_type, 'order') or []
	except Exception:
		orders = []
	ORDER_DONE = 56
	ORDER_CANCEL_STATES = (53, 54, 57)
	to_remove = []
	to_retry = []
	for remark in list(gobj.waiting_list):
		pinfo = gobj.pending_orders.get(remark)
		if not pinfo:
			to_remove.append(remark)
			continue
		if now_ts - pinfo['time'] < gobj.withdraw_secs:
			continue
		order_match = None
		for o in orders:
			if (getattr(o, 'm_strRemark', '') or '') == remark:
				order_match = o
				break
		if not order_match:
			if now_ts - pinfo['time'] >= gobj.withdraw_secs:
				_log_event(gobj, '\u59d4\u6258\u8ddf\u8e2a', pinfo.get('stock'), '\u8d85\u65f6\u672a\u627e\u5230\u59d4\u6258\u8bb0\u5f55',
				           remark=remark, wait_sec=gobj.withdraw_secs)
			continue
		status = getattr(order_match, 'm_nOrderStatus', 0)
		order_sys_id = getattr(order_match, 'm_strOrderSysID', '') or ''
		if status == ORDER_DONE:
			if remark not in gobj._logged_fill_remarks:
				gobj._logged_fill_remarks.add(remark)
				_log_buy_fill(gobj, remark, order_match, pinfo)
			to_remove.append(remark)
			continue
		if status in ORDER_CANCEL_STATES:
			retry_nr = int(pinfo.get('retry', 0)) + 1
			if retry_nr > gobj.max_retry:
				_log_unfilled(gobj, pinfo, remark,
				              '\u5e9f\u5355\u4e14\u5df2\u8fbe\u6700\u5927\u91cd\u8bd5%d\u6b21' % gobj.max_retry)
				to_remove.append(remark)
			else:
				_log_unfilled(gobj, pinfo, remark,
				              '\u59d4\u6258\u5df2\u64a4/\u5e9f\u5355\uff0c\u51c6\u5907\u91cd\u6302')
				to_retry.append((remark, pinfo, ''))
			continue
		if pinfo.get('retry', 0) >= gobj.max_retry:
			_log_unfilled(gobj, pinfo, remark, '\u8d85\u65f6\u672a\u6210\u4ea4\u4e14\u5df2\u8fbe\u6700\u5927\u91cd\u8bd5%d\u6b21' % gobj.max_retry)
			to_remove.append(remark)
			continue
		to_retry.append((remark, pinfo, order_sys_id))
	for r in to_remove:
		if r in gobj.waiting_list:
			gobj.waiting_list.remove(r)
		gobj.pending_orders.pop(r, None)
	for remark, pinfo, order_sys_id in to_retry:
		if remark in gobj.waiting_list:
			gobj.waiting_list.remove(remark)
		gobj.pending_orders.pop(remark, None)
		stock = pinfo['stock']
		shares = int(pinfo['shares'])
		retry = int(pinfo.get('retry', 0)) + 1
		if order_sys_id:
			if cancel is None:
				_log_event(gobj, '\u64a4\u5355\u672a\u6210\u529f', stock, '\u65e0cancel\u63a5\u53e3', remark=remark)
				continue
			try:
				cancel(order_sys_id, gobj.accid, gobj.account_type, C)
				print('%s [\u64a4\u5355\u6210\u529f] \u4ee3\u7801=%s \u5907\u6ce8=%s orderId=%s' % (
					gobj.strategy_tag, stock, remark, order_sys_id))
			except Exception as e:
				_log_event(gobj, '\u64a4\u5355\u672a\u6210\u529f', stock, str(e), orderId=order_sys_id, remark=remark)
				continue
		tick_map = tick_map_builder(C, [stock])
		last_px = tick_map.get(stock)
		if last_px is None or last_px <= 0:
			_log_event(gobj, '\u91cd\u6302\u672a\u6210\u529f', stock, '\u65e0\u73b0\u4ef7', retry=retry, remark=remark)
			continue
		prem = effective_buy_premium(gobj, retry)
		lp = limit_buy_price(last_px, prem)
		if lp is None:
			_log_event(gobj, '\u91cd\u6302\u672a\u6210\u529f', stock, '\u9650\u4ef7\u8ba1\u7b97\u5931\u8d25', retry=retry)
			continue
		msg2 = order_remark(gobj.remark_prefix + 'B', stock, shares, retry)
		if passorder_limit(C, gobj, stock, shares, lp, msg2):
			meta = dict(pinfo.get('meta') or {})
			meta.update({'last_px': last_px, 'limit_px': lp, 'retry': retry, 'premium_pct': prem})
			register_pending(gobj, msg2, stock, shares, retry, meta=meta)
			print('%s [\u64a4\u5355\u91cd\u6302] \u4ee3\u7801=%s \u80a1\u6570=%d retry=%d \u73b0\u4ef7=%.3f \u9650\u4ef7=%.3f \u6ea2\u4ef7=%.2f%% \u5907\u6ce8=%s' % (
				gobj.strategy_tag, stock, shares, retry, last_px, lp, prem * 100, msg2))
		else:
			_log_event(gobj, '\u91cd\u6302\u672a\u6210\u529f', stock, 'passorder\u5931\u8d25',
			           retry=retry, limit_px='%.3f' % lp, remark=msg2)


def try_buy_stock(C, gobj, stock, tick_map, tick_full, end_time_str, cash_cap):
	if stock in gobj._tried_stocks:
		_log_event(gobj, '\u4e70\u5165\u8df3\u8fc7', stock, '\u672c\u65e5\u5df2\u5904\u7406\u8fc7')
		return False, 'skip_tried'
	if has_pending_side(gobj, stock, 'buy'):
		_log_event(gobj, '\u4e70\u5165\u8df3\u8fc7', stock, '\u5df2\u6709\u4e70\u5355\u5728\u9014')
		gobj._tried_stocks.add(stock)
		return False, 'skip_pending'
	pos = get_positions_map(gobj)
	held = pos.get(stock, {})
	held_vol = int(held.get('volume', 0) or 0)
	last_px = tick_map.get(stock)
	if last_px is None or last_px <= 0:
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u65e0\u73b0\u4ef7')
		gobj._tried_stocks.add(stock)
		return False, 'fail_no_price'
	prev_c = prev_close_for_stock(C, stock, tick_full.get(stock), end_time_str)
	pct = pct_vs_prev_close(last_px, prev_c)
	blocked, reason = is_buy_blocked_by_pct(stock, last_px, prev_c)
	if blocked:
		_log_event(gobj, '\u4e70\u5165\u8df3\u8fc7', stock, reason,
		           last_px='%.3f' % last_px,
		           prev_close=('%.3f' % prev_c) if prev_c else '--',
		           pct=('%.2f%%' % pct) if pct is not None else '--')
		gobj._tried_stocks.add(stock)
		return False, 'skip_filter'
	remain_cap = float(cash_cap)
	# \u5355\u7b14\u4e0a\u9650\u6309\u672c\u6b21\u4e70\u5165\u91d1\u989d\uff0c\u4e0d\u56e0\u5df2\u6709\u6301\u4ed3\u6263\u51cf\uff08\u5141\u8bb8\u52a0\u4ed3\uff09
	if gobj.max_amount_per_stock > 0:
		remain_cap = min(remain_cap, float(gobj.max_amount_per_stock))
	if remain_cap < last_px * gobj.min_shares:
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u989d\u5ea6\u4e0d\u8db3',
		           remain_cap='%.0f' % remain_cap,
		           cap='%.0f' % gobj.max_amount_per_stock,
		           held_vol=held_vol)
		gobj._tried_stocks.add(stock)
		return False, 'fail_cap'
	shares = shares_for_amount(remain_cap, last_px, gobj.min_shares)
	if shares < gobj.min_shares:
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u8ba1\u7b97\u80a1\u6570\u4e0d\u8db3\u6700\u5c0f\u624b',
		           remain_cap='%.0f' % remain_cap, last_px='%.3f' % last_px)
		gobj._tried_stocks.add(stock)
		return False, 'fail_shares'
	lp = limit_buy_price(last_px, effective_buy_premium(gobj, 0))
	if lp is None:
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u9650\u4ef7\u8ba1\u7b97\u5931\u8d25', last_px='%.3f' % last_px)
		gobj._tried_stocks.add(stock)
		return False, 'fail_limit'
	rmk = order_remark(gobj.remark_prefix + 'B', stock, shares, 0)
	amount_est = float(shares) * float(lp)
	meta = {
		'stock': stock,
		'last_px': last_px,
		'limit_px': lp,
		'prev_close': prev_c,
		'pct': pct,
		'amount_est': amount_est,
	}
	if not should_passorder(C):
		_log_event(gobj, '\u4e70\u5165\u672a\u6210\u529f', stock, '\u56de\u6d4b\u6216\u975e\u4ea4\u6613\u65f6\u6bb5\u4e0d\u53d1\u5355',
		           shares=shares, limit_px='%.3f' % lp,
		           pct=('%.2f%%' % pct) if pct is not None else '--')
		gobj._tried_stocks.add(stock)
		return False, 'skip_backtest'
	ok = passorder_limit(C, gobj, stock, shares, lp, rmk)
	gobj._tried_stocks.add(stock)
	if ok:
		register_pending(gobj, rmk, stock, shares, 0, meta=meta)
		_log_buy_submit(gobj, stock, shares, last_px, lp, prev_c, pct, amount_est, rmk)
		return True, 'order_ok'
	return False, 'fail_order'


def init(C):
	g.strategy_tag = STRATEGY_TAG
	g.remark_prefix = 'YDC'
	g.accid = str(getattr(C, 'accountid', None) or getattr(C, 'account_id', None) or DEFAULT_ACCID).strip()
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'
	g.sector_name = getattr(C, 'sector_name', '') or DEFAULT_SECTOR
	g.max_amount_per_stock = float(getattr(C, 'max_amount_per_stock', DEFAULT_MAX_AMOUNT_PER_STOCK) or DEFAULT_MAX_AMOUNT_PER_STOCK)
	g.buy_premium_pct = float(getattr(C, 'buy_premium_pct', DEFAULT_BUY_PREMIUM_PCT) or DEFAULT_BUY_PREMIUM_PCT)
	g.buy_premium_retry_step = float(getattr(C, 'buy_premium_retry_step', DEFAULT_PREMIUM_RETRY_STEP) or DEFAULT_PREMIUM_RETRY_STEP)
	g.withdraw_secs = int(getattr(C, 'withdraw_secs', DEFAULT_WITHDRAW_SECS) or DEFAULT_WITHDRAW_SECS)
	g.max_retry = int(getattr(C, 'max_retry', 3) or 3)
	g.quick_trade = int(getattr(C, 'quick_trade', 2) or 2)
	g.live_orders = bool(getattr(C, 'live_orders', True))
	g.strategy_order_name = str(getattr(C, 'strategy_order_name', None) or '\u5361\u5f02\u52a8\u5c3e\u76d8\u4e70')[:20]
	g.min_shares = int(getattr(C, 'min_shares', DEFAULT_MIN_SHARES) or DEFAULT_MIN_SHARES)
	g.buy_code = 23 if g.account_type == 'STOCK' else 33
	g.waiting_list = []
	g.pending_orders = {}
	g._session_date = ''
	g._tried_stocks = set()
	g._last_handle_key = None
	g._logged_fill_remarks = set()
	g._buy_pool_snapshot = []
	print('=' * 64)
	print('%s init accid=%s sector=%r cap=%.0f premium=%.2f%%+step%.2f%% withdraw=%ds retry=%d live=%s' % (
		STRATEGY_TAG, g.accid, g.sector_name, g.max_amount_per_stock,
		g.buy_premium_pct * 100, g.buy_premium_retry_step * 100, g.withdraw_secs, g.max_retry, g.live_orders))
	print('%s \u677f\u575724h\u76d1\u63a7 \u53d8\u52a8\u624d\u6253\u65e5\u5fd7; \u4e70\u5165 14:55-15:00 \u5907\u6ce8=%s' % (STRATEGY_TAG, g.remark_prefix))
	print('=' * 64)


def _tick_prices_only(C, codes):
	return build_full_tick_prices(C, codes)


def handlebar(C):
	try:
		if not C.is_last_bar():
			return
	except Exception:
		pass

	now = datetime.datetime.now()
	hhmmss = now.strftime('%H%M%S')

	try:
		bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	except Exception:
		bar_date_str = now.strftime('%Y%m%d%H%M%S')
	d_str = bar_date_str[:8]

	bp = getattr(C, 'barpos', None)
	hkey = (d_str, bp, 'close_buy')
	if hkey == getattr(g, '_last_handle_key', None):
		return
	g._last_handle_key = hkey

	rollover_session(g, d_str)
	monitor_buy_pool(C, g, bar_date_str)
	if not in_handlebar_session(hhmmss):
		return

	sync_done_from_deals(g)
	process_cancel_retry(C, g, _tick_prices_only)

	if not g.accid:
		print('%s %s accid \u4e3a\u7a7a' % (STRATEGY_TAG, bar_date_str))
		return

	if not in_buy_window(hhmmss):
		return
	pool, _ = refresh_buy_pool(C, g)
	if not pool:
		return

	print('%s ========== %s \u5c3e\u76d8\u4e70\u5165\u626b\u63cf \u6c60=%d ==========' % (STRATEGY_TAG, bar_date_str, len(pool)))

	tick_full = build_full_tick_map(C, pool)
	tick_map = {}
	no_tick = []
	for code in pool:
		p = parse_tick_price(tick_full.get(code))
		if p:
			tick_map[code] = p
		else:
			no_tick.append(code)
	if no_tick:
		for code in no_tick:
			_log_event(g, '\u4e70\u5165\u672a\u6210\u529f', code, '\u80a1\u7968\u6c60\u5185\u65e0\u73b0\u4ef7\u6570\u636e')

	cash = get_account_cash(g)
	print('%s \u53ef\u7528\u8d44\u91d1=%.2f \u5355\u7968\u4e0a\u9650=%.0f' % (STRATEGY_TAG, cash, g.max_amount_per_stock))
	if cash <= 0 and should_passorder(C):
		print('%s %s [\u626b\u63cf\u7ec8\u6b62] \u539f\u56e0=\u53ef\u7528\u8d44\u91d1\u4e3a0' % (STRATEGY_TAG, bar_date_str))
		return

	stats = {}
	for stock in pool:
		if stock not in tick_map:
			stats['fail_no_price'] = stats.get('fail_no_price', 0) + 1
			continue
		cap = min(float(g.max_amount_per_stock), cash) if cash > 0 else float(g.max_amount_per_stock)
		_ok, st = try_buy_stock(C, g, stock, tick_map, tick_full, bar_date_str, cap)
		stats[st] = stats.get(st, 0) + 1
	process_cancel_retry(C, g, _tick_prices_only)
	log_scan_summary(g, bar_date_str, stats, extra='pool=%d' % len(pool))


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
