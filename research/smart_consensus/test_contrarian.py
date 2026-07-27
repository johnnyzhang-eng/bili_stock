"""Smart consensus is CONTRARIAN. Test:
1. Long bottom decile (low smart consensus = avoided by smart money but maybe oversold?)
2. Avoid top decile filter
3. Short-side (-signal) direction
"""
import os
import numpy as np
import pandas as pd
from scipy import stats

ROOT = '/Users/johnnyzhang/jz_code/bili_stock'
OUT = f'{ROOT}/research/smart_consensus/output'

sig = pd.read_csv(f'{OUT}/smart_consensus_ffill.csv', index_col=0)
sig.index = pd.to_datetime(sig.index)
sig = sig[~sig.index.duplicated(keep='first')]

fwd = pd.read_csv(f'{ROOT}/research/cube_attention_delta/output/forward_returns_v2.csv', index_col=0)
fwd.index = pd.to_datetime(fwd.index)
fwd = fwd[~fwd.index.duplicated(keep='first')]

common_weeks = sig.index.intersection(fwd.index)
common_stocks = sig.columns.intersection(fwd.columns)
sig = sig.loc[common_weeks, common_stocks]
ret = fwd.loc[common_weeks, common_stocks]

# Strategy: pick TOP and BOTTOM decile by signal, compare returns
COST_RT = 0.0056
rng_bt = np.random.default_rng(43)

records = []
for wk in common_weeks:
    f_row = sig.loc[wk]
    r_row = ret.loc[wk]
    # Distinguish: stocks WITH smart cube exposure (f > 0) vs without (f == 0)
    in_pool = f_row > 0  # has any smart cube holding it
    mask = r_row.notna()
    eligible_in_pool = (in_pool & mask)
    eligible_out_pool = (~in_pool & mask)

    if eligible_in_pool.sum() < 50 or eligible_out_pool.sum() < 100:
        continue

    n_top = max(int(eligible_in_pool.sum() * 0.1), 5)

    # Top decile: stocks with HIGHEST smart consensus
    top = f_row[eligible_in_pool].nlargest(n_top).index
    top_ret = r_row[top].mean()

    # Bottom decile of IN-POOL: lowest smart consensus among held stocks (oversold by smart?)
    bot = f_row[eligible_in_pool].nsmallest(n_top).index
    bot_ret = r_row[bot].mean()

    # OUT-OF-POOL: stocks no smart cube holds (the "ignored" universe)
    out_pool_stocks = f_row[eligible_out_pool].index
    rand_out_idx = rng_bt.choice(out_pool_stocks, size=min(n_top, len(out_pool_stocks)), replace=False)
    out_ret = r_row[rand_out_idx].mean()

    # All-universe random
    all_idx = rng_bt.choice(r_row[mask].index, size=n_top, replace=False)
    all_ret = r_row[all_idx].mean()

    records.append({
        'week': wk, 'n_pick': n_top,
        'top_decile_smart': top_ret,
        'bot_decile_smart': bot_ret,
        'no_smart_random': out_ret,
        'all_random': all_ret,
    })

bt = pd.DataFrame(records)
bt.to_csv(f'{OUT}/contrarian_test.csv', index=False)

def perf(returns, label):
    weeks = len(returns)
    cagr = (1 + returns).prod() ** (52 / weeks) - 1
    vol = returns.std() * np.sqrt(52)
    sharpe = cagr / vol if vol > 0 else np.nan
    win = (returns > 0).mean()
    return cagr, vol, sharpe, win

print(f"{'Strategy':25} {'CAGR':>10} {'Vol':>8} {'Sharpe':>8} {'Win%':>6}")
for col in ['top_decile_smart', 'bot_decile_smart', 'no_smart_random', 'all_random']:
    c, v, s, w = perf(bt[col], col)
    print(f"{col:25} {c*100:+9.2f}% {v*100:+7.1f}% {s:+8.2f} {w*100:5.1f}%")
    c, v, s, w = perf(bt[col] - COST_RT, col + '_net')
    print(f"  ↳ net 56bp        {c*100:+9.2f}% {v*100:+7.1f}% {s:+8.2f} {w*100:5.1f}%")

# Long-short
ls = bt['bot_decile_smart'] - bt['top_decile_smart']
print(f"\nLong-Short (bot - top):")
print(f"  Mean weekly: {ls.mean()*100:+.4f}% (ann {ls.mean()*52*100:+.2f}%)")
print(f"  t-stat: {ls.mean() / (ls.std() / np.sqrt(len(ls))):+.2f}")

# Train / Test
print("\n=== Train (2022-2023) ===")
train = bt[bt.week <= '2023-12-31']
for col in ['top_decile_smart', 'bot_decile_smart', 'no_smart_random', 'all_random']:
    c, v, s, w = perf(train[col], col)
    print(f"  {col:25} CAGR={c*100:+.2f}%, Sharpe={s:+.2f}")

print("\n=== Test (2024+) ===")
test = bt[bt.week > '2023-12-31']
for col in ['top_decile_smart', 'bot_decile_smart', 'no_smart_random', 'all_random']:
    c, v, s, w = perf(test[col], col)
    print(f"  {col:25} CAGR={c*100:+.2f}%, Sharpe={s:+.2f}")

# Avoid-top filter: simulate "remove top decile smart-consensus stocks from the universe"
print("\n=== Avoid-Top-Decile filter (regular pool minus top-decile-smart) ===")
records2 = []
for wk in common_weeks:
    f_row = sig.loc[wk]
    r_row = ret.loc[wk]
    in_pool = f_row > 0
    mask = r_row.notna()
    if (in_pool & mask).sum() < 50:
        continue
    n_top = max(int((in_pool & mask).sum() * 0.1), 5)
    top_smart = f_row[in_pool & mask].nlargest(n_top).index
    # Universe minus top-smart
    avoid_top_universe = r_row[mask].drop(top_smart, errors='ignore')
    if len(avoid_top_universe) < n_top:
        continue
    rand_idx = rng_bt.choice(avoid_top_universe.index, size=n_top, replace=False)
    filtered_ret = r_row[rand_idx].mean()
    # Baseline all-random
    all_idx = rng_bt.choice(r_row[mask].index, size=n_top, replace=False)
    base_ret = r_row[all_idx].mean()
    records2.append({'week': wk, 'avoid_top_random': filtered_ret, 'baseline': base_ret})

bt2 = pd.DataFrame(records2)
c, v, s, w = perf(bt2['avoid_top_random'], 'avoid_top')
print(f"  Random from universe-minus-top-smart: CAGR={c*100:+.2f}%, Sharpe={s:+.2f}")
c, v, s, w = perf(bt2['baseline'], 'baseline')
print(f"  Random from full universe:            CAGR={c*100:+.2f}%, Sharpe={s:+.2f}")
diff = bt2['avoid_top_random'] - bt2['baseline']
print(f"  Excess weekly: {diff.mean()*100:+.4f}% (ann {diff.mean()*52*100:+.2f}%), t={diff.mean()/(diff.std()/np.sqrt(len(diff))):+.2f}")
