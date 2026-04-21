# coding: gbk
"""
QMT 回测：截面强势分位 + 趋势确认 + 轮动

- 选股：先按 **前 mom_lookback 日（默认 10 日）累计涨幅** 做截面排名，取最强约 **winner_top_pct（默认 5%）**；再筛当日涨幅区间；其余过滤通过后按该 N 日收益降序买入。N 日涨幅上限见 max_momentum_ret；收盘站上 trend_ma；过滤一字板；可选收阳；可选低位涨幅过滤（max_25d_rise_from_low_pct）。
- 大盘（默认）：以 **中证500（000905.SH）** 为 `index_ma_filter_code` 做均线多头与倾角判断；MA10>MA20>MA30>MA60，且收盘>=MA10；倾角默认 **>=0.1°**；<=0 时仍按「严格大于 0°」理解。
- 卖出：**仅 ATR 吊灯**（持仓以来最高价回撤 ATR×倍数触发）；无固定比例止损、无跌破均线、无持有天数平仓。
- 仓位：默认最多 10 只；可 **`use_equity_based_sizing`** 按账户总资产×`equity_deploy_pct`÷`max_hold_count` 动态每票金额（复利）；否则固定 `per_stock_amount`。每日最多买 4、冷却 1 天。参数见 `STRATEGY_DEFAULTS`。

入口：init / handlebar。
"""

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# 可调参数默认值（init 批量写入 C；若 QMT 在 init 前已设 C.k 则保留界面值）
#
# 【仓位与交易节奏】
#   max_hold_count      同时最多持仓只数
#   per_stock_amount    每只股票目标金额（元）；若 use_equity_based_sizing 为真则作兜底（读不到权益时）
#   use_equity_based_sizing  True：每票≈账户总资产×equity_deploy_pct÷max_hold_count（复利均分）
#   equity_deploy_pct     总资产参与分配比例（0~1，如 0.95 留 5% 应对手续费/波动）
#   min_order_shares    最小下单股数（通常 100 为一手）
#   max_buy_per_day     每个交易日最多新开仓笔数
#   cooldown_days       卖出后冷却：未满 N 个自然日差则不再买回同一只
#
# 【截面动量与分层】
#   mom_lookback          截面排名用：近 N 日累计涨幅（默认 10 日）
#   winner_top_pct        截面前强比例（默认 0.05=约前 5%）
#
# 【低位已涨过滤】近窗口最低价→收盘涨幅过大则剔除（避免低位已拉满）
#   use_max_25d_rise_from_low_filter  是否启用该过滤
#   max_25d_rise_from_low_pct         涨幅上限比例（如 0.8 表示低于 80% 才保留）
#   max_25d_rise_lookback             最低价与收盘比较的回望天数
#
# 【趋势与一字板】
#   trend_ma_period       趋势确认：收盘需站上该周期均线
#   require_up_day        是否要求当日收阳（收盘>=昨收）
#   min_price             过滤低价股：收盘价低于则不买
#   min_day_volume        当日成交量下限（股），过低不买
#   limit_up_min_ret      一字板判定：日涨幅>=该值且振幅很小视为一字板并跳过
#   limit_up_max_spread   一字板判定：(高-低)/昨收 上限
#   daily_count             拉行情时请求的日 K 根数（需覆盖指标与 lookback）
#
# 【开仓当日涨幅】日 K 今收相对昨收涨幅，须在 [min, max] 内才允许买入（闭区间）
#   use_max_day_gain_buy_filter  是否启用该区间过滤
#   min_day_gain_buy_pct         下限（小数 3%）；低于则不买（大跌日不接）
#   max_day_gain_buy_pct         上限（小数 0.08=8%）；高于则不买（避免追高）
#
# 【卖出】仅 ATR 吊灯
#   atr_period            ATR 周期
#   atr_multiplier        吊灯线：止损价 = 持仓段最高价 ? ATR×倍数
#
# 【股票池】
#   stock_pool_indices    成分股来源指数代码元组（多指数合并去重）
#   stock_pool_scan_cap   每日最多扫描股票数量上限（控制回测耗时）
#
# 【大盘过滤】
#   use_index_ma_filter         是否启用指数侧过滤；False 则不做大盘判断
#   index_ma_filter_code        大盘过滤用的指数（默认 000905.SH 中证500）
#   use_index_bull_align        True：指数均线多头+可选倾角；False 时用下方简单/双均线逻辑
#   index_bull_ma_periods       多头排列各条均线周期（短到长递增）
#   index_bull_require_close_above_short  多头模式下是否要求收盘>=最短均线
#   use_index_ma_slope_check    是否检查各均线「倾角」
#   index_ma_slope_lookback     倾角计算：均线今值与若干日前比较的回望根数（须>=1 的整数）
#   index_ma_min_slope_deg      倾角下限（度）。默认 0：大盘各条 MA 倾角须严格大于 0°；设为正数则要求 >= 该角度
#   index_ma_period             非多头模式：短均线周期（收盘>=MA）
#   use_index_dual_ma           非多头且 True：还要收盘>=长均线
#
# 【相对强弱 RS】
#   use_rs_filter         是否要求个股 N 日收益不低于指数同期+超额
#   rs_index_code         对比用的指数；None 则用 index_ma_filter_code
#   rs_min_excess         相对指数的最小超额收益
#
# 【放量确认】
#   use_volume_confirm    是否要求当日量>=前 vol_ma_period 日均量×倍数
#   vol_ma_period         均量窗口
#   vol_ratio_min         量比下限
# ---------------------------------------------------------------------------
STRATEGY_DEFAULTS = {
    "max_hold_count": 10,
    "per_stock_amount": 100_000,
    "use_equity_based_sizing": True,
    "equity_deploy_pct": 0.95,
    "min_order_shares": 100,
    "max_buy_per_day": 4,
    "cooldown_days": 1,
    "mom_lookback": 10,
    "winner_top_pct": 0.05,
    "min_momentum_ret": 0.0,
    "winner_inner_pct": 1.0,
    "max_momentum_ret": 0.8,
    "max_extension_vs_ma": None,
    "max_atr_vol_pct": None,
    "use_max_25d_rise_from_low_filter": True,
    "max_25d_rise_from_low_pct": 0.80,
    "max_25d_rise_lookback": 25,
    "trend_ma_period": 10,
    "require_up_day": True,
    "min_price": 5.0,
    "min_day_volume": 1,
    "limit_up_min_ret": 0.095,
    "limit_up_max_spread": 0.005,
    "use_max_day_gain_buy_filter": True,
    "min_day_gain_buy_pct": 0.03,
    "max_day_gain_buy_pct": 0.08,
    "daily_count": 70,
    "atr_period": 14,
    "atr_multiplier": 2.0,
    "stock_pool_indices": (
        "000300.SH",
        "000905.SH",
        "000852.SH",
        "399006.SZ",
        "399001.SZ",
        "399007.SZ",
    ),
    "stock_pool_scan_cap": 4000,
    "use_index_ma_filter": True,
    "index_ma_filter_code": "000905.SH",
    "use_index_bull_align": True,
    "index_bull_ma_periods": (10, 20, 30, 60),
    "index_bull_require_close_above_short": True,
    "use_index_ma_slope_check": True,
    "index_ma_slope_lookback": 5,
    "index_ma_min_slope_deg": 0.1,
    "index_ma_period": 60,
    "use_index_dual_ma": False,
    "index_ma_long_period": 120,
    "use_rs_filter": True,
    "rs_index_code": None,
    "rs_min_excess": 0.0,
    "use_volume_confirm": True,
    "vol_ma_period": 20,
    "vol_ratio_min": 1.0,
}


