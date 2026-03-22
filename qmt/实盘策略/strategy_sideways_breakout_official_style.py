#coding:gbk
"""
横盘突破策略（简化版-优化版）- 按 QMT 官方实盘示例框架改写
- 过去20交易日（不含今日）横盘震荡：平均振幅≤5%，价格波动区间≤12%
- 今日涨幅2%-8%，前20日日均成交额>3000万，非一字板，价格>3元，尾盘买入
- 卖出：止盈10%/总亏7%止损/破MA10清仓
- 最多持有10只，每只10000元；非ST/创业板/科创板/北交所，深证300，深证1000，中证1000，中证500，沪深300
- 框架：全局类 G 存状态（格式对齐 qmt_style）；仅最后一根K线+交易时段；waiting_list 防超单；账号/持仓用 get_trade_detail_data
- 周期：日线/1 分钟均可；当前为测试模式：交易时段内随时扫描并下单（不限制尾盘）；持有天数日线用 barpos、分钟用日期差。
- 优化：quickTrade=2 当日立即下单；30秒未成交则撤单并重新下单（有重试上限）。
- 合规：首行 #coding:gbk；init/handlebar；全局类 G 存状态；投资备注<24 字；get_trade_detail_data 取 account/position/order/deal；cancel(orderId, acct, acctType, C) 撤单。
- 行情：handlebar 内统一用 C.get_market_data_ex 获取量价数据。
"""

import numpy as np
import time
import datetime


class G:
	"""策略全局状态，方便读取与扩展（格式对齐 strategy_sideways_breakout_qmt_style）"""
	pass


g = G()


def _order_remark(side, stock, shares, retry=0):
	"""生成投资备注，长度<24（QMT 知识库要求），用于 m_strRemark 对单与防超单。"""
	s = 'HB%s%s_%s' % ('B' if side == 'buy' else 'S', stock, shares)
	return ('%s_R%d' % (s, retry)) if retry else s


def _has_pending_order(stock, side):
	"""该标的是否已有未成交的指定方向委托，用于防重复下单。"""
	return any(p.get('stock') == stock and p.get('side') == side for p in g.pending_orders.values())


def init(C):
	# 账户与下单参数（兼容 accountid / account_id，未设置时使用默认账号）
	g.accid = getattr(C, 'accountid', '') or getattr(C, 'account_id', '') or '11219398'
	g.account_type = getattr(C, 'accountType', 'STOCK') or getattr(C, 'account_type', 'STOCK') or 'STOCK'
	g.buy_num = 10
	g.per_money = 10000
	# 持仓与买入记录（规则卖需要）
	g.holding = {}
	g.buy_price = {}
	g.buy_shares = {}
	g.buy_date = {}
	g.buy_barpos = {}
	# 防超单与撤单重下
	g.waiting_list = []
	g.pending_orders = {}   # remark -> {time, stock, side, shares, retry}
	g.QUICK_TRADE = 2      # 2=任意时刻立即发单，0=等K线走完再发
	g.WITHDRAW_SECS = 30  # 委托超时秒数，超过则撤单重下
	g.MAX_RETRY = 2       # 同一笔逻辑最多重下次数（首次+重试）
	# 买卖 opType（股票 23/24，两融 33/34）
	g.buy_code = 23 if g.account_type == 'STOCK' else 33
	g.sell_code = 24 if g.account_type == 'STOCK' else 34
	# 今日涨幅过滤：3%-8%
	g.min_today_return = 0.03
	g.max_today_return = 0.08
	# 前20日日均成交额（万元），> 该值才买，确保能进出
	g.min_avg_amount_wan = 3000   # 3000万
	# 股票池在 handlebar 中按日通过指数成分获取；行情统一用 C.get_market_data_ex 按需获取
	g.s = []
	if not g.accid:
		print('[实盘] 警告: accid 为空，请在策略设置中指定交易账户')
	# 测试模式：交易时段内随时扫描并下单（不限制尾盘）
	print('[横盘突破] 今日涨幅 %.0f%%-%.0f%% 前20日日均成交额>%.0f万' % (g.min_today_return * 100, g.max_today_return * 100, g.min_avg_amount_wan))
	print('横盘突破策略（官方框架） accid=%s quickTrade=%d 超时%d秒重下 max_retry=%d' % (g.accid, g.QUICK_TRADE, g.WITHDRAW_SECS, g.MAX_RETRY))


