import numpy as np
import pandas as pd
from datetime import datetime, timedelta

src = r"qmt/实盘策略/dafengniu_open_window_metrics_qmt.csv"
out = r"qmt/实盘策略/dafengniu_all_combo_compare_filtered.csv"

df = pd.read_csv(src)
for c in [f"D{i}_开盘" for i in range(6)] + [f"D{i}_收盘" for i in range(6)]:
    df[c] = pd.to_numeric(df[c], errors="coerce")

need = [f"D{i}_开盘" for i in range(6)] + [f"D{i}_收盘" for i in range(6)]
df = df.dropna(subset=need).copy()
# 过滤 D0 低流动性票：
# 1) 一字板（开=收）
# 2) 开收价差 <= 0.10（包含 1 分/1 角这类几乎无流动性的形态）
df = df[(df["D0_开盘"] - df["D0_收盘"]).abs() > 0.10].copy()

# 额外剔除：用户指定黑名单（来自截图，按 6 位代码过滤）
EXCLUDE_CODES = {
    "001217", "603628", "600478", "603132", "002805", "000505",
    "601155", "300638", "603986", "300394", "300548", "002565",
    "603920", "600151", "000547", "601698", "603698", "002149",
    "000818", "601330",
}

def _code6_from_any(v):
    s = str(v).strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    return s.zfill(6)[:6]

code_col = "代码" if "代码" in df.columns else None
if code_col:
    df = df[~df[code_col].map(_code6_from_any).isin(EXCLUDE_CODES)].copy()

# 额外剔除：按“入选日(=开仓日前一交易日) + 代码”成对过滤
# 说明：图片仅提供“月日”，这里统一按 MMDD 匹配，避免同代码跨期误杀
EXCLUDE_PICK_CODE_MMDD = {
    ("1105", "002636"), ("1105", "001217"),
    ("1112", "002317"), ("1112", "001298"),
    ("1114", "600478"), ("1114", "001332"),
    ("1117", "000620"), ("1117", "603132"),
    ("1118", "002153"), ("1118", "605136"),
    ("1119", "002805"), ("1119", "603129"),
    ("1120", "002246"), ("1120", "000505"),
    ("1121", "000892"), ("1121", "000070"), ("1121", "000681"),
    ("1124", "002153"), ("1124", "688195"), ("1124", "605598"),
    ("1125", "600105"), ("1125", "002728"), ("1125", "002759"),
    ("1126", "002249"), ("1126", "600246"), ("1126", "600103"),
    ("1203", "300638"), ("1203", "002353"), ("1203", "002565"),
    ("1204", "603986"), ("1204", "603933"), ("1204", "600151"),
    ("1210", "601869"), ("1210", "003031"), ("1210", "300548"),
    ("1211", "002544"), ("1211", "002202"), ("1211", "600105"),
    ("1212", "002149"), ("1212", "603929"), ("1212", "002565"),
    ("1215", "600879"), ("1215", "600151"), ("1215", "002565"),
    ("1215", "002565"), ("1216", "600879"), ("1216", "603920"),
    ("1216", "002565"),
    ("0114", "002131"), ("0114", "002465"), ("0114", "601698"),
    ("0115", "002446"), ("0115", "000681"), ("0115", "601208"),
    ("0116", "603698"), ("0116", "000547"), ("0116", "002565"),
    ("0119", "605376"), ("0119", "603286"), ("0119", "600391"),
    ("0130", "002455"), ("0130", "002149"), ("0130", "000818"),
    ("0202", "002606"), ("0202", "002491"), ("0202", "600785"),
    ("0203", "002165"), ("0203", "002342"), ("0203", "600481"),
    ("0224", "603256"), ("0224", "601869"), ("0224", "603124"),
    ("0303", "601975"), ("0303", "600635"), ("0303", "002506"),
    ("0304", "000533"), ("0304", "002167"), ("0304", "002877"),
    ("0305", "601179"), ("0305", "600875"), ("0305", "300303"),
    ("0309", "600821"), ("0309", "000533"), ("0309", "688158"),
    ("0313", "601611"), ("0313", "603659"), ("0313", "603366"),
    ("0316", "603929"), ("0316", "002636"), ("0316", "601975"),
    ("0316", "002565"), ("0317", "000572"), ("0317", "600408"),
    ("0318", "603757"), ("0318", "603881"), ("0318", "001287"),
    ("0319", "600996"), ("0319", "605389"), ("0319", "000617"),
    ("0320", "002150"), ("0320", "002428"), ("0320", "603026"),
    ("0323", "603529"), ("0323", "002218"), ("0323", "000703"),
    ("0324", "000065"), ("0324", "601330"), ("0324", "601975"),
    ("0326", "600163"), ("0326", "002109"), ("0326", "002192"),
    ("0331", "002565"), ("0331", "002342"), ("0331", "600528"),
    ("0402", "600339"), ("0402", "603477"), ("0402", "000155"),
    ("0403", "003031"), ("0403", "605589"), ("0403", "600056"),
    ("0407", "605589"), ("0407", "300821"), ("0407", "000703"),
    ("0424", "001339"), ("0424", "002290"), ("0424", "600633"),
    ("0427", "600418"), ("0427", "603501"), ("0427", "603486"),
    ("0428", "600744"), ("0428", "603629"), ("0428", "603259"),
    ("0428", "600770"),
}


