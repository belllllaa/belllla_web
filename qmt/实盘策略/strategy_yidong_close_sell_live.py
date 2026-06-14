#coding:gbk
import csv
import datetime
import os
import sys
import time

STRATEGY_TAG = '[\u5361\u5f02\u52a8\u5c3e\u76d8\u5356]'
DEFAULT_CSV = 'yidong_regulation_sell_watch.csv'
DEFAULT_SELL_WATCH_CSV_PATH = (
	'C:\\Users\\Dustin.hou\\belllla_web\\qmt\\'
	'\u5b9e\u76d8\u7b56\u7565\\yidong_regulation_sell_watch.csv'
)
SESSION_AM_START, SESSION_AM_END = 92500, 113000
SESSION_PM_START, SESSION_PM_END = 130000, 150000
TP_MONITOR_AM_START = 93000  # 16%止盈盘中监控：9:30开盘至收盘
SELL_WINDOW_START, SELL_WINDOW_END = 145500, 150000
REMARK_PREFIX = 'YDS'
DEFAULT_ACCID = '30262698'
DEFAULT_MIN_SHARES = 100
DEFAULT_MAX_HOLD_DAYS = 6
DEFAULT_TAKE_PROFIT_PCT = 16.0
STOP_MIN_HOLD_DAYS = 2  # 开仓后第2个交易日起(T+2)才检查止损，对齐回测


def _passorder_fn():
	fn = getattr(sys.modules.get('__main__'), 'passorder', None)
	return fn if fn else globals().get('passorder')


def _cancel_fn():
	fn = getattr(sys.modules.get('__main__'), 'cancel', None)
	return fn if fn else globals().get('cancel')


def _get_trade_detail_data_fn():
	fn = getattr(sys.modules.get('__main__'), 'get_trade_detail_data', None)
	return fn if fn else globals().get('get_trade_detail_data')


class G(object):
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


def _strategy_base_dir():
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
	if len(t) == 6 and t.isdigit():
		return (t + '.SH') if t.startswith(('60', '68', '51')) else (t + '.SZ')
	return t


def _normalize_position_code(pos):
	if pos is None:
		return ''
	ins = str(getattr(pos, 'm_strInstrumentID', None) or getattr(pos, 'stock_code', None) or '').strip()
	ex = str(getattr(pos, 'm_strExchangeID', None) or getattr(pos, 'exchange_id', None) or '').upper().strip()
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
	return (ins + '.SH') if ins.startswith(('60', '68', '51')) else (ins + '.SZ')


def _tag_to_yyyymmdd(raw):
	if raw is None:
		return None
	if isinstance(raw, str):
		s = raw.strip().replace('-', '').replace('/', '')
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


def _is_qmt_backtest_context(C):
	for a in ('do_back_test', 'doBackTest', 'isDoBackTest'):
		if bool(getattr(C, a, False)):
			return True
	rm = getattr(C, 'run_mode', None) or getattr(C, 'runMode', None)
	try:
		if rm is not None and int(rm) == 1:
			return True
	except (TypeError, ValueError):
		pass
	return isinstance(rm, str) and rm.strip().upper() in ('BACKTEST', 'TRUE', '1', 'T')


def _in_time_window(hms, start_hms, end_hms):
	try:
		w = int(hms)
		return int(start_hms) <= w <= int(end_hms)
	except (TypeError, ValueError):
		return False


def _wall_hhmmss():
	try:
		return int(datetime.datetime.now().strftime('%H%M%S'))
	except Exception:
		return None


def _in_handlebar_session(hms):
	if hms is None:
		return False
	try:
		h = int(hms)
	except (TypeError, ValueError):
		return False
	return (SESSION_AM_START <= h <= SESSION_AM_END) or (SESSION_PM_START <= h <= SESSION_PM_END)


def _in_sell_window(hms):
	return _in_time_window(hms, SELL_WINDOW_START, SELL_WINDOW_END)


def _in_tp_monitor_session(hms):
	"""16%止盈盘中监控：上午9:30-11:30、下午13:00-15:00。"""
	if hms is None:
		return False
	try:
		h = int(hms)
	except (TypeError, ValueError):
		return False
	return (TP_MONITOR_AM_START <= h <= SESSION_AM_END) or (SESSION_PM_START <= h <= SESSION_PM_END)


def _current_hhmmss(C):
	return getattr(g, '_handlebar_hhmmss', None) if _is_qmt_backtest_context(C) else _wall_hhmmss()


def _passorder_time_ok(C, sell_reason=None):
	hms = _current_hhmmss(C)
	if hms is None:
		return False
	try:
		h = int(hms)
	except (TypeError, ValueError):
		return False
	if SELL_WINDOW_START <= h <= SELL_WINDOW_END:
		return True
	if _is_tp_sell_reason(sell_reason):
		return _in_tp_monitor_session(h)
	return False


def _should_passorder(C, sell_reason=None):
	return (bool(getattr(g, 'live_orders', True)) and bool((g.accid or '').strip())
	        and not _is_qmt_backtest_context(C) and _passorder_time_ok(C, sell_reason))


def _stock_name(C, code):
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


def _watch_row_key(row):
	return (row.get('code') or '', row.get('open_date') or '')


def _int_shares(n):
	try:
		v = int(float(n))
	except (TypeError, ValueError):
		return 0
	return v if v > 0 else 0


def _float_price(v):
	try:
		x = float(v)
	except (TypeError, ValueError):
		return None
	return x if x > 0 else None


def _stop_ref_px(row, cost_px):
	"""止损基准价：优先 CSV 开仓价，否则账户成本。"""
	op = _float_price(row.get('open_buy_px'))
	if op is not None:
		return op
	return _float_price(cost_px)


def _effective_tp_price(row):
	"""CSV \u76f4\u63a5\u6b62\u76c8\u4ef7\u4f18\u5148\uff1b\u5426\u5219 \u5f00\u4ed3\u4ef7*(1+\u6b62\u76c8%%)\u3002"""
	tp = _float_price(row.get('tp_price'))
	if tp is not None:
		return tp
	op = _float_price(row.get('open_buy_px'))
	if op is None:
		return None
	pct = float(getattr(g, 'take_profit_pct', DEFAULT_TAKE_PROFIT_PCT) or DEFAULT_TAKE_PROFIT_PCT)
	return round(op * (1.0 + pct / 100.0), 3)


def _row_has_tp(row):
	return _effective_tp_price(row) is not None


def _is_tp_sell_reason(reason):
	return reason and '\u6b62\u76c8' in str(reason)


def _row_tp_log_fields(row):
	op = row.get('open_buy_px')
	tp = _effective_tp_price(row) if row else None
	op_s = ('%.3f' % float(op)) if op else '--'
	tp_s = ('%.3f' % float(tp)) if tp else '--'
	return op_s, tp_s


def _tp_gap_pct(last_px, tp):
	if not last_px or not tp:
		return None
	try:
		return (float(tp) / float(last_px) - 1.0) * 100.0
	except (TypeError, ValueError):
		return None


def _tp_watch_should_log(row_key, triggered):
	if triggered:
		return True
	now = time.time()
	ts_map = getattr(g, '_tp_watch_log_ts', None) or {}
	last = ts_map.get(row_key, 0)
	if now - last < 300:
		return False
	ts_map[row_key] = now
	g._tp_watch_log_ts = ts_map
	return True


def _resolve_sell_shares(row, can_use):
	"""CSV \u5356\u51fa\u80a1\u6570\u539f\u6837\u4f7f\u7528\uff08\u4e0d\u6574\u767e\uff09\uff1b\u4e0d\u8d85\u8fc7\u53ef\u5356\u3002\u65e7\u8868\u65e0\u5217\u5219\u5356\u51fa\u5168\u90e8\u53ef\u5356\u3002"""
	can_i = _int_shares(can_use)
	raw = row.get('sell_shares')
	if raw is None:
		return can_i
	csv_sh = _int_shares(raw)
	if csv_sh <= 0:
		return 0
	return min(csv_sh, can_i) if can_i > 0 else 0


def _sell_watch_snapshot(watch):
	rows = []
	for row in watch or []:
		sh = row.get('sell_shares')
		op = row.get('open_buy_px')
		tp = _effective_tp_price(row)
		rows.append((row.get('code') or '', row.get('open_date') or '',
		             int(row.get('sell_signal', 1) or 1),
		             None if sh is None else int(sh),
		             None if op is None else round(float(op), 4),
		             None if tp is None else round(float(tp), 4)))
	return tuple(sorted(rows))


