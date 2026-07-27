"""
Universe — 显式可投资宇宙定义
================================
核心: 显式声明宇宙的 size_tier (大盘/中盘/小盘), 决定 benchmark 类型.
基准错配 (HS300 vs 小盘) 是项目重复犯错的 #1 原因, 这里强制对齐.

使用:
  uni = Universe(data, size_tier='small_cap',
                 mcap_range=(30, 200),
                 min_turnover_20d=0.15)
  investable = uni.at(report_date, signal_date)  # 当日可投股票列表
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .data import DataBundle


class SizeTier(str, Enum):
    """市值层级 — 决定 benchmark 选择"""
    LARGE_CAP = "large_cap"      # > 500亿, 用 HS300
    MID_CAP   = "mid_cap"        # 100-500亿, 用 CSI500 (000905)
    SMALL_CAP = "small_cap"      # 30-100亿, 用 CSI1000 (000852) 或 random_from_universe
    MICRO_CAP = "micro_cap"      # < 30亿, 必须 random_from_universe (无合适 index)
    BROAD     = "broad"          # 不限市值, 用 random_from_universe


# 默认市值区间 (亿元)
DEFAULT_MCAP_RANGES = {
    SizeTier.LARGE_CAP: (500, 100000),
    SizeTier.MID_CAP:   (100, 500),
    SizeTier.SMALL_CAP: (30, 100),
    SizeTier.MICRO_CAP: (5, 30),
    SizeTier.BROAD:     (5, 100000),
}


@dataclass(frozen=True)
class Universe:
    """可投宇宙的不可变定义"""
    data: DataBundle
    size_tier: SizeTier
    mcap_range: Tuple[float, float]
    min_turnover_20d: float = 0.15
    exclude_st: bool = True
    exclude_new_listing_days: int = 180  # 上市后 N 日内不可投
    min_history_days: int = 252           # 至少 1 年历史

    @classmethod
    def small_cap(cls, data: DataBundle, **kwargs) -> "Universe":
        return cls(data=data, size_tier=SizeTier.SMALL_CAP,
                   mcap_range=DEFAULT_MCAP_RANGES[SizeTier.SMALL_CAP], **kwargs)

    @classmethod
    def mid_cap(cls, data: DataBundle, **kwargs) -> "Universe":
        return cls(data=data, size_tier=SizeTier.MID_CAP,
                   mcap_range=DEFAULT_MCAP_RANGES[SizeTier.MID_CAP], **kwargs)

    @classmethod
    def broad(cls, data: DataBundle,
              mcap_range: Tuple[float, float] = (30, 500),
              **kwargs) -> "Universe":
        return cls(data=data, size_tier=SizeTier.BROAD,
                   mcap_range=mcap_range, **kwargs)

    def at(self, report_date: pd.Timestamp,
           signal_date: pd.Timestamp) -> pd.DataFrame:
        """
        返回 signal_date 当日的可投股票表.

        过滤项:
          - panel report_date <= report_date (无前视)
          - 距 signal_date 6 个月内的最新报告 (避免老报告)
          - 有 OHLCV, 可在 signal_date 定价
          - 市值在 mcap_range
          - 近 20 日换手率 >= min_turnover_20d
          - 上市 >= exclude_new_listing_days
          - (TODO) 排除 ST (panel 缺标记, 暂用 name 包含 'ST' 排除)

        返回 DataFrame 列: code, name, industry, report_date, eps, bps, roe,
                          net_profit, np_single, ocf_ps, np_yoy, rev_yoy,
                          gross_margin, price, mcap_yi, turn20, bm_ratio
        """
        panel  = self.data.panel
        prices = self.data.price_cache

        avail = panel[panel["report_date"] <= report_date]
        latest = avail.sort_values("report_date").groupby("code").tail(1).reset_index(drop=True)

        # 排除 6 个月以上未更新的报告 (老报告掉队)
        cutoff = report_date - pd.Timedelta(days=200)
        latest = latest[latest["report_date"] >= cutoff]

        # 排除 ST (用 name)
        if self.exclude_st:
            latest = latest[~latest["name"].fillna("").str.contains("ST", na=False)]

        # 排除 BJ (没有 OHLCV)
        latest = latest[latest["code"].str[0].isin(list("0369"))]

        records = []
        for _, r in latest.iterrows():
            code = r["code"]
            if code not in prices: continue
            pf = prices[code]

            # 上市天数检查
            first_dt = pf["date"].iloc[0]
            if (signal_date - first_dt).days < self.exclude_new_listing_days: continue

            # 历史长度检查
            history = pf[pf["date"] <= signal_date]
            if len(history) < self.min_history_days: continue

            # 信号日定价
            price_at = self.data.get_price_at(code, signal_date)
            if price_at is None or price_at <= 0: continue

            # 市值
            eps = r["eps"]
            np_v = r["net_profit"]
            if pd.isna(eps) or abs(eps) < 1e-6: continue
            shares_yi = abs(np_v / eps) / 1e8
            mcap_yi = price_at * shares_yi
            if mcap_yi < self.mcap_range[0] or mcap_yi > self.mcap_range[1]: continue

            # 换手率
            past20 = pf[pf["date"] < signal_date].tail(20)
            if "turn" not in pf.columns or len(past20) < 10: continue
            turn20 = float(past20["turn"].mean())
            if turn20 < self.min_turnover_20d: continue

            records.append({
                "code": code,
                "name": r.get("name", ""),
                "industry": r.get("industry", ""),
                "report_date": r["report_date"],
                "eps": eps,
                "bps": r.get("bps", np.nan),
                "roe": r.get("roe", np.nan),
                "net_profit": np_v,
                "np_single": r.get("np_single", np.nan),
                "ocf_ps": r.get("ocf_ps", np.nan),
                "np_yoy": r.get("np_yoy", np.nan),
                "rev_yoy": r.get("rev_yoy", np.nan),
                "gross_margin": r.get("gross_margin", np.nan),
                "price": price_at,
                "mcap_yi": mcap_yi,
                "turn20": turn20,
                "bm_ratio": (r.get("bps", np.nan) / price_at) if not pd.isna(r.get("bps", np.nan)) else np.nan,
            })
        return pd.DataFrame(records)

    def describe(self) -> str:
        return (f"Universe(size_tier={self.size_tier.value}, "
                f"mcap={self.mcap_range[0]:.0f}-{self.mcap_range[1]:.0f}亿, "
                f"min_turn={self.min_turnover_20d:.2f}%)")
