# coding: gbk
"""
QMT 回测：最小脚本，仅验证「运行日志」里是否出现 print。

用法：在 QMT 回测里只加载本文件；若仍无输出，问题在客户端/日志窗口，不在策略逻辑。
"""


def init(C):
    print("MIN_PRINT init ok")


def handlebar(C):
    print("MIN_PRINT handlebar barpos=%s" % getattr(C, "barpos", -1))
