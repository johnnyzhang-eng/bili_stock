"""Long-only top-decile backtest for momentum_long.

Question: with IC ~ 0.0037 weekly + 56bp round-trip cost, is there tradeable alpha?

Strategy:
  - Each week, pick top 10% (decile 1) of stocks by momentum factor
  - Hold 1 week, full rebalance
  - 56bp round-trip cost per turn

Output: cumulative returns vs random control (same N, randomly picked)
"""
import os

import numpy as np
import pandas as pd

OUT = '/Users/johnnyzhang/jz_code/bili_stock/research/cube_attention_delta/output'
TRAIN_END = '2023-12-31'
TOP_PCT = 0.10
COST_RT = 0.0056

# Load
fac = pd.read_csv(f'{OUT}/factor_momentum.csv', index_col=0)
fac.index = pd.to_datetime(fac.index)
fac = fac[~fac.index.duplicated(keep='first')]

fwd = pd.read_csv(f'{OUT}/forward_returns_v2.csv', index_col=0)
fwd.index = pd.to_datetime(fwd.index)
fwd = fwd[~fwd.index.duplicated(keep='first')]

# Common weeks where both factor and return exist
common = fac.index.intersection(fwd.index)
fac = fac.loc[common]
fwd = fwd.loc[common]

# Drop weeks with no return data
weeks_with_data = fwd.notna().sum(axis=1) >= 100
fac = fac.loc[weeks_with_data]
fwd = fwd.loc[weeks_with_data]

print(f"Backtest weeks: {len(fac)} ({fac.index.min().date()} ~ {fac.index.max().date()})")

# Run per-week
rng = np.random.default_rng(42)
records = []
for wk in fac.index:
    f_row = fac.loc[wk]
    r_row = fwd.loc[wk]
    mask = f_row.notna() & r_row.notna()
    if mask.sum() < 50:
        continue

    # Pick top decile by factor
    n_pick = max(int(mask.sum() * TOP_PCT), 5)
    top_stocks = f_row[mask].nlargest(n_pick).index
    sig_ret = r_row[top_stocks].mean()

    # Random control: pick n_pick random stocks from same pool
    eligible = f_row[mask].index.tolist()
    rand_stocks = rng.choice(eligible, size=n_pick, replace=False)
    rand_ret = r_row[rand_stocks].mean()

    # Apply round-trip cost (assumes 100% turnover weekly — conservative)
    sig_ret_net = sig_ret - COST_RT
    rand_ret_net = rand_ret - COST_RT

    records.append({
        'week': wk, 'n_pick': n_pick,
        'sig_ret_gross': sig_ret, 'sig_ret_net': sig_ret_net,
        'rand_ret_gross': rand_ret, 'rand_ret_net': rand_ret_net,
    })

bt = pd.DataFrame(records)
bt.to_csv(f'{OUT}/long_only_bt_v2.csv', index=False)

# Cumulative
bt['sig_cum_gross'] = (1 + bt['sig_ret_gross']).cumprod()
bt['sig_cum_net'] = (1 + bt['sig_ret_net']).cumprod()
bt['rand_cum_gross'] = (1 + bt['rand_ret_gross']).cumprod()
bt['rand_cum_net'] = (1 + bt['rand_ret_net']).cumprod()

def perf(returns, label):
    weeks = len(returns)
    cagr = (1 + returns).prod() ** (52 / weeks) - 1
    vol = returns.std() * np.sqrt(52)
    sharpe = cagr / vol if vol > 0 else np.nan
    win_rate = (returns > 0).mean()
    print(f"  {label}: CAGR={cagr*100:+.2f}%, vol={vol*100:.1f}%, sharpe={sharpe:+.2f}, win={win_rate:.1%}")
    return cagr, vol, sharpe, win_rate

print("\n=== Whole-period performance ===")
perf(bt['sig_ret_gross'], 'Signal (gross)')
perf(bt['sig_ret_net'], 'Signal (after 56bp cost)')
perf(bt['rand_ret_gross'], 'Random (gross)')
perf(bt['rand_ret_net'], 'Random (after cost)')

print("\n=== Train 2022-2023 ===")
train = bt[bt.week <= TRAIN_END]
perf(train['sig_ret_gross'], 'Signal (gross)')
perf(train['sig_ret_net'], 'Signal (net)')
perf(train['rand_ret_gross'], 'Random (gross)')

print("\n=== Test 2024+ ===")
test = bt[bt.week > TRAIN_END]
perf(test['sig_ret_gross'], 'Signal (gross)')
perf(test['sig_ret_net'], 'Signal (net)')
perf(test['rand_ret_gross'], 'Random (gross)')

# Excess gross
sig_minus_rand_gross = bt['sig_ret_gross'] - bt['rand_ret_gross']
sig_minus_rand_net = bt['sig_ret_net'] - bt['rand_ret_net']
print("\n=== Excess (Signal - Random), gross weekly avg ===")
print(f"  Whole: {sig_minus_rand_gross.mean()*100:+.3f}% (annualized {sig_minus_rand_gross.mean()*52*100:+.2f}%)")
print(f"  Train: {sig_minus_rand_gross[bt.week<=TRAIN_END].mean()*100:+.3f}%")
print(f"  Test: {sig_minus_rand_gross[bt.week>TRAIN_END].mean()*100:+.3f}%")
print(f"\n  Net cost is symmetric so excess net = excess gross")
