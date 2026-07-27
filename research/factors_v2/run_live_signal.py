"""
Live Signal Runner — Low-Vol Production Strategy
=================================================

Production config:
    low_vol (vol_window=60, hold_step=12, enter_q=0.80, keep_q=0.70)
    + overlay: HS300 20d < -7% → hold cash

Outputs today's stock picks (or "HOLD CASH" if overlay fires).
Uses most recent available price data — run after update_stock_data.py
for freshest signal.

Run:
    python research/factors_v2/run_live_signal.py
"""

import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import baostock as bs

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.factors.factor_low_volatility import build_low_volatility_factor

STOCK_DATA_DIR  = os.path.join(ROOT, "data", "stock_data")
HS300_CACHE     = os.path.join(ROOT, "data", "market_cache", "hs300_daily_cache.csv")
OUTPUT_DIR      = os.path.join(ROOT, "research", "factors_v2", "output", "live")

# Production params
VOL_WINDOW   = 60
ENTER_Q      = 0.80
KEEP_Q       = 0.70
OVERLAY_THR  = -0.07


def _update_hs300_cache() -> str:
    """Append recent HS300 data to cache. Returns latest date after update."""
    hs = pd.read_csv(HS300_CACHE)
    hs["date"] = pd.to_datetime(hs["date"])
    latest = hs["date"].max()
    today  = pd.Timestamp(datetime.today().date())

    if latest >= today - timedelta(days=3):
        print(f"  HS300 cache current ({latest.date()}), skipping update")
        return str(latest.date())

    print(f"  Updating HS300 from {latest.date()} ...", flush=True)
    lg = bs.login()
    if str(lg.error_code) != "0":
        print(f"  BaoStock login failed: {lg.error_msg}")
        return str(latest.date())

    start = (latest + timedelta(days=1)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")
    rs = bs.query_history_k_data_plus(
        "sh.000300", "date,close",
        start_date=start, end_date=end,
        frequency="d", adjustflag="3"
    )
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    bs.logout()

    if not rows:
        print("  No new HS300 data from baostock")
        return str(latest.date())

    new_df = pd.DataFrame(rows, columns=["date", "close"])
    new_df["close"] = pd.to_numeric(new_df["close"], errors="coerce")
    new_df["date"]  = pd.to_datetime(new_df["date"])

    # Rebuild full series with ret20 and regime
    full = pd.concat([hs[["date", "close"]], new_df], ignore_index=True)
    full = full.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    full["ret20"] = full["close"].pct_change(20)
    full["hs300_ret20"] = full["ret20"]
    full["regime"] = full["ret20"].apply(
        lambda r: "上涨" if r > 0.03 else ("下跌" if r < -0.03 else "震荡")
        if pd.notna(r) else "震荡"
    )
    full["date"] = full["date"].dt.strftime("%Y-%m-%d")
    full.to_csv(HS300_CACHE, index=False)
    latest_new = full["date"].max()
    print(f"  HS300 updated → {latest_new}")
    return latest_new


def _get_regime(signal_date: pd.Timestamp) -> tuple:
    """Return (regime, ret20) for the most recent date <= signal_date."""
    hs = pd.read_csv(HS300_CACHE)
    hs["date"] = pd.to_datetime(hs["date"])
    hs = hs[hs["date"] <= signal_date].dropna(subset=["ret20"])
    if hs.empty:
        return "震荡", 0.0
    row = hs.iloc[-1]
    return row["regime"], float(row["ret20"])


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today = datetime.today().date()
    print(f"\n{'='*60}")
    print(f"LIVE SIGNAL — {today}")
    print(f"{'='*60}\n")

    # ── Step 1: Update HS300 ─────────────────────────────────────── #
    print("Step 1: Check HS300 cache ...")
    latest_hs300 = _update_hs300_cache()

    # ── Step 2: Check overlay ────────────────────────────────────── #
    print("\nStep 2: Check overlay (HS300 20d return vs -7% threshold) ...")
    signal_date = pd.Timestamp(latest_hs300)
    regime, ret20 = _get_regime(signal_date)
    print(f"  Latest HS300 date : {signal_date.date()}")
    print(f"  HS300 ret20       : {ret20:+.2%}")
    print(f"  Regime            : {regime}")

    overlay_fires = ret20 < OVERLAY_THR
    if overlay_fires:
        print(f"\n  🚨 OVERLAY FIRING — ret20 {ret20:+.2%} < {OVERLAY_THR:.0%}")
        print(f"  SIGNAL: HOLD CASH — do not enter new positions")
        signal = {
            "date": str(today),
            "hs300_date": latest_hs300,
            "hs300_ret20": ret20,
            "regime": regime,
            "overlay": "FIRED",
            "action": "HOLD_CASH",
            "picks": [],
        }
    else:
        print(f"  ✓ Overlay clear — proceed to stock selection")

        # ── Step 3: Build factor on latest available data ─────────── #
        print("\nStep 3: Building low_vol factor ...")
        # Use 2-year window ending at latest available stock data date
        end_date = signal_date.strftime("%Y-%m-%d")
        start_date = (signal_date - timedelta(days=400)).strftime("%Y-%m-%d")

        factor_df = build_low_volatility_factor(
            STOCK_DATA_DIR,
            start_date=start_date,
            end_date=end_date,
            window=VOL_WINDOW,
            min_periods=40,
        )

        if factor_df.empty:
            print("  ERROR: no factor data built")
            return

        # Get factor values on most recent available date
        factor_latest_date = factor_df["date"].max()
        print(f"  Factor computed to: {factor_latest_date.date()}")
        if (signal_date - factor_latest_date).days > 30:
            print(f"  ⚠ WARNING: factor data is {(signal_date - factor_latest_date).days} days stale")
            print(f"    Run research/data_prep/update_stock_data.py to refresh")

        snapshot = factor_df[factor_df["date"] == factor_latest_date].copy()

        # Exclude ETFs: SH 510/511/512/513/514/515/516/517/518/519/56x/588xxx
        #               SZ 159xxx
        def _is_etf(sym: str) -> bool:
            s = sym.upper()
            if s.startswith("SH"):
                code = s[2:]
                return code[:3] in {"510","511","512","513","514","515","516","517","518","519","588"} or code[:2] == "56"
            if s.startswith("SZ"):
                return s[2:5] == "159"
            return False

        before = len(snapshot)
        snapshot = snapshot[~snapshot["stock_symbol"].apply(_is_etf)].copy()
        print(f"  ETF filter removed {before - len(snapshot)} ETFs, {len(snapshot)} stocks remain")
        snapshot["rank_pct"] = snapshot["factor_z"].rank(pct=True, method="first")

        # ── Step 4: Select top picks (entry threshold) ───────────── #
        picks = snapshot[snapshot["rank_pct"] >= ENTER_Q].copy()
        picks = picks.sort_values("rank_pct", ascending=False)

        print(f"\nStep 4: Stock selection (enter_q={ENTER_Q}, keep_q={KEEP_Q})")
        print(f"  Universe    : {len(snapshot):,} stocks")
        print(f"  Top picks   : {len(picks)} stocks (rank >= {ENTER_Q:.0%})")
        print(f"  Factor date : {factor_latest_date.date()}")

        print(f"\n  Top 30 picks by low_vol rank:")
        print(f"  {'Stock':<15s} {'rank_pct':>9s} {'vol_score(raw)':>14s}")
        print(f"  {'-'*42}")
        for _, row in picks.head(30).iterrows():
            print(f"  {row['stock_symbol']:<15s} {row['rank_pct']:>8.3f}  {row['factor_raw']:>13.6f}")

        signal = {
            "date": str(today),
            "hs300_date": latest_hs300,
            "hs300_ret20": ret20,
            "regime": regime,
            "overlay": "CLEAR",
            "action": "INVEST",
            "factor_date": str(factor_latest_date.date()),
            "n_picks": len(picks),
            "picks": picks["stock_symbol"].tolist(),
        }

        # Save full ranked list
        out_path = os.path.join(OUTPUT_DIR, f"signal_{today}.csv")
        picks[["stock_symbol", "rank_pct", "factor_raw", "factor_z"]].to_csv(
            out_path, index=False, encoding="utf-8-sig"
        )
        print(f"\n  Full ranked list saved → {out_path}")

    # ── Step 5: Append to paper trade log ───────────────────────── #
    log_path = os.path.join(OUTPUT_DIR, "paper_trade_log.csv")
    log_entry = pd.DataFrame([{
        "date": signal["date"],
        "hs300_date": signal["hs300_date"],
        "hs300_ret20": f"{signal['hs300_ret20']:+.4f}",
        "regime": signal["regime"],
        "overlay": signal["overlay"],
        "action": signal["action"],
        "n_picks": signal.get("n_picks", 0),
        "factor_date": signal.get("factor_date", ""),
    }])
    if os.path.exists(log_path):
        existing = pd.read_csv(log_path)
        combined = pd.concat([existing, log_entry], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date"], keep="last")
        combined.to_csv(log_path, index=False, encoding="utf-8-sig")
    else:
        log_entry.to_csv(log_path, index=False, encoding="utf-8-sig")
    print(f"\nPaper trade log updated → {log_path}")

    print(f"\n{'='*60}")
    print(f"SUMMARY — {today}")
    print(f"  Regime  : {regime} (HS300 ret20 {ret20:+.2%})")
    print(f"  Action  : {signal['action']}")
    if signal["action"] == "INVEST":
        print(f"  Picks   : {signal.get('n_picks',0)} stocks")
        print(f"  (factor data from {signal.get('factor_date','?')} — "
              f"update stock data for fresher signal)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
