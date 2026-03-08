#coding:gbk
"""
彼得·林奇价值成长策略 - 纯A股版本 (Peter Lynch Strategy - A-Share Only)

策略核心原则：
A. 选择 PEG < 0.5 的股票（PEG = PE / 增长率）
B. 使用沪深300等指数成分股作为股票池
C. 最大持仓 5 只，优先小市值，按固定周期调仓（默认 30 天）
D. 剔除周期性与项目类行业（可选）
E. 仅按时间调仓，不设止盈止损；卖出仅发生在调仓日（按新名单换仓）
F. 兼容 QMT：若无 get_fundamentals，使用「PE/增长率」代理（价格与涨幅）筛选

本版仅按时间调仓，不设止盈止损；调仓日按新 PEG 名单换仓。
与同花顺彼得策略对齐：A PEG<0.5 ✓  B ES风险平价(可选)  D 5只+小市值优先+15天调仓 ✓  E 剔除周期/项目行业 ✓
说明：QMT 内置策略 API 文档中无 get_fundamentals/get_industry，本策略先尝试
      基本面接口；若无则用行情数据做 PEG 代理（PE 代理 + 历史涨幅作增长率代理），
      保证回测能选出股票。若你环境有 xtdata.get_financial_data 等，可再接入真实 PE/EPS。
"""

import numpy as np
import time
from datetime import datetime, timedelta

def init(C):
    C.accountid = getattr(C, 'accountid', '')
    # 优化版参考：持股 20 只、PEG≤0.4 时回测更优；当前可改 max_stocks=20、peg_proxy_max=0.4
    C.max_stocks = 5
    C.per_stock_amount = 20000
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.min_hold_days = 15
    C.last_rebalance_date = ""
    C.benchmark_index = "000300.SH"
    C.use_peg_proxy = True
    C.peg_proxy_max = 0.5          # 同花顺/林奇标准 PEG<0.5；优化版可改为 0.4
    C.rebalance_days = 15          # 同花顺彼得策略：15 天调仓一次
    # False=每期全清再按新名单买（轮动）；True=只卖不在新名单的（易长期持有）
    C.incremental_rebalance = False
    # ---------- 对齐「PEG价值选股（优化版）」的可选项 ----------
    C.exclude_new_stock_days = 250 # 剔除上市不足 N 交易日（约1年）；0=不剔除
    C.limit_up_no_buy = True       # 涨停不买
    C.limit_down_no_sell = True    # 跌停不卖
    # 选股时扫描候选池前 N 只（全池达标再按市值取小），避免只扫前几只好几期都是同一批
    C.peg_scan_limit = 2000
    # 行业映射：QMT 无 get_industry(股票)，需用「板块列表 + 成分股」反建 股票->行业
    C.stock_to_industry = _build_stock_industry_map(C)
    print('彼得·林奇价值成长策略（纯A股版）初始化 调仓%d天 持股%d PEG<%.2f 次新>%d天 涨跌停过滤=%s 行业映射=%d只' % (
        C.rebalance_days, C.max_stocks, C.peg_proxy_max, C.exclude_new_stock_days or 0,
        C.limit_up_no_buy or C.limit_down_no_sell, len(getattr(C, 'stock_to_industry', {}))))

def handlebar(C):
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')
    current_date_str = bar_date_str[:8]
    
    if should_rebalance(C, current_date_str):
        rebalance_days = getattr(C, 'rebalance_days', 30)
        incremental = getattr(C, 'incremental_rebalance', False)
        print(f"[{bar_date_str}] 触发{rebalance_days}天调仓 模式={'增量保留' if incremental else '全清轮动'}")
        if incremental:
            rebalance_portfolio_incremental(C, bar_date_str, current_date_str)
        else:
            clear_all_positions(C, bar_date_str)
            rebalance_portfolio(C, bar_date_str, current_date_str)
        C.last_rebalance_date = current_date_str
    # 不设止盈止损，平日不卖出，仅调仓日按名单换仓