def _cfg(C: Any, key: str) -> Any:
    """读取 C 上参数；若未初始化则用 STRATEGY_DEFAULTS（与 init 写入一致）。"""
    return getattr(C, key, STRATEGY_DEFAULTS[key])


def _account_type_for_query(C: Any) -> str:
    t = getattr(C, "accountType", None) or getattr(C, "account_type", None)
    if t:
        return str(t)
    return "STOCK"


def _get_total_asset(C: Any) -> Optional[float]:
    """账户总资产（QMT account.m_dBalance）；无账户或接口失败返回 None。"""
    accid = getattr(C, "accountid", None) or getattr(C, "account_id", None)
    if not accid:
        return None
    try:
        acc = get_trade_detail_data(accid, _account_type_for_query(C), "account")
    except Exception:
        return None
    if not acc:
        return None
    try:
        return float(acc[0].m_dBalance)
    except Exception:
        return None


def _effective_per_stock_amount(C: Any) -> float:
    """单笔买入目标金额：固定 per_stock_amount，或 总资产×equity_deploy_pct÷max_hold_count。"""
    if not bool(getattr(C, "use_equity_based_sizing", False)):
        return float(C.per_stock_amount)
    eq = _get_total_asset(C)
    if eq is None or eq <= 0:
        return float(C.per_stock_amount)
    try:
        pct = float(getattr(C, "equity_deploy_pct", 0.95))
    except (TypeError, ValueError):
        pct = 0.95
    pct = max(0.01, min(1.0, pct))
    n = max(1, int(C.max_hold_count))
    return eq * pct / float(n)


