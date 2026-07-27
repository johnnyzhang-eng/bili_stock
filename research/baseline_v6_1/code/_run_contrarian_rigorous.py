"""Rigorous contrarian signal test with randomized start dates."""
import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import numpy as np, pandas as pd

from research.baseline_v6_1.code.run_baseline_v6_v61_suite import _enrich_from_stock_data, _run_one
from research.baseline_v5.code.run_baseline_v5_with_costs import _prepare_panel_v5

print("Loading panel ...", flush=True)
t0 = time.time()
panel = _prepare_panel_v5()
panel = panel[(panel["date"] >= pd.Timestamp("2015-01-01")) & (panel["date"] <= pd.Timestamp("2025-12-31"))].copy()
panel, px_map = _enrich_from_stock_data(panel)
print(f"Panel loaded in {time.time()-t0:.0f}s", flush=True)

# Invert factor
panel_inv = panel.copy()
panel_inv["factor_z_raw"] = -panel_inv["factor_z_raw"]
panel_inv["factor_z_neu"] = -panel_inv["factor_z_neu"]
panel_inv["factor_z"] = -panel_inv["factor_z"]

BASE_REAL = dict(non_up_vol_q=0.50, dd_soft=-0.05, dd_mid=-0.07, dd_hard=-0.10,
                 choppy_loss_scale=1.0, choppy_loss_floor=0.0, go_flat_choppy=False,
                 use_srf=False, use_srf_v2=True, top_k=15,
                 buy_cost=0.0013, sell_cost=0.0043)
BASE_ZERO = {**BASE_REAL, "buy_cost": 0.0, "sell_cost": 0.0}


def run_random(panel_use, risk, hold_step, n_off, label):
    print(f"\n{label}", flush=True)
    calmars, rets, mdds = [], [], []
    for offset in range(n_off):
        p = panel_use.copy()
        dates = sorted(p["date"].unique())
        if offset < len(dates):
            p = p[p["date"].isin(dates[offset:])].copy()
        m, *_ = _run_one(p, px_map, hold_step=hold_step, liq_other=0.60,
                         cap_non_up=0.10, cap_up=0.20, with_takeprofit=True, risk_cfg=risk)
        c = m.get("calmar", np.nan); a = m.get("ann_ret", np.nan); d = m.get("mdd", np.nan)
        calmars.append(c); rets.append(a); mdds.append(d)
        print(f"  offset={offset}: calmar={c:.4f}, ann_ret={a*100:+.2f}%, mdd={d*100:.1f}%", flush=True)
    valid_c = [x for x in calmars if pd.notna(x)]
    valid_r = [x for x in rets if pd.notna(x)]
    valid_m = [x for x in mdds if pd.notna(x)]
    pos_pct = sum(1 for c in valid_c if c > 0) / len(valid_c) * 100 if valid_c else 0
    print(f"  SUMMARY:")
    print(f"    Calmar: mean={np.mean(valid_c):.4f}, median={np.median(valid_c):.4f}")
    print(f"    AnnRet: mean={np.mean(valid_r)*100:.2f}%, range=[{min(valid_r)*100:.1f}%, {max(valid_r)*100:.1f}%]")
    print(f"    MDD:    mean={np.mean(valid_m)*100:.1f}%, worst={min(valid_m)*100:.1f}%")
    print(f"    Positive: {pos_pct:.0f}%")


print("\n=== CONTRARIAN (inverted) signal — rigorous randomized test ===")

run_random(panel_inv, BASE_ZERO, 12, 12, "1. Inverted + SRF v2 top15, hold=12, ZERO cost (pure alpha)")
run_random(panel_inv, BASE_REAL, 12, 12, "2. Inverted + SRF v2 top15, hold=12, REAL cost (56bp RT)")
run_random(panel_inv, BASE_REAL, 21, 21, "3. Inverted + SRF v2 top15, hold=21 (monthly), REAL cost")
run_random(panel_inv, BASE_REAL, 10, 10, "4. Inverted + SRF v2 top15, hold=10 (biweekly), REAL cost")

print(f"\nTotal time: {time.time()-t0:.0f}s")