def _diagnose_sell_row(C, code, row, pos_map, d_str, bar_dt, tick_map=None):
	"""\u8fd4\u56de (\u6301\u4ed3\u5929\u6570,\u6210\u672c,\u73b0\u4ef7,\u76c8\u4e8f%%,\u89e6\u53d1\u8bf4\u660e) \u4f9b\u5f85\u5356\u6c60\u590d\u76d8\u3002"""
	p = pos_map.get(code)
	cost = float(p.get('cost', 0) or 0) if p else 0.0
	last = tick_map.get(code) if tick_map else None
	if (last is None or last <= 0) and p:
		last = float(p.get('last', 0) or 0) or None
	if last is not None and last <= 0:
		last = None
	hd = _trading_hold_days(C, code, row.get('open_date'), d_str, bar_dt)
	ret = _pnl_pct(cost, last) if cost and last else None
	if not p:
		trig = '\u65e0\u6301\u4ed3'
	elif last is None or not cost:
		trig = '\u65e0\u73b0\u4ef7/\u6210\u672c'
	else:
		tp_ok, tp_reason = _tp_hit(row, last)
		if tp_ok:
			trig = tp_reason
		else:
			should, reason = _eval_sell_reason(C, code, row, d_str, bar_dt, last, cost)
			trig = reason if should else '\u7ee7\u7eed\u6301\u6709'
	return hd, cost, last, ret, trig


def _log_today_sell_pool(C, bar_dt, watch, pos_map):
	d_str = bar_dt[:8]
	items = []
	rows = list(watch or [])
	rows.sort(key=lambda r: (_watch_row_key(r), r.get('sell_shares') or 0))
	codes = [r.get('code') for r in rows if r.get('code')]
	tick_map = dict((c, px) for c, t in _full_ticks(C, codes).items() for px in [_tick_px(t)] if px)
	for row in rows:
		code = row.get('code') or ''
		nm = _stock_name(C, code)
		p = pos_map.get(code)
		can_use = int(p.get('can_use', 0) or 0) if p else 0
		sh = _resolve_sell_shares(row, can_use)
		if p and sh > 0:
			pos_s = '\u53ef\u5356%d \u672c\u7b14\u5356%d' % (can_use, sh)
		elif p and can_use > 0:
			pos_s = '\u53ef\u5356%d \u672c\u7b14\u80a1\u6570\u4e0d\u8db3' % can_use
		elif p:
			pos_s = '\u65e0\u53ef\u5356\u91cf'
		else:
			pos_s = '\u65e0\u6301\u4ed3'
		csv_sh_s = ('%d' % row['sell_shares']) if row.get('sell_shares') is not None else '\u65e7\u8868\u5168\u5356'
		op_s = ('%.3f' % row['open_buy_px']) if row.get('open_buy_px') else '--'
		tp_s = ('%.3f' % _effective_tp_price(row)) if _row_has_tp(row) else '--'
		hd, cost, last, ret, trig = _diagnose_sell_row(C, code, row, pos_map, d_str, bar_dt, tick_map)
		label = '%s(%s)' % (nm, code) if nm else str(code)
		items.append(
			'%s \u5f00\u4ed3=%s \u4fe1\u53f7=%s \u5356\u51fa\u80a1\u6570=%s \u5f00\u4ed3\u4ef7=%s \u6b62\u76c8\u4ef7=%s \u6301\u4ed3\u4ea4\u6613\u65e5=%s \u6210\u672c=%s \u73b0\u4ef7=%s \u76c8\u4e8f=%s \u89e6\u53d1=%s %s' % (
				label, row.get('open_date', '--'), row.get('sell_signal', '--'), csv_sh_s, op_s, tp_s,
				hd if hd is not None else '--',
				('%.3f' % cost) if cost else '--',
				('%.3f' % last) if last else '--',
				('%.2f%%' % ret) if ret is not None else '--',
				trig, pos_s))
	print('%s [\u4eca\u65e5\u5f85\u5356\u6c60] \u65e5\u671f=%s csv=%r \u6570\u91cf=%d \u89c4\u5219=\u4fe1\u53f70|\u6ee1%d\u65e5|\u6301>2\u65e5\u4e8f>=%.0f%%' % (
		STRATEGY_TAG, d_str, g.sell_csv_path, len(watch or []),
		int(g.max_hold_days), float(g.stop_loss_pct)))
	print('%s [\u4eca\u65e5\u5f85\u5356\u6c60] %s' % (
		STRATEGY_TAG, ' | '.join(items) if items else '\u65e0'))


def _positions_snapshot(pos_map):
	rows = []
	for code in sorted((pos_map or {}).keys()):
		p = pos_map[code] or {}
		rows.append((code, int(p.get('volume', 0) or 0), int(p.get('can_use', 0) or 0),
		             round(float(p.get('cost', 0) or 0), 4)))
	return tuple(rows)


def _log_account_positions(C, bar_dt, pos_map):
	"""????????????? CSV \u65e0\u6301\u4ed3 \u662f\u5426\u56e0\u63a5\u53e3\u672a\u8fd4\u56de\u6216\u4ee3\u7801\u4e0d\u5339\u914d\u3002"""
	gtd = _get_trade_detail_data_fn()
	raw_n = getattr(g, '_last_position_raw_count', None)
	print('%s [\u8d26\u6237\u6301\u4ed3] \u65f6\u95f4=%s \u8d26\u53f7=%s \u7c7b\u578b=%s \u63a5\u53e3=%s \u539f\u59cb\u6761\u6570=%s' % (
		STRATEGY_TAG, bar_dt, g.accid or '--', getattr(g, 'account_type', 'STOCK'),
		'OK' if gtd else '\u65e0get_trade_detail_data',
		raw_n if raw_n is not None else '--'))
	err = getattr(g, '_last_position_fetch_err', '') or ''
	if err:
		print('%s [\u8d26\u6237\u6301\u4ed3] \u67e5\u8be2\u5f02\u5e38 err=%r' % (STRATEGY_TAG, err))
	if not pos_map:
		print('%s [\u8d26\u6237\u6301\u4ed3] \u5f53\u524d\u65e0\u6301\u4ed3\u8bb0\u5f55\uff08\u76d8\u524d\u4e5f\u5e94\u53ef\u67e5\u5230\u6301\u4ed3\uff1b\u82e5\u786e\u6709\u6301\u4ed3\u8bf7\u6838\u5bf9\u8d44\u91d1\u8d26\u53f7\u4e0e\u5b9e\u76d8\u52fe\u9009\uff09' % (STRATEGY_TAG,))
		return
	items = []
	for code in sorted(pos_map.keys()):
		p = pos_map[code]
		nm = _stock_name(C, code)
		vol = int(p.get('volume', 0) or 0)
		can = int(p.get('can_use', 0) or 0)
		cost = float(p.get('cost', 0) or 0)
		last = float(p.get('last', 0) or 0)
		label = '%s(%s)' % (nm, code) if nm else str(code)
		items.append('%s \u6301\u4ed3=%d \u53ef\u5356=%d \u6210\u672c=%.3f \u73b0\u4ef7=%s' % (
			label, vol, can, cost, ('%.3f' % last) if last > 0 else '--'))
	print('%s [\u8d26\u6237\u6301\u4ed3] \u5171%d\u53ea %s' % (
		STRATEGY_TAG, len(pos_map), ' | '.join(items)))