def _prev_trading_day_guess(d8: str) -> str:
    """仅用于 MMDD 口径匹配：按工作日回退到前一交易日（周末处理）。"""
    dt = datetime.strptime(str(int(d8)), "%Y%m%d")
    dt -= timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt.strftime("%m%d")


open_col = "开仓日" if "开仓日" in df.columns else None
if code_col and open_col:
    _code6_s = df[code_col].map(_code6_from_any)
    _pick_mmdd_s = df[open_col].map(_prev_trading_day_guess)
    _pair = list(zip(_pick_mmdd_s, _code6_s))
    df = df[[p not in EXCLUDE_PICK_CODE_MMDD for p in _pair]].copy()


def is_limit_down_locked(o, c, prev_c):
    if prev_c is None or prev_c <= 0:
        return False
    return abs(float(o) - float(c)) < 1e-12 and (float(o) / float(prev_c) - 1.0) <= -0.095


def sellable_open(i, row):
    prev_c = row[f"D{i-1}_收盘"] if i >= 1 else None
    return not is_limit_down_locked(row[f"D{i}_开盘"], row[f"D{i}_收盘"], prev_c)


def sellable_close(i, row):
    prev_c = row[f"D{i-1}_收盘"] if i >= 1 else None
    return not is_limit_down_locked(row[f"D{i}_开盘"], row[f"D{i}_收盘"], prev_c)


def settle_after_signal(row, sig_day, pref="close"):
    if pref == "open":
        if sellable_open(sig_day, row):
            return sig_day, float(row[f"D{sig_day}_开盘"])
    else:
        if sellable_close(sig_day, row):
            return sig_day, float(row[f"D{sig_day}_收盘"])
    for j in range(sig_day + 1, 6):
        if sellable_close(j, row):
            return j, float(row[f"D{j}_收盘"])
    return None, None


def pack_metrics(name, rets, unsold):
    a = np.asarray(rets, dtype=float)
    if len(a) == 0:
        return {
            "策略": name,
            "样本": 0,
            "胜率": np.nan,
            "盈亏比": np.nan,
            "单笔平均收益": np.nan,
            "总收益_线性": np.nan,
            "净值_顺序复利": np.nan,
            "未成交数": unsold,
        }
    pos = a[a > 0]
    neg = -a[a <= 0]
    pl = float(pos.mean() / neg.mean()) if len(pos) > 0 and len(neg) > 0 and neg.mean() > 0 else np.nan
    return {
        "策略": name,
        "样本": int(len(a)),
        "胜率": float((a > 0).mean()),
        "盈亏比": pl,
        "单笔平均收益": float(a.mean()),
        "总收益_线性": float(a.sum()),
        "净值_顺序复利": float(np.prod(1 + a)),
        "未成交数": int(unsold),
    }


rows = []

# 基准
rets, uns = [], 0
for _, r in df.iterrows():
    d, p = settle_after_signal(r, 1, "close")
    if d is None:
        uns += 1
        continue
    rets.append(p / float(r["D0_开盘"]) - 1.0)
rows.append(pack_metrics("基准_D0开盘买_D1收盘卖(可成交口径)", rets, uns))