def _optional_positive_float_cap(C: Any, key: str) -> Optional[float]:
    """从 C 读正数阈值；None/无效/<=0 表示不启用该上限。"""
    cap = _cfg(C, key)
    if cap is None:
        return None
    try:
        c = float(cap)
    except (TypeError, ValueError):
        return None
    if c <= 0:
        return None
    return c


def trading_days_diff(date_start: str, date_end: str) -> int:
    try:
        d1 = datetime.strptime(str(date_start), "%Y%m%d")
        d2 = datetime.strptime(str(date_end), "%Y%m%d")
        return max(0, (d2 - d1).days)
    except Exception:
        return 0


def timetag_to_datetime(timetag: Any, format_str: str = "%Y%m%d") -> str:
    try:
        return time.strftime(format_str, time.localtime(float(timetag) / 1000.0))
    except Exception:
        try:
            return time.strftime(format_str, time.localtime(float(timetag)))
        except Exception:
            return str(timetag)


def _fmt_index_slope_req(C) -> str:
    m = float(_cfg(C, "index_ma_min_slope_deg"))
    if m <= 0.0:
        return ">0°"
    if m < 1.0:
        return ">=%.2f°" % m
    return ">=%.1f°" % m


def _index_ma_slope_ok(C, deg: float) -> bool:
    """大盘 MA 倾角：min<=0 时须严格大于 0°；min>0 时须 >= min（度）。"""
    min_deg = float(_cfg(C, "index_ma_min_slope_deg"))
    if min_deg <= 0.0:
        return deg > 0.0
    return deg >= min_deg


def init(C) -> None:
    """初始化账户、持仓字典，并把 STRATEGY_DEFAULTS 中各项写入 C。

    参数含义见文件上方 STRATEGY_DEFAULTS 前的注释；QMT 若在 init 前已设置 C.xxx，则以界面为准不覆盖。
    """
    C.accountid = getattr(C, "accountid", "")
    C.holding = {}
    C.buy_price = {}
    C.buy_shares = {}
    C.buy_date = {}
    C.sell_date = {}

    for key, val in STRATEGY_DEFAULTS.items():
        setattr(C, key, getattr(C, key, val))

    _idx_on = C.use_index_ma_filter
    _bull = C.use_index_bull_align
    _rise_tag = (
        "<%.0f%%" % (float(C.max_25d_rise_from_low_pct) * 100)
        if C.use_max_25d_rise_from_low_filter
        else "关"
    )
    _slope_lbl = _fmt_index_slope_req(C)
    _amt_hint = (
        "每票≈总权益×%.0f%%÷%d(复利)"
        % (float(C.equity_deploy_pct) * 100, int(C.max_hold_count))
        if getattr(C, "use_equity_based_sizing", False)
        else "每票%.0f元" % float(C.per_stock_amount)
    )
    print(
        "强势轮动 前%d日最强%.0f%% 持仓%d只 %s 日买%d 冷却%d日 | MA%d 收阳:%s | 大盘:%s 多头%s 倾角%s | 卖出:ATR(%d)×%.1f | %d日低→收涨幅%s"
        % (
            int(C.mom_lookback),
            C.winner_top_pct * 100,
            C.max_hold_count,
            _amt_hint,
            C.max_buy_per_day,
            C.cooldown_days,
            C.trend_ma_period,
            "开" if C.require_up_day else "关",
            "开" if _idx_on else "关",
            str(C.index_bull_ma_periods) if (_idx_on and _bull) else "关",
            _slope_lbl,
            int(C.atr_period),
            float(C.atr_multiplier),
            int(C.max_25d_rise_lookback),
            _rise_tag,
        )
    )