def _monitor_sell_watch(C, bar_dt, d_str, force=False):
	"""24h CSV \u76d1\u63a7\uff1a\u6bcf\u6839 K \u7ebf\u91cd\u8bfb\uff1b\u4ec5 CSV \u5185\u5bb9\u53d8\u5316\u65f6\u6253\u5f85\u5356\u6c60\u65e5\u5fd7\u3002"""
	csv_changed = _ensure_sell_csv(d_str, force=force)
	watch = list(getattr(g, '_sell_watch', []) or [])
	cur = _sell_watch_snapshot(watch)
	prev = getattr(g, '_sell_watch_snapshot', None)
	pos_map = _positions()
	pos_snap = _positions_snapshot(pos_map)
	pos_changed = pos_snap != getattr(g, '_account_pos_snapshot', None)
	if cur == prev and not csv_changed and not pos_changed:
		return watch, False
	g._sell_watch_snapshot = cur
	if pos_changed:
		g._account_pos_snapshot = pos_snap
	if csv_changed:
		print('%s [CSV\u91cd\u8f7d] \u65f6\u95f4=%s \u884c\u6570=%d path=%r' % (
			STRATEGY_TAG, bar_dt, len(watch), g.sell_csv_path))
	if csv_changed or cur != prev or pos_changed:
		_log_today_sell_pool(C, bar_dt, watch, pos_map)
		_log_account_positions(C, bar_dt, pos_map)
	if not watch:
		err = getattr(g, '_sell_csv_load_err', '') or ''
		if err:
			print('%s %s CSV \u8bfb\u53d6\u5f02\u5e38 path=%r err=%r' % (
				STRATEGY_TAG, bar_dt, g.sell_csv_path, err))
	return watch, True


def _sell_csv_abs_if_file(path_str):
	if not path_str:
		return None
	p = os.path.normpath(os.path.abspath(str(path_str).strip()))
	return p if os.path.isfile(p) else None


def _default_sell_watch_csv_path():
	base = _strategy_base_dir()
	if not base:
		return ''
	return os.path.normpath(os.path.join(base, DEFAULT_CSV))


def _find_sell_watch_csv_walk_up():
	"""QMT cwd \u5e38\u4e3a bin.x64\uff1a\u5411\u4e0a\u67e5\u627e qmt/\u5b9e\u76d8\u7b56\u7565/yidong_regulation_sell_watch.csv\u3002"""
	try:
		cwd = os.path.abspath(os.getcwd())
	except Exception:
		return None
	cur = cwd
	for _ in range(14):
		for rel in (
			os.path.join('qmt', '\u5b9e\u76d8\u7b56\u7565', DEFAULT_CSV),
			os.path.join('\u5b9e\u76d8\u7b56\u7565', DEFAULT_CSV),
			DEFAULT_CSV,
		):
			cand = os.path.normpath(os.path.join(cur, rel))
			if os.path.isfile(cand):
				return cand
		parent = os.path.dirname(cur)
		if not parent or parent == cur:
			break
		cur = parent
	return None


def _iter_sell_watch_csv_candidates():
	seen = set()

	def _add(p):
		if not p:
			return
		n = os.path.normpath(os.path.abspath(str(p).strip()))
		if n in seen:
			return
		seen.add(n)
		yield n

	for p in (
		DEFAULT_SELL_WATCH_CSV_PATH,
		_default_sell_watch_csv_path(),
		_find_sell_watch_csv_walk_up(),
		os.environ.get('BELLLLA_WEB_ROOT', '').strip(),
		os.environ.get('YIDONG_SELL_CSV_DIR', '').strip(),
	):
		if not p:
			continue
		if os.path.isfile(str(p)):
			for x in _add(str(p)):
				yield x
			continue
		if os.path.isdir(str(p)):
			for x in _add(os.path.join(str(p), DEFAULT_CSV)):
				yield x

	prof = os.environ.get('USERPROFILE', '') or ''
	for p in (
		os.path.join(prof, 'belllla_web', 'qmt', '\u5b9e\u76d8\u7b56\u7565', DEFAULT_CSV),
		os.path.join(prof, 'Documents', 'belllla_web', 'qmt', '\u5b9e\u76d8\u7b56\u7565', DEFAULT_CSV),
	):
		for x in _add(p):
			yield x


def _resolve_csv_path(context_raw):
	cr = (context_raw or '').strip()
	if cr:
		got = _sell_csv_abs_if_file(cr)
		if got:
			return got, 'context'
	for ev in ('YIDONG_SELL_WATCH_CSV', 'BELLLLA_YIDONG_SELL_CSV'):
		got = _sell_csv_abs_if_file(os.environ.get(ev))
		if got:
			return got, ev
	for cand in _iter_sell_watch_csv_candidates():
		if cand and os.path.isfile(cand):
			return os.path.normpath(os.path.abspath(cand)), 'auto_found'
	if cr:
		return os.path.normpath(os.path.abspath(cr)), 'context_missing_file'
	fb = _default_sell_watch_csv_path() or os.path.join(os.path.abspath(os.getcwd()), DEFAULT_CSV)
	return fb, 'fallback_default'


_COMBO_SHARES_OPEN_HDR = (
	'\u5356\u51fa\u80a1\u6570,\u5f00\u4ed3\u4ef7',
	'sell_shares,open_price',
	'shares,open_price',
	'shares,open_buy_px',
)


def _sell_csv_header_map(row):
	"""\u8868\u5934\u884c -> \u5217\u540d\u7d22\u5f15\u3002"""
	keys = {
		'code': ('code', 'symbol', 'stock', 'stock_code', 'ts_code', '\u80a1\u7968\u4ee3\u7801'),
		'open_date': ('open_date', 'open', 'buy_date', '\u5f00\u4ed3\u65e5'),
		'signal': ('signal', 'sell_signal', '\u89e6\u53d1\u5356\u51fa\u4fe1\u53f7'),
		'shares': ('sell_shares', 'shares', 'volume', '\u5356\u51fa\u80a1\u6570', '\u4e70\u5165\u80a1\u6570'),
		'open_buy_px': ('open_buy_px', 'buy_price', 'open_price', 'cost', '\u5f00\u4ed3\u4ef7', '\u4e70\u5165\u4ef7'),
		'tp_price': ('tp_price', 'take_profit', 'take_profit_price', '\u6b62\u76c8\u4ef7', '\u76ee\u6807\u4ef7'),
	}
	mp = {}
	for i, raw in enumerate(row):
		raw_s = (raw or '').strip()
		h = raw_s.lower()
		if not h or h.startswith('#'):
			continue
		if raw_s in _COMBO_SHARES_OPEN_HDR or h in _COMBO_SHARES_OPEN_HDR:
			mp['shares'] = i
			mp['open_buy_px'] = i
			continue
		for name, aliases in keys.items():
			if h in aliases or raw_s in aliases:
				mp[name] = i
	if 'code' in mp and 'open_date' in mp:
		return mp
	return None


def _cell(row, idx):
	if idx is None or idx >= len(row):
		return ''
	return (row[idx] or '').strip()


def _parse_shares_open_px_cell(text):
	"""'27000' / '27000,' / '27000,10.5' -> (shares, open_px)"""
	if not text:
		return None, None
	s = text.strip()
	if not s:
		return None, None
	if ',' in s:
		a, _, b = s.partition(',')
		csv_sh = None
		if a.strip():
			try:
				csv_sh = int(float(a.strip()))
			except (TypeError, ValueError):
				csv_sh = 0
		open_buy_px = _float_price(b.strip()) if b.strip() else None
		return csv_sh, open_buy_px
	try:
		return int(float(s)), None
	except (TypeError, ValueError):
		return 0, None


def _parse_sell_watch_row(row, col_map=None):
	if col_map:
		a = _cell(row, col_map.get('code'))
		b = _cell(row, col_map.get('open_date'))
		c = _cell(row, col_map.get('signal'))
		d = _cell(row, col_map.get('shares'))
		e = _cell(row, col_map.get('open_buy_px'))
		f = _cell(row, col_map.get('tp_price'))
	else:
		a = row[0].strip() if row else ''
		b = row[1].strip() if len(row) > 1 else ''
		c = row[2].strip() if len(row) > 2 else ''
		d = row[3].strip() if len(row) > 3 else ''
		e = row[4].strip() if len(row) > 4 else ''
		f = row[5].strip() if len(row) > 5 else ''
	if not a or a.startswith('#'):
		return None
	_hdr = ('code', 'symbol', 'stock', 'stock_code', 'ts_code', '\u80a1\u7968\u4ee3\u7801')
	if a.lower() in _hdr or a in _hdr:
		return None
	code = _canonical_stock_code(a)
	od = _tag_to_yyyymmdd(b)
	if not code or not od:
		return None
	try:
		sig = int(float(c))
	except (TypeError, ValueError):
		sig = 1
	shares_same_col = False
	if col_map:
		si = col_map.get('shares')
		oi = col_map.get('open_buy_px')
		shares_same_col = si is not None and oi is not None and si == oi
	csv_sh = None
	open_buy_px = None
	tp_price = None
	if shares_same_col or (d and ',' in d):
		csv_sh, open_buy_px = _parse_shares_open_px_cell(d)
		tp_raw = f if f else (e if shares_same_col else '')
	elif d:
		try:
			csv_sh = int(float(d))
		except (TypeError, ValueError):
			csv_sh = 0
		if col_map and 'open_buy_px' in col_map and not shares_same_col:
			open_buy_px = _float_price(e)
			tp_raw = f
		elif not col_map:
			open_buy_px = _float_price(e) if e else None
			tp_raw = f if f else ''
			if not open_buy_px and e and not f:
				tp_raw = e
				open_buy_px = None
		else:
			tp_raw = f
	else:
		tp_raw = f if f else ''
	if tp_raw:
		tp_price = _float_price(tp_raw)
	return {
		'code': code, 'open_date': od, 'sell_signal': sig,
		'sell_shares': csv_sh, 'open_buy_px': open_buy_px, 'tp_price': tp_price,
	}


