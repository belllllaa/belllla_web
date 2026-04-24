#coding:gbk
"""
\u624b\u5de5 CSV \u5f00\u4ed3\u65e5 \u2192 \u65e5\u5386\u6301\u4ed3\u5929\u6570\uff08\u4ec5 print\uff0c\u65e0\u4e0b\u5355\uff09

CSV \u683c\u5f0f\u540c strategy_hold_days_probe\uff1a\u4e24\u5217 code,open_date\uff08YYYYMMDD\uff09\u3002

ContextInfo \u53ef\u9009\uff1a
  open_date_csv_path / manual_open_date_csv \u2014 \u672c\u5730 CSV \u7edd\u5bf9\u8def\u5f84
  accountid \u2014 \u8d44\u91d1\u8d26\u53f7\uff08\u7a7a\u5219\u9ed8\u8ba4 30262698\uff09
  accountType \u2014 \u9ed8\u8ba4 STOCK
  hold_days_log_mode: daily\uff08\u6bcf\u4ea4\u6613\u65e5\u53ea\u6253\u4e00\u6b21\uff09/ each
  handlebar_each_bar: \u56de\u6d4b\u6bcf\u6839 K

\u9ed8\u8ba4 CSV\uff1a\u4e0e\u7b56\u7565\u6587\u4ef6\u540c\u76ee\u5f55 manual_open_date_my_holdings.csv\uff08\u53ef\u6539\uff09\u3002
QMT \u6709\u65f6 cwd \u4e3a bin.x64\uff1b\u4f1a\u6309\u5019\u9009\u8def\u5f84\u81ea\u52a8\u67e5\u627e\u5df2\u5b58\u5728\u7684 CSV\u3002
\u4ecd\u53ef\u7528\u73af\u5883\u53d8\u91cf MANUAL_OPEN_DATE_CSV / BELLLLA_MANUAL_OPEN_CSV \u6216 ContextInfo.open_date_csv_path\u3002

\u5efa\u8bae\u5468\u671f 1m\uff0c\u5b9e\u76d8\u4f9d\u8d56 is_last_bar\u3002
"""

import csv
import os
import sys
import time
import datetime

STRATEGY_TAG = '[MANUAL-HOLD-DAYS]'
_MANUAL_CSV_NAME = 'manual_open_date_my_holdings.csv'


def _strategy_base_dir():
	"""QMT may exec strategy without __file__ (NameError); argv0/cwd fallback."""
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


def default_manual_csv_path():
	"""Same-dir CSV filename; directory from __file__ or fallback."""
	base = _strategy_base_dir()
	if not base:
		return ''
	return os.path.normpath(os.path.join(base, _MANUAL_CSV_NAME))


def _abs_if_file(path_str):
	if not path_str:
		return None
	p = os.path.normpath(os.path.abspath(str(path_str).strip()))
	return p if os.path.isfile(p) else None


def _iter_auto_csv_candidates():
	"""Ordered search when cwd points to bin.x64 etc.; skip duplicates."""
	seen = set()
	for p in (
		default_manual_csv_path(),
		os.path.join(
			os.environ.get('USERPROFILE', '') or '',
			'Documents',
			'belllla_web',
			'qmt',
			'\u5b9e\u76d8\u7b56\u7565',
			_MANUAL_CSV_NAME,
		),
		os.path.join(
			r'c:\Users\admin\Documents\belllla_web',
			'qmt',
			'\u5b9e\u76d8\u7b56\u7565',
			_MANUAL_CSV_NAME,
		),
	):
		if not p:
			continue
		n = os.path.normpath(p)
		if n in seen:
			continue
		seen.add(n)
		yield n


def resolve_open_date_csv_path(context_raw):
	"""
	Pick first existing CSV: explicit ContextInfo, env, then repo-style paths, then default.
	Returns (path_str, how).
	"""
	cr = (context_raw or '').strip()
	if cr:
		ap = os.path.normpath(os.path.abspath(cr))
		if os.path.isfile(ap):
			return ap, 'context'
	for ev in ('MANUAL_OPEN_DATE_CSV', 'BELLLLA_MANUAL_OPEN_CSV'):
		got = _abs_if_file(os.environ.get(ev))
		if got:
			return got, ev
	for cand in _iter_auto_csv_candidates():
		if cand and os.path.isfile(cand):
			return os.path.normpath(os.path.abspath(cand)), 'auto_found'
	if cr:
		return os.path.normpath(os.path.abspath(cr)), 'context_missing_file'
	base = default_manual_csv_path()
	return base, 'fallback_default'


class G(object):
	pass


g = G()


def _get_trade_detail_data_fn():
	fn = getattr(sys.modules.get('__main__'), 'get_trade_detail_data', None)
	if fn is None:
		fn = globals().get('get_trade_detail_data')
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


def _position_volume(p):
	try:
		v = int(getattr(p, 'm_nVolume', 0) or getattr(p, 'volume', 0) or 0)
		if v <= 0 and isinstance(p, dict):
			v = int(p.get('m_nVolume') or p.get('volume') or 0)
		return v
	except Exception:
		return 0


def _load_manual_open_date_csv(path_str):
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