def _calc_atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> Optional[float]:
    if not highs or not lows or not closes or len(closes) < period + 1:
        return None
    n = min(len(highs), len(lows), len(closes))
    tr_list = []
    for i in range(1, n):
        prev_close = float(closes[i - 1])
        hi, lo = float(highs[i]), float(lows[i])
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        tr_list.append(tr)
    if len(tr_list) < period:
        return None
    return float(np.mean(tr_list[-period:]))


def _ret_n_days(closes: Sequence[float], n_days: int) -> Optional[float]:
    if not closes or len(closes) < n_days + 2:
        return None
    a = float(closes[-(n_days + 1)])
    b = float(closes[-1])
    if a <= 0 or b <= 0:
        return None
    return b / a - 1.0


def _day_ret_last(closes: Sequence[float]) -> Optional[float]:
    """最近一根日 K 相对昨收的涨跌幅；数据不足返回 None。"""
    if len(closes) < 2:
        return None
    try:
        prev_c = float(closes[-2])
        last = float(closes[-1])
        if prev_c <= 0:
            return None
        return last / prev_c - 1.0
    except Exception:
        return None


def _above_ma(closes: Sequence[float], period: int) -> bool:
    if not closes or len(closes) < period:
        return False
    ma = float(np.mean(closes[-period:]))
    return float(closes[-1]) > ma and ma > 0


def _passes_max_day_gain_for_buy(C, closes: Sequence[float]) -> bool:
    """当日涨幅（昨收→今收）须在 [min_day_gain_buy_pct, max_day_gain_buy_pct] 内才通过。"""
    if not _cfg(C, "use_max_day_gain_buy_filter"):
        return True
    try:
        lo = float(_cfg(C, "min_day_gain_buy_pct"))
        hi = float(_cfg(C, "max_day_gain_buy_pct"))
    except (TypeError, ValueError):
        return True
    if lo > hi:
        return True
    day_ret = _day_ret_last(closes)
    if day_ret is None:
        return True
    return lo <= day_ret <= hi