def _load_sell_watch_csv(path_str):
	rows = []
	if not path_str or not os.path.isfile(path_str):
		return rows, 'not_a_file'
	last_err = None
	for enc in ('utf-8-sig', 'gbk', 'utf-8'):
		try:
			col_map = None
			with open(path_str, 'r', encoding=enc, newline='') as f:
				for row in csv.reader(f):
					if not row or len(row) < 3:
						continue
					if col_map is None:
						hm = _sell_csv_header_map(row)
						if hm is not None:
							col_map = hm
							continue
					parsed = _parse_sell_watch_row(row, col_map)
					if parsed:
						rows.append(parsed)
			return rows, None
		except Exception as e:
			last_err = str(e)[:100]
			rows = []
	return rows, last_err or 'read_failed'


def _ensure_sell_csv(d_str, force=False):
	"""force=True \u65f6\u5ffd\u7f13\u5b58\u91cd\u8bfb\uff08\u5c3e\u76d8\u4e0b\u5355\u524d\u5fc5\u987b\u8d70\u6b64\u5206\u652f\uff09\u3002"""
	path = g.sell_csv_path
	if not path:
		g._sell_watch = []
		return False
	need = bool(force)
	if not need:
		try:
			mt = os.path.getmtime(path)
		except Exception:
			mt = None
		if mt != getattr(g, '_sell_csv_mtime', None):
			need = True
		elif d_str and getattr(g, '_sell_csv_loaded_day', None) != d_str:
			need = True
	if not need:
		return False
	prev = list(getattr(g, '_sell_watch', []) or [])
	mp, err = _load_sell_watch_csv(path)
	g._sell_watch = mp
	g._sell_csv_load_err = err or ''
	try:
		g._sell_csv_mtime = os.path.getmtime(path)
	except Exception:
		g._sell_csv_mtime = None
	if d_str:
		g._sell_csv_loaded_day = d_str
	changed = (prev != mp)
	if changed:
		g._tried_stocks = set()
	return changed


def _tick_px(t):
	if t is None:
		return None
	for k in ('lastPrice', 'last_price', 'm_nLastPrice', 'nLast'):
		v = getattr(t, k, None) if not isinstance(t, dict) else t.get(k)
		if v is not None:
			try:
				x = float(v)
				return x if x > 0 else None
			except Exception:
				pass
	return None


def _full_ticks(C, codes):
	out = {}
	if codes and hasattr(C, 'get_full_tick'):
		try:
			out.update(C.get_full_tick(codes) or {})
		except Exception:
			pass
	return out


def _positions():
	gtd = _get_trade_detail_data_fn()
	out = {}
	g._last_position_fetch_err = ''
	g._last_position_raw_count = 0
	if not gtd:
		g._last_position_fetch_err = 'no_get_trade_detail_data'
		return out
	if not (g.accid or '').strip():
		g._last_position_fetch_err = 'empty_accid'
		return out
	try:
		raw = gtd(g.accid, g.account_type, 'position') or []
		g._last_position_raw_count = len(raw)
		for p in raw:
			code = _canonical_stock_code(_normalize_position_code(p)) or ''
			if not code:
				continue
			vol = int(getattr(p, 'm_nVolume', 0) or 0)
			can = int(getattr(p, 'm_nCanUseVolume', 0) or 0)
			if vol <= 0 and can <= 0:
				continue
			last = float(getattr(p, 'm_dLastPrice', 0) or getattr(p, 'last_price', 0) or 0)
			prev = out.get(code)
			if prev:
				vol += int(prev.get('volume', 0) or 0)
				can += int(prev.get('can_use', 0) or 0)
				if last <= 0:
					last = float(prev.get('last', 0) or 0)
			out[code] = {
				'volume': vol,
				'can_use': can,
				'cost': float(getattr(p, 'm_dOpenPrice', 0) or getattr(p, 'cost_price', 0) or 0),
				'last': last,
			}
	except Exception as e:
		g._last_position_fetch_err = str(e)[:120]
	return out


# \u4e0a\u4ea4\u6240 2026 \u516c\u544a\u4f11\u5e02\uff08\u4e0d\u542b\u5468\u672b\uff09\uff1b\u5176\u4ed6\u5e74\u4efd\u4ec5\u6392\u9664\u5468\u672b
_CN_SSE_EXTRA_HOLIDAYS = frozenset({
	'20260101', '20260102', '20260103',
	'20260215', '20260216', '20260217', '20260218', '20260219',
	'20260220', '20260221', '20260222', '20260223',
	'20260404', '20260405', '20260406',
	'20260501', '20260502', '20260503', '20260504', '20260505',
	'20260619', '20260620', '20260621',
	'20260925', '20260926', '20260927',
	'20261001', '20261002', '20261003', '20261004', '20261005', '20261006', '20261007',
})


def _is_cn_sse_trading_day(ymd):
	if not ymd:
		return False
	s = str(ymd)[:8]
	if len(s) < 8 or not s.isdigit():
		return False
	try:
		dt = datetime.datetime.strptime(s, '%Y%m%d')
	except ValueError:
		return False
	if dt.weekday() >= 5:
		return False
	return s not in _CN_SSE_EXTRA_HOLIDAYS


def _trading_days_after_open(open_yyyymmdd, asof_yyyymmdd):
	"""\u5f00\u4ed3\u65e5\u4e4b\u540e\u5230\u5f53\u65e5\u542b\u5c3e\u7684\u4ea4\u6613\u65e5\u5929\u6570\uff08\u4e0d\u542b\u5468\u672b/\u8282\u5047\u65e5\uff09\u3002"""
	if not open_yyyymmdd or not asof_yyyymmdd or open_yyyymmdd > asof_yyyymmdd:
		return 0
	if open_yyyymmdd == asof_yyyymmdd:
		return 0
	n = 0
	d = datetime.datetime.strptime(open_yyyymmdd, '%Y%m%d')
	e = datetime.datetime.strptime(asof_yyyymmdd, '%Y%m%d')
	while d <= e:
		s = d.strftime('%Y%m%d')
		if _is_cn_sse_trading_day(s) and open_yyyymmdd < s <= asof_yyyymmdd:
			n += 1
		d += datetime.timedelta(days=1)
	return n


def _trading_hold_days(C, stock, open_yyyymmdd, asof_yyyymmdd, end_time_str):
	"""\u6301\u4ed3\u4ea4\u6613\u65e5\u6570\uff1a\u5f00\u4ed3\u65e5<d<=\u5f53\u65e5 \u7684 A \u80a1\u4ea4\u6613\u65e5\u4e2a\u6570\uff08\u8282\u5047\u65e5\u4e0d\u8ba1\uff09\u3002"""
	if not open_yyyymmdd or not asof_yyyymmdd or open_yyyymmdd > asof_yyyymmdd:
		return None
	if open_yyyymmdd == asof_yyyymmdd:
		return 0
	fallback = _trading_days_after_open(open_yyyymmdd, asof_yyyymmdd)
	if not hasattr(C, 'get_market_data_ex'):
		return fallback
	try:
		kw = dict(period='1d', count=60, subscribe=False)
		if end_time_str:
			kw['end_time'] = end_time_str
		data = C.get_market_data_ex([], [stock], **kw) or {}
		stk = data.get(stock)
		dates = []
		if isinstance(stk, dict):
			for k in ('stime', 'time', 'timetag', 'date'):
				if k in stk and stk[k] is not None:
					for x in list(stk[k]):
						d8 = _tag_to_yyyymmdd(x)
						if d8 and _is_cn_sse_trading_day(d8):
							dates.append(d8)
					break
		if not dates:
			return fallback
		md_n = sum(1 for d in sorted(set(dates)) if open_yyyymmdd < d <= asof_yyyymmdd)
		return md_n
	except Exception:
		return fallback


