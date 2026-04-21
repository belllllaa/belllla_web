#coding:gbk
"""
QMT 环境检测：是否已安装 TA-Lib（talib）

用法：
1. 在 QMT「策略」里新建策略，把本文件内容粘进去，或指向本文件路径；
2. 运行一次（回测/实盘模拟均可），看「日志」输出；
3. 或在 QMT 内置 Python 里：exec(open(r'本文件绝对路径', encoding='utf-8').read())

成功：打印 talib 版本 + 一次 SMA 计算结果
失败：打印 No module named 'talib' 或异常信息
"""

import numpy as np

def init(C):
    print("=" * 50)
    print("[check_talib] 开始检测 TA-Lib ...")
    try:
        import talib
        ver = getattr(talib, "__version__", "未知版本")
        print("[OK] talib 已安装，版本:", ver)
        # 简单算一条 SMA，确认 C 扩展可用
        close = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], dtype=np.float64)
        sma5 = talib.SMA(close, timeperiod=5)
        print("[OK] talib.SMA 测试通过，最后一根 SMA(5) =", float(sma5[-1]))
    except ImportError as e:
        print("[FAIL] 未安装 talib:", e)
        print("       可在 QMT 对应 Python 下执行: pip install TA-Lib")
    except Exception as e:
        print("[FAIL] talib 导入后出错:", type(e).__name__, e)
    print("=" * 50)


def handlebar(C):
    # 只跑一次即可：init 里已打印；若希望每根 K 都打印可解开下面注释
    pass