def _normalize_position_code(pos):
	"""从持仓对象得到与股票池一致的代码（如 000001.SZ）。兼容 QMT 不同交易所字段写法。"""
	if pos is None:
		return ''
	ins = (getattr(pos, 'm_strInstrumentID', None) or getattr(pos, 'stock_code', None) or '').strip()
	ex = (getattr(pos, 'm_strExchangeID', None) or getattr(pos, 'exchange_id', None) or '').upper().strip()
	# 代码已带后缀则直接返回
	if '.' in ins:
		return ins
	if not ins:
		return ''
	# 统一为 .SH / .SZ，与常见股票池格式一致
	if ex in ('SH', 'SS', '上海'):
		return ins + '.SH'
	if ex in ('SZ', '深圳'):
		return ins + '.SZ'
	if ex:
		return ins + '.' + ex
	# 交易所为空时按代码推断：60/68/51 沪，其余深
	if ins.startswith(('60', '68', '51')):
		return ins + '.SH'
	return ins + '.SZ'


def _parse_tick_price(t):
	"""从 get_full_tick 返回的 tick 对象中解析最新价。QMT 文档/社区：最新价字段为 lastPrice（驼峰）。"""
	if t is None:
		return None
	# 优先 lastPrice（QMT 全推 tick 常用字段名），再兼容 last_price / m_nLastPrice / nLast
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


def _build_full_tick_prices(C, stock_list):
	"""
	按 QMT 知识库：使用 Lv1 全推数据 get_full_tick(股票列表) 取当前价，随盘口更新。
	get_market_data_ex(..., subscribe=False) 为本地数据，实盘可能停在启动时刻不更新。
	返回 (dict: stock -> last_price, reason_str)；无数据时 reason_str 说明原因便于排查。
	"""
	out = {}
	reason = ""
	if not stock_list:
		return out, "股票列表为空"
	if not hasattr(C, 'get_full_tick'):
		return out, "当前环境无 get_full_tick 接口（实盘测试/回测下常见，仅实盘+全推时有）"
	try:
		ticks = C.get_full_tick(stock_list)
		if not ticks:
			return out, "get_full_tick 返回为空（实盘测试或无全推行情时常见，请确认实盘并开启 Lv1 全推）"
		for code, t in ticks.items():
			p = _parse_tick_price(t)
			if p is not None and p > 0:
				out[code] = p
		if not out:
			return out, "get_full_tick 有返回但解析不到有效 last_price（检查 tick 字段名）"
	except Exception as e:
		reason = "get_full_tick 调用异常: %s" % (str(e)[:80])
		return out, reason
	return out, ""


def _get_current_price(C, stock, bar_date_str, fallback_close, tick_snapshot=None):
	"""
	当日目前价：优先用全推快照 tick_snapshot（每次 handlebar 一次 get_full_tick 列表），
	否则单只 get_full_tick -> 1m 本地 -> 日线 fallback。
	知识库：subscribe=False 为本地可能不随盘更新；全推 get_full_tick 无订阅数限制且随盘更新。
	"""
	if tick_snapshot is not None and stock in tick_snapshot and tick_snapshot[stock] > 0:
		return tick_snapshot[stock]
	try:
		if hasattr(C, 'get_full_tick'):
			ticks = C.get_full_tick([stock])
			if ticks and stock in ticks:
				p = _parse_tick_price(ticks[stock])
				if p is not None and p > 0:
					return p
	except Exception:
		pass
	try:
		m1 = C.get_market_data_ex(['close'], [stock], period='1m', count=1, end_time=bar_date_str, subscribe=False)
		if m1 and stock in m1 and 'close' in m1[stock] and len(m1[stock]['close']) > 0:
			c = m1[stock]['close']
			p = c[-1] if hasattr(c, '__getitem__') else list(c)[-1]
			if p is not None and float(p) > 0:
				return float(p)
	except Exception:
		pass
	return fallback_close