def _is_one_word_limit_up(C, highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> bool:
    if not highs or not lows or not closes or len(closes) < 2:
        return False
    try:
        prev_close = float(closes[-2])
        if prev_close <= 0:
            return False
        day_ret = _day_ret_last(closes)
        if day_ret is None:
            return False
        spread = (float(highs[-1]) - float(lows[-1])) / prev_close
        min_ret = float(_cfg(C, "limit_up_min_ret"))
        max_spread = float(_cfg(C, "limit_up_max_spread"))
        return day_ret >= min_ret and spread <= max_spread
    except Exception:
        return False


def _is_chinext_star_bse_or_st(C, stock_code: str) -> bool:
    if not stock_code or len(stock_code) < 6:
        return False
    code = stock_code.split(".")[0]
    suf = (stock_code.split(".")[-1] or "").upper()
    if suf == "BJ":
        return True
    if code.startswith("300") or code.startswith("688") or code.startswith("689"):
        return True
    try:
        name = C.get_stock_name(stock_code)
        if name and ("ST" in name.upper()):
            return True
    except Exception:
        pass
    return False


def get_stock_pool(C, current_date_str: str) -> List[str]:
    all_stocks: List[str] = []
    try:
        index_stocks = []
        for index_code in C.stock_pool_indices:
            try:
                if hasattr(C, "get_index_constituent"):
                    stocks = C.get_index_constituent(index_code)
                    if stocks:
                        index_stocks.extend(list(stocks))
                elif hasattr(C, "get_stock_list_in_sector"):
                    stocks = C.get_stock_list_in_sector(index_code)
                    if stocks:
                        index_stocks.extend(list(stocks))
                elif hasattr(C, "get_sector"):
                    stocks = C.get_sector(index_code)
                    if stocks:
                        index_stocks.extend(list(stocks))
            except Exception:
                continue
        if index_stocks:
            all_stocks = list(set(index_stocks))
    except Exception as e:
        print("股票池获取失败: %s" % e)
    return all_stocks


def _get_index_daily_closes(C, code: str, bar_date_str: str, count: int) -> Optional[List[float]]:
    try:
        data = C.get_market_data_ex(
            ["close"], [code], end_time=bar_date_str, period="1d", count=count, subscribe=False
        )
        if not data or code not in data or "close" not in data[code]:
            return None
        return list(data[code]["close"])
    except Exception:
        return None


def _index_ma_slope_deg(closes: List[float], period: int, lookback: int) -> Optional[float]:
    """单条均线近 lookback 根K的涨跌率 rise=(MA今-MA昨段)/MA昨段，角度=degrees(atan(rise))。数据不足返回 None。"""
    if len(closes) < period + lookback:
        return None
    ma_now = float(np.mean(closes[-period:]))
    ma_past = float(np.mean(closes[-(period + lookback) : -lookback]))
    if ma_past <= 0:
        return None
    rise = (ma_now - ma_past) / ma_past
    return float(np.degrees(np.arctan(rise)))


def _index_bull_align_from_closes(C, closes: List[float]) -> bool:
    """指数：MA短>…>MA长；可选收盘>=最短均线；可选各均线倾角（默认 min_deg=0 即须>0°）。"""
    raw = _cfg(C, "index_bull_ma_periods")
    try:
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            ps = tuple(int(x) for x in raw)
        else:
            ps = (10, 20, 30, 60)
    except Exception:
        ps = (10, 20, 30, 60)
    lb = max(1, int(_cfg(C, "index_ma_slope_lookback")))
    pmax = max(ps)
    need_len = pmax + lb
    if len(closes) < need_len:
        return True
    mas = [float(np.mean(closes[-p:])) for p in ps]
    for i in range(len(mas) - 1):
        if mas[i] <= mas[i + 1]:
            return False
    if _cfg(C, "index_bull_require_close_above_short"):
        if float(closes[-1]) < mas[0]:
            return False
    if _cfg(C, "use_index_ma_slope_check"):
        for p in ps:
            deg = _index_ma_slope_deg(closes, p, lb)
            if deg is None:
                return True
            if not _index_ma_slope_ok(C, deg):
                return False
    return True


def _index_market_allows_buy(C, bar_date_str: str) -> bool:
    """大盘允许开仓：优先指数均线多头排列；否则收盘>=短均线，可选双均线。数据不足时放行。"""
    if not _cfg(C, "use_index_ma_filter"):
        return True
    code = C.index_ma_filter_code
    bull = _cfg(C, "use_index_bull_align")
    p_short = int(C.index_ma_period)
    dual = _cfg(C, "use_index_dual_ma")
    p_long = int(_cfg(C, "index_ma_long_period"))
    raw_periods = _cfg(C, "index_bull_ma_periods")
    lb_slope = max(1, int(_cfg(C, "index_ma_slope_lookback")))
    try:
        if isinstance(raw_periods, (list, tuple)) and len(raw_periods) >= 2:
            p_bull_max = max(int(x) for x in raw_periods)
        else:
            p_bull_max = 60
    except Exception:
        p_bull_max = 60
    need = (
        p_bull_max + lb_slope + 5
        if bull
        else (max(p_short, p_long) + 5 if dual else p_short + 5)
    )
    try:
        data = C.get_market_data_ex(
            ["close"], [code], end_time=bar_date_str, period="1d", count=need, subscribe=False
        )
        if not data or code not in data or "close" not in data[code]:
            return True
        closes = list(data[code]["close"])
        if bull:
            return _index_bull_align_from_closes(C, closes)
        if len(closes) < p_short:
            return True
        last = float(closes[-1])
        ma_s = float(np.mean(closes[-p_short:]))
        if last < ma_s:
            return False
        if dual:
            if len(closes) < p_long:
                return True
            ma_l = float(np.mean(closes[-p_long:]))
            if last < ma_l:
                return False
        return True
    except Exception:
        return True


def _relative_strength_ok(
    C, stock_closes: List[float], index_closes: Optional[List[float]], lb: int
) -> bool:
    """个股 N 日收益不低于指数同期收益 + rs_min_excess。数据不足时放行。"""
    if not _cfg(C, "use_rs_filter"):
        return True
    if not index_closes or len(index_closes) < lb + 2:
        return True
    r_s = _ret_n_days(stock_closes, lb)
    r_i = _ret_n_days(index_closes, lb)
    if r_s is None or r_i is None:
        return True
    excess = float(_cfg(C, "rs_min_excess"))
    return r_s >= r_i + excess


def _volume_confirm_ok(C, vols: List[float]) -> bool:
    """当日量 >= 前 vol_ma_period 日均量 * vol_ratio_min。数据不足时放行。"""
    if not _cfg(C, "use_volume_confirm"):
        return True
    p = int(_cfg(C, "vol_ma_period"))
    ratio = float(_cfg(C, "vol_ratio_min"))
    if len(vols) < p + 1:
        return True
    today = float(vols[-1])
    prev_avg = float(np.mean([float(x) for x in vols[-(p + 1) : -1]]))
    if prev_avg <= 0:
        return True
    return today >= prev_avg * ratio


def _passes_momentum_cap(C, r25: float) -> bool:
    """N 日收益不超过 max_momentum_ret，避免末端过热；未设置则放行。"""
    c = _optional_positive_float_cap(C, "max_momentum_ret")
    if c is None:
        return True
    return r25 <= c


def _passes_extension_vs_ma_cap(C, closes: List[float], period: int) -> bool:
    """(收盘/MA-1) 不超过 max_extension_vs_ma；未设置则放行。"""
    c = _optional_positive_float_cap(C, "max_extension_vs_ma")
    if c is None:
        return True
    if len(closes) < period:
        return True
    ma = float(np.mean(closes[-period:]))
    if ma <= 0:
        return True
    ext = float(closes[-1]) / ma - 1.0
    return ext <= c


def _passes_atr_vol_cap(C, highs: List[float], lows: List[float], closes: List[float]) -> bool:
    """ATR/收盘 不超过 max_atr_vol_pct；未设置则放行。"""
    c = _optional_positive_float_cap(C, "max_atr_vol_pct")
    if c is None:
        return True
    p = int(_cfg(C, "atr_period"))
    atr_v = _calc_atr(highs, lows, closes, p)
    if atr_v is None or float(closes[-1]) <= 0:
        return True
    return (atr_v / float(closes[-1])) <= c


def _passes_max_rise_from_low_25d(C, closes: List[float], lows: List[float]) -> bool:
    """近 max_25d_rise_lookback 日最低价到收盘涨幅 (收盘-最低)/最低 < max_25d_rise_from_low_pct（默认 0.8）。"""
    if not _cfg(C, "use_max_25d_rise_from_low_filter"):
        return True
    try:
        cap = float(_cfg(C, "max_25d_rise_from_low_pct"))
    except (TypeError, ValueError):
        return True
    if cap <= 0:
        return True
    n = int(_cfg(C, "max_25d_rise_lookback"))
    if len(closes) < n:
        return True
    if lows and len(lows) >= n:
        window = [float(x) for x in lows[-n:]]
    else:
        window = [float(x) for x in closes[-n:]]
    mn = min(window)
    if mn <= 0:
        return True
    last = float(closes[-1])
    rise = (last - mn) / mn
    return rise < cap


def handlebar(C) -> None:
    current_datetime_str = ""
    try:
        current_timetag = C.get_bar_timetag(C.barpos)
        current_date_str = timetag_to_datetime(current_timetag, "%Y%m%d")
        current_datetime_str = timetag_to_datetime(current_timetag, "%Y%m%d%H%M%S")

        all_stocks = get_stock_pool(C, current_datetime_str)
        if not all_stocks:
            return

        lb = int(C.mom_lookback)
        need_len = max(lb + 2, int(C.trend_ma_period) + 1)
        if C.use_max_25d_rise_from_low_filter:
            need_len = max(need_len, int(C.max_25d_rise_lookback))
        if C.use_volume_confirm:
            need_len = max(need_len, int(C.vol_ma_period) + 2)
        count = max(int(C.daily_count), need_len + 5)

        stocks_to_remove: List[str] = []
        for stock in list(C.holding.keys()):
            if not C.holding.get(stock, False):
                continue
            try:
                data = C.get_market_data_ex(
                    ["close", "high", "low"],
                    [stock],
                    end_time=current_datetime_str,
                    period="1d",
                    count=max(80, C.atr_period + 25),
                    subscribe=False,
                )
                if stock not in data or "close" not in data[stock]:
                    continue
                closes = list(data[stock]["close"])
                highs = list(data[stock].get("high", []))
                lows = list(data[stock].get("low", []))
                if len(closes) < 5:
                    continue
                current_close = float(closes[-1])
                buy_date = C.buy_date.get(stock, current_date_str)
                days_held = trading_days_diff(buy_date, current_date_str)
                buy_price = float(C.buy_price.get(stock, current_close))
                profit_pct = (current_close - buy_price) / buy_price if buy_price > 0 else 0.0
                shares = int(C.buy_shares.get(stock, 0))

                bars_since_entry = min(days_held + 1, len(closes), len(highs) if highs else 0)
                if bars_since_entry <= 0 or not highs:
                    highest_high = current_close
                else:
                    highest_high = max(float(x) for x in highs[-bars_since_entry:])

                atr_v = _calc_atr(highs, lows, closes, C.atr_period) if highs and lows else None
                chandelier = (
                    highest_high - (atr_v * float(C.atr_multiplier))
                    if atr_v is not None
                    else None
                )

                should_sell = chandelier is not None and current_close <= chandelier
                sell_reason = "ATR吊灯止损" if should_sell else ""

                if should_sell and shares >= C.min_order_shares:
                    passorder(24, 1101, C.accountid, stock, 5, 0, shares, "强势涨幅快进快出", 1, "", C)
                    C.holding[stock] = False
                    C.sell_date[stock] = current_date_str
                    stocks_to_remove.append(stock)
                    profit = (current_close - buy_price) * shares
                    print(
                        "%s 卖出 %s %d股 @ %.3f %s 盈亏:%.2f (%.1f%%)"
                        % (current_datetime_str, stock, shares, current_close, sell_reason, profit, profit_pct * 100)
                    )
            except Exception as e:
                print("%s 卖出异常 %s: %s" % (current_datetime_str, stock, e))

        for stock in stocks_to_remove:
            for d in (C.holding, C.buy_price, C.buy_shares, C.buy_date):
                d.pop(stock, None)

        if not _index_market_allows_buy(C, current_datetime_str):
            if C.use_index_bull_align:
                print(
                    "%s 大盘非多头/均线倾角不足(%s MA%s 倾角%s) 不开新仓"
                    % (
                        current_datetime_str,
                        C.index_ma_filter_code,
                        C.index_bull_ma_periods,
                        _fmt_index_slope_req(C),
                    )
                )
            elif C.use_index_dual_ma:
                print(
                    "%s 大盘过滤: %s需收盘>=MA%d且>=MA%d 不开新仓"
                    % (
                        current_datetime_str,
                        C.index_ma_filter_code,
                        int(C.index_ma_period),
                        int(C.index_ma_long_period),
                    )
                )
            else:
                print(
                    "%s 大盘破位(%s收盘<MA%d) 不开新仓"
                    % (current_datetime_str, C.index_ma_filter_code, int(C.index_ma_period))
                )
            return

        rs_code = C.rs_index_code or C.index_ma_filter_code
        index_closes_rs = None
        if C.use_rs_filter:
            index_closes_rs = _get_index_daily_closes(
                C, rs_code, current_datetime_str, max(lb + 5, 40)
            )

        total_scan = min(int(C.stock_pool_scan_cap), len(all_stocks))
        scored: List[Tuple[str, float]] = []
        bar_cache: Dict[str, Dict[str, List[float]]] = {}
        n_ok = 0
        min_m = float(C.min_momentum_ret)

        for stock in all_stocks[:total_scan]:
            if C.holding.get(stock, False):
                continue
            if _is_chinext_star_bse_or_st(C, stock):
                continue
            try:
                data = C.get_market_data_ex(
                    ["close", "high", "low", "volume"],
                    [stock],
                    end_time=current_datetime_str,
                    period="1d",
                    count=count,
                    subscribe=False,
                )
                if stock not in data or len(data[stock].get("close", [])) < need_len:
                    continue
                closes = list(data[stock]["close"])
                vols = list(data[stock].get("volume", []))
                if vols and float(vols[-1]) < float(C.min_day_volume):
                    continue
                if float(closes[-1]) < float(C.min_price):
                    continue
                r = _ret_n_days(closes, lb)
                if r is None or r < min_m:
                    continue
                n_ok += 1
                scored.append((stock, r))
                bar_cache[stock] = {
                    "closes": closes,
                    "highs": list(data[stock].get("high", [])),
                    "lows": list(data[stock].get("low", [])),
                    "vols": vols,
                }
            except Exception:
                pass

        if not scored:
            print("%s [强势] 无有效收益率样本 扫描%d只" % (current_datetime_str, total_scan))
            return

        scored.sort(key=lambda x: x[1], reverse=True)
        pct = float(C.winner_top_pct)
        k = max(1, int(np.ceil(len(scored) * pct)))
        inner = float(C.winner_inner_pct)
        inner = max(0.01, min(1.0, inner))
        k2 = max(1, int(np.ceil(k * inner)))
        winner_set = {s for s, _ in scored[:k2]}

        candidates: List[Dict[str, Any]] = []
        trend_ma = int(C.trend_ma_period)
        for stock, r25 in scored:
            if stock not in winner_set:
                continue
            try:
                cached = bar_cache.get(stock)
                if not cached:
                    continue
                closes = cached["closes"]
                highs = cached["highs"]
                lows = cached["lows"]
                vols = cached["vols"]
                if _is_one_word_limit_up(C, highs, lows, closes):
                    continue
                if not _passes_max_day_gain_for_buy(C, closes):
                    continue
                if float(closes[-1]) < float(C.min_price):
                    continue
                if not _above_ma(closes, trend_ma):
                    continue
                if not _passes_max_rise_from_low_25d(C, closes, lows):
                    continue
                if C.require_up_day and len(closes) >= 2 and float(closes[-1]) < float(closes[-2]):
                    continue
                if not _relative_strength_ok(C, closes, index_closes_rs, lb):
                    continue
                if not _volume_confirm_ok(C, vols):
                    continue
                if not _passes_momentum_cap(C, r25):
                    continue
                if not _passes_extension_vs_ma_cap(C, closes, trend_ma):
                    continue
                if not _passes_atr_vol_cap(C, highs, lows, closes):
                    continue
                price = float(closes[-1])
                per_amt = _effective_per_stock_amount(C)
                target_shares = int(per_amt / price)
                shares = (target_shares // C.min_order_shares) * C.min_order_shares
                if shares < C.min_order_shares:
                    continue
                candidates.append(
                    {
                        "stock": stock,
                        "r25": r25,
                        "price": price,
                        "shares": shares,
                    }
                )
            except Exception:
                pass

        candidates.sort(key=lambda x: x["r25"], reverse=True)

        current_holdings = sum(1 for h in C.holding.values() if h)
        final_bought = 0
        bought_today = 0
        if candidates and current_holdings < C.max_hold_count:
            for c in candidates:
                if current_holdings >= C.max_hold_count or bought_today >= C.max_buy_per_day:
                    break
                stock = c["stock"]
                if stock in C.sell_date:
                    if trading_days_diff(C.sell_date[stock], current_date_str) < C.cooldown_days:
                        continue
                passorder(23, 1101, C.accountid, stock, 5, 0, c["shares"], "强势涨幅快进快出", 1, "", C)
                C.holding[stock] = True
                C.buy_price[stock] = c["price"]
                C.buy_shares[stock] = c["shares"]
                C.buy_date[stock] = current_date_str
                current_holdings += 1
                final_bought += 1
                bought_today += 1
                print(
                    "%s 买入 %s %d股 @ %.3f 目标约%.0f元 当日涨幅[%.0f%%,%.0f%%] 前%d日:%.2f%% (最强约%.0f%%池 按前%d日收益序+MA%d)"
                    % (
                        current_datetime_str,
                        stock,
                        c["shares"],
                        c["price"],
                        _effective_per_stock_amount(C),
                        float(C.min_day_gain_buy_pct) * 100,
                        float(C.max_day_gain_buy_pct) * 100,
                        lb,
                        c["r25"] * 100,
                        pct * 100,
                        lb,
                        trend_ma,
                    )
                )

        print(
            "%s [强势] 有效样本%d 前%d日最强%.0f%%池%d只 内层%.0f%%实取%d只 候选%d(前%d日序) 买入%d 持仓%d"
            % (
                current_datetime_str,
                n_ok,
                lb,
                pct * 100,
                k,
                inner * 100,
                k2,
                len(candidates),
                lb,
                final_bought,
                sum(1 for h in C.holding.values() if h),
            )
        )

    except Exception as e:
        print("%s handlebar异常: %s" % (current_datetime_str or "?", e))
