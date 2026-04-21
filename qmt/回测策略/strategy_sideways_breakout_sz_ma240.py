# coding: gbk
"""
横盘异动突破 + 深证 MA240 过滤 + 破线防御选股（红利/低波/质量/行业）

- 未破 MA240：横盘+突破截面选股；破 MA240：防御因子（见 _run_defensive_buy）
- 卖出：可选总亏止损 + ATR 移动止损；持仓按 barpos 计交易日
- 入口：init / handlebar；QMT 约定见 qmt_complete_functions.md
"""

import time
from itertools import chain
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import talib
except Exception:
    talib = None

# ---------------------------------------------------------------------------
# 常量（指数、财务字段、策略备注名）
# ---------------------------------------------------------------------------
SZ_INDEX_CODE = "399001.SZ"

# get_financial_data 字段（与迅投 data_function 表一致；勿随意改名）
FINANCIAL_FIELDS: Tuple[str, ...] = (
    "PERSHAREINDEX.equity_roe",
    "PERSHAREINDEX.net_roe",
    "PERSHAREINDEX.gear_ratio",
    "PERSHAREINDEX.sales_gross_profit",
    "PERSHAREINDEX.gross_profit",
    "ASHARECASHFLOW.cash_pay_dist_dpcp_int_exp",
    "CAPITALSTRUCTURE.total_capital",
)

STRATEGY_TAG_BREAKOUT = "横盘突破"
STRATEGY_TAG_DEFENSIVE = "防御红利低波"

DEFAULT_STOCK_POOL_INDICES: Tuple[str, ...] = ("399007.SZ", "000903.SH")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
def init(C) -> None:
    """初始化 ContextInfo：参数全部挂在 C 上，便于回测前在界面或代码中覆盖。"""
    C.accountid = getattr(C, "accountid", "")
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.buy_barpos = {}

    # --- 仓位与资金 ---
    C.max_stocks = 7
    C.per_stock_amount = 140_000
    C.min_hold_days = 7
    C.sort_by_factor = getattr(C, "sort_by_factor", "market_cap")

    # --- 横盘 ---
    C.amp_min = getattr(C, "amp_min", 0.03)
    C.amp_max = 0.06
    C.price_range_max = 1.15
    C.sideways_days = 20
    C.min_closes_for_buy = 22

    # --- 突破 ---
    C.breakout_amp_mult = 1.3
    C.today_return_max = 0.08
    C.today_high_return_max = getattr(C, "today_high_return_max", 0.095)

    # --- 价格 / 停牌 ---
    C.min_price = 3.0
    C.min_shares = 100
    C.skip_suspended = getattr(C, "skip_suspended", True)
    C.min_day_volume = getattr(C, "min_day_volume", 1)

    # --- 卖出 ---
    C.use_stop_loss_total = getattr(C, "use_stop_loss_total", False)
    C.stop_loss_total = 0.07
    C.atr_period = 14
    C.atr_stop_mult = 2.0

    C.use_squeeze_entry = getattr(C, "use_squeeze_entry", False)

    # --- 深证 MA240 ---
    C.sz_ma240_count = 250
    C.sz_ma240_period = 240
    C.bar_count = getattr(C, "bar_count", 25)

    # --- 破 MA240：防御选股 ---
    C.enable_defensive_ma240 = getattr(C, "enable_defensive_ma240", True)
    C.defensive_vol_window = getattr(C, "defensive_vol_window", 60)
    C.defensive_bar_count = getattr(C, "defensive_bar_count", 75)
    C.defensive_max_ann_vol = getattr(C, "defensive_max_ann_vol", 0.50)
    C.defensive_min_equity_roe = getattr(C, "defensive_min_equity_roe", 0.05)
    C.defensive_max_gear_ratio = getattr(C, "defensive_max_gear_ratio", 0.75)
    C.defensive_min_sales_gross = getattr(C, "defensive_min_sales_gross", 0.05)
    # 股息率下限：0=不强制红利（现金流为 0 或 mcap 估算偏差时易全灭）
    C.defensive_min_div_yield = getattr(C, "defensive_min_div_yield", 0.0)
    C.defensive_div_annualize = getattr(C, "defensive_div_annualize", False)
    # 财报字段缺失时是否跳过该条筛选（否则 gear/gross 为 None 会整票淘汰）
    C.defensive_skip_gear_if_missing = getattr(C, "defensive_skip_gear_if_missing", True)
    C.defensive_skip_gross_if_missing = getattr(C, "defensive_skip_gross_if_missing", True)
    C.defensive_max_scan = getattr(C, "defensive_max_scan", 500)
    C.defensive_fin_batch = getattr(C, "defensive_fin_batch", 40)
    C.defensive_require_sector = getattr(C, "defensive_require_sector", False)
    C.defensive_sector_names = getattr(
        C,
        "defensive_sector_names",
        [
            "银行", "电力", "电力设备", "公用事业", "交通运输", "公路铁路运输", "港口航运",
            "煤炭开采", "石油石化", "食品加工制造", "饮料制造", "医药生物", "中药", "化学制药",
            "电信服务", "通信设备", "水务", "燃气", "机场", "高速公路",
        ],
    )
    C._defensive_sector_cache_date = None
    C._defensive_sector_cache_set = None

    print("横盘突破策略（简化版-优化版）+ 深证MA240过滤 初始化完成")
    print(f"  日线取数 bar_count={C.bar_count}  最少K线 min_closes_for_buy={C.min_closes_for_buy}")
    print(f"  破MA240防御买入 enable_defensive_ma240={getattr(C, 'enable_defensive_ma240', True)}（需财务数据+板块名与客户端一致）")


