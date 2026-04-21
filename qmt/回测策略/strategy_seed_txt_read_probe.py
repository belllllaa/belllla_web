# coding: gbk
"""
仅用于验证：从「导出板块」txt 读出股票代码（与主策略同一套规范化逻辑思路：open + gbk/utf-8、SZ000657→000657.SZ）。

用法：在 QMT 回测里只加载本策略；看 init 日志里【SEED_TXT_PROBE】。
可选设置 C.seed_export_txt_path 为任意导出 txt 完整路径；不设时自动探测：某目录下仅 1 个 .txt 则采用，否则再试常见文件名。
"""

import os
import re


def _normalize_export_code(token):
    t = str(token).strip().upper().replace("\u3000", " ")
    if not t or t.startswith("#"):
        return None
    t = t.split()[0]
    if not t:
        return None
    if "." in t:
        a, b = t.split(".", 1)
        if len(a) == 6 and a.isdigit() and b in ("SH", "SZ", "BJ"):
            return "%s.%s" % (a, b)
        if a in ("SH", "SZ", "BJ") and len(b) == 6 and b.isdigit():
            return "%s.%s" % (b, a)
        return None
    if len(t) == 8 and t[:2] in ("SH", "SZ", "BJ") and t[2:].isdigit():
        return "%s.%s" % (t[2:], t[:2])
    return None


def _bare_six(part):
    s = str(part).strip().upper().replace(" ", "")
    if not re.match(r"^\d{6}$", s):
        return None
    if s.startswith(("600", "601", "603", "605", "688", "689")):
        return "%s.SH" % s
    if s.startswith(("11", "51", "58")):
        return "%s.SH" % s
    return "%s.SZ" % s


def _parse_file(path):
    if not path or not os.path.isfile(path):
        return []
    raw_text = ""
    for enc in ("gbk", "utf-8", "utf-8-sig"):
        try:
            with open(path, "r", encoding=enc) as f:
                raw_text = f.read()
            break
        except Exception:
            continue
    if raw_text == "":
        return []
    out = []
    seen = set()

    def add(c):
        if c and c not in seen:
            seen.add(c)
            out.append(c)

    for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in re.split(r"[\s,;|]+", line):
            part = part.strip()
            if not part:
                continue
            c = _normalize_export_code(part)
            if c:
                add(c)
                continue
            c6 = _bare_six(part)
            if c6:
                add(c6)
    for m in re.finditer(r"\b(\d{6})\.(SH|SZ|BJ)\b", raw_text, re.I):
        add("%s.%s" % (m.group(1), m.group(2).upper()))
    return out


def _auto_path():
    home = os.path.expanduser("~")
    if not home or home == "~":
        return ""
    names = ("我的自选.txt", "我的自选", "export.txt", "block.txt")
    for desk in ("Desktop", "桌面"):
        base = os.path.join(home, desk)
        for folder in (os.path.join(base, "新建文件夹"), base):
            if not os.path.isdir(folder):
                continue
            try:
                txts = sorted(
                    fn
                    for fn in os.listdir(folder)
                    if fn.lower().endswith(".txt") and os.path.isfile(os.path.join(folder, fn))
                )
            except Exception:
                continue
            if len(txts) == 1:
                return os.path.join(folder, txts[0])
            for name in names:
                p = os.path.join(folder, name)
                if os.path.isfile(p):
                    return p
    return ""


def init(C):
    print("SEED_TXT_PROBE init")
    p = (getattr(C, "seed_export_txt_path", None) or "").strip()
    if not p:
        p = _auto_path()
        if p:
            print("SEED_TXT_PROBE auto path=%r" % p)
    print("========== 【SEED_TXT_PROBE】==========")
    if not p:
        print("  无路径：请设 seed_export_txt_path，或在桌面常见目录下放唯一一个 .txt 导出文件")
        print("======================================")
        return
    if not os.path.isfile(p):
        print("  文件不存在: %r" % p)
        print("======================================")
        return
    enc_used = None
    body = None
    last = None
    for enc in ("gbk", "utf-8", "utf-8-sig"):
        try:
            with open(p, "r", encoding=enc) as f:
                body = f.read()
            enc_used = enc
            break
        except Exception as e:
            last = e
    if body is None:
        print("  读失败: %r" % (last,))
        print("======================================")
        return
    print("  path=%r enc=%s len=%d" % (p, enc_used, len(body)))
    print("  raw_repr_head=%r" % body[:200])
    codes = _parse_file(p)
    print("  parsed_count=%d codes=%s" % (len(codes), codes))
    print("======================================")


def handlebar(C):
    pass