def _ensure_manual_open_dates(asof_trade_day=None):
	"""\u540c\u4e00\u4ea4\u6613\u65e5\u4ec5\u8bfb\u76d8\u4e00\u6b21\uff1binit \u9884\u8bfb\u540e\u9996\u6b21\u5f53\u65e5 d_str \u518d\u8bfb\u4e00\u6b21\u4ee5\u7eb3\u5165\u9694\u591c CSV\u3002"""
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
	mp, err = _load_manual_open_date_csv(path)
	g._manual_open_dates = mp
	g._manual_csv_mtime = mt
	g._manual_csv_load_err = err or ''
	if sd:
		g._manual_csv_loaded_trade_day = sd
	else:
		g._manual_csv_loaded_trade_day = '__PREBAR__'


def _account_type():
	t = getattr(g, 'account_type', None) or 'STOCK'
	return str(t) if t else 'STOCK'


def _calendar_hold_days(buy_yyyymmdd, asof_yyyymmdd):
	if not buy_yyyymmdd or not asof_yyyymmdd:
		return None
	try:
		dh = (datetime.datetime.strptime(asof_yyyymmdd, '%Y%m%d') -
		      datetime.datetime.strptime(buy_yyyymmdd, '%Y%m%d')).days
		return max(1, int(dh))
	except Exception:
		return None


def _positions_from_gtd():
	_gtd = _get_trade_detail_data_fn()
	if not _gtd or not (g.accid or '').strip():
		return []
	try:
		return _gtd(g.accid, _account_type(), 'position') or []
	except Exception:
		return []


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
	g.accid = getattr(C, 'accountid', '') or getattr(C, 'account_id', '') or '30262698'
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'
	g.handlebar_each_bar = bool(getattr(C, 'handlebar_each_bar', False))
	g.hold_days_log_mode = str(getattr(C, 'hold_days_log_mode', 'daily') or 'daily').lower()
	ctx_csv = getattr(C, 'open_date_csv_path', None) or getattr(C, 'manual_open_date_csv', None)
	picked, how = resolve_open_date_csv_path(ctx_csv)
	g.open_date_csv_path = str(picked or '').strip()
	g._csv_resolve_how = how
	g._manual_open_dates = {}
	g._manual_csv_mtime = None
	g._manual_csv_load_err = ''
	g._last_handle_key = None
	g._logged_days = set()
	g._manual_csv_loaded_trade_day = None
	_ensure_manual_open_dates()
	print('=' * 64)
	print('%s init accid=%s csv=%r resolve=%s loaded=%d csv_err=%r log_mode=%s cwd_fallback=%r'
	      % (STRATEGY_TAG, g.accid, g.open_date_csv_path, getattr(g, '_csv_resolve_how', ''),
	         len(getattr(g, '_manual_open_dates', {}) or {}),
	         getattr(g, '_manual_csv_load_err', ''), g.hold_days_log_mode, default_manual_csv_path()))
	print('%s only print, no orders. calendar_hold_days = max(1, asof-open)\u3002' % STRATEGY_TAG)
	print('=' * 64)


def handlebar(C):
	if not _handlebar_should_run(C):
		return

	dt_full = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	d_str = dt_full[:8]
	bp = getattr(C, 'barpos', None)
	# dedupe (asof_date, barpos); barpos alone may repeat on a new session day
	_hkey = (d_str, bp)
	if _hkey == getattr(g, '_last_handle_key', None):
		return
	g._last_handle_key = _hkey

	if g.hold_days_log_mode == 'daily' and d_str in g._logged_days:
		return

	if not (g.accid or '').strip():
		print('%s %s accid empty' % (dt_full, STRATEGY_TAG))
		return

	_ensure_manual_open_dates(d_str)

	gtd = _get_trade_detail_data_fn()
	if not gtd:
		print('%s %s get_trade_detail_data missing' % (dt_full, STRATEGY_TAG))
		return

	pos_list = _positions_from_gtd()
	rows_out = []
	for p in pos_list:
		can = _normalize_position_code(p)
		can = _canonical_stock_code(can) or can
		if not can or _position_volume(p) <= 0:
			continue
		op = (getattr(g, '_manual_open_dates', None) or {}).get(can)
		hd = _calendar_hold_days(op, d_str) if op else None
		vol = _position_volume(p)
		rows_out.append((can, vol, op, hd))

	if not rows_out:
		print('%s %s no position vol>0' % (dt_full, STRATEGY_TAG))
		if g.hold_days_log_mode == 'daily':
			g._logged_days.add(d_str)
		return

	print('')
	print('%s ========== %s bar=%s asof_date=%s ==========' % (STRATEGY_TAG, dt_full, bp, d_str))
	print('%s csv=%r rows_in_csv=%d' % (STRATEGY_TAG, g.open_date_csv_path, len(getattr(g, '_manual_open_dates', {}) or {})))
	print('%s %-12s %8s %-10s %-10s %-6s' % ('tag', 'code', 'volume', 'csv_open', 'calendar_days', 'note'))
	print('%s ------------ -------- ---------- ---------- ------ ----' % STRATEGY_TAG)
	for can, vol, op, hd in sorted(rows_out, key=lambda x: x[0]):
		note = ''
		if not op:
			note = 'NO_CSV_ROW'
			hd_s = '--'
		else:
			hd_s = str(hd) if hd is not None else '--'
		print('%s %-12s %8d %-10s %-10s %-6s' % (STRATEGY_TAG, can, vol, op or '--', hd_s, note))

	if g.hold_days_log_mode == 'daily':
		g._logged_days.add(d_str)
	print('%s ========== end ==========' % STRATEGY_TAG)
	print('')


def handleBar(C):
	handlebar(C)


def handle_bar(C):
	handlebar(C)