def _tp_hit(row, last_px):
	tp = _effective_tp_price(row)
	if tp is None or not last_px:
		return False, ''
	if float(last_px) >= tp - 1e-6:
		return True, '\u6b62\u76c8\u4ef7\u89e6\u8fbe(%.3f)' % tp
	return False, ''


def _eval_sell_reason(C, stock, row, asof_yyyymmdd, end_time_str, last_px, cost_px, tp_only=False):
	tp_ok, tp_reason = _tp_hit(row, last_px)
	if tp_only:
		return (tp_ok, tp_reason) if tp_ok else (False, '')
	if tp_ok:
		return True, tp_reason
	if int(row.get('sell_signal', 1)) == 0:
		return True, 'G0\u89e6\u53d1\u5356\u51fa\u4fe1\u53f70'
	open_d = row.get('open_date')
	hd = _trading_hold_days(C, stock, open_d, asof_yyyymmdd, end_time_str)
	if hd is not None and hd >= int(g.max_hold_days):
		return True, '\u6301\u6ee1%d\u4ea4\u6613\u65e5' % int(g.max_hold_days)
	stop_min = int(getattr(g, 'stop_min_hold_days', STOP_MIN_HOLD_DAYS) or STOP_MIN_HOLD_DAYS)
	ref_px = _stop_ref_px(row, cost_px)
	if hd is not None and hd >= stop_min and ref_px and last_px:
		ret_pct = (float(last_px) / float(ref_px) - 1.0) * 100.0
		if ret_pct <= -float(g.stop_loss_pct) + 1e-6:
			return True, '\u6b62\u635f%.0f%%(\u5f00\u4ed3\u4ef7%.3f\u6301%d\u65e5,\u6d6e\u4e8f%.2f%%)' % (
				float(g.stop_loss_pct), ref_px, hd, ret_pct)
	return False, ''


def _pnl_pct(cost_px, fill_px):
	try:
		c, p = float(cost_px), float(fill_px)
		return (p / c - 1.0) * 100.0 if c > 0 else None
	except (TypeError, ValueError):
		return None


def _limit_sell(last_px):
	try:
		px = float(last_px) * (1.0 - float(g.sell_discount_pct))
		return max(0.01, round(px, 3)) if px > 0 else None
	except Exception:
		return None


def _limit_sell_for_row(row, last_px, reason):
	tp = _effective_tp_price(row)
	if tp is not None and reason and '\u6b62\u76c8' in reason:
		return max(0.01, round(tp, 3))
	return _limit_sell(last_px)


def _remark(stock, shares, retry=0, open_date=None):
	c6 = (stock or '').split('.')[0][:6]
	od4 = (str(open_date or '')[-4:]) if open_date else '0000'
	base = '%s%s%s_%d' % (REMARK_PREFIX, c6, od4, int(shares))
	return ((base + 'R%d' % retry) if retry else base)[:23]


def _log(tag, stock, reason, **kw):
	parts = ['%s [%s] \u4ee3\u7801=%s \u539f\u56e0=%s' % (STRATEGY_TAG, tag, stock or '--', reason or '--')]
	for k, v in kw.items():
		if v is not None:
			parts.append('%s=%s' % (k, v))
	print(' '.join(parts))


def _pending_sell(stock):
	return any(p.get('stock') == stock and p.get('side') == 'sell' for p in g.pending_orders.values())


def _passorder_go(C, stock, volume, remark, limit_px):
	po = _passorder_fn()
	if po is None:
		_log('\u5356\u51fa\u672a\u6210\u529f', stock, '\u65e0passorder', shares=volume, limit_px=limit_px, remark=remark)
		return False
	try:
		sh = int(volume)
		lp = max(0.01, round(float(limit_px), 3))
	except Exception:
		return False
	if sh <= 0:
		_log('\u5356\u51fa\u672a\u6210\u529f', stock, '\u80a1\u6570\u65e0\u6548', shares=sh)
		return False
	try:
		ret = po(int(g.sell_code), 1101, g.accid, str(stock), 11, lp, sh,
		         str(g.strategy_order_name), int(g.quick_trade), str(remark)[:23], C)
	except Exception as e:
		_log('\u5356\u51fa\u672a\u6210\u529f', stock, 'passorder\u5f02\u5e38:%s' % e, shares=sh, limit_px=lp, remark=remark)
		return False
	if ret is False:
		_log('\u5356\u51fa\u672a\u6210\u529f', stock, '\u5238\u5546\u62d2\u5355', shares=sh, limit_px=lp, remark=remark)
		return False
	return True


def _reg_pending(remark, stock, shares, retry, meta):
	g.waiting_list.append(remark)
	g.pending_orders[remark] = {'time': time.time(), 'stock': stock, 'side': 'sell',
	                            'shares': int(shares), 'retry': int(retry), 'meta': dict(meta or {})}


def _deal_attr(deal, *names):
	for n in names:
		v = getattr(deal, n, None) if not isinstance(deal, dict) else deal.get(n)
		if v is not None:
			return v
	return None


def _log_fill(remark, deal, pinfo):
	if remark in g._logged_fill_remarks:
		return
	g._logged_fill_remarks.add(remark)
	meta = pinfo.get('meta') or {}
	fp = _deal_attr(deal, 'm_dPrice', 'm_dTradedPrice', 'price')
	fv = _deal_attr(deal, 'm_nVolume', 'volume')
	sh = int(fv) if fv is not None else int(pinfo.get('shares', 0) or 0)
	st = pinfo.get('stock') or meta.get('stock') or '--'
	cost = meta.get('cost_px')
	pnl = _pnl_pct(cost, fp) if cost and fp else meta.get('ret_pct')
	row_stub = {'open_buy_px': meta.get('open_buy_px'), 'tp_price': meta.get('tp_price')}
	op_s, tp_s = _row_tp_log_fields(row_stub)
	print('%s [\u5356\u51fa\u6210\u4ea4] \u4ee3\u7801=%s \u80a1\u6570=%d \u6210\u4ea4\u4ef7=%s \u5356\u51fa\u539f\u56e0=%s \u5f00\u4ed3\u65e5=%s \u6301\u4ed3\u5929\u6570=%s \u6210\u672c=%s \u5f00\u4ed3\u4ef7=%s \u6b62\u76c8\u4ef7=%s \u76c8\u4e8f\u6bd4\u4f8b=%s \u5907\u6ce8=%s' % (
		STRATEGY_TAG, st, sh, ('%.3f' % fp) if fp else '--', meta.get('reason', '--'),
		meta.get('open_date', '--'), meta.get('hold_days', '--'),
		('%.3f' % cost) if cost else '--', op_s, tp_s,
		('%.2f%%' % pnl) if pnl is not None else '--', remark))


def _sync_deals():
	gtd = _get_trade_detail_data_fn()
	if not gtd or not g.waiting_list:
		return
	try:
		deals = gtd(g.accid, g.account_type, 'deal') or []
	except Exception:
		return
	by_rmk = dict((str(_deal_attr(d, 'm_strRemark', 'remark') or ''), d) for d in deals)
	by_rmk.pop('', None)
	done = []
	for r in list(g.waiting_list):
		if r in by_rmk:
			p = g.pending_orders.get(r)
			if p:
				_log_fill(r, by_rmk[r], p)
			done.append(r)
	for r in done:
		g.waiting_list.remove(r)
		g.pending_orders.pop(r, None)