def should_rebalance(C, current_date):
    if not C.last_rebalance_date:
        return True
    try:
        last_date = datetime.strptime(C.last_rebalance_date, '%Y%m%d')
        current_date_obj = datetime.strptime(current_date, '%Y%m%d')
        days = getattr(C, 'rebalance_days', 30)
        return (current_date_obj - last_date).days >= days
    except Exception:
        return True

def clear_all_positions(C, bar_date_str):
    for stock in list(C.holding.keys()):
        if not C.holding.get(stock, False) or stock not in C.buy_shares:
            continue
        try:
            shares = C.buy_shares[stock]
            if shares < 100:
                continue
            data = C.get_market_data_ex(['close', 'open'], [stock], end_time=bar_date_str, period='1d', count=2, subscribe=False)
            if stock not in data or len(data[stock]['close']) < 2:
                continue
            current_price = data[stock]['close'][-1]
            if getattr(C, 'limit_down_no_sell', False):
                o, c = data[stock]['open'][-1], data[stock]['close'][-1]
                if o and o > 0 and (c - o) / o <= -0.095:
                    continue
            passorder(24, 1101, C.accountid, stock, 5, 0, shares, "彼得林奇-调仓", 1, "", C)
            C.holding[stock] = False
            buy_price = C.buy_price.get(stock, current_price)
            profit_pct = (current_price - buy_price) / buy_price if buy_price else 0
            print(f"{bar_date_str} 调仓卖出 {stock} {shares}股 @ {current_price:.3f} 盈亏: {profit_pct:.1%}")
            for key in [C.buy_price, C.buy_shares, C.buy_date]:
                if stock in key:
                    del key[stock]
        except Exception as e:
            print(f"调仓卖出异常 {stock}: {e}")

def _is_new_stock(C, stock, current_date_str, min_days=250):
    """上市不足 min_days 的视为次新股并剔除。min_days=0 表示不剔除。"""
    if not min_days or min_days <= 0:
        return False
    try:
        if not hasattr(C, 'get_open_date') or not callable(getattr(C, 'get_open_date')):
            return False
        open_date_val = C.get_open_date(stock)
        if open_date_val is None:
            return False
        # 支持时间戳(ms)或 YYYYMMDD 整数
        if open_date_val > 1e10:
            open_dt = datetime.fromtimestamp(open_date_val / 1000.0)
        elif open_date_val > 1e4:
            open_dt = datetime.strptime(str(int(open_date_val)), '%Y%m%d')
        else:
            return False
        current_dt = datetime.strptime(str(current_date_str)[:8], '%Y%m%d')
        return (current_dt - open_dt).days < min_days
    except Exception:
        return False

def _get_qualified_lynch_list(C, bar_date_str, candidate_stocks):
    """
    从候选池筛出 PEG 达标的股票，按市值从小到大排序，优先小市值，取前 max_stocks 只。
    必须遍历足够多候选（不提前 break），否则会一直只选到池子前段的几只。
    市值由 get_market_cap() 计算；取不到时返回 inf，会排到后面。
    """
    current_date_str = bar_date_str[:8]
    exclude_days = getattr(C, 'exclude_new_stock_days', 0)
    qualified = []
    # 遍历全池（或前 N 只），收集所有 PEG 达标，再按市值取最小的 max_stocks 只
    scan_limit = getattr(C, 'peg_scan_limit', 2000)
    for stock in candidate_stocks[:scan_limit]:
        if _is_chinext_star_bse_or_st(stock):
            continue
        if exclude_days and _is_new_stock(C, stock, current_date_str, exclude_days):
            continue
        try:
            peg_ratio = calculate_peg_ratio(C, stock, bar_date_str)
            if peg_ratio is None:
                continue
            if peg_ratio >= getattr(C, 'peg_proxy_max', 0.5):
                continue
            if is_cyclical_or_project_based_industry(C, stock):
                continue
            market_cap = get_market_cap(C, stock, bar_date_str)
            qualified.append({'code': stock, 'peg': peg_ratio, 'market_cap': market_cap})
        except Exception:
            continue
    # 市值从小到大排列，优先购买小市值（林奇偏好小公司十倍股）
    qualified.sort(key=lambda x: x['market_cap'])
    return [x['code'] for x in qualified[:C.max_stocks]]

