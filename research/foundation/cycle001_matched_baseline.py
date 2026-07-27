"""
Cycle 001 supplemental size/liquidity-matched baseline audit.

Foundation Backtest random control samples from the same filtered universe. This
script adds a stricter per-period control for cross-sectional Cycle 001
strategies: each signal pick is matched to a random non-pick from the same
market-cap decile and 20-day turnover decile, with deterministic fallbacks.

Event-driven H2/H3 already use same-stock random non-event dates in
Backtest._event_random_baseline, so size/liquidity are fixed by construction.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from research.foundation import DataBundle, Universe
from research.foundation.strategies_a1 import make_strategy as make_a1_strategy
from research.foundation.strategies_h4_buy_intensity import make_strategy as make_h4_strategy


OUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "smart_consensus", "output")
)


@dataclass
class AuditSpec:
    id: str
    make_strategy: Callable
    hold_days: int


def _bucket_codes(universe_df: pd.DataFrame) -> pd.DataFrame:
    df = universe_df.copy()
    n_bins = min(10, max(2, len(df) // 30))
    df["mcap_bin"] = pd.qcut(df["mcap_yi"].rank(method="first"), q=n_bins, labels=False)
    df["turn_bin"] = pd.qcut(df["turn20"].rank(method="first"), q=n_bins, labels=False)
    return df


def _portfolio_ret(data: DataBundle, codes: list[str], start, end) -> float:
    rets = []
    for code in codes:
        p0 = data.get_price_at(code, start)
        p1 = data.get_price_at(code, end)
        if p0 is None or p1 is None or p0 <= 0:
            continue
        rets.append(p1 / p0 - 1)
    return float(np.mean(rets)) if rets else float("nan")


def _matched_random_codes(df: pd.DataFrame, picks: list[str], seed: int) -> list[str]:
    rng = np.random.default_rng(seed)
    pick_set = set(picks)
    available = df[~df["code"].isin(pick_set)].copy()
    used: set[str] = set()
    matched: list[str] = []
    attrs = df.set_index("code")[["mcap_bin", "turn_bin"]]

    for code in picks:
        if code not in attrs.index:
            continue
        mcap_bin, turn_bin = attrs.loc[code]
        pool = available[
            (available["mcap_bin"] == mcap_bin)
            & (available["turn_bin"] == turn_bin)
            & (~available["code"].isin(used))
        ]
        if pool.empty:
            pool = available[
                (available["mcap_bin"] == mcap_bin)
                & (~available["code"].isin(used))
            ]
        if pool.empty:
            pool = available[
                (available["turn_bin"] == turn_bin)
                & (~available["code"].isin(used))
            ]
        if pool.empty:
            pool = available[~available["code"].isin(used)]
        if pool.empty:
            break
        chosen = str(rng.choice(pool["code"].values))
        used.add(chosen)
        matched.append(chosen)
    return matched


def run_cross_sectional_matched(spec: AuditSpec, data: DataBundle) -> pd.DataFrame:
    strategy = spec.make_strategy()
    universe = Universe.broad(
        data,
        mcap_range=(30, 500),
        min_turnover_20d=0.15,
        exclude_st=True,
        exclude_new_listing_days=180,
    )
    rows = []
    q_month = [3, 6, 9, 12]
    q_day = [31, 30, 30, 31]
    for yr in range(2017, 2026):
        for q in [1, 2, 3, 4]:
            rpt_date = pd.Timestamp(yr, q_month[q - 1], q_day[q - 1])
            sig_date = data.get_signal_date(rpt_date)
            fwd_date = sig_date + pd.Timedelta(days=spec.hold_days)
            universe_df = universe.at(rpt_date, sig_date)
            if len(universe_df) < 50:
                continue
            universe_df = _bucket_codes(universe_df)
            picks = strategy.select(universe_df, data.price_cache, sig_date)
            if not picks:
                continue
            signal_ret = _portfolio_ret(data, picks, sig_date, fwd_date)
            if np.isnan(signal_ret):
                continue
            random_codes = _matched_random_codes(
                universe_df, picks, seed=42 + yr * 4 + q
            )
            random_ret = _portfolio_ret(data, random_codes, sig_date, fwd_date)
            if np.isnan(random_ret):
                continue
            rows.append(
                {
                    "id": spec.id,
                    "period": f"{yr}Q{q}",
                    "signal_date": sig_date.date().isoformat(),
                    "fwd_date": fwd_date.date().isoformat(),
                    "universe_n": len(universe_df),
                    "signal_n": len(picks),
                    "matched_n": len(random_codes),
                    "signal_ret": signal_ret,
                    "matched_ret": random_ret,
                    "alpha": signal_ret - random_ret,
                    "split": "train" if sig_date <= pd.Timestamp("2021-12-31") else "test",
                }
            )
    return pd.DataFrame(rows)


def _summary(df: pd.DataFrame, split: str) -> dict:
    sub = df if split == "full" else df[df["split"] == split]
    alpha = sub["alpha"].dropna()
    if alpha.empty:
        return {"n": 0, "alpha_mean": np.nan, "t_stat": np.nan}
    std = alpha.std(ddof=1)
    t_stat = alpha.mean() / (std / np.sqrt(len(alpha))) if len(alpha) > 1 and std > 0 else np.nan
    return {"n": len(alpha), "alpha_mean": alpha.mean(), "t_stat": t_stat}


def _write_report(all_rows: pd.DataFrame) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, "cycle001_matched_baseline.csv")
    md_path = os.path.join(OUT_DIR, "cycle001_matched_baseline.md")
    all_rows.to_csv(csv_path, index=False)

    lines = [
        "# Cycle 001 Size/Liquidity-Matched Baseline Audit",
        "",
        "Cross-sectional strategies A1 and H4 are re-scored against a stricter",
        "per-period baseline: one random non-signal stock per pick from the same",
        "market-cap decile and 20-day-turnover decile, with deterministic fallback",
        "to one-axis matching when a cell is empty.",
        "",
        "H2 and H3 are event-driven and already use same-stock random non-event",
        "dates in the foundation engine; size, liquidity, board, and industry are",
        "therefore fixed by stock identity.",
        "",
        "| ID | Split | n | alpha/period | t | Verdict impact |",
        "|---|---|---:|---:|---:|---|",
    ]
    for sid in ["A1", "H4"]:
        sdf = all_rows[all_rows["id"] == sid]
        for split in ["train", "test", "full"]:
            s = _summary(sdf, split)
            impact = "REJECT unchanged" if split == "full" and (s["t_stat"] < 2 or s["alpha_mean"] <= 0) else ""
            lines.append(
                f"| {sid} | {split} | {s['n']} | {s['alpha_mean']*100:+.2f}% | "
                f"{s['t_stat']:+.2f} | {impact} |"
            )
    lines.extend(
        [
            "",
            "Output CSV: `research/smart_consensus/output/cycle001_matched_baseline.csv`",
        ]
    )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    data = DataBundle.load(verbose=False)
    specs = [
        AuditSpec("A1", make_a1_strategy, hold_days=63),
        AuditSpec("H4", make_h4_strategy, hold_days=63),
    ]
    rows = [run_cross_sectional_matched(spec, data) for spec in specs]
    all_rows = pd.concat(rows, ignore_index=True)
    _write_report(all_rows)
    for sid in ["A1", "H4"]:
        s = _summary(all_rows[all_rows["id"] == sid], "full")
        print(f"{sid}: n={s['n']} alpha={s['alpha_mean']*100:+.2f}% t={s['t_stat']:+.2f}")
    print(f"[+] Wrote {OUT_DIR}/cycle001_matched_baseline.md")


if __name__ == "__main__":
    main()