def _cancel_retry(C):
	if not g.waiting_list:
		return
	hms = _current_hhmmss(C)
	if hms is None or not _in_handlebar_session(hms):
		return
	gtd, cancel = _get_trade_detail_data_fn(), _cancel_fn()
	if not gtd:
		return
	now = time.time()
	try:
		orders = gtd(g.accid, g.account_type, 'order') or []
	except Exception:
		orders = []
	DONE, CANCEL = 56, (53, 54, 57)
	rm, retry_q = [], []
	for r in list(g.waiting_list):
		p = g.pending_orders.get(r)
		if not p or now - p['time'] < g.withdraw_secs:
			continue
		om = None
		for o in orders:
			if (getattr(o, 'm_strRemark', '') or '') == r:
				om = o
				break
		if not om:
			continue
		st = getattr(om, 'm_nOrderStatus', 0)
		oid = getattr(om, 'm_strOrderSysID', '') or ''
		stock = p.get('stock') or ''
		if st == DONE:
			_log_fill(r, om, p)
			rm.append(r)
		elif st in CANCEL:
			_log('\u5356\u51fa\u672a\u6210\u4ea4', stock, '\u59d4\u6258\u5df2\u64a4/\u5e9f\u5355', remark=r, retry=p.get('retry', 0))
			rm.append(r)
			if can_new_order:
				retry_q.append((r, p))
		elif p.get('retry', 0) >= g.max_retry:
			_log('\u5356\u51fa\u672a\u6210\u4ea4', stock, '\u8fbe\u6700\u5927\u91cd\u8bd5%d' % g.max_retry, remark=r)
			rm.append(r)
		elif cancel and oid and _should_passorder(C, (p.get('meta') or {}).get('reason')):
			try:
				cancel(oid, g.accid, g.account_type, C)
				print('%s [\u64a4\u5355\u6210\u529f] \u4ee3\u7801=%s \u5907\u6ce8=%s orderId=%s' % (STRATEGY_TAG, stock, r, oid))
			except Exception as e:
				_log('\u5356\u51fa\u672a\u6210\u529f', stock, '\u64a4\u5355\u5f02\u5e38:%s' % e, orderId=oid, remark=r)
				continue
			retry_q.append((r, p))
	for r in rm:
		if r in g.waiting_list:
			g.waiting_list.remove(r)
		g.pending_orders.pop(r, None)
	tick_cache = {}
	for old_r, p in retry_q:
		retry = int(p.get('retry', 0)) + 1
		if retry > g.max_retry:
			continue
		stock = p.get('stock')
		sh = int(p.get('shares', 0) or 0)
		meta = dict(p.get('meta') or {})
		reason = meta.get('reason')
		if not _should_passorder(C, reason):
			continue
		if stock not in tick_cache:
			tick_cache.update(dict((c, px) for c, t in _full_ticks(C, [stock]).items()
			                       for px in [_tick_px(t)] if px))
		last = tick_cache.get(stock)
		if not last:
			_log('\u91cd\u6302\u672a\u6210\u529f', stock, '\u65e0\u73b0\u4ef7', retry=retry)
			continue
		row_stub = {'open_buy_px': meta.get('open_buy_px'), 'tp_price': meta.get('tp_price')}
		if _is_tp_sell_reason(reason):
			lp = _limit_sell_for_row(row_stub, last, reason)
		else:
			lp = _limit_sell(last)
		if not lp:
			_log('\u91cd\u6302\u672a\u6210\u529f', stock, '\u9650\u4ef7\u5931\u8d25', retry=retry)
			continue
		nr = _remark(stock, sh, retry, meta.get('open_date'))
		op_s, tp_s = _row_tp_log_fields(row_stub)
		meta['last_px'] = last
		meta['limit_px'] = lp
		if _passorder_go(C, stock, sh, nr, lp):
			_reg_pending(nr, stock, sh, retry, meta)
			print('%s [\u64a4\u5355\u91cd\u6302] \u4ee3\u7801=%s \u80a1\u6570=%d retry=%d \u73b0\u4ef7=%.3f \u9650\u4ef7=%.3f \u5f00\u4ed3\u4ef7=%s \u6b62\u76c8\u4ef7=%s \u5907\u6ce8=%s' % (
				STRATEGY_TAG, stock, sh, retry, last, lp, op_s, tp_s, nr))


def _log_watch(code, row, cost_px, last_px, hold_days, should_sell, reason, shares=0, tp_intraday=False):
	ret = _pnl_pct(cost_px, last_px) if cost_px and last_px else None
	action = '\u89e6\u53d1\u5356\u51fa' if should_sell else ('\u672a\u5356(\u65e0\u53ef\u5356\u91cf)' if shares <= 0 and reason else '\u7ee7\u7eed\u6301\u4ed3')
	tp = _effective_tp_price(row) if row else None
	gap = _tp_gap_pct(last_px, tp)
	if should_sell and reason:
		suffix = ' \u89e6\u53d1\u539f\u56e0=' + reason
	elif _row_has_tp(row) and last_px and tp and not should_sell:
		suffix = ' \u6b62\u76c8\u76d1\u63a7\u4e2d(\u8ddd\u6b62\u76c8%.2f%%)' % gap if gap is not None else ' \u6b62\u76c8\u76d1\u63a7\u4e2d'
	elif not should_sell and hold_days is not None and ret is not None:
		stop_min = int(getattr(g, 'stop_min_hold_days', STOP_MIN_HOLD_DAYS) or STOP_MIN_HOLD_DAYS)
		ref = _stop_ref_px(row, cost_px) if row else None
		stop_ret = _pnl_pct(ref, last_px) if ref and last_px else ret
		suffix = ' \u672a\u8fbe\u6807(\u4ea4\u6613\u65e5%d/%d \u5f00\u4ed3\u4ef7\u76c8\u4e8f%.2f%% \u6b62\u635f<=-%.0f%% \u9700\u2265%dd)' % (
			hold_days, int(g.max_hold_days), stop_ret if stop_ret is not None else ret,
			float(g.stop_loss_pct), stop_min)
	elif not should_sell:
		suffix = ' \u672a\u8fbe\u5356\u51fa\u6761\u4ef6'
	else:
		suffix = ''
	csv_sh = row.get('sell_shares')
	csv_sh_s = str(csv_sh) if csv_sh is not None else '\u65e7\u8868\u5168\u5356'
	op_s, tp_s = _row_tp_log_fields(row)
	tag = '\u6b62\u76c8\u76d1\u63a7' if tp_intraday else '\u76d1\u63a7'
	print('%s [%s] \u4ee3\u7801=%s \u5f00\u4ed3\u65e5=%s \u4fe1\u53f7=%s \u5356\u51fa\u80a1\u6570=%s \u5f00\u4ed3\u4ef7=%s \u6b62\u76c8\u4ef7=%s \u672c\u7b14\u5356=%s \u6301\u4ed3\u4ea4\u6613\u65e5=%s \u6210\u672c=%s \u73b0\u4ef7=%s \u76c8\u4e8f=%s \u52a8\u4f5c=%s%s' % (
		STRATEGY_TAG, tag, code, row.get('open_date', '--'), row.get('sell_signal', '--'), csv_sh_s, op_s, tp_s,
		shares if shares else '--',
		hold_days if hold_days is not None else '--',
		('%.3f' % cost_px) if cost_px else '--',
		('%.3f' % last_px) if last_px else '--',
		('%.2f%%' % ret) if ret is not None else '--', action, suffix))


def _run_sell_pass(C, bar_dt, d_str, watch, pos_map, stats, tp_only=False):
	if not watch:
		return
	for row in watch:
		if tp_only and not _row_has_tp(row):
			continue
		code = row.get('code') or ''
		p = pos_map.get(code)
		if not p:
			continue
		can_use = int(p.get('can_use', 0) or 0)
		cost_px = float(p.get('cost', 0) or 0)
		hd = _trading_hold_days(C, code, row.get('open_date'), d_str, bar_dt)
		if row.get('sell_shares') is not None and _int_shares(row.get('sell_shares')) <= 0:
			continue
		if can_use <= 0:
			continue
		shares = _resolve_sell_shares(row, can_use)
		if shares <= 0:
			continue
		rkey = _watch_row_key(row)
		if rkey in g._tried_stocks:
			stats['skip_tried'] = stats.get('skip_tried', 0) + 1
			continue
		tick_map = dict((c, px) for c, t in _full_ticks(C, [code]).items()
		                for px in [_tick_px(t)] if px)
		last = tick_map.get(code)
		should, reason = _eval_sell_reason(
			C, code, row, d_str, bar_dt, last, cost_px, tp_only=tp_only,
		)
		ret_pct = (float(last) / float(cost_px) - 1.0) * 100.0 if cost_px and last else None
		if tp_only:
			rkey = _watch_row_key(row)
			if _tp_watch_should_log(rkey, should):
				_log_watch(code, row, cost_px, last, hd, should, reason, shares, tp_intraday=True)
		if not should:
			if tp_only:
				stats['skip_tp'] = stats.get('skip_tp', 0) + 1
			else:
				stats['skip_hold'] = stats.get('skip_hold', 0) + 1
			continue
		meta = {
			'open_date': row.get('open_date'), 'hold_days': hd, 'cost_px': cost_px,
			'ret_pct': ret_pct, 'reason': reason, 'stock': code,
			'csv_shares': row.get('sell_shares'),
			'open_buy_px': row.get('open_buy_px'),
			'tp_price': _effective_tp_price(row),
		}
		_ok, tag = _try_sell(C, code, shares, tick_map, reason, meta, row=row)
		stats[tag] = stats.get(tag, 0) + 1
		g._tried_stocks.add(rkey)