def rebalance_portfolio(C, bar_date_str, current_date_str):
    """全量调仓（轮动）：先清空所有持仓，再按当日新名单建仓，每期都会换仓。"""
    candidate_stocks = get_peter_lynch_stock_pool(C, bar_date_str)
    if not candidate_stocks:
        print(f"[{bar_date_str}] 股票池为空，跳过调仓")
        return
    selected = _get_qualified_lynch_list(C, bar_date_str, candidate_stocks)
    print(f"[{bar_date_str}] 选出 {len(selected)} 只 PEG达标: {selected}")
    build_new_positions(C, selected, bar_date_str, current_date_str)

def rebalance_portfolio_incremental(C, bar_date_str, current_date_str):
    """增量调仓：只卖出不在新名单的持仓，补足空缺。仍在名单里的持仓不卖→可能长期持有数月。"""
    candidate_stocks = get_peter_lynch_stock_pool(C, bar_date_str)
    if not candidate_stocks:
        return
    selected_set = set(_get_qualified_lynch_list(C, bar_date_str, candidate_stocks))
    current_holdings = [s for s in C.holding if C.holding.get(s, False)]
    # 1) 卖出不在新名单中的持仓
    for stock in list(current_holdings):
        if stock not in selected_set and stock in C.buy_shares:
            try:
                shares = C.buy_shares[stock]
                if shares < 100:
                    continue
                data = C.get_market_data_ex(['close', 'open'], [stock], end_time=bar_date_str, period='1d', count=2, subscribe=False)
                if stock not in data or len(data[stock]['close']) < 2:
                    continue
                current_price = data[stock]['close'][-1]
                if getattr(C, 'limit_down_no_sell', False):
                    o, c = data[stock]['open'][-1], data[stock]['close'][-1]
                    if o and o > 0 and (c - o) / o <= -0.095:
                        continue
                passorder(24, 1101, C.accountid, stock, 5, 0, shares, "彼得林奇-调出", 1, "", C)
                C.holding[stock] = False
                buy_price = C.buy_price.get(stock, current_price)
                profit_pct = (current_price - buy_price) / buy_price if buy_price else 0
                print(f"{bar_date_str} 调出 {stock} {shares}股 @ {current_price:.3f} 盈亏: {profit_pct:.1%}")
                for key in [C.buy_price, C.buy_shares, C.buy_date]:
                    if stock in key:
                        del key[stock]
            except Exception as e:
                print(f"调出异常 {stock}: {e}")
    # 2) 补足到 max_stocks：在 selected 里选尚未持仓的买入
    selected_list = list(selected_set)
    need = C.max_stocks - sum(1 for s in C.holding if C.holding.get(s, False))
    for stock in selected_list:
        if need <= 0:
            break
        if C.holding.get(stock, False):
            continue
        try:
            data = C.get_market_data_ex(['close', 'open'], [stock], end_time=bar_date_str, period='1d', count=2, subscribe=False)
            if stock not in data or len(data[stock]['close']) < 2:
                continue
            current_price = float(data[stock]['close'][-1])
            if current_price <= 0:
                continue
            if getattr(C, 'limit_up_no_buy', False):
                o, c = data[stock]['open'][-1], data[stock]['close'][-1]
                if o and o > 0 and (c - o) / o >= 0.095:
                    continue
            target_shares = int(C.per_stock_amount / current_price)
            shares = (target_shares // 100) * 100
            if shares < 100 or shares > 10000:
                continue
            passorder(23, 1101, C.accountid, stock, 5, 0, shares, "彼得林奇", 1, "", C)
            C.holding[stock] = True
            C.buy_price[stock] = current_price
            C.buy_shares[stock] = shares
            C.buy_date[stock] = current_date_str
            print(f"{bar_date_str} 买入 {stock} {shares}股 @ {current_price:.3f} PEG策略")
            C.draw_text(1, 1, '买')
            need -= 1
        except Exception as e:
            print(f"建仓异常 {stock}: {e}")

def build_new_positions(C, selected_stocks, bar_date_str, current_date_str):
    for stock in selected_stocks:
        try:
            data = C.get_market_data_ex(['close', 'open'], [stock], end_time=bar_date_str, period='1d', count=2, subscribe=False)
            if stock not in data or len(data[stock]['close']) < 2:
                continue
            current_price = float(data[stock]['close'][-1])
            if current_price <= 0:
                continue
            if getattr(C, 'limit_up_no_buy', False):
                o, c = data[stock]['open'][-1], data[stock]['close'][-1]
                if o and o > 0 and (c - o) / o >= 0.095:
                    continue
            target_shares = int(C.per_stock_amount / current_price)
            shares = (target_shares // 100) * 100
            if shares < 100 or shares > 10000:
                continue
            passorder(23, 1101, C.accountid, stock, 5, 0, shares, "彼得林奇", 1, "", C)
            C.holding[stock] = True
            C.buy_price[stock] = current_price
            C.buy_shares[stock] = shares
            C.buy_date[stock] = current_date_str
            print(f"{bar_date_str} 买入 {stock} {shares}股 @ {current_price:.3f} PEG策略")
            C.draw_text(1, 1, '买')
        except Exception as e:
            print(f"建仓异常 {stock}: {e}")

# ---------- 股票池：使用 QMT 文档中的 get_sector（无 get_index_constituent） ----------
def get_peter_lynch_stock_pool(C, bar_date_str):
    all_stocks = []
    try:
        index_stocks = []
        # 与项目内 strategy_range_breakout_20d 等一致：用 get_sector 取指数成分
        indices = ['000300.SH', '000905.SH', '000852.SH']
        for index_code in indices:
            try:
                if hasattr(C, 'get_sector') and callable(getattr(C, 'get_sector')):
                    stocks = C.get_sector(index_code)
                    if stocks:
                        index_stocks.extend(stocks)
            except Exception:
                continue
        if not index_stocks and hasattr(C, 'get_stock_list_in_sector') and callable(getattr(C, 'get_stock_list_in_sector')):
            try:
                index_stocks = list(C.get_stock_list_in_sector('沪深A股') or [])
            except Exception:
                pass
        if index_stocks:
            all_stocks = list(set(index_stocks))
            print(f"[{bar_date_str}] 彼得林奇股票池: {len(all_stocks)} 只")
            return all_stocks[:1800]
    except Exception as e:
        print(f"股票池获取失败: {e}")
    # 兜底
    all_stocks = [
        '600036.SH', '000333.SZ', '601318.SH', '000651.SZ', '600104.SH',
        '000858.SZ', '601288.SH', '000002.SZ', '600519.SH', '002475.SZ',
    ]
    return all_stocks

# ---------- PEG：优先真实 PE/增长率，否则用行情代理 ----------
def calculate_peg_ratio(C, stock, bar_date_str):
    try:
        pe = get_pe_ratio(C, stock, bar_date_str)
        growth_rate = calculate_earnings_growth_rate(C, stock, bar_date_str)
        if pe is not None and pe > 0 and growth_rate is not None and growth_rate > 0:
            # growth_rate 为小数，如 0.15 表示 15%
            peg = pe / (growth_rate * 100)
            return peg
        # 无基本面时使用代理：PEG_proxy = PE_proxy / (1年涨幅%)
        if getattr(C, 'use_peg_proxy', True):
            return calculate_peg_proxy(C, stock, bar_date_str)
    except Exception:
        pass
    return None

def get_pe_ratio(C, stock, bar_date_str):
    """优先 QMT 基本面（若存在），否则 None，由上层用 proxy"""
    try:
        if hasattr(C, 'get_fundamentals') and callable(getattr(C, 'get_fundamentals')):
            fd = C.get_fundamentals([stock], end_time=bar_date_str)
            if fd and stock in fd and fd[stock].get('pe_ratio') and fd[stock]['pe_ratio'] > 0:
                return float(fd[stock]['pe_ratio'])
        # 备用：价格/EPS（若 get_fundamentals 返回 eps）
        if hasattr(C, 'get_fundamentals') and callable(getattr(C, 'get_fundamentals')):
            fd = C.get_fundamentals([stock], end_time=bar_date_str)
            if fd and stock in fd:
                eps = fd[stock].get('eps')
                if eps and eps > 0:
                    data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=1, subscribe=False)
                    if stock in data and len(data[stock]['close']) > 0:
                        price = float(data[stock]['close'][-1])
                        return price / eps
    except Exception:
        pass
    return None

def calculate_earnings_growth_rate(C, stock, bar_date_str):
    """真实 3 年复合增长率（需历史 EPS）；若无则返回 None，由 PEG 代理处理"""
    try:
        eps_history = get_eps_history(C, stock, bar_date_str, years=3)
        if len(eps_history) < 2:
            return None
        oldest_eps = float(eps_history[0])
        latest_eps = float(eps_history[-1])
        if oldest_eps <= 0 or latest_eps <= 0:
            return None
        years = len(eps_history) - 1
        if years <= 0:
            return None
        cagr = (latest_eps / oldest_eps) ** (1 / years) - 1
        return cagr
    except Exception:
        return None

def get_eps_history(C, stock, bar_date_str, years=3):
    """若 QMT 无历史 EPS 接口，返回空或仅当前一条，供增长率计算返回 None"""
    eps_list = []
    try:
        if hasattr(C, 'get_fundamentals') and callable(getattr(C, 'get_fundamentals')):
            fd = C.get_fundamentals([stock], end_time=bar_date_str)
            if fd and stock in fd and fd[stock].get('eps'):
                eps_list.append(float(fd[stock]['eps']))
        if len(eps_list) == 0:
            return []
        # 若有历史 EPS 接口可在此扩展；否则仅当前值，上面 growth 会返回 None
    except Exception:
        pass
    return eps_list

def calculate_peg_proxy(C, stock, bar_date_str):
    """
    无 PE/EPS 时的 PEG 代理：1 年涨幅作「增长率」代理，PE 代理=10。
    PEG_proxy = 10 / (1年涨幅*100)。PEG<0.5 即 1年涨幅>20%，回测易选出标的。
    """
    try:
        data = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=260, subscribe=False)
        if stock not in data or len(data[stock]['close']) < 250:
            return None
        closes = list(data[stock]['close'])
        price_now = float(closes[-1])
        price_1y = float(closes[-min(250, len(closes))])
        if price_1y <= 0:
            return None
        ret_1y = (price_now - price_1y) / price_1y
        growth_pct = ret_1y * 100
        if growth_pct <= 0:
            return None
        pe_proxy = 10.0
        peg_proxy = pe_proxy / growth_pct
        return peg_proxy
    except Exception:
        return None

