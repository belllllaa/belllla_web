# coding: gbk
"""
仅检测股票池：打印各来源能拿到的代码列表，无任何买卖/下单逻辑。

可调：PROBE_SECTOR_NAMES、PROBE_INDEX_CODES；策略参数 seed_export_txt_path、basket_name。
板块名含「我的」便于对照客户端里短名/自定义板块是否一致。
"""

import os
import re
import sys

# 与客户端「板块」名称完全一致；含「我的」用于测试短名筛选
PROBE_SECTOR_NAMES = (
    "我的",
    "我的自选",
    "自选股池",
)

PROBE_INDEX_CODES = (
    "000300.SH",
)


def _flush(s):
    try:
        print(s)
        sys.stdout.flush()
    except Exception:
        pass


def _norm_list(raw):
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    out = []
    try:
        for x in raw:
            if isinstance(x, dict):
                for k in ("code", "stockCode", "stock_code", "证券代码"):
                    if k in x and x[k]:
                        out.append(str(x[k]).strip())
                        break
                else:
                    out.append(str(x))
            else:
                t = str(x).strip()
                if t:
                    out.append(t)
    except Exception:
        out = [str(raw)]
    seen = set()
    acc = []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            acc.append(c)
    return acc


def _codes_from_txt_file(path):
    p = (path or "").strip()
    if not p or not os.path.isfile(p):
        return []
    try:
        with open(p, "rb") as f:
            b = f.read()
    except Exception:
        return []
    if not b:
        return []
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        try:
            text = b.decode("utf-16")
        except Exception:
            text = ""
    else:
        text = ""
        for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
            try:
                text = b.decode(enc)
                break
            except Exception:
                continue
        if not text:
            try:
                text = b.decode("latin-1")
            except Exception:
                return []
    out = []
    for m in re.finditer(r"(?<![0-9])(\d{6})\.(SH|SZ|BJ)(?![0-9])", text, re.I):
        out.append("%s.%s" % (m.group(1), m.group(2).upper()))
    for m in re.finditer(r"(?<![A-Za-z0-9])(SH|SZ|BJ)(\d{6})(?![0-9])", text, re.I):
        out.append("%s.%s" % (m.group(2), m.group(1).upper()))
    seen = set()
    acc = []
    for c in out:
        if c not in seen:
            seen.add(c)
            acc.append(c)
    return acc


def _get_basket_raw(C, name):
    if not (name or "").strip():
        return None
    for getter in (
        lambda: globals().get("get_basket"),
        lambda: getattr(C, "get_basket", None),
        lambda: getattr(sys.modules.get("__main__"), "get_basket", None),
    ):
        try:
            fn = getter()
            if callable(fn):
                return fn(name.strip())
        except Exception:
            pass
    return None


def _print_pool(tag, codes):
    n = len(codes)
    _flush("POOL %s count=%d %s" % (tag, n, codes))


def _run_probe(C, where):
    _flush("---- POOL_PROBE %s ----" % where)

    if hasattr(C, "get_stock_list_in_sector"):
        for nm in PROBE_SECTOR_NAMES:
            try:
                raw = C.get_stock_list_in_sector(nm)
                codes = _norm_list(raw)
                _print_pool("sector:%s" % nm, codes)
            except Exception as e:
                _flush("POOL sector:%s ERR %r" % (nm, e))
    else:
        _flush("POOL sector SKIP no get_stock_list_in_sector")

    bn = (getattr(C, "basket_name", None) or "").strip()
    if bn:
        try:
            raw = _get_basket_raw(C, bn)
            codes = _norm_list(raw)
            _print_pool("basket:%s" % bn, codes)
        except Exception as e:
            _flush("POOL basket:%s ERR %r" % (bn, e))
    else:
        _flush("POOL basket SKIP basket_name empty")

    for ix in PROBE_INDEX_CODES:
        found = False
        for meth in ("get_index_constituent", "get_stock_list_in_sector", "get_sector"):
            fn = getattr(C, meth, None)
            if not callable(fn):
                continue
            try:
                raw = fn(ix)
                if raw:
                    codes = _norm_list(raw)
                    _print_pool("index:%s via %s" % (ix, meth), codes)
                    found = True
                    break
            except Exception as e:
                _flush("POOL index:%s %s ERR %r" % (ix, meth, e))
        if not found:
            _flush("POOL index:%s SKIP" % ix)

    path = (getattr(C, "seed_export_txt_path", None) or "").strip()
    if path:
        fp = path
        if os.path.isdir(path):
            fp = ""
            for name in ("我的自选.txt", "我的自选", "export.txt", "block.txt"):
                cand = os.path.join(path, name)
                if os.path.isfile(cand):
                    fp = cand
                    break
            if not fp:
                _flush("POOL file SKIP dir no 我的自选.txt: %r" % path)
        if fp and os.path.isfile(fp):
            codes = _codes_from_txt_file(fp)
            _print_pool("file:%s" % fp, codes)
        elif path and not os.path.isdir(path) and not os.path.isfile(path):
            _flush("POOL file SKIP not found: %r" % path)
    else:
        _flush("POOL file SKIP seed_export_txt_path empty")

    _flush("---- POOL_PROBE %s end ----" % where)


def init(C):
    if not getattr(C, "basket_name", None):
        C.basket_name = ""
    if not getattr(C, "seed_export_txt_path", None):
        C.seed_export_txt_path = ""
    C._pool_probe_once = False


def handlebar(C):
    if getattr(C, "_pool_probe_once", False):
        return
    C._pool_probe_once = True
    try:
        _run_probe(C, "handlebar")
    except Exception as e:
        _flush("POOL_PROBE ERR %r" % (e,))


def handleBar(C):
    handlebar(C)


def handle_bar(C):
    handlebar(C)