def _scan_summary(bar_dt, stats, extra=''):
	parts = ['%s [\u626b\u63cf\u6c47\u603b] %s' % (STRATEGY_TAG, bar_dt)]
	labels = {
		'order_ok': '\u59d4\u6258\u6210\u529f', 'fail_order': '\u4e0b\u5355\u5931\u8d25', 'fail_no_price': '\u65e0\u73b0\u4ef7',
		'fail_shares': '\u80a1\u6570\u4e0d\u8db3', 'fail_limit': '\u9650\u4ef7\u5931\u8d25', 'skip_pending': '\u5728\u9014\u5355',
		'skip_tried': '\u5df2\u5904\u7406', 'skip_backtest': '\u56de\u6d4b\u4e0d\u53d1', 'skip_hold': '\u7ee7\u7eed\u6301\u4ed3',
		'skip_no_pos': '\u65e0\u6301\u4ed3', 'skip_can_use': '\u53ef\u5356\u4e0d\u8db3',
		'skip_csv_shares': 'CSV\u80a1\u6570\u65e0\u6548', 'skip_shares_cap': 'CSV\u8d85\u53ef\u5356',
		'skip_tp': '\u672a\u89e6\u53ca\u6b62\u76c8\u4ef7',
	}
	for k in ('order_ok', 'fail_order', 'fail_no_price', 'fail_shares', 'fail_limit',
	          'skip_pending', 'skip_tried', 'skip_backtest', 'skip_hold', 'skip_no_pos', 'skip_can_use',
	          'skip_csv_shares', 'skip_shares_cap', 'skip_tp'):
		if stats.get(k):
			parts.append('%s=%d' % (labels.get(k, k), stats[k]))
	if extra:
		parts.append(extra)
	print(' | '.join(parts))


def _try_sell(C, stock, shares, tick_map, reason, meta, row=None):
	if shares <= 0:
		_log('\u5356\u51fa\u672a\u6210\u529f', stock, '\u5356\u51fa\u80a1\u6570\u65e0\u6548', shares=shares, sell_reason=reason)
		return False, 'fail_shares'
	if _pending_sell(stock):
		_log('\u5356\u51fa\u8df3\u8fc7', stock, '\u5df2\u6709\u5356\u5355\u5728\u9014', sell_reason=reason)
		return False, 'skip_pending'
	last = tick_map.get(stock)
	if not last or last <= 0:
		_log('\u5356\u51fa\u672a\u6210\u529f', stock, '\u65e0\u73b0\u4ef7', sell_reason=reason)
		return False, 'fail_no_price'
	lp = _limit_sell_for_row(row or {}, last, reason) if row else _limit_sell(last)
	if not lp:
		_log('\u5356\u51fa\u672a\u6210\u529f', stock, '\u9650\u4ef7\u5931\u8d25', last_px='%.3f' % last, sell_reason=reason)
		return False, 'fail_limit'
	meta = dict(meta or {})
	meta.setdefault('last_px', last)
	meta.setdefault('limit_px', lp)
	meta.setdefault('reason', reason)
	rmk = _remark(stock, shares, 0, meta.get('open_date'))
	if not _should_passorder(C, reason):
		why = '\u56de\u6d4b\u4e0d\u53d1\u5355' if _is_qmt_backtest_context(C) else '\u975e\u5356\u51fa\u65f6\u95f4\u7a97'
		op_s, tp_s = _row_tp_log_fields(row or {})
		_log('\u5356\u51fa\u672a\u6210\u529f', stock, why, shares=shares, limit_px='%.3f' % lp,
		     sell_reason=reason, hold_days=meta.get('hold_days'),
		     open_buy_px=op_s, tp_price=tp_s,
		     pnl=('%.2f%%' % meta['ret_pct']) if meta.get('ret_pct') is not None else '--')
		return False, 'skip_backtest' if _is_qmt_backtest_context(C) else 'skip_time'
	if _passorder_go(C, stock, shares, rmk, lp):
		_reg_pending(rmk, stock, shares, 0, meta)
		op_s, tp_s = _row_tp_log_fields(row or {})
		print('%s [\u5356\u51fa\u59d4\u6258] \u4ee3\u7801=%s \u80a1\u6570=%d \u73b0\u4ef7=%.3f \u9650\u4ef7=%.3f \u5356\u51fa\u539f\u56e0=%s \u5f00\u4ed3\u65e5=%s \u6301\u4ed3\u5929\u6570=%s \u6210\u672c=%s \u5f00\u4ed3\u4ef7=%s \u6b62\u76c8\u4ef7=%s \u6d6e\u52a8\u76c8\u4e8f=%s' % (
			STRATEGY_TAG, stock, shares, last, lp, reason,
			meta.get('open_date', '--'), meta.get('hold_days', '--'),
			('%.3f' % meta['cost_px']) if meta.get('cost_px') else '--',
			op_s, tp_s,
			('%.2f%%' % meta['ret_pct']) if meta.get('ret_pct') is not None else '--'))
		return True, 'order_ok'
	return False, 'fail_order'


def _rollover(d_str):
	if g._session_date != d_str:
		g._session_date = d_str
		g._tried_stocks = set()
		g.waiting_list = []
		g.pending_orders = {}
		g._logged_fill_remarks = set()
		g._sell_watch_snapshot = None
		g._account_pos_snapshot = None
		g._tp_watch_log_ts = {}


