"""
数据加载器 - Version 1.0：基础框架
"""

import pickle
from pathlib import Path
from typing import List

class DataLoader:
    """数据加载器 - Version 1.0：基础框架"""

    def __init__(self, data_dir: str = './data'):
        """
        初始化数据加载器

        Args:
            data_dir: 数据目录路径（包含 data_daily, data_ret 等子目录）
        """
        self.data_dir = Path(data_dir)

        # 加载交易日列表
        with open(self.data_dir / 'date.pkl', 'rb') as f:
            all_trade_dates = pickle.load(f)

        # 过滤出实际有数据文件的交易日（date.pkl 可能包含更早的日期）
        self.trade_dates = []
        for date in all_trade_dates:
            if (self.data_dir / 'data_daily' / f'{date}.csv').exists():
                self.trade_dates.append(date)

        print(f"✅ 数据加载器初始化成功")
        print(f"📅 交易日数量: {len(self.trade_dates)}")
        if self.trade_dates:
            print(f"📅 起始日期: {self.trade_dates[0]}")
            print(f"📅 结束日期: {self.trade_dates[-1]}")
        else:
            print("⚠️ 未找到任何交易日数据，请检查 data_dir 是否正确")

    def get_all_dates(self) -> List[str]:
        """获取所有交易日"""
        return self.trade_dates


# ========== 测试代码 ==========
if __name__ == '__main__':
    loader = DataLoader('./data')
    dates = loader.get_all_dates()
    if not dates:
        print("\n未找到交易日数据，跳过展示")
    else:
        print(f"\n前 5 个交易日:")
        for d in dates[:5]:
            print(f"  {d}")
