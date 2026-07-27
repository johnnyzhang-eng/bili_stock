"""
Broad Liquid A-share Panel
==========================

Panel for factor evaluation that does NOT pre-filter to Xueqiu-active stocks.
The existing `_prepare_panel_v5()` starts from `rebalancing_history` in cubes.db,
which limits the universe to ~500-600 stocks that Xueqiu cubes have traded.
That's the right universe for evaluating the Xueqiu consensus factor itself,
but the wrong universe for evaluating value / quality / low-vol factors —
their natural habitat is the full liquid A-share universe.

This builder starts from every per-stock CSV in `data/stock_data/`, attaches
the same industry / liquidity / regime / tradability fields as v5, and caches
the result so subsequent factor runs are fast.

Columns produced:
    date, stock_symbol, close, fwd_ret_2w,
    industry_l2, amount, liq_rank_pct,
    regime, hs300_ret20
"""

import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.baseline_v4.code.run_baseline_v4_2_up_filter import _load_hs300
from research.baseline_v5.code.run_baseline_v5_with_costs import _load_tradability_from_stock_data


CACHE_DIR = os.path.join(ROOT, "research", "factors_v2", "cache")


# --------------------------------------------------------------------------- #
# Universe filter
# --------------------------------------------------------------------------- #
def _is_a_share_equity(sym: str) -> bool:
    """
    Accept regular A-share common stocks. Reject HK-listed, ETFs, and LOF funds.

    Codes (6-digit) we accept:
      60xxxx  (SH main)          000xxx (SZ main)
      601xxx  (SH main)          001xxx (SZ main)
      603xxx  (SH main)          002xxx (SZ SME)
      605xxx  (SH main)          003xxx (SZ main)
      688xxx  (SH STAR)          300xxx (SZ ChiNext)
                                 301xxx (SZ ChiNext)

    Reject: 5xxxxx (SH ETF), 15xxxx (SZ ETF), 16xxxx (SZ LOF), .HK
    """
    sym = sym.upper()
    if sym.endswith(".HK"):
        return False
    # Extract 6-digit code
    if sym.startswith(("SH", "SZ", "BJ")) and len(sym) >= 8:
        code = sym[2:8]
    elif len(sym) >= 9 and sym[6] == ".":
        code = sym[:6]
    else:
        return False
    if not code.isdigit() or len(code) != 6:
        return False
    first2 = code[:2]
    # A-share equity prefixes
    if first2 in ("60", "68"):  # SH
        return True
    if first2 in ("00", "30"):  # SZ main + ChiNext
        return True
    # BJ (Beijing Stock Exchange): 43, 83, 87, 88, 92
    if first2 in ("43", "83", "87", "88", "92"):
        return True
    return False


# --------------------------------------------------------------------------- #
# Price loader — ALL stock_data CSVs, not just Xueqiu-traded
# --------------------------------------------------------------------------- #
def _load_broad_price_panel(
    stock_data_dir: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    files = glob.glob(os.path.join(stock_data_dir, "*.csv"))
    rows = []
    kept = 0
    dropped_filter = 0
    dropped_load = 0
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        if not _is_a_share_equity(sym):
            dropped_filter += 1
            continue
        try:
            # Read amount directly from CSV — the external liquidity_daily_v1.csv
            # doesn't cover the backfilled delisted names, so we fall back to
            # per-stock 成交额 (yuan) which is always present.
            df = pd.read_csv(fp, usecols=["日期", "收盘", "成交额"])
        except Exception:
            dropped_load += 1
            continue
        df.columns = ["date", "close", "amount_csv"]
        df["date"]       = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        df["close"]      = pd.to_numeric(df["close"], errors="coerce")
        df["amount_csv"] = pd.to_numeric(df["amount_csv"], errors="coerce")
        df = df.dropna(subset=["date", "close"])
        df = df[df["close"] > 0]
        # Keep an extra 40 calendar days past end for fwd_ret lookahead
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date + pd.Timedelta(days=40))]
        if df.empty:
            continue
        df["stock_symbol"] = sym
        rows.append(df[["date", "stock_symbol", "close", "amount_csv"]])
        kept += 1
    print(f"[broad] files: total={len(files)} kept={kept} "
          f"filter-reject={dropped_filter} load-fail={dropped_load}")
    if not rows:
        return pd.DataFrame(columns=["date", "stock_symbol", "close"])
    out = pd.concat(rows, ignore_index=True)
    return out.sort_values(["stock_symbol", "date"]).reset_index(drop=True)


def _add_forward_returns(px: pd.DataFrame, horizon_bdays: int = 10) -> pd.DataFrame:
    """
    Forward return over `horizon_bdays` TRADING-days per stock.

    Implementation note: the existing `add_forward_returns()` in
    `build_rebalance_momentum_panel.py` uses `.shift(-N)` over the row order,
    which only equals N business days if the panel has exactly one row per
    business day per stock. Since we load every stock's full CSV before
    dropping missing days, this assumption holds here too.
    """
    out = px.sort_values(["stock_symbol", "date"]).copy()
    out["fwd_ret_2w"] = out.groupby("stock_symbol")["close"].transform(
        lambda s: s.shift(-horizon_bdays) / s - 1.0
    )
    return out


