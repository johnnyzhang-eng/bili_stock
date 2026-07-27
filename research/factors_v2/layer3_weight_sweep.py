"""快速扫描 Layer 3 的 (W_FUND, W_SENT, W_VOL) 组合。"""
import os
import sys
import warnings

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path: sys.path.insert(0, ROOT)

import research.factors_v2.layer3_full_stack as L3

# 预加载一次
print("预加载..."); sys.stdout.flush()
fund = L3.load_fundamentals()
prices = L3.load_prices()
sent = L3.load_sentiment()

# 预计算 pivot 一次
prices = prices.sort_values(["code","date"])
wide_close = prices.pivot(index="date", columns="code", values="close")
wide_amt   = prices.pivot(index="date", columns="code", values="amount")
log_ret = np.log(wide_close / wide_close.shift(1))
wide_vol = log_ret.rolling(60, min_periods=40).std()
wide_sent = sent.pivot_table(index="date", columns="code", values="factor_z", aggfunc="last")
print("预加载完成\n")

dates = wide_close.index
dates = dates[dates >= pd.Timestamp(L3.START)]
rebal_dates = [dates[i] for i in range(0, len(dates), L3.HOLD_STEP)]


def run(w_fund, w_sent, w_vol, top_k=20):
    L3.W_FUND = w_fund; L3.W_SENT = w_sent; L3.W_VOL = w_vol
    rows = []
    prev = None
    for i, t in enumerate(rebal_dates):
        if i+1 >= len(rebal_dates): break
        t_next = rebal_dates[i+1]
        avg_amt = wide_amt.loc[:t].tail(20).mean()
        vol60 = wide_vol.loc[t] if t in wide_vol.index else pd.Series(dtype=float)
        sent_row = wide_sent.loc[:t].ffill().iloc[-1] if len(wide_sent.loc[:t])>0 else pd.Series(dtype=float)
        snap = L3.get_fund_snapshot(fund, t)
        if len(snap) == 0: continue
        hold = L3.pick_topk(snap, avg_amt, vol60, sent_row, top_k)
        if len(hold) < 5: continue
        p_t = wide_close.loc[t, hold]
        p_next = wide_close.loc[t_next, hold]
        r = (p_next/p_t - 1).replace([np.inf,-np.inf], np.nan).dropna()
        if len(r)==0: continue
        pr = float(r.mean())
        turn = 1.0 if prev is None else len(set(hold)-prev)/len(hold)
        cost = turn*(L3.BUY_BP+L3.SELL_BP)/10000
        rows.append({"date":t,"pr":pr,"pr_net":pr-cost,"turn":turn})
        prev = set(hold)

    log = pd.DataFrame(rows)
    r = np.clip(log["pr_net"].values, -0.99, None)
    eq = np.cumprod(1+r)
    years = (log["date"].iloc[-1] - log["date"].iloc[0]).days / 365.25
    cagr = eq[-1]**(1/years) - 1
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    vol = log["pr_net"].std() * np.sqrt(252/L3.HOLD_STEP)
    sharpe = (cagr - 0.02) / vol
    calmar = cagr / abs(mdd) if mdd<0 else np.nan
    return cagr, mdd, sharpe, calmar, log["turn"].mean()


print(f"{'WFund/WSent/WVol':<18s} {'CAGR':>7s} {'MDD':>7s} {'Sharpe':>7s} {'Calmar':>7s} {'换手':>5s}")
print("-"*58)
configs = [
    # (fund, sent, vol)
    (1.0, 0.0, 0.0),   # baseline Layer 1
    (0.4, 0.3, 0.3),   # Layer 3 default
    (0.3, 0.3, 0.4),
    (0.2, 0.2, 0.6),
    (0.3, 0.2, 0.5),
    (0.4, 0.1, 0.5),
    (0.5, 0.2, 0.3),
    (0.2, 0.4, 0.4),
    (0.1, 0.1, 0.8),   # vol-dominant
    (0.0, 0.0, 1.0),   # pure low-vol within fund pool
    (0.0, 1.0, 0.0),   # pure sentiment reverse within pool
]
results = []
for wf, ws, wv in configs:
    cagr, mdd, sh, cal, tu = run(wf, ws, wv)
    print(f"  {wf:.1f}/{ws:.1f}/{wv:.1f}         "
          f"{cagr:>+7.2%} {mdd:>+7.2%} {sh:>7.2f} {cal:>7.2f} {tu*100:>4.0f}%")
    results.append({"w_fund":wf,"w_sent":ws,"w_vol":wv,
                    "cagr":cagr,"mdd":mdd,"sharpe":sh,"calmar":cal,"turn":tu})

print("\n对比:")
print("  512890:              +12.06%  -11.43%    0.56    1.05")

pd.DataFrame(results).to_csv(
    os.path.join(ROOT, "research", "factors_v2", "output", "layer3_weight_sweep.csv"),
    index=False, encoding="utf-8-sig")
