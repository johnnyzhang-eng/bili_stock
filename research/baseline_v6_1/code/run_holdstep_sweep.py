"""
Hold-step turnover sweep — can the strategy survive at lower turnover?

Motivation (see docs/quant_strategy_lessons.md):
    zero-cost alpha   =  +5.3% / yr
    annual cost       =   9.8% / yr  (83% turnover × 56bp round-trip × 21 rebal)
    net               =  -0.5% / yr

The one remaining degree of freedom math still permits is TURNOVER reduction.
Each doubling of hold_step roughly halves the annualised cost. This script
measures whether raw alpha degrades faster than cost drops — the only
scenario in which this strategy category can be profitable.

Sweep: hold_step in {12, 21, 42, 63} (≈ biweekly, monthly, bi-monthly, quarterly)

For each step H:
  - Rebuild fwd_ret_2w as close.shift(-H) / close - 1  (horizon matches hold)
  - Run full baseline_v6_1 pipeline with hold_step = H
  - Annualise with ann_factor = 252 / H (not the hardcoded 21)
  - Record: turnover, raw Top30, trade_cost_rate, Top30_net, ann_ret, MDD, calmar

Output: research/baseline_v6_1/output/holdstep_sweep.csv
"""

import os
import sys
import time

import numpy as np
import pandas as pd


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)

from research.baseline_v5.code.run_baseline_v5_with_costs import _prepare_panel_v5
from research.baseline_v6_1.code.run_baseline_v6_v61_suite import (
    _enrich_from_stock_data,
    _run_one,
)
from research.baseline_v6_1.prod_config import PROD


def rebuild_fwd_ret(panel: pd.DataFrame, px_map: dict, horizon: int) -> pd.DataFrame:
    """Overwrite fwd_ret_2w with an H-day forward return so it matches hold_step."""
    frames = []
    for sym, px in px_map.items():
        d = px.sort_values("date").copy()
        d["stock_symbol"] = sym
        d["fwd_ret_new"] = d["close_sd"].shift(-horizon) / d["close_sd"] - 1.0
        frames.append(d[["date", "stock_symbol", "fwd_ret_new"]])
    if not frames:
        return panel
    fwd = pd.concat(frames, ignore_index=True)
    p = panel.copy()
    p["date"] = pd.to_datetime(p["date"]).dt.normalize()
    p["stock_symbol"] = p["stock_symbol"].astype(str).str.upper()
    fwd["date"] = pd.to_datetime(fwd["date"]).dt.normalize()
    fwd["stock_symbol"] = fwd["stock_symbol"].astype(str).str.upper()
    p = p.merge(fwd, on=["date", "stock_symbol"], how="left")
    p["fwd_ret_2w"] = p["fwd_ret_new"].combine_first(p["fwd_ret_2w"])
    p = p.drop(columns=["fwd_ret_new"])
    return p


def correct_annualised(ret: pd.DataFrame, hold_step: int) -> dict:
    """Recompute ann_ret / MDD / calmar with the correct periods-per-year."""
    if ret is None or ret.empty or "Top30_net" not in ret.columns:
        return {"ann_ret_corr": np.nan, "mdd_corr": np.nan, "calmar_corr": np.nan,
                "hit_ratio_corr": np.nan, "go_flat_ratio": np.nan}
    r = ret["Top30_net"].fillna(0.0)
    periods_per_year = 252.0 / hold_step
    avg = float(r.mean())
    ann = float((1.0 + avg) ** periods_per_year - 1.0)
    curve = (1.0 + r).cumprod()
    peak = curve.cummax()
    dd = curve / peak - 1.0
    mdd = float(dd.min())
    calmar = ann / abs(mdd) if mdd != 0 else float("nan")
    active = r[r != 0]
    hit = float((active > 0).mean()) if len(active) else float("nan")
    go_flat = float((r == 0).mean())
    return {
        "ann_ret_corr": ann, "mdd_corr": mdd, "calmar_corr": calmar,
        "hit_ratio_corr": hit, "go_flat_ratio": go_flat,
    }