def init(C):
	g.accid = str(getattr(C, 'accountid', None) or getattr(C, 'account_id', None) or DEFAULT_ACCID).strip()
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'
	g.sell_discount_pct = float(getattr(C, 'sell_discount_pct', 0.01) or 0.01)
	g.stop_loss_pct = float(getattr(C, 'stop_loss_pct', 8.0) or 8.0)
	g.stop_min_hold_days = int(getattr(C, 'stop_min_hold_days', STOP_MIN_HOLD_DAYS) or STOP_MIN_HOLD_DAYS)
	g.take_profit_pct = float(getattr(C, 'take_profit_pct', DEFAULT_TAKE_PROFIT_PCT) or DEFAULT_TAKE_PROFIT_PCT)
	g.max_hold_days = int(getattr(C, 'max_hold_days', DEFAULT_MAX_HOLD_DAYS) or DEFAULT_MAX_HOLD_DAYS)
	g.withdraw_secs = int(getattr(C, 'withdraw_secs', 60) or 60)
	g.max_retry = int(getattr(C, 'max_retry', 3) or 3)
	g.quick_trade = int(getattr(C, 'quick_trade', 2) or 2)
	g.strategy_order_name = str(getattr(C, 'strategy_order_name', None) or '\u5361\u5f02\u52a8\u5c3e\u76d8\u5356')[:20]
	g.live_orders = bool(getattr(C, 'live_orders', True))
	g.min_shares = int(getattr(C, 'min_shares', DEFAULT_MIN_SHARES) or DEFAULT_MIN_SHARES)
	g.sell_code = 24 if g.account_type == 'STOCK' else 34
	ctx = (getattr(C, 'sell_watch_csv_path', None) or getattr(C, 'sell_csv_path', None) or '')
	ctx = str(ctx).strip() or DEFAULT_SELL_WATCH_CSV_PATH
	try:
		C.sell_watch_csv_path = ctx
	except Exception:
		pass
	picked, how = _resolve_csv_path(ctx)
	g.sell_csv_path = str(picked or '').strip()
	g._sell_csv_resolve = how
	g.waiting_list, g.pending_orders = [], []
	g._session_date, g._tried_stocks = '', set()
	g._last_handle_key, g._logged_fill_remarks = None, set()
	g._sell_watch, g._sell_csv_mtime, g._sell_csv_loaded_day = [], None, None
	g._sell_csv_load_err = ''
	g._handlebar_hhmmss = None
	g._sell_watch_snapshot = None
	g._account_pos_snapshot = None
	g._tp_watch_log_ts = {}
	print('=' * 64)
	print('%s init acc=%s csv=%r resolve=%s exists=%s' % (
		STRATEGY_TAG, g.accid, g.sell_csv_path, how, os.path.isfile(g.sell_csv_path)))
	if not os.path.isfile(g.sell_csv_path):
		print('%s [WARN] CSV\u672a\u627e\u5230: \u8bf7\u5c06 %s \u653e\u5230\u7b56\u7565\u76ee\u5f55\uff0c\u6216\u5728\u7b56\u7565\u53c2\u6570\u8bbe ContextInfo.sell_watch_csv_path \u4e3a\u7edd\u5bf9\u8def\u5f84' % (
			STRATEGY_TAG, DEFAULT_CSV))
		print('%s [WARN] \u4ea6\u53ef\u8bbe\u73af\u5883\u53d8\u91cf YIDONG_SELL_WATCH_CSV \u6216\u628a\u6587\u4ef6\u590d\u5236\u5230 QMT bin \u76ee\u5f55' % (STRATEGY_TAG,))
	print('%s \u6b62\u76c8\u76d8\u4e2d09:30-15:00\u89e6\u8fbe\u5373\u5356(\u9650\u4ef7=\u6b62\u76c8\u4ef7); \u5c3e\u76d814:55-15:00 discount=%.2f%% stop=%.0f%%(CSV\u5f00\u4ed3\u4ef7,T+%d\u8d77) tp=%.0f%% max_hold=%d wd=%ds retry=%d live=%s' % (
		STRATEGY_TAG, g.sell_discount_pct * 100, g.stop_loss_pct, g.stop_min_hold_days,
		g.take_profit_pct, g.max_hold_days,
		g.withdraw_secs, g.max_retry, g.live_orders))
	print('%s CSV\u5217: \u80a1\u7968\u4ee3\u7801,\u5f00\u4ed3\u65e5,\u89e6\u53d1\u5356\u51fa\u4fe1\u53f7,\u5356\u51fa\u80a1\u6570,\u5f00\u4ed3\u4ef7[,\u6b62\u76c8\u4ef7\u8986\u76d6]; tp=\u5f00\u4ed3\u4ef7*(1+tp%%)' % (STRATEGY_TAG,))
	print('%s CSV24h\u76d1\u63a7 \u5185\u5bb9\u53d8\u5316\u6253\u5f85\u5356\u6c60(\u542b\u6b62\u76c8\u4ef7); \u5907\u6ce8=%s_*' % (STRATEGY_TAG, REMARK_PREFIX))
	print('=' * 64)


def handlebar(C):
	try:
		if not C.is_last_bar():
			return
	except Exception:
		pass
	wall = _wall_hhmmss()
	now = datetime.datetime.now()
	try:
		bar_dt = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	except Exception:
		bar_dt = now.strftime('%Y%m%d%H%M%S')
	d_str = bar_dt[:8]
	hkey = (d_str, getattr(C, 'barpos', None), 'close_sell')
	if hkey == g._last_handle_key:
		return
	g._last_handle_key = hkey
	_rollover(d_str)
	in_sell = _in_sell_window(wall) if wall is not None else False
	watch, _ = _monitor_sell_watch(C, bar_dt, d_str, force=in_sell)
	if wall is None or not _in_handlebar_session(wall):
		return
	g._handlebar_hhmmss = int(bar_dt[8:14]) if len(bar_dt) >= 14 else wall
	_sync_deals()
	_cancel_retry(C)
	if not g.accid:
		print('%s %s accid \u4e3a\u7a7a' % (STRATEGY_TAG, bar_dt))
		return
	if not watch:
		return
	pos_map = _positions()
	tp_stats = {}
	if wall is not None and _in_tp_monitor_session(wall):
		_run_sell_pass(C, bar_dt, d_str, watch, pos_map, tp_stats, tp_only=True)
	if tp_stats.get('order_ok'):
		_scan_summary(bar_dt, tp_stats, 'mode=tp_intraday csv=%d' % len(watch))
	if not in_sell:
		return
	print('%s ========== %s \u5c3e\u76d8\u5356\u51fa CSV\u884c=%d \u53ef\u6267\u884c\u7b14\u6570=%d ==========' % (
		STRATEGY_TAG, bar_dt, len(watch),
		sum(1 for row in watch if row.get('code') in pos_map
		    and _resolve_sell_shares(row, int(pos_map[row['code']].get('can_use', 0) or 0)) > 0)))
	stats = {}
	targets = []
	for row in watch:
		code = row.get('code') or ''
		p = pos_map.get(code)
		if not p:
			_log_watch(code, row, None, None, None, False, '\u65e0\u6301\u4ed3', 0)
			stats['skip_no_pos'] = stats.get('skip_no_pos', 0) + 1
			continue
		can_use = int(p.get('can_use', 0) or 0)
		cost_px = float(p.get('cost', 0) or 0)
		hd = _trading_hold_days(C, code, row.get('open_date'), d_str, bar_dt)
		if row.get('sell_shares') is not None and _int_shares(row.get('sell_shares')) <= 0:
			_log_watch(code, row, cost_px, None, hd, False, 'CSV\u5356\u51fa\u80a1\u6570\u65e0\u6548', 0)
			stats['skip_csv_shares'] = stats.get('skip_csv_shares', 0) + 1
			continue
		if can_use <= 0:
			_log_watch(code, row, cost_px, None, hd, False, '\u65e0\u53ef\u5356\u91cf', can_use)
			stats['skip_can_use'] = stats.get('skip_can_use', 0) + 1
			continue
		sh = _resolve_sell_shares(row, can_use)
		if sh <= 0:
			if row.get('sell_shares') is not None and _int_shares(row.get('sell_shares')) > can_use:
				_log_watch(code, row, cost_px, None, hd, False, 'CSV\u80a1\u6570\u8d85\u8fc7\u53ef\u5356', can_use)
				stats['skip_shares_cap'] = stats.get('skip_shares_cap', 0) + 1
			else:
				_log_watch(code, row, cost_px, None, hd, False, '\u672c\u7b14\u53ef\u5356\u4e0d\u8db3', can_use)
				stats['skip_can_use'] = stats.get('skip_can_use', 0) + 1
			continue
		targets.append((code, sh, cost_px, row, hd))
	if not targets:
		print('%s %s [\u626b\u63cf\u7ec8\u6b62] \u539f\u56e0=\u65e0\u53ef\u5356\u6807\u7684' % (STRATEGY_TAG, bar_dt))
		_scan_summary(bar_dt, stats, 'csv=%d' % len(watch))
		return
	tick_map = dict((c, px) for c, t in _full_ticks(C, [t[0] for t in targets]).items()
	                for px in [_tick_px(t)] if px)
	for code, shares, cost_px, row, hd in targets:
		last = tick_map.get(code)
		should, reason = _eval_sell_reason(C, code, row, d_str, bar_dt, last, cost_px, tp_only=False)
		ret_pct = (float(last) / float(cost_px) - 1.0) * 100.0 if cost_px and last else None
		_log_watch(code, row, cost_px, last, hd, should, reason, shares)
		if not should:
			stats['skip_hold'] = stats.get('skip_hold', 0) + 1
			continue
		rkey = _watch_row_key(row)
		if rkey in g._tried_stocks:
			_log('\u5356\u51fa\u8df3\u8fc7', code, '\u672c\u65e5\u8be5\u7b14\u5df2\u5c1d\u8bd5\u5356\u51fa', sell_reason=reason, open_date=row.get('open_date'))
			stats['skip_tried'] = stats.get('skip_tried', 0) + 1
			continue
		meta = {
			'open_date': row.get('open_date'), 'hold_days': hd, 'cost_px': cost_px,
			'ret_pct': ret_pct, 'reason': reason, 'stock': code,
			'csv_shares': row.get('sell_shares'),
			'open_buy_px': row.get('open_buy_px'),
			'tp_price': _effective_tp_price(row),
		}
		_ok, tag = _try_sell(C, code, shares, tick_map, reason, meta, row=row)
		stats[tag] = stats.get(tag, 0) + 1
		g._tried_stocks.add(rkey)
	_scan_summary(bar_dt, stats, 'csv=%d targets=%d' % (len(watch), len(targets)))


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