def handlebar(C):
	if not C.is_last_bar():
		return
	now = datetime.datetime.now()
	now_time = now.strftime('%H%M%S')
	if now_time < '093000' or now_time > '150000':
		return

	# 持有天数：日线用 barpos，分钟线用日期差
	chart_period = getattr(C, 'period', '1d') or '1d'
	is_daily = (chart_period == '1d' or chart_period == '1D')

	try:
		account = get_trade_detail_data(g.accid, g.account_type, 'account')
	except Exception:
		account = []
	if len(account) == 0:
		print('账号 %s 未登录 请检查' % g.accid)
		return
	account = account[0]
	available_cash = int(getattr(account, 'm_dAvailable', 0))

	if g.waiting_list:
		found_list = []
		try:
			deals = get_trade_detail_data(g.accid, g.account_type, 'deal')
			for deal in deals:
				remark = getattr(deal, 'm_strRemark', '') or ''
				if remark in g.waiting_list:
					found_list.append(remark)
		except Exception:
			pass
		for r in found_list:
			pinfo = g.pending_orders.get(r)
			if pinfo and pinfo.get('side') == 'sell':
				# 卖出成交确认后再清理买入记录，便于撤单重下时恢复
				s = pinfo['stock']
				for d in [g.buy_price, g.buy_shares, g.buy_date, g.buy_barpos]:
					d.pop(s, None)
			if r in g.waiting_list:
				g.waiting_list.remove(r)
			g.pending_orders.pop(r, None)
	# 30秒未成交则撤单并重新下单
	_do_withdraw_and_retry(C)

	if g.waiting_list:
		print('当前有未查到委托 暂停后续报单', g.waiting_list[:3])
		return

	try:
		positions = get_trade_detail_data(g.accid, g.account_type, 'position')
		holdings = {}       # code -> 可卖数量（含 T+1 当日买入为 0 的持仓，以便账号持股数正确）
		position_objs = {}  # code -> 持仓对象（用于取成本价等）
		for i in positions:
			code = _normalize_position_code(i)
			if not code:
				continue
			# 可卖数量（T+1：当日买入为 0）；总持仓可用 m_nVolume 等，此处用可卖做卖出判断
			vol = getattr(i, 'm_nCanUseVolume', 0) or 0
			holdings[code] = vol  # 全部计入，账号持股数 = len(holdings)
			position_objs[code] = i
	except Exception:
		positions = []
		holdings = {}
		position_objs = {}

	bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
	current_date_str = bar_date_str[:8]

	# 顺序：先同步持仓 → 先执行卖出逻辑 → 再执行买入逻辑（同一 handlebar 内先卖后买）
	# 以账号实际持股同步 g.holding；无买入记录时补全成本/可卖/买入日
	for code in list(g.holding.keys()):
		g.holding[code] = (code in holdings)
	for code in holdings:
		g.holding[code] = True
		if code not in g.buy_price and code in position_objs:
			g.buy_price[code] = getattr(position_objs[code], 'm_dOpenPrice', None) or getattr(position_objs[code], 'm_dCost', None)
		if code not in g.buy_shares and code in holdings:
			g.buy_shares[code] = (holdings[code] // 100) * 100
		if code not in g.buy_date:
			g.buy_date[code] = current_date_str
		if code not in g.buy_barpos:
			g.buy_barpos[code] = C.barpos if is_daily else 0
	all_stocks = get_stock_pool_method2_only(C, bar_date_str)
	print('[%s] 股票池 %d 只 账号持股 %d 只' % (bar_date_str, len(all_stocks), len(holdings)))

	# 卖出：先于买入执行；按账号实际持股逐只做卖出逻辑判断（可卖>=100 才挂卖单）
	tick_holdings, _ = _build_full_tick_prices(C, list(holdings.keys()))
	for stock in list(holdings.keys()):
		can_use = holdings.get(stock, 0)
		if can_use < 100:
			continue
		try:
			# 横盘/MA 等逻辑一律用日线数据；当前价用全推/1m 实时价，止损与 MA 判断才准确
			data = C.get_market_data_ex(['close', 'high', 'low', 'open'], [stock], end_time=bar_date_str, period='1d', count=25, subscribe=False)
			if stock not in data or len(data[stock]['close']) < 2:
				continue
			closes = list(data[stock]['close'])
			opens = list(data[stock]['open'])
			highs = list(data[stock]['high'])
			lows = list(data[stock]['low'])
			day_close = closes[-1]
			current_price = _get_current_price(C, stock, bar_date_str, day_close, tick_holdings)
			pos_obj = position_objs.get(stock)
			buy_price = g.buy_price.get(stock) or (getattr(pos_obj, 'm_dOpenPrice', None) if pos_obj else None) or current_price
			today_open = opens[-1]
			today_high = highs[-1]
			today_low = lows[-1]
			if today_open <= 0:
				continue
			total_loss = (current_price - buy_price) / buy_price if buy_price else 0

			ma_10 = np.mean(closes[-10:]) if len(closes) >= 10 else None
			sell_condition = False
			sell_reason = ''
			if total_loss < -0.07:
				sell_condition = True
				sell_reason = '总亏损7%止损'
			elif total_loss >= 0.10:
				sell_condition = True
				sell_reason = '止盈10%'
			elif ma_10 is not None and current_price < ma_10:
				sell_condition = True
				sell_reason = '破MA10清仓'

			if sell_condition:
				shares = g.buy_shares.get(stock) or (can_use // 100) * 100
				shares = min(shares, can_use // 100 * 100)
				if shares >= 100 and not _has_pending_order(stock, 'sell'):
					msg = _order_remark('sell', stock, shares)
					passorder(g.sell_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg, C)
					g.holding[stock] = False
					g.waiting_list.append(msg)
					g.pending_orders[msg] = {'time': time.time(), 'stock': stock, 'side': 'sell', 'shares': shares, 'retry': 0}
					print(bar_date_str, '卖出', stock, shares, sell_reason)
		except Exception as e:
			print('卖出异常', stock, e)

	current_holdings = sum(1 for h in g.holding.values() if h)
	if current_holdings >= g.buy_num:
		print('[%s] 扫描完成 已达最大持仓 %d 只 跳过买入' % (bar_date_str, g.buy_num))
		return

	# 按知识库：全推 get_full_tick(股票列表) 取当前价，涨跌幅才随盘口更新；本地 subscribe=False 可能停在启动时刻
	total_stocks = min(3500, len(all_stocks))
	tick_snapshot, tick_reason = _build_full_tick_prices(C, all_stocks[:total_stocks])
	if not tick_snapshot and total_stocks > 0:
		print('[%s] 未取到全推快照，当日涨跌幅可能不随盘更新。原因: %s' % (bar_date_str, tick_reason))
	# 诊断计数：有数据、通过横盘、通过涨幅、实际下单数、因资金不足跳过数
	n_with_data = 0
	n_sideways_ok = 0
	n_return_ok = 0
	n_candidates = 0
	n_skipped_cash = 0
	sample_sideways = None  # (stock, today_open, current_close, today_return, day_close)
	for stock in all_stocks[:total_stocks]:
		if current_holdings >= g.buy_num:
			break
		# 先以账号实际持仓为准：已有该标的则不再买入（含 T+1 可卖为 0 的当日买入）
		if stock in holdings:
			continue
		if g.holding.get(stock, False):
			continue
		if _is_chinext_star_bse_or_st(stock):
			continue
		try:
			data = C.get_market_data_ex(['close', 'high', 'low', 'open', 'amount'], [stock], end_time=bar_date_str, period='1d', count=25, subscribe=False)
			if stock not in data or len(data[stock]['close']) < 22:
				continue
			n_with_data += 1
			closes = list(data[stock]['close'])
			highs = list(data[stock]['high'])
			lows = list(data[stock]['low'])
			opens = list(data[stock]['open'])
			amounts = list(data[stock].get('amount', []))
			today_open = opens[-1]
			today_high = highs[-1]
			# 当日目前价：优先用本根 handlebar 的全推快照 tick_snapshot，涨跌幅随盘口更新
			current_close = _get_current_price(C, stock, bar_date_str, closes[-1], tick_snapshot)
			if current_close <= 0 or today_open <= 0 or current_close <= 3.0:
				continue
			avg_amplitude, price_range = calculate_sideways_metrics(highs, lows, closes, 20)
			if avg_amplitude > 0.05 or price_range > 1.12:
				continue
			n_sideways_ok += 1
			today_return = (current_close - today_open) / today_open
			if sample_sideways is None:
				sample_sideways = (stock, today_open, current_close, today_return, closes[-1])
			if today_return < g.min_today_return or today_return > g.max_today_return:
				continue
			n_return_ok += 1
			# 前20日日均成交额 > 3000万（不含今日）；amount 单位一般为元
			if len(amounts) >= 21:
				amt_20 = amounts[-21:-1]  # 前20个交易日（不含今日）
				avg_amount = sum(float(x) for x in amt_20 if x is not None) / 20
				if avg_amount < g.min_avg_amount_wan * 10000:  # 万 -> 元
					continue
			target_shares = int(g.per_money / current_close)
			shares = (target_shares // 100) * 100
			if shares < 100 or shares > 10000:
				continue
			if g.per_money > available_cash:
				n_skipped_cash += 1
				if n_skipped_cash == 1:
					print('[%s] 剩余可用资金 %.0f 不足单笔 %d 跳过后续买入' % (bar_date_str, available_cash, g.per_money))
				continue
			if _has_pending_order(stock, 'buy'):
				continue
			n_candidates += 1
			msg = _order_remark('buy', stock, shares)
			passorder(g.buy_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg, C)
			g.holding[stock] = True
			g.buy_price[stock] = current_close
			g.buy_shares[stock] = shares
			g.buy_date[stock] = current_date_str
			g.buy_barpos[stock] = C.barpos if is_daily else 0
			g.waiting_list.append(msg)
			g.pending_orders[msg] = {'time': time.time(), 'stock': stock, 'side': 'buy', 'shares': shares, 'retry': 0}
			current_holdings += 1
			available_cash -= g.per_money
			print(bar_date_str, '买入', stock, shares, '@', current_close)
			# 每次下单后重查可用资金，避免多笔连下时用旧快照导致券商报“资金不够”
			try:
				acc_list = get_trade_detail_data(g.accid, g.account_type, 'account')
				if acc_list:
					available_cash = int(getattr(acc_list[0], 'm_dAvailable', 0))
			except Exception:
				pass
		except Exception as e:
			print('买入异常', stock, e)

	print('[%s] 扫描完成 有数据=%d 横盘通过=%d 涨幅通过=%d 实际下单=%d只' % (bar_date_str, n_with_data, n_sideways_ok, n_return_ok, n_candidates))
	if n_skipped_cash > 0:
		print('  -> 因可用资金不足单笔 %d 元，跳过 %d 只未挂单' % (g.per_money, n_skipped_cash))
	if n_candidates == 0 and n_with_data > 0:
		print('  -> 无信号原因：暂无标的同时满足 20日横盘(振幅≤5%%/区间≤12%%) + 今日涨幅%.0f%%-%.0f%% + 前20日日均成交额>%.0f万 + 价格>3元' % (g.min_today_return * 100, g.max_today_return * 100, g.min_avg_amount_wan))
		if n_sideways_ok > 0 and n_return_ok == 0 and sample_sideways:
			s, open_p, cur_p, ret, day_close = sample_sideways
			print('  -> [涨幅排查] 样本 %s 今开=%.2f 当前价=%.2f 日线收=%.2f 今日涨幅=%.2f%% (当前条件%.0f%%-%.0f%%)' % (s, open_p, cur_p, day_close, ret * 100, g.min_today_return * 100, g.max_today_return * 100))
	elif n_with_data == 0:
		print('  -> 无信号原因：股票池无足够日线数据(len>=22)，请检查数据下载或 end_time')


def _do_withdraw_and_retry(C):
	"""30秒未成交则撤单并重新下单；已撤/部撤/废单只清理不重下；超过最大重试次数则不再重下。"""
	if not g.waiting_list:
		return
	now_ts = time.time()
	try:
		orders = get_trade_detail_data(g.accid, g.account_type, 'order')
	except Exception:
		orders = []
	# 订单状态：56=已成 53=部撤 54=已撤 57=废单；其余视为可撤的未完成状态
	ORDER_DONE = 56
	ORDER_CANCEL_STATES = (53, 54, 57)
	to_remove = []
	to_retry = []  # (remark, pinfo, order_sys_id)
	for remark in list(g.waiting_list):
		pinfo = g.pending_orders.get(remark)
		if not pinfo:
			to_remove.append(remark)
			continue
		elapsed = now_ts - pinfo['time']
		if elapsed < g.WITHDRAW_SECS:
			continue
		order_match = None
		for o in orders:
			if (getattr(o, 'm_strRemark', '') or '') == remark:
				order_match = o
				break
		if not order_match:
			continue
		status = getattr(order_match, 'm_nOrderStatus', 0)
		order_sys_id = getattr(order_match, 'm_strOrderSysID', '') or ''
		if status == ORDER_DONE:
			to_remove.append(remark)
			continue
		if status in ORDER_CANCEL_STATES:
			to_remove.append(remark)
			if pinfo.get('side') == 'sell':
				g.holding[pinfo['stock']] = True
			else:
				# 买入撤单/废单：释放持仓槽位，避免失败单占名额
				s = pinfo.get('stock')
				g.holding[s] = False
				for d in [g.buy_price, g.buy_shares, g.buy_date, g.buy_barpos]:
					d.pop(s, None)
			continue
		# 未完成且超时：撤单并准备重下
		if pinfo.get('retry', 0) >= g.MAX_RETRY:
			to_remove.append(remark)
			continue
		to_retry.append((remark, pinfo, order_sys_id))
	for r in to_remove:
		if r in g.waiting_list:
			g.waiting_list.remove(r)
		g.pending_orders.pop(r, None)
	for remark, pinfo, order_sys_id in to_retry:
		if remark in g.waiting_list:
			g.waiting_list.remove(remark)
		g.pending_orders.pop(remark, None)
		try:
			cancel(order_sys_id, g.accid, g.account_type, C)
		except Exception as e:
			print('撤单失败', order_sys_id, e)
			continue
		stock = pinfo['stock']
		side = pinfo.get('side', 'buy')
		shares = pinfo['shares']
		retry = pinfo.get('retry', 0) + 1
		if side == 'sell':
			g.holding[stock] = True
		msg2 = _order_remark(side, stock, shares, retry)
		if side == 'sell':
			passorder(g.sell_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg2, C)
			g.holding[stock] = False
		else:
			passorder(g.buy_code, 1101, g.accid, stock, 5, 0, shares, '横盘突破', g.QUICK_TRADE, msg2, C)
		g.waiting_list.append(msg2)
		g.pending_orders[msg2] = {'time': time.time(), 'stock': stock, 'side': side, 'shares': shares, 'retry': retry}
		print('超时撤单重下', side, stock, shares, 'retry=%d' % retry)


def calculate_sideways_metrics(highs, lows, closes, period=20):
	if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
		return float('inf'), float('inf')
	amplitude_sum = 0
	valid_days = 0
	for i in range(len(closes) - period - 1, len(closes) - 1):
		if closes[i] > 0:
			amplitude_sum += (highs[i] - lows[i]) / closes[i]
			valid_days += 1
	avg_amplitude = amplitude_sum / valid_days if valid_days else float('inf')
	recent_highs = highs[-period - 1 : -1]
	recent_lows = lows[-period - 1 : -1]
	if not recent_highs or not recent_lows:
		price_range = float('inf')
	else:
		period_low = min(recent_lows)
		price_range = max(recent_highs) / period_low if period_low > 0 else float('inf')
	return avg_amplitude, price_range


def get_stock_pool_method2_only(C, current_date_str):
	all_stocks = []
	try:
		index_stocks = []
		indices = ['399007.SZ', '399009.SZ', '000300.SH', '000852.SH']
		for index_code in indices:
			try:
				if hasattr(C, 'get_index_constituent'):
					stocks = C.get_index_constituent(index_code)
				elif hasattr(C, 'get_sector'):
					stocks = C.get_sector(index_code)
				else:
					continue
				if stocks:
					index_stocks.extend(stocks)
			except Exception:
				continue
		if index_stocks:
			all_stocks = list(set(index_stocks))
			print('组合指数成分股 %d 只' % len(all_stocks))
	except Exception as e:
		print('组合指数成分股失败:', e)
	return all_stocks


def _is_chinext_star_bse_or_st(stock_code):
	if not stock_code or len(stock_code) < 6:
		return False
	code = stock_code.split('.')[0]
	suffix = (stock_code.split('.')[-1] or '').upper()
	if suffix == 'BJ' or code.startswith('300') or code.startswith('688') or code.startswith('689'):
		return True
	if 'ST' in stock_code.upper():
		return True
	return False


def _trading_days_diff(date_start, date_end):
	try:
		d1 = datetime.datetime.strptime(str(date_start), '%Y%m%d')
		d2 = datetime.datetime.strptime(str(date_end), '%Y%m%d')
		return max(0, (d2 - d1).days)
	except Exception:
		return 0


def timetag_to_datetime(timetag, format_str='%Y%m%d'):
	try:
		return time.strftime(format_str, time.localtime(timetag / 1000))
	except Exception:
		return str(timetag)
