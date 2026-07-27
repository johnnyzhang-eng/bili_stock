"""
Strategy — 策略抽象 + 两类具体策略
====================================
设计:
  - Strategy: 策略接口
  - CrossSectionalStrategy: 周期回测 (季度/月度选股)
  - EventDrivenStrategy: 事件驱动 (涨停/财报/突发)

策略类只描述 "如何选股" 与 "如何持有", 不直接执行回测.
回测交给 Backtest 引擎统一处理 (强制 random control).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np
import pandas as pd


# ── 抽象基类 ─────────────────────────────────────────────────────────────────
class Strategy(ABC):
    name: str

    @abstractmethod
    def kind(self) -> str:
        """'cross_sectional' 或 'event_driven'"""
        ...


# ── Cross-sectional (周期回测) ───────────────────────────────────────────────
@dataclass
class CrossSectionalStrategy(Strategy):
    """
    周期回测策略: 每 hold_days 在 universe 内按 factor_fn 排序选 top_pct.

    factor_fn 接口:
      def factor_fn(row: dict, price_cache: Dict[str, pd.DataFrame],
                     signal_date: pd.Timestamp) -> float
      返回越大越好 (会取 top).
    """
    name: str
    factor_fn: Callable
    top_pct: float = 0.20
    n_signal_cap: int = 30
    hold_days: int = 180
    rebalance_freq: str = "Q"   # 'Q' (季度) 或 'M' (月度) 或 'D-N' (每 N 日)

    def kind(self) -> str:
        return "cross_sectional"

    def select(self, universe_df: pd.DataFrame,
                price_cache, signal_date: pd.Timestamp) -> List[str]:
        """从给定 universe DataFrame 选出 top picks"""
        if universe_df.empty: return []

        # 计算 factor
        scores = []
        for _, r in universe_df.iterrows():
            try:
                f = self.factor_fn(r.to_dict(), price_cache, signal_date)
            except Exception:
                f = np.nan
            scores.append(f)

        df = universe_df.copy()
        df["factor"] = scores
        df = df.dropna(subset=["factor"])
        if df.empty: return []

        # 取 top
        df = df.sort_values("factor", ascending=False)
        n_top = max(int(len(df) * self.top_pct), 5)
        n_top = min(n_top, self.n_signal_cap)
        return df.head(n_top)["code"].tolist()


# ── Event-driven (事件型) ────────────────────────────────────────────────────
@dataclass
class EventDrivenStrategy(Strategy):
    """
    事件驱动策略: 检测器返回触发事件的 (code, idx) 列表, 持有 hold_days.

    detect_fn 接口:
      def detect_fn(price_cache: Dict[str, pd.DataFrame]) -> Dict[str, List[int]]
      返回 {code: [event_idx_list]} 每个 idx 是该事件发生的日索引.

    entry_at: 'today_close' (尾盘抢板) 或 'next_open' (次日开盘)
    exit_at:  'next_close' / 'next_open' / 'after_n_days'
    """
    name: str
    detect_fn: Callable
    entry_at: str = "next_open"
    exit_at: str = "next_close"
    hold_days: int = 1

    def kind(self) -> str:
        return "event_driven"

    def detect_events(self, price_cache) -> dict:
        """返回 {code: [event_idx]}"""
        return self.detect_fn(price_cache)
