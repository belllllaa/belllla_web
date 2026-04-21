from abc import ABC, abstractmethod
import pandas as pd


class Strategy(ABC):
    """策略基类 - 抽象接口"""

    def __init__(self, name: str):
        """
        初始化策略

        Args:
            name: 策略名称
        """
        self.name = name

    @abstractmethod
    def calculate_factor(
        self,
        date: str,
        data_loader,
        **kwargs
    ) -> pd.DataFrame:
        """
        计算因子值(子类必须实现)

        Args:
            date: 当前日期
            data_loader: 数据加载器
            **kwargs: 其他参数

        Returns:
            DataFrame: 包含 code, date, factor_value 列
        """
        pass

    @abstractmethod
    def generate_signal(
        self,
        factor_df: pd.DataFrame,
        top_n: int = 10
    ) -> list:
        """
        生成选股信号(子类必须实现)

        Args:
            factor_df: 因子数据
            top_n: 选股数量

        Returns:
            选中的股票代码列表
        """
        pass


# ========== 示例策略 1: 动量策略 ==========
class MomentumStrategy(Strategy):
    """动量策略: 买入过去N日涨幅最大的股票"""

    def __init__(self, period: int = 20):
        super().__init__(name=f'Momentum_{period}')
        self.period = period

    def calculate_factor(self, date: str, data_loader, **kwargs) -> pd.DataFrame:
        trade_dates = data_loader.get_all_dates()
        if date not in trade_dates:
            return pd.DataFrame()

        current_idx = trade_dates.index(date)
        if current_idx < self.period:
            return pd.DataFrame()

        past_date = trade_dates[current_idx - self.period]

        current_data = data_loader.get_daily_data(date)
        past_data = data_loader.get_daily_data(past_date)

        if current_data.empty or past_data.empty:
            return pd.DataFrame()

        merged = pd.merge(
            current_data[['code', 'close']],
            past_data[['code', 'close']],
            on='code',
            suffixes=('_now', '_past')
        )

        merged['factor_value'] = (merged['close_now'] / merged['close_past']) - 1
        merged['date'] = date

        return merged[['code', 'date', 'factor_value']]

    def generate_signal(self, factor_df: pd.DataFrame, top_n: int = 10) -> list:
        if factor_df.empty:
            return []

        # 降序排序(动量越大越好)
        sorted_df = factor_df.sort_values('factor_value', ascending=False)
        selected = sorted_df.head(top_n)['code'].tolist()

        return selected


# ========== 示例策略 2: 反转策略 ==========
class ReversalStrategy(Strategy):
    """反转策略: 买入过去N日跌幅最大的股票(预期反弹)"""

    def __init__(self, period: int = 5):
        super().__init__(name=f'Reversal_{period}')
        self.period = period

    def calculate_factor(self, date: str, data_loader, **kwargs) -> pd.DataFrame:
        # 计算逻辑与动量相同,只是选股逻辑相反
        trade_dates = data_loader.get_all_dates()
        if date not in trade_dates:
            return pd.DataFrame()

        current_idx = trade_dates.index(date)
        if current_idx < self.period:
            return pd.DataFrame()

        past_date = trade_dates[current_idx - self.period]

        current_data = data_loader.get_daily_data(date)
        past_data = data_loader.get_daily_data(past_date)

        if current_data.empty or past_data.empty:
            return pd.DataFrame()

        merged = pd.merge(
            current_data[['code', 'close']],
            past_data[['code', 'close']],
            on='code',
            suffixes=('_now', '_past')
        )

        merged['factor_value'] = (merged['close_now'] / merged['close_past']) - 1
        merged['date'] = date

        return merged[['code', 'date', 'factor_value']]

    def generate_signal(self, factor_df: pd.DataFrame, top_n: int = 10) -> list:
        if factor_df.empty:
            return []

        # 升序排序(跌幅越大越好,预期反弹)
        sorted_df = factor_df.sort_values('factor_value', ascending=True)
        selected = sorted_df.head(top_n)['code'].tolist()

        return selected


# ========== 测试代码 ==========
if __name__ == '__main__':
    from data_loader import DataLoader

    loader = DataLoader('./data')
    test_date = loader.trade_dates[50]

    # 测试动量策略
    print("=== 测试动量策略 ===")
    momentum = MomentumStrategy(period=20)
    factor_df = momentum.calculate_factor(test_date, loader)
    if not factor_df.empty:
        print(f"因子计算成功: {len(factor_df)} 只股票")
        selected = momentum.generate_signal(factor_df, top_n=5)
        print(f"选股结果: {selected}")

    # 测试反转策略
    print("\n=== 测试反转策略 ===")
    reversal = ReversalStrategy(period=5)
    factor_df = reversal.calculate_factor(test_date, loader)
    if not factor_df.empty:
        print(f"因子计算成功: {len(factor_df)} 只股票")
        selected = reversal.generate_signal(factor_df, top_n=5)
        print(f"选股结果: {selected}")