def main():
    t0 = time.time()
    print("[1/2] Loading panel + px_map (one-time)...")
    panel_base = _prepare_panel_v5()
    panel_base = panel_base[(panel_base["date"] >= pd.Timestamp("2015-01-01"))
                            & (panel_base["date"] <= pd.Timestamp("2025-12-31"))].copy()
    panel_base, px_map = _enrich_from_stock_data(panel_base)
    print(f"      panel rows={len(panel_base):,}, symbols={len(px_map):,}, "
          f"elapsed={time.time()-t0:.1f}s")

    hold_steps = [12, 21, 42, 63]
    rows = []
    for H in hold_steps:
        print(f"[2/2] hold_step={H} (≈ {252/H:.1f} rebalances/yr)...")
        t1 = time.time()
        p = rebuild_fwd_ret(panel_base, px_map, horizon=H)
        m, ret, _, _, _, _ = _run_one(
            panel=p,
            px_map=px_map,
            hold_step=H,
            liq_other=PROD["liq_other"],
            cap_non_up=PROD["cap_non_up"],
            cap_up=PROD["cap_up"],
            with_takeprofit=PROD["with_takeprofit"],
            risk_cfg=PROD["risk_cfg"],
        )
        corr = correct_annualised(ret, H)

        turnover = float(ret["one_way_turnover"].mean()) if "one_way_turnover" in ret.columns else np.nan
        cost_rate = float(ret["trade_cost_rate"].mean()) if "trade_cost_rate" in ret.columns else np.nan
        raw_top = float(ret["Top30"].mean()) if "Top30" in ret.columns else np.nan
        net_top = float(ret["Top30_net"].mean()) if "Top30_net" in ret.columns else np.nan
        n_periods = int(len(ret)) if ret is not None else 0
        rebalances_per_year = 252.0 / H

        rows.append({
            "hold_step_bdays": H,
            "rebalances_per_year": round(rebalances_per_year, 1),
            "n_periods": n_periods,
            "avg_turnover_per_period": round(turnover, 4) if pd.notna(turnover) else np.nan,
            "avg_cost_per_period_bp": round(cost_rate * 10000, 2) if pd.notna(cost_rate) else np.nan,
            "annual_cost_pct": round(cost_rate * rebalances_per_year * 100, 2) if pd.notna(cost_rate) else np.nan,
            "raw_top30_mean_per_period_pct": round(raw_top * 100, 3) if pd.notna(raw_top) else np.nan,
            "raw_top30_annual_pct": round(((1 + raw_top) ** rebalances_per_year - 1) * 100, 2) if pd.notna(raw_top) else np.nan,
            "net_top30_mean_per_period_pct": round(net_top * 100, 3) if pd.notna(net_top) else np.nan,
            "net_ann_ret_pct": round(corr["ann_ret_corr"] * 100, 2) if pd.notna(corr["ann_ret_corr"]) else np.nan,
            "mdd_pct": round(corr["mdd_corr"] * 100, 2) if pd.notna(corr["mdd_corr"]) else np.nan,
            "calmar": round(corr["calmar_corr"], 3) if pd.notna(corr["calmar_corr"]) else np.nan,
            "hit_ratio_pct": round(corr["hit_ratio_corr"] * 100, 1) if pd.notna(corr["hit_ratio_corr"]) else np.nan,
            "go_flat_ratio_pct": round(corr["go_flat_ratio"] * 100, 1),
            "reported_ann_ret_pct_WRONG": round(m.get("ann_ret", np.nan) * 100, 2) if pd.notna(m.get("ann_ret", np.nan)) else np.nan,
        })
        print(f"      turnover={turnover*100:.1f}%, ann_cost={cost_rate*rebalances_per_year*100:.2f}%, "
              f"net_ann={corr['ann_ret_corr']*100:.2f}%, calmar={corr['calmar_corr']:.3f}, "
              f"mdd={corr['mdd_corr']*100:.1f}%, elapsed={time.time()-t1:.1f}s")

    df = pd.DataFrame(rows)
    out_path = os.path.join(ROOT, "research", "baseline_v6_1", "output", "holdstep_sweep.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nSweep complete in {time.time()-t0:.1f}s")
    print(f"Results → {out_path}\n")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
