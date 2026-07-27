"""
Benchmark — 自动匹配宇宙的基准
==================================
项目 #1 重复犯错原因: 用 HS300 做小盘策略基准, 自动虚高 alpha 5pp+.
本模块强制: 通过 size_tier 自动选基准, 错配直接抛 BenchmarkMismatch.

支持两种基准:
  1. Index: HS300 / CSI500 / CSI1000 (长期 buy-and-hold)
  2. Random: 同宇宙随机抽 N 只 (项目历史教训, 这是更严的对照)

策略默认应该用 Random. Index 仅用于对外汇报"跑赢基准了吗"这类 UI 层问题.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from .data import DataBundle
from .universe import Universe, SizeTier
from .exceptions import BenchmarkMismatch


class BenchmarkKind(str, Enum):
    HS300       = "hs300"          # 沪深300 (000300)
    CSI500      = "csi500"         # 中证500 (000905)
    CSI1000     = "csi1000"        # 中证1000 (000852)
    RANDOM      = "random"         # 同宇宙随机抽样
    EQUAL_WEIGHT = "equal_weight"  # 全宇宙等权


# size_tier → 推荐基准
SIZE_TIER_TO_BENCHMARK = {
    SizeTier.LARGE_CAP: BenchmarkKind.HS300,
    SizeTier.MID_CAP:   BenchmarkKind.CSI500,
    SizeTier.SMALL_CAP: BenchmarkKind.CSI1000,
    SizeTier.MICRO_CAP: BenchmarkKind.RANDOM,
    SizeTier.BROAD:     BenchmarkKind.RANDOM,
}


@dataclass(frozen=True)
class Benchmark:
    """基准定义. 必须经 validate_against(universe) 才能使用."""
    kind: BenchmarkKind
    universe: Universe

    @classmethod
    def auto_for(cls, universe: Universe) -> "Benchmark":
        """根据宇宙 size_tier 自动选择基准"""
        kind = SIZE_TIER_TO_BENCHMARK[universe.size_tier]
        return cls(kind=kind, universe=universe)

    @classmethod
    def random(cls, universe: Universe) -> "Benchmark":
        """显式选择随机对照 (推荐, 严格)"""
        return cls(kind=BenchmarkKind.RANDOM, universe=universe)

    def validate_against(self, universe: Universe) -> None:
        """检查基准与宇宙是否匹配, 不配抛 BenchmarkMismatch"""
        # Random 永远兼容
        if self.kind in (BenchmarkKind.RANDOM, BenchmarkKind.EQUAL_WEIGHT):
            return

        # Index 必须市值层匹配
        recommended = SIZE_TIER_TO_BENCHMARK[universe.size_tier]
        if self.kind != recommended:
            raise BenchmarkMismatch(
                f"宇宙 {universe.size_tier.value} 应使用 {recommended.value}, "
                f"但传入 {self.kind.value}. 这是项目反复犯错的 #1 原因. "
                f"使用 Benchmark.auto_for(universe) 或 Benchmark.random(universe)."
            )

    # ── 计算基准收益 ─────────────────────────────────────────────────────────
    def period_return(self, start_date: pd.Timestamp, end_date: pd.Timestamp,
                      cost: float = 0.0) -> Optional[float]:
        """基准在 [start, end] 区间收益. 返回 None 如不可计算."""
        if self.kind == BenchmarkKind.RANDOM:
            return self._random_return(start_date, end_date, cost)
        elif self.kind == BenchmarkKind.EQUAL_WEIGHT:
            return self._equal_weight_return(start_date, end_date, cost)
        else:
            # Index 需要 AKShare, 先在 backtest 层提供 cache
            return None

    def _random_return(self, start_date: pd.Timestamp, end_date: pd.Timestamp,
                       cost: float, n_random: int = 30, seed: int = 42) -> Optional[float]:
        """同宇宙随机抽 n 只的等权平均收益"""
        # 用 universe.at(start_date) 作为可投样本
        # signal_date 用 start_date (买入日)
        report_date = start_date - pd.Timedelta(days=60)  # 估个 report cutoff
        try:
            inv = self.universe.at(report_date, start_date)
        except Exception:
            return None
        if len(inv) < n_random: return None

        rng = np.random.default_rng(seed=seed + start_date.toordinal())
        picks = rng.choice(inv["code"].values, size=n_random, replace=False)
        rets = []
        for code in picks:
            p_start = self.universe.data.get_price_at(code, start_date)
            p_end   = self.universe.data.get_price_at(code, end_date)
            if p_start and p_end and p_start > 0:
                rets.append(p_end / p_start - 1)
        if not rets: return None
        return float(np.mean(rets) - cost)

    def _equal_weight_return(self, start_date, end_date, cost) -> Optional[float]:
        """全宇宙等权 (流动性过滤后) - 比 random 更稳定但慢"""
        report_date = start_date - pd.Timedelta(days=60)
        try:
            inv = self.universe.at(report_date, start_date)
        except Exception:
            return None
        if len(inv) < 50: return None
        rets = []
        for code in inv["code"].values:
            p_start = self.universe.data.get_price_at(code, start_date)
            p_end   = self.universe.data.get_price_at(code, end_date)
            if p_start and p_end and p_start > 0:
                rets.append(p_end / p_start - 1)
        if not rets: return None
        return float(np.mean(rets) - cost)

    def describe(self) -> str:
        return f"Benchmark({self.kind.value}, {self.universe.describe()})"