def get_market_cap(C, stock, bar_date_str):
    """
    获取单只股票市值，用于「市值从小到大、优先买小市值」的排序。
    优先流通市值 circulation_market_value，其次 market_value，再次 收盘价×FloatVolume。
    """
    try:
        if hasattr(C, 'get_instrument_detail') and callable(getattr(C, 'get_instrument_detail')):
            info = C.get_instrument_detail([stock])
            if info and stock in info:
                m = info[stock]
                if m.get('circulation_market_value', 0) > 0:
                    return m['circulation_market_value']
                if m.get('market_value', 0) > 0:
                    return m['market_value']
                # 部分 QMT 返回流通股本 FloatVolume，市值 = 收盘价 * FloatVolume
                if m.get('FloatVolume') is not None and m.get('FloatVolume') > 0:
                    d = C.get_market_data_ex(['close'], [stock], end_time=bar_date_str, period='1d', count=1, subscribe=False)
                    if stock in d and len(d[stock]['close']) > 0:
                        return float(d[stock]['close'][-1]) * float(m['FloatVolume'])
    except Exception:
        pass
    return float('inf')

def _build_stock_industry_map(C):
    """
    QMT 策略里没有 get_industry(股票) 这类「根据股票查行业」的接口；
    需用「板块列表 + 成分股」反建 股票->行业名（见迅投社区/xtdata 文档）。
    - 方式1：xtdata.get_sector_list() 取 SW1 申万一级，再 get_stock_list_in_sector(sector)
    - 方式2：get_sector_list(节点/类型) 取板块名列表，再 get_stock_list_in_sector(板块名)
    申万行业名如 SW1银行、SW1钢铁，is_cyclical 里用关键字匹配。
    """
    out = {}
    try:
        # 方式1：xtquant.xtdata（若在策略环境可用）
        try:
            from xtquant import xtdata
            sector_list = xtdata.get_sector_list()
            if sector_list:
                sw_sectors = [s for s in sector_list if isinstance(s, str) and s.startswith('SW1') and '加权' not in s]
                for sector in sw_sectors[:50]:
                    try:
                        stocks = xtdata.get_stock_list_in_sector(sector)
                        if stocks:
                            for s in stocks:
                                out[s] = sector
                    except Exception:
                        continue
                if out:
                    return out
        except Exception:
            pass
        # 方式2：ContextInfo 或全局 get_sector_list + get_stock_list_in_sector
        get_list = getattr(C, 'get_stock_list_in_sector', None) or getattr(C, 'get_sector', None)
        try:
            get_list = get_list or __import__('builtins').__dict__.get('get_stock_list_in_sector')
        except Exception:
            pass
        node_list = getattr(C, 'get_sector_list', None)
        try:
            if not node_list:
                node_list = __import__('builtins').__dict__.get('get_sector_list')
        except Exception:
            pass
        if get_list and callable(get_list):
            sector_names = []
            if node_list and callable(node_list):
                for arg in [None, '申万一级行业板块', '申万二级行业板块', '申万行业', '行业板块']:
                    try:
                        ret = node_list(arg) if arg is not None else node_list()
                        if ret is None:
                            continue
                        names = ret[0] if isinstance(ret, (tuple, list)) and len(ret) > 0 and isinstance(ret[0], list) else (ret if isinstance(ret, list) else [ret] if isinstance(ret, (tuple, list)) else [])
                        if isinstance(names, list) and names:
                            sector_names = names
                            break
                    except Exception:
                        continue
            if not sector_names:
                try:
                    from xtquant import xtdata
                    sector_names = [s for s in xtdata.get_sector_list() if isinstance(s, str) and ('SW1' in s or 'SW2' in s) and '加权' not in s]
                except Exception:
                    pass
            for sector_name in sector_names[:80]:
                try:
                    stocks = get_list(sector_name)
                    if stocks:
                        for s in stocks:
                            out[s] = sector_name
                except Exception:
                    continue
    except Exception:
        pass
    return out