# --------------------------------------------------------------------------- #
# Attachments: industry, amount, regime, tradability, liq_rank
# --------------------------------------------------------------------------- #
def _load_industry(path: str) -> pd.DataFrame:
    ind = pd.read_csv(path, encoding="utf-8-sig")
    # normalize symbol column name
    sym_col = "stock_symbol_standard" if "stock_symbol_standard" in ind.columns else "stock_symbol"
    ind = ind.rename(columns={sym_col: "stock_symbol"})
    ind["stock_symbol"] = ind["stock_symbol"].astype(str).str.upper()
    return ind[["stock_symbol", "industry_l2"]]


def _load_liquidity(path: str) -> pd.DataFrame:
    liq = pd.read_csv(path, encoding="utf-8-sig", usecols=["date", "stock_symbol", "amount"])
    liq["date"] = pd.to_datetime(liq["date"], errors="coerce").dt.normalize()
    liq["stock_symbol"] = liq["stock_symbol"].astype(str).str.upper()
    liq["amount"] = pd.to_numeric(liq["amount"], errors="coerce")
    return liq.dropna(subset=["date", "stock_symbol"])


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def build_broad_panel(
    start_date: str = "2015-01-01",
    end_date: str = "2025-12-31",
    fwd_horizon: int = 10,
    liq_keep_other: float = 0.60,
    liq_keep_up: float = 0.20,
    use_cache: bool = True,
) -> pd.DataFrame:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_tag = f"broad_panel_{start_date[:4]}_{end_date[:4]}_fwd{fwd_horizon}.pkl"
    cache_path = os.path.join(CACHE_DIR, cache_tag)
    if use_cache and os.path.exists(cache_path):
        print(f"[broad] loading cached panel: {cache_path}")
        return pd.read_pickle(cache_path)

    start_dt = pd.to_datetime(start_date).normalize()
    end_dt   = pd.to_datetime(end_date).normalize()

    print("[broad] loading prices from all stock_data CSVs …")
    stock_dir = os.path.join(ROOT, "data", "stock_data")
    px = _load_broad_price_panel(stock_dir, start_dt, end_dt)
    print(f"[broad] price rows: {len(px):,}  stocks: {px['stock_symbol'].nunique()}")

    print("[broad] computing forward returns …")
    px = _add_forward_returns(px, horizon_bdays=fwd_horizon)

    # Trim back to requested window (prices had +40d extra for fwd_ret)
    px = px[(px["date"] >= start_dt) & (px["date"] <= end_dt)].copy()

    print("[broad] attaching industry …")
    ind = _load_industry(os.path.join(ROOT, "research", "baseline_v1",
                                     "data_delivery", "industry_mapping_v2.csv"))
    px = px.merge(ind, on="stock_symbol", how="left")
    px["industry_l2"] = px["industry_l2"].fillna("其他")

    print("[broad] attaching amount …")
    liq = _load_liquidity(os.path.join(ROOT, "research", "baseline_v1",
                                       "data_delivery", "liquidity_daily_v1.csv"))
    px = px.merge(liq, on=["date", "stock_symbol"], how="left")
    # Fallback: use per-CSV 成交额 when external liquidity file is missing
    # (backfilled delisted names are not covered by liquidity_daily_v1.csv).
    px["amount"] = px["amount"].fillna(px["amount_csv"])
    px = px.drop(columns=["amount_csv"])

    print("[broad] attaching HS300 regime …")
    regime = _load_hs300(start_date, end_date)
    regime["date"] = pd.to_datetime(regime["date"]).dt.normalize()
    px = px.merge(regime, on="date", how="left")
    px["regime"] = px["regime"].fillna("震荡")

    print("[broad] attaching tradability (suspended / limit) …")
    trad = _load_tradability_from_stock_data(ROOT)
    px = px.merge(trad, on=["date", "stock_symbol"], how="left")
    px["is_suspended"] = px["is_suspended"].fillna(False)
    px["is_limit"]     = px["is_limit"].fillna(False)
    before = len(px)
    px = px[~px["is_suspended"] & ~px["is_limit"]].copy()
    print(f"[broad] tradability filter: {before:,} → {len(px):,} "
          f"({(before-len(px))/before*100:.1f}% dropped)")

    print("[broad] computing liq_rank_pct and applying dynamic liquidity filter …")
    px["liq_rank_pct"] = px.groupby("date")["amount"].transform(
        lambda s: s.rank(pct=True, method="first") if s.notna().any() else np.nan
    )
    keep_ratio = np.where(px["regime"] == "上涨", liq_keep_up, liq_keep_other)
    has_amt = px.groupby("date")["amount"].transform(lambda s: s.notna().any())
    keep_mask = np.where(has_amt, px["liq_rank_pct"] >= (1 - keep_ratio), True)
    before = len(px)
    px = px[keep_mask].copy()
    print(f"[broad] liquidity filter: {before:,} → {len(px):,} "
          f"({(before-len(px))/before*100:.1f}% dropped)")

    px = px.sort_values(["date", "stock_symbol"]).reset_index(drop=True)
    print(f"[broad] final panel: {len(px):,} rows, "
          f"{px['stock_symbol'].nunique()} stocks, "
          f"{px['date'].nunique()} dates")

    # Cache
    px.to_pickle(cache_path)
    print(f"[broad] cached → {cache_path}")
    return px


if __name__ == "__main__":
    panel = build_broad_panel(start_date="2015-01-01", end_date="2025-12-31")
    print(panel.head())
    print(panel.dtypes)
