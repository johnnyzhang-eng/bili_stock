"""Rerun IC + sub-period + random control using forward_returns_v2.csv (already built)."""
import os
import time

import numpy as np
import pandas as pd
from scipy import stats

OUT = '/Users/johnnyzhang/jz_code/bili_stock/research/cube_attention_delta/output'
TRAIN_END = '2023-12-31'  # daily_k starts 2022-01-01; split 2022-2023 train / 2024+ test

print("=== Loading ===")
factors = {}
for name in ('delta', 'momentum', 'accel'):
    df = pd.read_csv(f'{OUT}/factor_{name}.csv', index_col=0)
    df.index = pd.to_datetime(df.index)
    # Deduplicate week index (keep first)
    df = df[~df.index.duplicated(keep='first')]
    factors[name] = df

fwd_ret = pd.read_csv(f'{OUT}/forward_returns_v2.csv', index_col=0)
fwd_ret.index = pd.to_datetime(fwd_ret.index)
fwd_ret = fwd_ret[~fwd_ret.index.duplicated(keep='first')]

print(f"weeks: {len(fwd_ret)} (after dedup), stocks: {fwd_ret.shape[1]}")
print(f"fwd non-null: {fwd_ret.notna().sum().sum()/fwd_ret.size*100:.1f}%")

def weekly_ic(factor_df, fwd_df):
    common = factor_df.index.intersection(fwd_df.index)
    ics = []
    for wk in common:
        f = factor_df.loc[wk]
        r = fwd_df.loc[wk]
        # Both should be Series after dedup
        mask = f.notna() & r.notna()
        n = int(mask.sum())
        if n < 30:
            continue
        ic, _ = stats.spearmanr(f[mask], r[mask])
        ics.append({'week': wk, 'ic': ic, 'n': n})
    return pd.DataFrame(ics)

print("\n=== IC by factor x direction ===")
ic_results = {}
summary_rows = []
for fname in ('delta', 'momentum', 'accel'):
    for direction in ('long', 'short'):
        fac = factors[fname] if direction == 'long' else -factors[fname]
        ic_df = weekly_ic(fac, fwd_ret)
        key = f'{fname}_{direction}'
        ic_results[key] = ic_df

        train_mask = ic_df['week'] <= TRAIN_END
        test_mask = ic_df['week'] > TRAIN_END
        train_ic = ic_df.loc[train_mask, 'ic'].mean()
        test_ic = ic_df.loc[test_mask, 'ic'].mean()
        n_test = int(test_mask.sum())
        test_std = ic_df.loc[test_mask, 'ic'].std()
        test_t = test_ic / (test_std / np.sqrt(n_test)) if test_std > 0 else np.nan

        # Whole-period t
        n_all = len(ic_df)
        all_std = ic_df['ic'].std()
        all_t = ic_df['ic'].mean() / (all_std / np.sqrt(n_all)) if all_std > 0 else np.nan

        summary_rows.append({
            'factor': fname, 'direction': direction,
            'n_weeks': n_all, 'mean_ic': ic_df['ic'].mean(),
            'mean_n_stocks': ic_df['n'].mean(),
            'all_t': all_t,
            'train_ic': train_ic, 'train_weeks': int(train_mask.sum()),
            'test_ic': test_ic, 'test_weeks': n_test, 'test_t': test_t,
        })
        print(f"  {key}: mean_ic={ic_df['ic'].mean():+.4f} (t={all_t:+.2f}, n_wk={n_all}, n_stk={ic_df['n'].mean():.0f}); train={train_ic:+.4f} | test={test_ic:+.4f} (t={test_t:+.2f})")

summary_df = pd.DataFrame(summary_rows)
summary_df.to_csv(f'{OUT}/ic_summary_v2.csv', index=False)

# Save weekly IC tables
for key, df in ic_results.items():
    df.to_csv(f'{OUT}/ic_{key}_v2.csv', index=False)

print("\n=== Sub-period (yearly) IC ===")
sub_rows = []
for key, ic_df in ic_results.items():
    ic_df2 = ic_df.copy()
    ic_df2['year'] = pd.to_datetime(ic_df2['week']).dt.year
    for year, g in ic_df2.groupby('year'):
        sub_rows.append({
            'factor_direction': key, 'year': int(year),
            'n_weeks': len(g), 'mean_ic': g['ic'].mean(), 'std_ic': g['ic'].std(),
            't_stat': g['ic'].mean() / (g['ic'].std() / np.sqrt(len(g))) if g['ic'].std() > 0 else np.nan,
        })
sub_df = pd.DataFrame(sub_rows)
sub_df.to_csv(f'{OUT}/sub_period_ic_v2.csv', index=False)

# Print focus on momentum_short and momentum_long
for focus in ('momentum_short', 'momentum_long'):
    print(f"\n{focus} yearly IC:")
    for _, r in sub_df[sub_df.factor_direction == focus].iterrows():
        print(f"  {r.year}: IC={r.mean_ic:+.4f}, t={r.t_stat:+.2f}, n={r.n_weeks}")

print("\n=== Random control (30 shuffles per combo) ===")
rng = np.random.default_rng(42)
N_RANDOM = 30

rc_rows = []
t_rc = time.time()
for fname in ('delta', 'momentum', 'accel'):
    for direction in ('long', 'short'):
        key = f'{fname}_{direction}'
        sig_ic = float(summary_df[(summary_df.factor == fname) & (summary_df.direction == direction)]['mean_ic'].iloc[0])

        fac_base = factors[fname] if direction == 'long' else -factors[fname]
        fac_vals = fac_base.values.copy()

        rc_ics = []
        for run in range(N_RANDOM):
            # Shuffle each row (week) in-place; do it on numpy for speed
            shuf = fac_vals.copy()
            for i in range(shuf.shape[0]):
                rng.shuffle(shuf[i])
            shuf_df = pd.DataFrame(shuf, index=fac_base.index, columns=fac_base.columns)
            ic_df = weekly_ic(shuf_df, fwd_ret)
            rc_ics.append(ic_df['ic'].mean())

        rc_mean = float(np.mean(rc_ics))
        rc_std = float(np.std(rc_ics))
        delta = sig_ic - rc_mean
        delta_t = delta / rc_std if rc_std > 0 else np.nan
        rc_rows.append({
            'factor_direction': key, 'signal_ic': sig_ic,
            'random_mean_ic': rc_mean, 'random_std_ic': rc_std,
            'delta': delta, 'delta_t': delta_t, 'n_random': N_RANDOM,
        })
        print(f"  {key}: signal={sig_ic:+.4f}, random={rc_mean:+.4f}±{rc_std:.4f}, delta_t={delta_t:+.2f} ({time.time()-t_rc:.0f}s)")

rc_df = pd.DataFrame(rc_rows)
rc_df.to_csv(f'{OUT}/random_control_v2.csv', index=False)

print("\n=== Final ===")
final = summary_df.copy()
final['key'] = final['factor'] + '_' + final['direction']
final = final.merge(rc_df, left_on='key', right_on='factor_direction', how='left')
print(final[['factor', 'direction', 'mean_ic', 'all_t', 'train_ic', 'test_ic', 'test_t', 'random_mean_ic', 'delta', 'delta_t']].to_string(index=False))
final.to_csv(f'{OUT}/final_summary_v2.csv', index=False)
print("\nDONE")
