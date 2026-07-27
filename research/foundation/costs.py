"""
CostModel — 透明可注入的成本模型
=================================
区分两种场景:
  1. 周期回测 (rebalance every N months): 滑点小, 主要佣金+印花税
  2. 短线事件 (1-5 日持仓): 滑点大, 印花税相同

A 股散户实盘成本 (来自实测 + 行业常识):
  佣金:         单边 0.013% (券商 + 过户)
  印花税:       卖出 0.10%
  滑点周期:     单边 0.10% (季度再平衡型)
  滑点短线:     单边 0.50-1.00% (尾盘抢板/开盘抛压)
  冲击成本:     视成交额, 小资金 < 0.05% 可忽略
"""
from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class CostModel:
    """完整的成本模型. 所有数值是小数 (0.001 = 0.1%)"""
    name: str
    buy_slippage: float       # 买入滑点
    sell_slippage: float      # 卖出滑点
    commission: float         # 单边佣金 (买/卖各一次)
    stamp_tax_sell: float     # 卖出印花税 (买入不收)

    @property
    def total_round_trip(self) -> float:
        """完整一次买卖的成本"""
        return (self.buy_slippage + self.sell_slippage +
                2 * self.commission + self.stamp_tax_sell)

    def buy_cost(self) -> float:
        """单次买入成本 (用于持仓建仓)"""
        return self.buy_slippage + self.commission

    def sell_cost(self) -> float:
        """单次卖出成本 (用于持仓平仓)"""
        return self.sell_slippage + self.commission + self.stamp_tax_sell

    def cost_per_turnover_unit(self) -> float:
        """每单位换手对应的成本 (用于 cross-sectional 周期回测)"""
        return self.total_round_trip / 2  # turnover 是单边换手

    @classmethod
    def a_share_retail_quarterly(cls) -> "CostModel":
        """A 股散户季度再平衡: 标准 56bp round-trip"""
        return cls(
            name="A股散户季度",
            buy_slippage=0.0010,    # 10bp
            sell_slippage=0.0010,
            commission=0.00013,
            stamp_tax_sell=0.0010,
        )

    @classmethod
    def a_share_retail_intraday(cls) -> "CostModel":
        """A 股散户短线: 滑点显著放大 (尾盘抢板/开盘抛压)"""
        return cls(
            name="A股散户短线",
            buy_slippage=0.010,      # 100bp 抢板
            sell_slippage=0.005,     # 50bp 开盘抛压
            commission=0.00013,
            stamp_tax_sell=0.0010,
        )

    @classmethod
    def a_share_retail_swing(cls) -> "CostModel":
        """A 股散户波段 (1-2 周持仓): 中等滑点"""
        return cls(
            name="A股散户波段",
            buy_slippage=0.0030,
            sell_slippage=0.0030,
            commission=0.00013,
            stamp_tax_sell=0.0010,
        )

    @classmethod
    def etf_quarterly(cls) -> "CostModel":
        """ETF 季度再平衡: 无印花税, 滑点小"""
        return cls(
            name="ETF季度",
            buy_slippage=0.0005,
            sell_slippage=0.0005,
            commission=0.00013,
            stamp_tax_sell=0.0,        # ETF 免印花税
        )

    def describe(self) -> str:
        return (f"{self.name}: round-trip {self.total_round_trip*100:.2f}% "
                f"(滑点 {self.buy_slippage*100:.2f}+{self.sell_slippage*100:.2f}, "
                f"佣金 2×{self.commission*100:.3f}, 印花税 {self.stamp_tax_sell*100:.2f})")