def is_cyclical_or_project_based_industry(C, stock):
    """
    行业过滤：剔除周期性与项目类行业。
    QMT 无 get_industry(股票)，使用 init 时构建的 C.stock_to_industry（股票->行业名）判断；
    若映射为空则仅用 get_stock_name 做简单关键字过滤。
    """
    cyclical = ['煤炭', '钢铁', '有色', '石油', '化工', '建材', '房地产', '银行', '保险',
                '建筑', '工程', '电力', '航运', '航空', '汽车', '家电', '造纸']
    project = ['建筑', '工程', '电力设备', '环保', '通信设备', '计算机设备']
    try:
        industry_name = getattr(C, 'stock_to_industry', {}).get(stock, '')
        if industry_name:
            s = str(industry_name)
            if any(c in s for c in cyclical) or any(p in s for p in project):
                return True
        # 无行业映射时用名称简单过滤
        if hasattr(C, 'get_stock_name') and callable(getattr(C, 'get_stock_name')):
            name = C.get_stock_name(stock) or ''
            if 'ST' in name or '银行' in name or '保险' in name:
                return True
    except Exception:
        pass
    return False

def _is_chinext_star_bse_or_st(stock_code):
    if not stock_code or len(stock_code) < 6:
        return False
    code = stock_code.split('.')[0]
    suffix = (stock_code.split('.')[-1] or '').upper()
    if suffix == 'BJ':
        return True
    if code.startswith('300'):
        return True
    if code.startswith('688') or code.startswith('689'):
        return True
    if 'ST' in stock_code.upper():
        return True
    return False

def _trading_days_diff(date_start, date_end):
    try:
        d1 = datetime.strptime(str(date_start), '%Y%m%d')
        d2 = datetime.strptime(str(date_end), '%Y%m%d')
        return max(0, (d2 - d1).days)
    except Exception:
        return 0

def timetag_to_datetime(timetag, format_str='%Y-%m-%d'):
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)