# 动态四组
rets, uns = [], 0
for _, r in df.iterrows():
    d0 = float(r["D0_开盘"])
    c = [float(r[f"D{i}_收盘"]) for i in range(6)]
    sig = 1 if c[1] <= d0 else 5
    if c[1] > d0:
        for i in [2, 3, 4, 5]:
            if c[i] <= c[i - 1]:
                sig = i
                break
    d, p = settle_after_signal(r, sig, "close")
    if d is None:
        uns += 1
        continue
    rets.append(p / d0 - 1.0)
rows.append(pack_metrics("动态强势_不创新高则卖(最多D5,可成交)", rets, uns))

rets, uns = [], 0
for _, r in df.iterrows():
    d0 = float(r["D0_开盘"])
    c = [float(r[f"D{i}_收盘"]) for i in range(6)]
    sig = 1 if c[1] <= d0 * 1.01 else 5
    if c[1] > d0 * 1.01:
        for i in [2, 3, 4, 5]:
            if c[i] <= c[i - 1] * 1.01:
                sig = i
                break
    d, p = settle_after_signal(r, sig, "close")
    if d is None:
        uns += 1
        continue
    rets.append(p / d0 - 1.0)
rows.append(pack_metrics("动态强势_日涨幅<1%则卖(最多D5,可成交)", rets, uns))

rets, uns = [], 0
for _, r in df.iterrows():
    d0 = float(r["D0_开盘"])
    c1 = float(r["D1_收盘"])
    sig = 5 if c1 > d0 else 1
    d, p = settle_after_signal(r, sig, "close")
    if d is None:
        uns += 1
        continue
    rets.append(p / d0 - 1.0)
rows.append(pack_metrics("D1强势直接持有到D5(可成交)", rets, uns))

rets, uns = [], 0
for _, r in df.iterrows():
    d0 = float(r["D0_开盘"])
    c = [float(r[f"D{i}_收盘"]) for i in range(6)]
    if c[1] <= d0 * 0.95:
        sig = 1
    elif c[1] <= d0:
        sig = 1
    else:
        sig = 5
        for i in [2, 3, 4, 5]:
            if c[i] <= d0 * 0.95 or c[i] <= c[i - 1]:
                sig = i
                break
    d, p = settle_after_signal(r, sig, "close")
    if d is None:
        uns += 1
        continue
    rr = p / d0 - 1.0
    if sig == 1 and c[1] <= d0 * 0.95:
        rr = min(rr, -0.05)
    rets.append(rr)
rows.append(pack_metrics("动态强势+5%止损(收盘口径,可成交)", rets, uns))

# 18 网格
for sl in [-0.04, -0.05, -0.06]:
    for th in [0.00, 0.01]:
        for tp in [0.06, 0.08, 0.10]:
            rets, uns = [], 0
            for _, r in df.iterrows():
                d0 = float(r["D0_开盘"])
                if float(r["D1_开盘"]) <= d0 * (1.0 + sl):
                    d, p = settle_after_signal(r, 1, "open")
                    if d is None:
                        uns += 1
                        continue
                    rets.append(p / d0 - 1.0)
                    continue
                if float(r["D1_开盘"]) >= d0 * (1.0 + tp):
                    d, p = settle_after_signal(r, 1, "open")
                    if d is None:
                        uns += 1
                        continue
                    rets.append(p / d0 - 1.0)
                    continue
                if float(r["D1_收盘"]) < d0 * (1.0 + th):
                    d, p = settle_after_signal(r, 1, "close")
                    if d is None:
                        uns += 1
                        continue
                    rets.append(p / d0 - 1.0)
                    continue

                if float(r["D2_开盘"]) <= d0 * (1.0 + sl):
                    d, p = settle_after_signal(r, 2, "open")
                    if d is None:
                        uns += 1
                        continue
                    rets.append(p / d0 - 1.0)
                    continue
                if float(r["D2_开盘"]) >= d0 * (1.0 + tp):
                    d, p = settle_after_signal(r, 2, "open")
                    if d is None:
                        uns += 1
                        continue
                    rets.append(p / d0 - 1.0)
                    continue

                d, p = settle_after_signal(r, 2, "close")
                if d is None:
                    uns += 1
                    continue
                rets.append(p / d0 - 1.0)

            rows.append(pack_metrics(f"网格_止损{int(sl*100)}|强势{int(th*100)}|兑现{int(tp*100)}(可成交)", rets, uns))

