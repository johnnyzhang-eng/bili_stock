"""
Shared Xueqiu cube event extraction for foundation strategies.

The functions here only build event indices. Return evaluation must still go
through research.foundation.Backtest.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REB_DIR = os.path.join(ROOT, "research", "attention_orj", "cache", "rebalancing")
OUT_DIR = os.path.join(ROOT, "research", "smart_consensus", "output")
ROLLING_ANN_PATH = os.path.join(OUT_DIR, "rolling_ann_gain.csv")

NON_STOCK_PREFIXES = (
    "510", "511", "512", "513", "515", "516", "518", "588", "159", "160",
    "110", "113", "118", "123", "127", "128",
)


@dataclass(frozen=True)
class CubeTradeEvent:
    cube: str
    stock: str
    ts_ms: int
    dt: pd.Timestamp
    prev_weight: float
    target_weight: float


@dataclass(frozen=True)
class ClusterEvent:
    stock: str
    latest_dt: pd.Timestamp
    cubes: tuple[str, ...]
    n_events: int
    event_idx: int


def normalize_stock_symbol(raw: str) -> Optional[str]:
    sym = (raw or "").upper()
    if not sym.startswith(("SH", "SZ")) or len(sym) != 8:
        return None
    code = sym[2:]
    if code.startswith(NON_STOCK_PREFIXES):
        return None
    return code


def load_rolling_ann(path: str = ROLLING_ANN_PATH) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index).normalize()
    return df.sort_index()


def _cube_symbol_from_path(path: str) -> str:
    return os.path.basename(path).replace(".json", "")


def _event_bucket(dt: pd.Timestamp) -> pd.Timestamp:
    return dt.to_period("W-SUN").start_time.normalize()


def _cube_is_smart_at(
    rolling_ann: pd.DataFrame,
    cube: str,
    event_dt: pd.Timestamp,
    skill_min: float,
    skill_max: float,
) -> bool:
    bucket = _event_bucket(event_dt)
    if cube not in rolling_ann.columns or bucket not in rolling_ann.index:
        return False
    ann = rolling_ann.at[bucket, cube]
    return bool(pd.notna(ann) and skill_min < float(ann) <= skill_max)


def iter_trade_events(
    *,
    category: str = "user_rebalancing",
    rolling_ann: Optional[pd.DataFrame] = None,
    skill_min: float = 25.0,
    skill_max: float = 200.0,
    min_target_weight: float = 0.01,
) -> Iterable[CubeTradeEvent]:
    """Yield point-in-time cube stock weight changes.

    If rolling_ann is provided, only cubes that pass the ex-ante rolling skill
    gate at the event bucket are yielded.
    """
    for path in glob.glob(os.path.join(REB_DIR, "*.json")):
        cube = _cube_symbol_from_path(path)
        try:
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
        except Exception:
            continue
        if not isinstance(rows, list):
            continue

        rows = [
            r for r in rows
            if isinstance(r, dict)
            and r.get("status") == "success"
            and r.get("category") == category
            and r.get("created_at")
        ]
        rows.sort(key=lambda r: r.get("created_at", 0))

        for row in rows:
            ts_ms = int(row.get("created_at") or 0)
            if ts_ms <= 0:
                continue
            dt = pd.Timestamp(datetime.fromtimestamp(ts_ms / 1000))
            if rolling_ann is not None and not _cube_is_smart_at(
                rolling_ann, cube, dt, skill_min, skill_max
            ):
                continue

            for h in row.get("rebalancing_histories") or []:
                stock = normalize_stock_symbol(h.get("stock_symbol"))
                if stock is None:
                    continue
                try:
                    target = float(h.get("target_weight") or 0.0)
                    prev = float(h.get("prev_weight_adjusted") or 0.0)
                except (TypeError, ValueError):
                    continue
                if abs(target - prev) < min_target_weight:
                    continue
                yield CubeTradeEvent(
                    cube=cube,
                    stock=stock,
                    ts_ms=ts_ms,
                    dt=dt,
                    prev_weight=prev,
                    target_weight=target,
                )


def _event_idx_for_latest_dt(df: pd.DataFrame, latest_dt: pd.Timestamp) -> Optional[int]:
    """Return index whose next_open is strictly after the event day."""
    dates = pd.DatetimeIndex(pd.to_datetime(df["date"]).dt.normalize())
    pos = dates.searchsorted(latest_dt.normalize(), side="right") - 1
    if pos < 0 or pos + 1 >= len(df):
        return None
    return int(pos)


def build_cluster_events(
    price_cache: Dict[str, pd.DataFrame],
    *,
    side: str = "buy",
    min_cubes: int = 3,
    window_days: int = 7,
    cooldown_days: int = 7,
    skill_min: float = 25.0,
    skill_max: float = 200.0,
    min_target_weight: float = 0.01,
) -> Dict[str, List[int]]:
    """Build {stock: [event_idx]} for smart-cube cluster buys/exits.

    side='buy' means prev_weight <= 0 and target_weight > 0.
    side='exit' means prev_weight > 0 and target_weight <= 0.
    """
    if side not in {"buy", "exit"}:
        raise ValueError("side must be 'buy' or 'exit'")

    rolling_ann = load_rolling_ann()
    events = list(
        iter_trade_events(
            rolling_ann=rolling_ann,
            skill_min=skill_min,
            skill_max=skill_max,
            min_target_weight=min_target_weight,
        )
    )
    if side == "buy":
        events = [e for e in events if e.prev_weight <= 0 and e.target_weight > 0]
    else:
        events = [e for e in events if e.prev_weight > 0 and e.target_weight <= 0]

    by_stock: Dict[str, List[CubeTradeEvent]] = {}
    for event in events:
        if event.stock in price_cache:
            by_stock.setdefault(event.stock, []).append(event)

    out: Dict[str, List[int]] = {}
    window = pd.Timedelta(days=window_days)
    cooldown = pd.Timedelta(days=cooldown_days)

    for stock, stock_events in by_stock.items():
        stock_events.sort(key=lambda e: e.dt)
        df = price_cache.get(stock)
        if df is None or len(df) < 10:
            continue

        left = 0
        last_emitted: Optional[pd.Timestamp] = None
        idxs: List[int] = []
        for right, event in enumerate(stock_events):
            while left <= right and event.dt - stock_events[left].dt > window:
                left += 1
            window_events = stock_events[left:right + 1]
            cubes = tuple(sorted({e.cube for e in window_events}))
            if len(cubes) < min_cubes:
                continue
            if last_emitted is not None and event.dt - last_emitted < cooldown:
                continue
            idx = _event_idx_for_latest_dt(df, event.dt)
            if idx is None:
                continue
            idxs.append(idx)
            last_emitted = event.dt

        if idxs:
            # De-dup when multiple events map to the same trading day.
            out[stock] = sorted(set(idxs))

    return out


def make_cluster_detect_fn(**kwargs):
    """Return a foundation EventDrivenStrategy detect_fn."""
    def detect(price_cache):
        return build_cluster_events(price_cache, **kwargs)

    return detect
