# coding: gbk
"""
行业 / 板块读取测试（放 QMT 里跑）

用法：
  1）迅投 QMT → 策略管理 → 新建策略 → 将本文件**全部内容**粘贴进去保存；
  2）回测或「运行」一次，在**日志 / 输出**里查看打印。

说明：
  - 不同 QMT 版本 ContextInfo 方法名可能略有差异，本脚本对常见接口做了 try/except；
  - 「申万一级」等板块名请以你终端里**板块列表实际名称**为准（本脚本只试探若干常见写法）；
  - **xtdata.get_stock_list_in_sector / get_sector_list** 常依赖**行情服务**；若日志出现「无法连接行情服务」，请先**登录 QMT 等行情就绪**，或在策略里**优先用 ContextInfo** 的 `get_stock_list_in_sector`、`get_sector`（回测内往往更稳）。
  - 若需命令行测 xtquant，见文件末尾 `if __name__ == "__main__"`（需 QMT 自带 Python）。

入口：init 内执行一次测试；handlebar 空实现避免报错。
"""


def _p(title, msg=""):
    try:
        if msg:
            print("[行业测试] %s %s" % (title, msg))
        else:
            print("[行业测试] %s" % title)
    except Exception:
        print(str(title))


def _summarize_list(name, lst, head=15):
    if lst is None:
        _p(name, "-> None")
        return
    try:
        n = len(lst)
    except Exception:
        _p(name, "-> 不可 len，类型=%s" % type(lst).__name__)
        return
    _p(name, "数量=%d 类型=%s" % (n, type(lst).__name__))
    if n == 0:
        return
    try:
        sample = list(lst)[:head]
        _p(name + " 前%d项" % head, repr(sample))
    except Exception as e:
        _p(name, "取样失败: %s" % e)


def _run_sector_probe(C):
    _p("========== ContextInfo 板块/行业探测 ==========")

    # 1) get_sector_list（目录树）
    fn = getattr(C, "get_sector_list", None)
    if callable(fn):
        for node in (None, "", 0, "0"):
            try:
                r = fn(node)
                _summarize_list("get_sector_list(%r)" % (node,), r, head=20)
                break
            except TypeError:
                try:
                    r = fn()
                    _summarize_list("get_sector_list()", r, head=20)
                    break
                except Exception as e:
                    _p("get_sector_list 失败", str(e))
                    break
            except Exception as e:
                _p("get_sector_list(%r)" % (node,), str(e))
    else:
        _p("无 get_sector_list")

    # 2) get_stock_list_in_sector（板块名 -> 成分）
    gsis = getattr(C, "get_stock_list_in_sector", None)
    sector_names = (
        "沪深A股",
        "全部A股",
        "申万一级行业",
        "申万一级",
        "申万行业",
        "银行",
        "电子",
        "计算机",
        "医药生物",
        "传媒",
        "非银金融",
        "食品饮料",
        "电力设备",
    )
    if callable(gsis):
        for sn in sector_names:
            try:
                r = gsis(sn)
                if r:
                    _summarize_list("get_stock_list_in_sector(%r)" % sn, r, head=8)
                else:
                    _p("get_stock_list_in_sector(%r)" % sn, "空或假值 -> %r" % (r,))
            except Exception as e:
                _p("get_stock_list_in_sector(%r)" % sn, str(e))
    else:
        _p("无 get_stock_list_in_sector")

    # 3) get_sector（部分版本用指数/板块代码取成分，与指数类似）
    gsec = getattr(C, "get_sector", None)
    if callable(gsec):
        codes = ("000852.SH", "000852.ZZ", "000300.SH", "399006.SZ")
        for code in codes:
            try:
                r = gsec(code)
                _summarize_list("get_sector(%r)" % code, r, head=8)
            except Exception as e:
                _p("get_sector(%r)" % code, str(e))
    else:
        _p("无 get_sector")

    # 4) 单券行业：常见命名试探
    for meth in (
        "get_stock_industry",
        "get_stock_sector",
        "get_industry_name",
        "get_instrument_detail",
    ):
        f = getattr(C, meth, None)
        if not callable(f):
            continue
        for code in ("600519.SH", "000001.SZ", "601398.SH"):
            try:
                r = f(code)
                _p("%s(%r)" % (meth, code), repr(r)[:500])
            except Exception as e:
                _p("%s(%r)" % (meth, code), str(e))

    _p("========== ContextInfo 探测结束 ==========")


def _is_quote_service_err(msg: str) -> bool:
    s = str(msg)
    return ("无法连接行情" in s) or ("行情服务" in s) or ("连接行情" in s)


def _run_xtquant_probe():
    _p("========== xtquant.xtdata 探测（可选，需行情服务）==========")
    try:
        from xtquant import xtdata
    except ImportError as e:
        _p("无法 import xtquant", str(e))
        return

    names = [x for x in dir(xtdata) if "sector" in x.lower() or "industry" in x.lower() or "block" in x.lower()]
    _p("dir(xtdata) 含 sector/industry/block 的方法", repr(names[:40]))

    quote_err_seen = False

    for meth in (
        "get_stock_list_in_sector",
        "get_sector_list",
        "get_stock_list",
    ):
        f = getattr(xtdata, meth, None)
        if not callable(f):
            continue
        if meth == "get_stock_list_in_sector":
            for sn in ("沪深A股", "银行", "申万一级行业"):
                try:
                    r = f(sn)
                    _summarize_list("xtdata.%s(%r)" % (meth, sn), r, head=8)
                except Exception as e:
                    es = str(e)
                    _p("xtdata.%s(%r)" % (meth, sn), es)
                    if _is_quote_service_err(es):
                        quote_err_seen = True
        else:
            try:
                r = f()
                _summarize_list("xtdata.%s()" % meth, r, head=15)
            except TypeError:
                try:
                    r = f("")
                    _summarize_list("xtdata.%s('')" % meth, r, head=15)
                except Exception as e:
                    es = str(e)
                    _p("xtdata.%s" % meth, es)
                    if _is_quote_service_err(es):
                        quote_err_seen = True
            except Exception as e:
                es = str(e)
                _p("xtdata.%s" % meth, es)
                if _is_quote_service_err(es):
                    quote_err_seen = True

    if quote_err_seen:
        _p(
            "提示（xtdata）",
            "出现「无法连接行情服务」时：先登录客户端、等行情连接后再测；选股/回测可优先用上方 ContextInfo.get_stock_list_in_sector / get_sector，不必依赖 xtdata。",
        )

    _p("========== xtdata 探测结束 ==========")


def init(C):
    C.accountid = getattr(C, "accountid", "")
    _run_sector_probe(C)
    _run_xtquant_probe()


def handlebar(C):
    return


if __name__ == "__main__":
    # 独立运行：无 ContextInfo，仅测 xtquant
    print("独立模式：仅尝试 xtquant（无 C）")
    _run_xtquant_probe()