# 扩展多维网格（多类型）：
# 维度：
# - 开盘止损: -3/-4/-5/-6/-7%
# - 开盘止盈: 6/7/8/9/10/12%
# - 首日强势阈值: 0/0.5/1/2%
# - 强势参考: 相对D0开盘 / 相对前一日收盘
# - 续持上限: D2/D3/D4/D5
# - 动量转弱卖出: 当日收盘 <= 前日收盘*(1+cut)
#   cut: +1% / 0% / -1% / -2%
for sl in [-0.03, -0.04, -0.05, -0.06, -0.07]:
    for tp in [0.06, 0.07, 0.08, 0.09, 0.10, 0.12]:
        for th in [0.00, 0.005, 0.01, 0.02]:
            for strong_ref in ["d0", "prev_close"]:
                for max_day in [2, 3, 4, 5]:
                    for weaken_cut in [0.01, 0.00, -0.01, -0.02]:
                        rets, uns = [], 0
                        for _, r in df.iterrows():
                            d0 = float(r["D0_开盘"])
                            o = [float(r[f"D{i}_开盘"]) for i in range(6)]
                            c = [float(r[f"D{i}_收盘"]) for i in range(6)]

                            # D1 开盘风控/止盈优先
                            if o[1] <= d0 * (1.0 + sl):
                                d, p = settle_after_signal(r, 1, "open")
                                if d is None:
                                    uns += 1
                                    continue
                                rets.append(p / d0 - 1.0)
                                continue
                            if o[1] >= d0 * (1.0 + tp):
                                d, p = settle_after_signal(r, 1, "open")
                                if d is None:
                                    uns += 1
                                    continue
                                rets.append(p / d0 - 1.0)
                                continue

                            # D1 是否强势决定是否续持
                            if strong_ref == "d0":
                                d1_strong = c[1] >= d0 * (1.0 + th)
                            else:
                                d1_strong = c[1] >= c[0] * (1.0 + th)

                            if not d1_strong:
                                d, p = settle_after_signal(r, 1, "close")
                                if d is None:
                                    uns += 1
                                    continue
                                rets.append(p / d0 - 1.0)
                                continue

                            # 强势续持：D2..max_day 逐日评估
                            sold = False
                            for i in range(2, max_day + 1):
                                if o[i] <= d0 * (1.0 + sl):
                                    d, p = settle_after_signal(r, i, "open")
                                    if d is None:
                                        uns += 1
                                        sold = True
                                        break
                                    rets.append(p / d0 - 1.0)
                                    sold = True
                                    break
                                if o[i] >= d0 * (1.0 + tp):
                                    d, p = settle_after_signal(r, i, "open")
                                    if d is None:
                                        uns += 1
                                        sold = True
                                        break
                                    rets.append(p / d0 - 1.0)
                                    sold = True
                                    break

                                if c[i] <= c[i - 1] * (1.0 + weaken_cut):
                                    d, p = settle_after_signal(r, i, "close")
                                    if d is None:
                                        uns += 1
                                        sold = True
                                        break
                                    rets.append(p / d0 - 1.0)
                                    sold = True
                                    break

                            if sold:
                                continue

                            d, p = settle_after_signal(r, max_day, "close")
                            if d is None:
                                uns += 1
                                continue
                            rets.append(p / d0 - 1.0)

                        rows.append(
                            pack_metrics(
                                f"扩展网格_止损{int(sl*100)}|止盈{int(tp*100)}|强势阈值{th*100:.1f}|强势参考{strong_ref}|最多D{max_day}|转弱阈值{int(weaken_cut*100)}(可成交)",
                                rets,
                                uns,
                            )
                        )

out_df = pd.DataFrame(rows).sort_values("单笔平均收益", ascending=False)
out_df.to_csv(out, index=False, encoding="utf-8-sig", float_format="%.6f")

print("combo_count", len(out_df))
print("sample_after_filter", len(df))
print(out_df[["策略", "样本", "胜率", "单笔平均收益", "盈亏比", "总收益_线性", "净值_顺序复利", "未成交数"]].head(8).to_string(index=False))
