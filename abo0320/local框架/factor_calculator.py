"""
因子计算器 
"""

import pandas as pd
from pathlib import Path
from data_loader import DataLoader


class FactorCalculator:
    """因子计算器 - Version 1.0"""

    @staticmethod
    def momentum_col(period: int) -> str:
        """动量因子列名"""
        return f"momentum_{period}"

    def __init__(self, data_loader: DataLoader):
        """
        初始化因子计算器

        Args:
            data_loader: 数据加载器实例
        """
        self.loader = data_loader
        self.factor_dir = Path(data_loader.data_dir) / 'factors'
        self.factor_dir.mkdir(parents=True, exist_ok=True)

        print("✅ 因子计算器初始化成功")

    def calculate_momentum_daily(self, date: str, period: int = 20) -> pd.DataFrame:
        """
        计算单日的动量因子

        Args:
            date: 当前日期（字符串，如 '2020-02-04'）
            period: 回看周期（天数）

        Returns:
            DataFrame: 当日各股票的动量因子值（列：code, date, momentum_{period}）
        """
        # 1. 找到 period 天前的日期
        trade_dates = self.loader.get_all_dates()
        if date not in trade_dates:
            return pd.DataFrame()

        current_idx = trade_dates.index(date)
        if current_idx < period:
            # 数据不足，返回空
            return pd.DataFrame()

        past_date = trade_dates[current_idx - period]

        # 2. 读取当前日期和过去日期的数据
        current_data = self.loader.get_daily_data(date)
        past_data = self.loader.get_daily_data(past_date)

        if current_data.empty or past_data.empty:
            return pd.DataFrame()

        # 3. 合并数据（按 code）
        merged = pd.merge(
            current_data[['code', 'close']],
            past_data[['code', 'close']],
            on='code',
            suffixes=('_now', '_past')
        )

        # 4. 计算动量因子
        factor_col = self.momentum_col(period)
        merged[factor_col] = (merged['close_now'] / merged['close_past']) - 1
        merged['date'] = date

        # 5. 只保留需要的列
        result = merged[['code', 'date', factor_col]]

        return result

    def calculate_and_save_all(self, period: int = 20):
        """
        批量计算并保存所有交易日的因子

        Args:
            period: 回看周期
        """
        factor_col = self.momentum_col(period)
        trade_dates = self.loader.get_all_dates()
        total = len(trade_dates)

        print(f"📊 开始计算因子: {factor_col}")
        print(f"📊 回看周期: {period} 天")
        print(f"📊 总交易日: {total}")

        success_count = 0

        for i, date in enumerate(trade_dates):
            # 计算单日因子
            factor_df = self.calculate_momentum_daily(date, period)

            if not factor_df.empty:
                # 保存到文件
                save_path = self.factor_dir / f'{date}.csv'
                factor_df.to_csv(save_path, index=False)
                success_count += 1

            # 每 100 天打印一次进度
            if (i + 1) % 100 == 0:
                print(f"进度: {i + 1}/{total} ({(i+1)/total*100:.1f}%)")

        print(f"✅ 因子计算完成！成功: {success_count}/{total}")
        print(f"💾 因子已保存至: {self.factor_dir}")

    def load_factor(self, date: str) -> pd.DataFrame:
        """
        读取单日因子数据

        Args:
            date: 日期字符串

        Returns:
            DataFrame: 因子数据（列名取决于计算时的 period，例如 momentum_20）
        """
        file_path = self.factor_dir / f'{date}.csv'
        if not file_path.exists():
            return pd.DataFrame()

        df = pd.read_csv(file_path)
        return df


# ========== 测试代码 ==========
if __name__ == '__main__':
    # 初始化
    loader = DataLoader('./data')
    calculator = FactorCalculator(loader)

    # 测试单日计算
    if len(loader.trade_dates) > 30:
        test_date = loader.trade_dates[30]  # 选择第 31 天（确保有 20 天历史）
        factor_df = calculator.calculate_momentum_daily(test_date, period=20)

        print(f"\n📊 {test_date} 的动量因子（前 5 只股票）:")
        print(factor_df.head())
        print(f"\n因子统计:")
        factor_col = calculator.momentum_col(20)
        print(factor_df[factor_col].describe())

        # 批量计算并保存（取消注释可运行，但会花费较长时间）
        # calculator.calculate_and_save_all(period=20)
    else:
        print("交易日数据不足，无法进行测试")