# ---------------------------------------------------------------------------
# 持仓与下单（减少 handlebar 重复）
# ---------------------------------------------------------------------------
def _active_holdings_count(C) -> int:
    return sum(1 for h in C.holding.values() if h)


def _execute_buy(
    C,
    *,
    stock: str,
    price: float,
    bar_date_str: str,
    current_date_str: str,
    strategy_tag: str,
    log_suffix: str = "",
) -> bool:
    """按金额与最小手数买入；成功返回 True。"""
    target_shares = int(C.per_stock_amount / price)
    shares = (target_shares // C.min_shares) * C.min_shares
    if shares < C.min_shares:
        return False
    passorder(23, 1101, C.accountid, stock, 5, 0, shares, strategy_tag, 1, "", C)
    C.holding[stock] = True
    C.buy_price[stock] = price
    C.buy_shares[stock] = shares
    C.buy_date[stock] = current_date_str
    C.buy_barpos[stock] = C.barpos
    extra = f" {log_suffix}" if log_suffix else ""
    print(f"{bar_date_str} 买入 {stock} {shares}股 @ {price:.3f} {strategy_tag}{extra}")
    C.draw_text(1, 1, "买")
    return True


def _clear_holding_metadata(C, stock: str) -> None:
    for d in (C.buy_price, C.buy_shares, C.buy_date, C.buy_barpos):
        d.pop(stock, None)


# ---------------------------------------------------------------------------
# 风险与指数
# ---------------------------------------------------------------------------
def _check_stop_loss_total(C, current_price: float, buy_price: float) -> Tuple[bool, str]:
    if not getattr(C, "use_stop_loss_total", True):
        return False, ""
    if buy_price is None or buy_price <= 0:
        return False, ""
    pct = getattr(C, "stop_loss_total", 0.07)
    total_loss = (current_price - buy_price) / buy_price
    if total_loss < -pct:
        return True, "总亏损{:.0%}止损".format(pct)
    return False, ""


def _is_sz_below_ma240(C, bar_date_str: str) -> bool:
    """深证成指是否收于 MA240 下方；数据不足时返回 False（不拦截）。"""
    try:
        count = getattr(C, "sz_ma240_count", 250)
        period_len = getattr(C, "sz_ma240_period", 240)
        data = C.get_market_data_ex(
            ["close"], [SZ_INDEX_CODE],
            end_time=bar_date_str, period="1d", count=count, subscribe=False,
        )
        if SZ_INDEX_CODE not in data or len(data[SZ_INDEX_CODE]["close"]) < period_len:
            return False
        closes = list(data[SZ_INDEX_CODE]["close"])
        ma240 = np.mean(closes[-period_len:])
        return float(closes[-1]) < float(ma240)
    except Exception as e:
        print(f"深证MA240检查异常: {e}")
        return False


def _sz_index_status_message(sz_below: bool, enable_defensive: bool) -> str:
    if not sz_below:
        return "未破MA240：可横盘突破"
    base = "破MA240：暂停横盘突破"
    return base + ("，启用防御选股" if enable_defensive else "，防御买入已关(不开新仓)")


# ---------------------------------------------------------------------------
# 停牌 / 波动
# ---------------------------------------------------------------------------
def _is_suspended_last_day(
    volumes, highs, lows, closes, opens, min_vol: float,
) -> bool:
    if not closes:
        return True
    i = -1
    if volumes is not None and len(volumes) > 0:
        idx = i if len(volumes) >= len(closes) else -1
        try:
            return float(volumes[idx]) < float(min_vol)
        except Exception:
            pass
    try:
        h, l, o, c = float(highs[i]), float(lows[i]), float(opens[i]), float(closes[i])
        return h == l == o == c
    except Exception:
        return True


def _annualized_vol_from_closes(closes: Sequence[float], window: int) -> Optional[float]:
    if closes is None or len(closes) < window + 1:
        return None
    arr = np.array(closes[-(window + 1):], dtype=np.float64)
    if np.any(arr <= 0):
        return None
    rets = np.diff(arr) / arr[:-1]
    if len(rets) < 2:
        return None
    return float(np.std(rets, ddof=1)) * np.sqrt(252.0)


# ---------------------------------------------------------------------------
# 财务工具
# ---------------------------------------------------------------------------
def _get_financial_data_fn(C):
    fn = getattr(C, "get_financial_data", None)
    if callable(fn):
        return fn
    g = globals()
    gfd = g.get("get_financial_data")
    return gfd if callable(gfd) else None


def _financial_start_time(end_date_yyyy_mm_dd: str) -> str:
    y = int(end_date_yyyy_mm_dd[:4])
    return f"{y - 5}0101"


def _norm_pct_value(x) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
        if np.isnan(v):
            return None
        return v / 100.0 if abs(v) > 1.5 else v
    except Exception:
        return None


def _norm_ratio_0_1(x) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
        if np.isnan(v):
            return None
        return v / 100.0 if v > 1.0 + 1e-6 else v
    except Exception:
        return None


def _is_tabular_df(obj: Any) -> bool:
    """是否为类 DataFrame（不 import pandas，兼容 QMT 返回的表对象）。"""
    return hasattr(obj, "iloc") and hasattr(obj, "columns") and hasattr(obj, "__len__")


def _is_tabular_series(obj: Any) -> bool:
    """是否为类 Series（有 index、iloc，无 columns）。"""
    return hasattr(obj, "iloc") and hasattr(obj, "index") and not hasattr(obj, "columns")


def _slice_financial_table_for_stock(df: Any, stock: str) -> Any:
    """
    批量财务表可能为多行多标的：按代码/多级索引切到当前 stock 再取数。
    """
    if not _is_tabular_df(df) or len(df) < 1:
        return df
    prefix = stock.split(".")[0]
    try:
        idx = df.index
        if hasattr(idx, "names") and idx.names and len(idx.names) > 1:
            for level in range(len(idx.names)):
                lev = idx.get_level_values(level)
                as_set = {str(x) for x in lev}
                if stock in as_set or f"{prefix}.SH" in as_set or f"{prefix}.SZ" in as_set:
                    try:
                        sub = df.xs(stock, level=level, drop_level=False)
                        if _is_tabular_df(sub) and len(sub) >= 1:
                            return sub
                    except Exception:
                        pass
                    try:
                        for key in (stock, prefix):
                            if key in lev:
                                sub = df.xs(key, level=level, drop_level=False)
                                if _is_tabular_df(sub) and len(sub) >= 1:
                                    return sub
                    except Exception:
                        pass
    except Exception:
        pass
    for col in ("thscode", "stock_code", "证券代码", "股票代码", "code"):
        if col not in getattr(df, "columns", []):
            continue
        try:
            ser = df[col].astype(str)
            if hasattr(ser, "str"):
                mask = ser.str.contains(prefix, na=False)
            else:
                mask = [prefix in str(x) for x in ser]
            sub = df[mask]
            if _is_tabular_df(sub) and len(sub) >= 1:
                return sub
        except Exception:
            continue
    return df


def _filter_df_by_code_column(df: Any, col: str, code_prefix: str) -> Any:
    """按代码列包含 code_prefix 筛选；优先用 pandas 风格 .str.contains。"""
    if not _is_tabular_df(df) or col not in df.columns:
        return None
    col_data = df[col]
    try:
        if hasattr(col_data, "str"):
            mask_series = col_data.astype(str).str.contains(code_prefix, na=False)
            return df[mask_series]
        mask = [code_prefix in str(df.iloc[i][col]) for i in range(len(df))]
        return df.loc[mask] if hasattr(df, "loc") else None
    except Exception:
        return None


def _parse_financial_to_metrics(raw: Any, stock: str) -> Optional[Dict[str, Any]]:
    """
    解析 get_financial_data 返回值。
    不依赖 import pandas：对 QMT 返回的 DataFrame/Series 用鸭子类型访问；
    若环境无 pandas 且接口返回 dict，则走 dict 分支即可。
    """
    keys = {
        "equity_roe": "PERSHAREINDEX.equity_roe",
        "net_roe": "PERSHAREINDEX.net_roe",
        "gear_ratio": "PERSHAREINDEX.gear_ratio",
        "sales_gross_profit": "PERSHAREINDEX.sales_gross_profit",
        "gross_profit": "PERSHAREINDEX.gross_profit",
        "cash_dist": "ASHARECASHFLOW.cash_pay_dist_dpcp_int_exp",
        "total_capital": "CAPITALSTRUCTURE.total_capital",
    }
    try:
        df = None
        if isinstance(raw, dict):
            df = raw.get(stock)
            if df is None:
                for k, v in raw.items():
                    if k == stock or (isinstance(k, str) and stock in k):
                        df = v
                        break
        elif _is_tabular_df(raw):
            df = raw

        if df is None or not _is_tabular_df(df) or len(df) < 1:
            return None

        df = _slice_financial_table_for_stock(df, stock)

        prefix = stock.split(".")[0]
        cols = getattr(df, "columns", None)
        for col in ("stock_code", "code", "证券代码", "股票代码"):
            if cols is None or col not in cols:
                continue
            sub = _filter_df_by_code_column(df, col, prefix)
            if sub is not None and len(sub) >= 1:
                df = sub
            break

        try:
            idx = getattr(df, "index", None)
            if idx is not None and hasattr(idx, "get_level_values"):
                level0 = idx.get_level_values(0)
                if stock in set(level0):
                    df = df.loc[stock]
        except Exception:
            pass

        if _is_tabular_series(df):
            row = df
        else:
            row = df.iloc[-1]

        def pick(col_name: str):
            if col_name in row.index:
                return row[col_name]
            for idx in row.index:
                if str(idx).endswith(col_name.split(".")[-1]):
                    return row[idx]
            return None

        return {short: pick(full) for short, full in keys.items()}
    except Exception:
        return None


def _defensive_gross_margin(m: Optional[Dict]) -> Optional[float]:
    if not m:
        return None
    g = _norm_pct_value(m.get("sales_gross_profit"))
    return g if g is not None else _norm_pct_value(m.get("gross_profit"))


def _defensive_roe(m: Optional[Dict]) -> Optional[float]:
    if not m:
        return None
    r = _norm_pct_value(m.get("equity_roe"))
    return r if r is not None else _norm_pct_value(m.get("net_roe"))


def _fetch_financial_metrics(C, stock: str, end_date: str) -> Optional[Dict[str, Any]]:
    fn = _get_financial_data_fn(C)
    if not fn:
        return None
    start = _financial_start_time(end_date)
    try:
        raw = fn(list(FINANCIAL_FIELDS), [stock], "announce_time", start_time=start, end_time=end_date)
    except Exception:
        return None
    return _parse_financial_to_metrics(raw, stock)


def _fetch_financial_metrics_batch(C, stocks: List[str], end_date: str) -> Dict[str, Dict]:
    fn = _get_financial_data_fn(C)
    if not fn or not stocks:
        return {}
    start = _financial_start_time(end_date)
    try:
        raw = fn(list(FINANCIAL_FIELDS), list(stocks), "announce_time", start_time=start, end_time=end_date)
    except Exception:
        raw = None
    def _resolve_m(stock: str):
        m = _parse_financial_to_metrics(raw, stock) if raw is not None else None
        if not m or all(v is None for v in m.values()):
            m = _fetch_financial_metrics(C, stock, end_date)
        return stock, m

    return {
        s: m
        for s, m in (_resolve_m(s) for s in stocks)
        if m and any(v is not None for v in m.values())
    }


def _defensive_composite_score(dy: Optional[float], roe: Optional[float], vol: Optional[float]) -> float:
    dy = dy or 0.0
    roe = roe or 0.0
    vol = vol if vol is not None else 1.0
    return dy * 3.0 + roe * 2.0 - vol * 0.5


def _defensive_pass_filters(
    C, m: Dict, current_close: float, ann_vol: float,
) -> Optional[float]:
    """通过则返回综合分，否则 None。"""
    roe = _defensive_roe(m)
    gear = _norm_ratio_0_1(m.get("gear_ratio"))
    gross = _defensive_gross_margin(m)
    tc_raw, cashd_raw = m.get("total_capital"), m.get("cash_dist")
    try:
        tc = float(tc_raw) if tc_raw is not None else None
        cashd = float(cashd_raw) if cashd_raw is not None else None
    except Exception:
        tc, cashd = None, None

    mcap = tc * current_close if (tc and tc > 0 and current_close > 0) else None
    dy = None
    if mcap and mcap > 0 and cashd is not None and cashd >= 0:
        dy = cashd / mcap
        if getattr(C, "defensive_div_annualize", False):
            dy *= 4.0

    min_roe = float(getattr(C, "defensive_min_equity_roe", 0.05))
    if roe is None or roe < min_roe:
        return None

    max_gear = float(getattr(C, "defensive_max_gear_ratio", 0.75))
    skip_gear = getattr(C, "defensive_skip_gear_if_missing", True)
    if gear is not None:
        if gear > max_gear:
            return None
    elif not skip_gear:
        return None

    min_g = float(getattr(C, "defensive_min_sales_gross", 0.05))
    skip_gross = getattr(C, "defensive_skip_gross_if_missing", True)
    if gross is not None:
        if gross < min_g:
            return None
    elif not skip_gross:
        return None

    min_dy = float(getattr(C, "defensive_min_div_yield", 0.0))
    if min_dy > 0 and (dy is None or dy < min_dy):
        return None
    return _defensive_composite_score(dy, roe, ann_vol)


def _sector_constituents_safe(C, sector_name: str) -> List[str]:
    try:
        if hasattr(C, "get_stock_list_in_sector"):
            lst = C.get_stock_list_in_sector(sector_name)
            return list(lst) if lst else []
    except Exception:
        pass
    return []


def _build_defensive_sector_set(C, current_date_str: str) -> set:
    if (
        getattr(C, "_defensive_sector_cache_date", None) == current_date_str
        and getattr(C, "_defensive_sector_cache_set", None) is not None
    ):
        return C._defensive_sector_cache_set
    names = getattr(C, "defensive_sector_names", []) or []
    s = set(chain.from_iterable(_sector_constituents_safe(C, n) for n in names))
    C._defensive_sector_cache_date = current_date_str
    C._defensive_sector_cache_set = s
    return s


# ---------------------------------------------------------------------------
# 卖出单标的逻辑（供 handlebar 循环调用）
# ---------------------------------------------------------------------------
def _process_sell_one_stock(C, stock: str, bar_date_str: str) -> None:
    try:
        buy_bar = C.buy_barpos.get(stock, C.barpos)
        days_held = max(0, C.barpos - buy_bar)
        in_min_hold = days_held < C.min_hold_days
        bar_count = max(
            getattr(C, "bar_count", 25),
            days_held + 10,
            getattr(C, "atr_period", 14) + 5,
        )
        data = C.get_market_data_ex(
            ["close", "high", "low", "open"], [stock],
            end_time=bar_date_str, period=getattr(C, "period", "1d"),
            count=bar_count, subscribe=False,
        )
        if stock not in data or len(data[stock].get("close", [])) < 2:
            return

        closes = list(data[stock]["close"])
        opens = list(data[stock]["open"])
        highs = list(data[stock]["high"])
        lows = list(data[stock]["low"])
        current_price = closes[-1]
        buy_price = C.buy_price.get(stock, current_price)

        if opens[-1] <= 0:
            return

        sell_condition = False
        sell_reason = ""

        stop_triggered, stop_reason = _check_stop_loss_total(C, current_price, buy_price)
        if stop_triggered:
            sell_condition, sell_reason = True, stop_reason
        elif not in_min_hold and talib is not None and days_held >= 1:
            n_since_entry = min(days_held + 1, len(highs))
            highest_high_since_entry = max(highs[-n_since_entry:])
            try:
                atr_arr = talib.ATR(
                    np.array(highs, dtype=np.float64),
                    np.array(lows, dtype=np.float64),
                    np.array(closes, dtype=np.float64),
                    getattr(C, "atr_period", 14),
                )
                atr_14 = float(atr_arr[-1]) if len(atr_arr) and not np.isnan(atr_arr[-1]) else None
            except Exception:
                atr_14 = None
            if atr_14 is not None and atr_14 > 0:
                mult = getattr(C, "atr_stop_mult", 2.0)
                stop_loss = highest_high_since_entry - atr_14 * mult
                if current_price <= stop_loss:
                    sell_condition = True
                    sell_reason = (
                        "ATR移动止损(最高{hh:.3f}-ATR*{m:.1f}={sl:.3f})".format(
                            hh=highest_high_since_entry, m=mult, sl=stop_loss
                        )
                    )

        if not sell_condition or stock not in C.buy_shares:
            return
        shares = C.buy_shares[stock]
        if shares < C.min_shares:
            return
        passorder(24, 1101, C.accountid, stock, 5, 0, shares, STRATEGY_TAG_BREAKOUT, 1, "", C)
        C.holding[stock] = False
        profit = (current_price - buy_price) * shares
        profit_pct = (current_price - buy_price) / buy_price
        print(f"{bar_date_str} 卖出 {stock} {shares}股 @ {current_price:.3f} {sell_reason} 盈亏: {profit:.2f} ({profit_pct:.1%})")
        _clear_holding_metadata(C, stock)
        C.draw_text(1, 1, "卖")
    except Exception as e:
        print(f"卖出异常 {stock}: {e}")


# ---------------------------------------------------------------------------
# 横盘突破买入扫描
# ---------------------------------------------------------------------------
def _scan_sideways_breakout_candidates(
    C, all_stocks: List[str], bar_date_str: str,
) -> Tuple[List[Tuple[str, float, float]], Dict[str, int]]:
    """返回 (候选列表, 统计计数器)。"""
    stats = {
        "sector": 0,
        "data": 0,
        "skipped_susp": 0,
        "price": 0,
        "sideways": 0,
        "breakout": 0,
    }
    candidates: List[Tuple[str, float, float]] = []

    for stock in all_stocks:
        if C.holding.get(stock, False) or _is_chinext_star_bse_or_st(stock):
            continue
        stats["sector"] += 1
        try:
            fields = ["close", "high", "low", "open"]
            if getattr(C, "use_squeeze_entry", False) or getattr(C, "skip_suspended", True):
                fields = fields + ["volume"] if "volume" not in fields else fields
            data = C.get_market_data_ex(
                fields, [stock], end_time=bar_date_str, period="1d",
                count=C.bar_count, subscribe=False,
            )
            if stock not in data or len(data[stock]["close"]) < C.min_closes_for_buy:
                continue
            stats["data"] += 1

            closes = list(data[stock]["close"])
            highs = list(data[stock]["high"])
            lows = list(data[stock]["low"])
            opens = list(data[stock]["open"])
            volumes = list(data[stock].get("volume", [])) if "volume" in data[stock] else None
            if len(closes) < 2:
                continue
            if getattr(C, "skip_suspended", True) and _is_suspended_last_day(
                volumes, highs, lows, closes, opens, getattr(C, "min_day_volume", 1),
            ):
                stats["skipped_susp"] += 1
                continue

            prev_close = float(closes[-2])
            current_close = float(closes[-1])
            if prev_close <= 0 or current_close <= 0 or current_close <= C.min_price:
                continue
            stats["price"] += 1

            if getattr(C, "use_squeeze_entry", False) and not _check_squeeze_entry(
                closes, highs, lows, volumes,
            ):
                continue

            avg_amp, price_range = calculate_sideways_metrics(highs, lows, closes, C.sideways_days)
            if not (C.amp_min <= avg_amp <= C.amp_max and price_range <= C.price_range_max):
                continue
            stats["sideways"] += 1

            today_return = (current_close - prev_close) / prev_close
            today_high_return = (float(highs[-1]) - prev_close) / prev_close if prev_close > 0 else 0.0
            if today_high_return >= C.today_high_return_max:
                continue
            if not (
                today_return > avg_amp * C.breakout_amp_mult
                and today_return < C.today_return_max
            ):
                continue
            if _is_three_consecutive_down(closes):
                continue
            stats["breakout"] += 1
            sort_value = _get_sort_value(C, stock, current_close)
            candidates.append((stock, current_close, sort_value))
        except Exception as e:
            print(f"买入异常 {stock}: {e}")

    return candidates, stats


def _run_sideways_buy(
    C, bar_date_str: str, current_date_str: str, all_stocks: List[str], current_holdings: int,
) -> None:
    total_stocks = len(all_stocks)
    candidates, st = _scan_sideways_breakout_candidates(C, all_stocks, bar_date_str)

    if C.sort_by_factor == "market_cap" and candidates:
        candidates.sort(key=lambda x: x[2])

    need_buy = min(C.max_stocks - current_holdings, len(candidates))
    to_buy = candidates[:need_buy]
    final_selected = sum(
        _execute_buy(
            C, stock=s, price=p, bar_date_str=bar_date_str,
            current_date_str=current_date_str, strategy_tag=STRATEGY_TAG_BREAKOUT,
        )
        for s, p, _ in to_buy
    )

    print(
        f"[{bar_date_str}] 筛选统计: 总分析{total_stocks} 板块{st['sector']} 数据{st['data']} "
        f"停牌剔除{st['skipped_susp']} 价格>{C.min_price}共{st['price']} 横盘{st['sideways']} "
        f"突破{st['breakout']} 候选{len(candidates)} 买入{final_selected}"
    )


# ---------------------------------------------------------------------------
# 防御买入
# ---------------------------------------------------------------------------
def _run_defensive_buy(
    C, bar_date_str: str, current_date_str: str, all_stocks: List[str], current_holdings: int,
) -> None:
    if not getattr(C, "enable_defensive_ma240", True):
        print(f"[{bar_date_str}] 深证破MA240，防御买入已关闭(enable_defensive_ma240=False)，当前持仓: {current_holdings}")
        return

    defensive_set = _build_defensive_sector_set(C, current_date_str)
    require_sector = getattr(C, "defensive_require_sector", False)
    if require_sector and len(defensive_set) == 0:
        print(f"[{bar_date_str}] 深证破MA240：防御板块合并为空且 defensive_require_sector=True，跳过防御买入，持仓: {current_holdings}")
        return

    if len(defensive_set) == 0 and not getattr(C, "_warned_defensive_sector_empty", False):
        print(f"[{bar_date_str}] 提示：防御板块合并为空，仅按财务+低波筛选（请核对 get_stock_list_in_sector 板块名）")
        C._warned_defensive_sector_empty = True

    vol_w = int(getattr(C, "defensive_vol_window", 60))
    bc = max(int(getattr(C, "defensive_bar_count", 75)), vol_w + 5)
    max_scan = int(getattr(C, "defensive_max_scan", 500) or 0)

    prelim: List[Tuple[str, float, float]] = []
    scanned = 0
    for stock in all_stocks:
        if max_scan > 0 and scanned >= max_scan:
            break
        scanned += 1
        if C.holding.get(stock, False) or _is_chinext_star_bse_or_st(stock):
            continue
        if defensive_set and stock not in defensive_set:
            continue
        try:
            data = C.get_market_data_ex(
                ["close", "high", "low", "open", "volume"], [stock],
                end_time=bar_date_str, period="1d", count=bc, subscribe=False,
            )
            if stock not in data or len(data[stock].get("close", [])) < C.min_closes_for_buy:
                continue
            closes = list(data[stock]["close"])
            highs = list(data[stock]["high"])
            lows = list(data[stock]["low"])
            opens = list(data[stock]["open"])
            volumes = list(data[stock].get("volume", [])) if "volume" in data[stock] else None
            if len(closes) < 2:
                continue
            if getattr(C, "skip_suspended", True) and _is_suspended_last_day(
                volumes, highs, lows, closes, opens, getattr(C, "min_day_volume", 1),
            ):
                continue
            current_close = float(closes[-1])
            if current_close <= 0 or current_close < C.min_price:
                continue
            ann_vol = _annualized_vol_from_closes(closes, vol_w)
            if ann_vol is None or ann_vol > float(getattr(C, "defensive_max_ann_vol", 0.50)):
                continue
            prelim.append((stock, current_close, float(ann_vol)))
        except Exception as e:
            print(f"防御预选异常 {stock}: {e}")

    fin_bs = max(1, int(getattr(C, "defensive_fin_batch", 40)))
    chunks = [prelim[i : i + fin_bs] for i in range(0, len(prelim), fin_bs)]
    candidates_def: List[Tuple[str, float, float]] = []
    for chunk in chunks:
        fin_map = _fetch_financial_metrics_batch(C, [x[0] for x in chunk], current_date_str)
        candidates_def.extend(
            (s, cc, sc)
            for s, cc, av in chunk
            for m in (fin_map.get(s),)
            if m
            for sc in (_defensive_pass_filters(C, m, cc, av),)
            if sc is not None
        )

    candidates_def.sort(key=lambda x: -x[2])
    need_buy = min(C.max_stocks - current_holdings, len(candidates_def))
    to_buy_d = candidates_def[:need_buy]
    final_d = sum(
        _execute_buy(
            C, stock=s, price=p, bar_date_str=bar_date_str,
            current_date_str=current_date_str, strategy_tag=STRATEGY_TAG_DEFENSIVE,
            log_suffix="(破MA240)",
        )
        for s, p, _ in to_buy_d
    )
    print(f"[{bar_date_str}] 防御买入统计: 扫描{scanned} 预选{len(prelim)} 财务通过{len(candidates_def)} 买入{final_d}")


# ---------------------------------------------------------------------------
# handlebar
# ---------------------------------------------------------------------------
def handlebar(C) -> None:
    bar_date_str = timetag_to_datetime(C.get_bar_timetag(C.barpos), "%Y%m%d%H%M%S")
    current_date_str = bar_date_str[:8]

    all_stocks = get_stock_pool(C, bar_date_str)
    print(f"[{bar_date_str}] 股票池大小: {len(all_stocks)} 只股票")

    held = [s for s in list(C.holding.keys()) if C.holding.get(s, False)]
    for stock in held:
        _process_sell_one_stock(C, stock, bar_date_str)

    sz_below = _is_sz_below_ma240(C, bar_date_str)
    en_def = getattr(C, "enable_defensive_ma240", True)
    print(f"[{bar_date_str}] 深证指数: {_sz_index_status_message(sz_below, en_def)}")

    holdings = _active_holdings_count(C)
    if holdings >= C.max_stocks:
        return

    if not sz_below:
        _run_sideways_buy(C, bar_date_str, current_date_str, all_stocks, holdings)
    else:
        _run_defensive_buy(C, bar_date_str, current_date_str, all_stocks, holdings)


# ---------------------------------------------------------------------------
# 挤压 / 横盘指标 / 股票池 / 过滤
# ---------------------------------------------------------------------------
def _check_squeeze_entry(closes, highs, lows, volumes, bb_period=20, kc_mult=1.5, vol_mult=1.5):
    if talib is None or len(closes) < 22 or len(highs) < 22 or len(lows) < 22:
        return False
    if volumes is None or len(volumes) < 21:
        return False
    try:
        close_arr = np.array(closes, dtype=np.float64)
        high_arr = np.array(highs, dtype=np.float64)
        low_arr = np.array(lows, dtype=np.float64)
        bb_upper, bb_middle, bb_lower = talib.BBANDS(close_arr, bb_period, 2, 2)
        kc_middle = talib.SMA(close_arr, bb_period)
        tr = talib.TRANGE(high_arr, low_arr, close_arr)
        kc_range = talib.SMA(tr, bb_period)
        kc_upper = kc_middle + kc_mult * kc_range
        kc_lower = kc_middle - kc_mult * kc_range
        squeeze_on = (bb_lower > kc_lower) & (bb_upper < kc_upper)
        if not (squeeze_on[-1] and squeeze_on[-2] and squeeze_on[-3]):
            return False
        prev_20_high = max(highs[-21:-1]) if len(highs) >= 21 else 0
        if closes[-1] <= prev_20_high or prev_20_high <= 0:
            return False
        vol_ma20 = np.mean(volumes[-20:])
        return vol_ma20 > 0 and volumes[-1] > vol_ma20 * vol_mult
    except Exception:
        return False


def calculate_sideways_metrics(highs, lows, closes, period=20):
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return float("inf"), float("inf")

    idx = range(len(closes) - period - 1, len(closes) - 1)
    amps = [(highs[i + 1] - lows[i + 1]) / closes[i] for i in idx if closes[i] > 0]
    avg_amplitude = float("inf") if not amps else sum(amps) / len(amps)

    recent_highs = highs[-period - 1 : -1]
    recent_lows = lows[-period - 1 : -1]
    if not recent_highs or not recent_lows:
        return avg_amplitude, float("inf")
    period_low = min(recent_lows)
    if period_low <= 0:
        return avg_amplitude, float("inf")
    return avg_amplitude, max(recent_highs) / period_low


def _index_constituents_safe(C, index_code: str) -> List[str]:
    try:
        if hasattr(C, "get_index_constituent"):
            s = C.get_index_constituent(index_code)
            return list(s) if s else []
        if hasattr(C, "get_sector"):
            s = C.get_sector(index_code)
            return list(s) if s else []
    except Exception:
        pass
    return []


def get_stock_pool(C, current_date_str: str) -> List[str]:
    try:
        index_stocks = [c for code in DEFAULT_STOCK_POOL_INDICES for c in _index_constituents_safe(C, code)]
        if index_stocks:
            out = list(set(index_stocks))
            print(f"组合指数成分股 {len(out)} 只")
            return out
    except Exception as e:
        print(f"组合指数成分股失败: {e}")
    return []


def _is_three_consecutive_down(closes) -> bool:
    if len(closes) < 6:
        return False
    return closes[-2] < closes[-3] and closes[-3] < closes[-4] and closes[-4] < closes[-5]


def _qmt_sort_market_cap(C, stock_code: str, price: float) -> Optional[float]:
    try:
        p = float(price)
    except Exception:
        p = 0.0
    if p <= 0:
        return None
    for name in ("get_instrumentdetail", "get_instrumentDetail"):
        if not hasattr(C, name):
            continue
        try:
            inf = getattr(C, name)(stock_code)
            if isinstance(inf, dict):
                fv = inf.get("FloatVolume", inf.get("float_volume"))
                tv = inf.get("TotalVolume", inf.get("total_volume"))
                try:
                    if fv is not None and float(fv) > 0:
                        return float(fv) * p
                    if tv is not None and float(tv) > 0:
                        return float(tv) * p
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass
    if hasattr(C, "get_instrument_detail"):
        for complete in (True, False):
            try:
                info = C.get_instrument_detail([stock_code], iscomplete=complete)
            except TypeError:
                break
            except Exception:
                continue
            if info and stock_code in info:
                inf = info[stock_code]
                for k in ("circulation_market_value", "market_value"):
                    try:
                        v = inf.get(k, 0) if isinstance(inf, dict) else getattr(inf, k, 0)
                        if v and float(v) > 0:
                            return float(v)
                    except Exception:
                        pass
        try:
            instrument_info = C.get_instrument_detail([stock_code])
            if instrument_info and stock_code in instrument_info:
                info = instrument_info[stock_code]
                if isinstance(info, dict):
                    for k in ("circulation_market_value", "market_value"):
                        if info.get(k, 0) > 0:
                            return float(info[k])
        except Exception:
            pass
    return None


def _get_sort_value(C, stock_code: str, current_close: float) -> float:
    if C.sort_by_factor != "market_cap":
        return 0.0
    mv = _qmt_sort_market_cap(C, stock_code, current_close)
    return float(mv) if (mv is not None and mv > 0) else float(current_close)


def _is_chinext_star_bse_or_st(stock_code: str) -> bool:
    if not stock_code or len(stock_code) < 6:
        return False
    code = stock_code.split(".")[0]
    suf = (stock_code.split(".")[-1] or "").upper()
    risky_prefix = ("300", "688", "689", "920")
    return (
        suf == "BJ"
        or any(code.startswith(p) for p in risky_prefix)
        or "ST" in stock_code.upper()
    )


def timetag_to_datetime(timetag, format_str="%Y-%m-%d"):
    try:
        return time.strftime(format_str, time.localtime(timetag / 1000))
    except Exception:
        return str(timetag)
