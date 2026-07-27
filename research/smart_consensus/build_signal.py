"""
Alpha A1 — Smart Cube Weight-Weighted Consensus

Thesis: previous cube_count signals treated all 926 cubes equally.
The 4-year baseline alpha (5.3% raw / cost-adj negative) was because dumb
cubes diluted the signal from the 109 smart ones.

This signal uses TWO weights stacked:
  1. Cube quality weight: each cube's contribution is weighted by its
     annualized_gain_rate (skill score), clipped + log-scaled to avoid
     domination by ZH085468 etc. simulated-portfolio outliers.
  2. Position size weight: each cube's contribution to a stock signal is
     proportional to that stock's weight in the cube's portfolio, not
     binary 'do they hold it or not'.

Final signal:
  signal(stock, week) = SUM over smart_cubes [ skill_weight(cube) * portfolio_weight(cube, stock, week) ]

Then cross-sectional rank within each week.

Test against forward_returns_v2 (2022-2026 already available).
"""
import json
import os
import sqlite3
import glob
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

ROOT = '/Users/johnnyzhang/jz_code/bili_stock'
REB_DIR = f'{ROOT}/research/attention_orj/cache/rebalancing'
PROFILE = f'{ROOT}/research/trader_profile/output/trader_profile.csv'
FWD = f'{ROOT}/research/cube_attention_delta/output/forward_returns_v2.csv'
OUT = f'{ROOT}/research/smart_consensus/output'
DAILY_DIRS = [
    f'{ROOT}/research/attention_orj/cache/daily_k_pre2022',
    f'{ROOT}/research/attention_orj/cache/daily_k',
]
os.makedirs(OUT, exist_ok=True)


def load_trading_calendar():
    """Load the union A-share trading calendar from local daily_k caches."""
    dates = set()
    for daily_dir in DAILY_DIRS:
        if not os.path.isdir(daily_dir):
            continue
        for path in glob.glob(f'{daily_dir}/*.csv'):
            try:
                df = pd.read_csv(path, usecols=['date'])
            except Exception:
                continue
            dates.update(pd.to_datetime(df['date'], errors='coerce').dropna().dt.normalize())
    if not dates:
        raise RuntimeError('No trading dates found in daily_k caches')
    return pd.DatetimeIndex(sorted(dates))


def first_trading_day_after(ts, trading_calendar):
    """Strictly next trading day after an event timestamp."""
    event_day = pd.Timestamp(ts).normalize()
    pos = trading_calendar.searchsorted(event_day, side='right')
    if pos >= len(trading_calendar):
        return pd.NaT
    return trading_calendar[pos]

# ─── Step 1: Load rolling skill matrix (B1 fix, 2026-05-23 audit) ────────────
# Previously this step filtered cubes once via trader_profile.csv's 2026 snapshot
# `annualized_gain_rate` field. Codex's audit (CRITICAL/INVALIDATES) showed this
# makes the smart-cube identity itself forward-looking: the 96 selected cubes are
# those whose CUMULATIVE return through 2026 passed the 25%-200% gate, so they are
# survivors selected on the backtest's own outcome window.
#
# Fix (Codex Q2 primary path): use cube_nav_history.py's rolling 12-month ann_gain
# matrix, indexed by Monday-anchored week. At each event's bucket-start Monday we
# look up the cube's trailing 52-week ann_gain. If valid (≥52 weeks of NAV history)
# AND in (25%, 200%], the cube is "smart" for that bucket and its event contributes.
# Skill weight is recomputed per bucket so cubes only compete against other cubes
# that pass the gate at the same time.
#
# Filters dropped vs the snapshot version: `followers_count` (no time series
# available) and `n_user_events ≥ 30` (effectively enforced by the rolling 52w
# requirement). Sensitivity check with snapshot followers/event filters can be
# layered on top later; primary verdict does not depend on them.
print("=== Step 1: rolling skill load ===")
ROLLING_ANN = f'{OUT}/rolling_ann_gain.csv'
rolling_ann = pd.read_csv(ROLLING_ANN, index_col=0)
rolling_ann.index = pd.to_datetime(rolling_ann.index)
print(f"rolling_ann_gain shape: {rolling_ann.shape} "
      f"(weeks {rolling_ann.index.min().date()} ~ {rolling_ann.index.max().date()}, "
      f"{rolling_ann.shape[1]} cubes)")

SKILL_MIN, SKILL_MAX = 25.0, 200.0  # smart filter range (percent)

# ─── Step 2: Extract weekly holdings panel; per-bucket smart filter ──────────
print("\n=== Step 2: build holdings panel (per-bucket smart filter) ===")
trading_calendar = load_trading_calendar()
print(f"Trading calendar: {len(trading_calendar)} days ({trading_calendar.min().date()} ~ {trading_calendar.max().date()})")
all_cube_symbols = set(rolling_ann.columns)

# holdings field is empty. Reconstruct cube portfolio state from rebalancing_histories.
# For each cube: maintain a running dict of {stock: target_weight} and snapshot after each event.
# B1: per-event filter by rolling_ann_gain at the event's bucket-start Monday.
NON_STOCK_PREFIXES = (
    # ETF / LOF
    '510', '511', '512', '513', '515', '516', '518', '588', '159', '160',
    # CB (可转债) — SH 1xxxxx via 110/113/118, SZ 12xxxx via 123/127/128
    '110', '113', '118', '123', '127', '128',
)

records = []
bucket_latest_event = {}
n_event_total = 0
n_event_kept = 0
n_event_skipped_no_skill_row = 0
n_event_skipped_unskilled = 0

for sym in all_cube_symbols:
    path = f'{REB_DIR}/{sym}.json'
    if not os.path.exists(path):
        continue
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        continue
    user_events = [e for e in data if e.get('status') == 'success' and e.get('category') == 'user_rebalancing']
    user_events.sort(key=lambda e: e.get('created_at', 0))

    holdings = {}  # stock -> current target_weight
    for evt in user_events:
        ts = evt.get('created_at', 0)
        if not ts:
            continue
        # Apply rebalancing_histories to update state
        for h in evt.get('rebalancing_histories') or []:
            stock = (h.get('stock_symbol') or '').upper()
            if not stock:
                continue
            tw = h.get('target_weight') or 0
            if tw > 0:
                holdings[stock] = tw
            else:
                holdings.pop(stock, None)
        n_event_total += 1
        # Snapshot the cube's state at this timestamp
        dt = datetime.fromtimestamp(ts / 1000)
        # B2 fix: do not backdate events to Monday of the same week. Build a
        # Monday-Sunday event bucket, stamp the whole bucket to the first tradable
        # day after its latest event (resolved below in the signal_date mapping).
        bucket = pd.Timestamp(dt).to_period('W-SUN').start_time.normalize()

        # B1 filter: rolling 12-month ann_gain at bucket-start Monday must be valid
        # AND inside (SKILL_MIN, SKILL_MAX]. NaN (cube has < 52 weeks NAV) and out-of-
        # range cubes are skipped at this bucket; the same cube may qualify or fail
        # at different buckets, which is the whole point of the ex-ante fix.
        if bucket not in rolling_ann.index:
            n_event_skipped_no_skill_row += 1
            continue
        ann = rolling_ann.at[bucket, sym] if sym in rolling_ann.columns else float('nan')
        if not (pd.notna(ann) and SKILL_MIN < ann <= SKILL_MAX):
            n_event_skipped_unskilled += 1
            continue

        prev_latest = bucket_latest_event.get(bucket)
        if prev_latest is None or pd.Timestamp(dt) > prev_latest:
            bucket_latest_event[bucket] = pd.Timestamp(dt)

        for stock, w in holdings.items():
            if not stock.startswith(('SZ', 'SH')) or len(stock) != 8:
                continue
            code6 = stock[2:]
            if code6.startswith(NON_STOCK_PREFIXES):
                continue
            records.append({'cube': sym, 'bucket': bucket, 'stock': code6, 'weight': w})
        n_event_kept += 1

print(f"  events scanned: {n_event_total:,}")
print(f"  events kept (smart at bucket): {n_event_kept:,}")
print(f"  events skipped (cube not in skill range): {n_event_skipped_unskilled:,}")
print(f"  events skipped (no skill row for bucket): {n_event_skipped_no_skill_row:,}")

raw = pd.DataFrame(records)
print(f"Raw cube-stock-week records: {len(raw):,}")

# B1 per-bucket skill weight: log1p(clip(ann_gain, SKILL_MIN, SKILL_MAX)) normalized
# across the cubes that pass the smart filter in each bucket.
unique_cb = raw[['cube', 'bucket']].drop_duplicates().reset_index(drop=True)
unique_cb['ann'] = unique_cb.apply(
    lambda r: float(rolling_ann.at[r['bucket'], r['cube']]), axis=1)
unique_cb['skill_raw'] = np.log1p(unique_cb['ann'].clip(SKILL_MIN, SKILL_MAX))
unique_cb['skill_weight'] = unique_cb.groupby('bucket')['skill_raw'].transform(
    lambda x: x / x.sum() if x.sum() > 0 else 0.0)

raw = raw.merge(unique_cb[['cube', 'bucket', 'skill_weight']], on=['cube', 'bucket'])
raw['contribution'] = raw['skill_weight'] * raw['weight']

# Save per-bucket smart-cube roster (replaces single smart_cubes_v1.csv snapshot)
unique_cb[['cube', 'bucket', 'ann', 'skill_weight']].to_csv(
    f'{OUT}/smart_cubes_per_bucket.csv', index=False)
print(f"  unique (cube, bucket) smart pairs: {len(unique_cb):,}, "
      f"distinct cubes: {unique_cb['cube'].nunique()}, "
      f"distinct buckets: {unique_cb['bucket'].nunique()}")

# Aggregate to (week, stock)
signal_long = raw.groupby(['bucket', 'stock'])['contribution'].sum().reset_index()
print(f"Unique (week, stock) signal points: {len(signal_long):,}")

# Pivot
signal_wide = signal_long.pivot(index='bucket', columns='stock', values='contribution').fillna(0)
# Convert each event bucket to an honest signal/entry date: first trading day
# after the latest event contained in that bucket. A Friday post-close event
# therefore enters on the next trading day, not the already-known Friday close.
signal_dates = pd.Series(bucket_latest_event, name='latest_event').sort_index().to_frame()
signal_dates['signal_date'] = signal_dates['latest_event'].map(lambda x: first_trading_day_after(x, trading_calendar))
signal_dates = signal_dates.dropna(subset=['signal_date'])
signal_dates.index.name = 'bucket_start'
signal_dates.to_csv(f'{OUT}/smart_consensus_signal_dates.csv')

signal_wide = signal_wide.loc[signal_wide.index.intersection(signal_dates.index)]
signal_wide.index = pd.DatetimeIndex(signal_dates.loc[signal_wide.index, 'signal_date'])
signal_wide = signal_wide.dropna(axis=0)
signal_wide = signal_wide.sort_index()
dup_count = int(signal_wide.index.duplicated().sum())
if dup_count:
    print(f"Warning: {dup_count} duplicate signal dates after B2 shift; keeping latest bucket state")
    signal_wide = signal_wide.groupby(level=0).last()
signal_wide = signal_wide[~signal_wide.index.duplicated(keep='first')]
signal_wide.index.name = 'signal_date'
print(f"Signal panel shape: {signal_wide.shape}")

# Forward-fill: a cube's holding state persists between rebalance events
signal_wide_ff = signal_wide.replace(0, np.nan).ffill().fillna(0)
signal_wide.to_csv(f'{OUT}/smart_consensus_raw.csv')
signal_wide_ff.to_csv(f'{OUT}/smart_consensus_ffill.csv')

# Cross-sectional rank each week
signal_rank = signal_wide_ff.rank(axis=1, pct=True)
signal_rank.to_csv(f'{OUT}/smart_consensus_rank.csv')

# ─── Step 3: Compute IC vs forward returns ──────────────────────────────────
print("\n=== Step 3: IC analysis ===")
fwd = pd.read_csv(FWD, index_col=0)
fwd.index = pd.to_datetime(fwd.index)
fwd = fwd[~fwd.index.duplicated(keep='first')]

# Align indices and columns
common_weeks = signal_rank.index.intersection(fwd.index)
common_stocks = signal_rank.columns.intersection(fwd.columns)
sig = signal_rank.loc[common_weeks, common_stocks]
sig_raw = signal_wide_ff.loc[common_weeks, common_stocks]  # B3-i: raw contributions for mask
ret = fwd.loc[common_weeks, common_stocks]
print(f"Aligned: {len(common_weeks)} weeks × {len(common_stocks)} stocks")

# Per-week cross-sectional IC
# B3-i fix (2026-05-23 audit): previous mask `sig.loc[wk] > 0` was applied on the
# rank-pct matrix (sig = signal_rank), where every non-NaN value is > 0 because
# rank.pct gives ties at zero a small positive value. Empirically, n_stocks per
# week was 3,277 — full universe — not the ~30 in-pool stocks the comment claimed.
# This turned the reported IC=-0.0164/t=-4.97 into a held-vs-not-held SELECTION
# EFFECT t-test, not a cross-sectional rank-skill test among held stocks.
#
# Fix: mask on the RAW signal contribution (signal_wide_ff > 0), AND re-rank within
# the in-pool subset each week so the rank-pct spread is meaningful among the
# ~30 held stocks rather than clustered at the top of the full-universe rank.
ics = []
for wk in common_weeks:
    raw_row = sig_raw.loc[wk]
    r_row = ret.loc[wk]
    mask = raw_row.notna() & r_row.notna() & (raw_row > 0)
    n = int(mask.sum())
    if n < 20:
        continue
    # Re-rank within in-pool: spreads the ~30 held stocks across (0, 1] instead of
    # using their tied-at-top rank from the full-universe signal_rank.
    in_pool_rank = raw_row[mask].rank(pct=True)
    ic, _ = stats.spearmanr(in_pool_rank, r_row[mask])
    ics.append({'week': wk, 'ic': ic, 'n': n})

ic_df = pd.DataFrame(ics)
ic_df.to_csv(f'{OUT}/ic_weekly.csv', index=False)

mean_ic = ic_df['ic'].mean()
se = ic_df['ic'].std() / np.sqrt(len(ic_df))
t_stat = mean_ic / se if se > 0 else np.nan
print(f"Mean IC: {mean_ic:+.4f}, t={t_stat:+.2f}, n_weeks={len(ic_df)}, avg n_stocks={ic_df['n'].mean():.0f}")

# Yearly sub-period
print("\nYearly IC:")
ic_df['year'] = ic_df['week'].dt.year
for yr, g in ic_df.groupby('year'):
    y_ic = g['ic'].mean()
    y_t = y_ic / (g['ic'].std() / np.sqrt(len(g))) if g['ic'].std() > 0 else np.nan
    print(f"  {yr}: IC={y_ic:+.4f}, t={y_t:+.2f}, n={len(g)}")

# Train (2022-2023) / Test (2024+)
train = ic_df[ic_df['week'] <= '2023-12-31']
test = ic_df[ic_df['week'] > '2023-12-31']
print(f"\nTrain (2022-2023): IC={train['ic'].mean():+.4f}, t={train['ic'].mean()/(train['ic'].std()/np.sqrt(len(train))):+.2f}, n={len(train)}")
print(f"Test (2024+): IC={test['ic'].mean():+.4f}, t={test['ic'].mean()/(test['ic'].std()/np.sqrt(len(test))):+.2f}, n={len(test)}")

# ─── Step 4: Random control (same-universe shuffle) ──────────────────────────
# B3-i fix: shuffle the RAW signal contributions (sig_raw) row-by-row, then
# apply the same raw>0 mask + in-pool re-rank used by the signal IC at lines
# 164-189. Without this parallel update, the mask/re-rank logic above no
# longer matches the random control, breaking the comparison.
# B4 separately notes that 30-shuffle + cross-shuffle std underestimates the
# true null variance (AUDIT_FINDINGS_2026-04-27 B2 fix); this commit does
# NOT yet address B4 — it only realigns the random control with the fixed
# signal IC. B4 fix is a separate commit (foundation Backtest path).
print("\n=== Step 4: random control ===")
rng = np.random.default_rng(42)
N_RANDOM = 30
rc_mean_ics = []
for run in range(N_RANDOM):
    shuf_raw = sig_raw.values.copy()
    for i in range(shuf_raw.shape[0]):
        rng.shuffle(shuf_raw[i])
    shuf_raw_df = pd.DataFrame(shuf_raw, index=sig.index, columns=sig.columns)
    rc_ics = []
    for wk in common_weeks:
        raw_row = shuf_raw_df.loc[wk]
        r_row = ret.loc[wk]
        mask = raw_row.notna() & r_row.notna() & (raw_row > 0)
        if mask.sum() < 20:
            continue
        in_pool_rank = raw_row[mask].rank(pct=True)
        ic, _ = stats.spearmanr(in_pool_rank, r_row[mask])
        rc_ics.append(ic)
    rc_mean_ics.append(np.mean(rc_ics))

rc_mean = np.mean(rc_mean_ics)
rc_std = np.std(rc_mean_ics)
delta = mean_ic - rc_mean
delta_t = delta / rc_std if rc_std > 0 else np.nan
print(f"Signal IC: {mean_ic:+.4f}")
print(f"Random IC: {rc_mean:+.4f} ± {rc_std:.4f}")
print(f"Delta: {delta:+.4f}, delta_t: {delta_t:+.2f}")

# ─── Step 5: Long-only top-decile backtest ──────────────────────────────────
# B3-i consistency: same in-pool mask + in-pool re-rank as Step 3, so the
# backtest measures rank skill WITHIN the smart-held subset, not the
# held-vs-not-held selection effect that an unfixed mask would test.
# The out-of-pool / contrarian comparison lives in test_contrarian.py.
print("\n=== Step 5: long-only top-decile backtest (in-pool) ===")
TOP_PCT = 0.10
COST_RT = 0.0056

bt_records = []
rng_bt = np.random.default_rng(43)
for wk in common_weeks:
    raw_row = sig_raw.loc[wk]
    r_row = ret.loc[wk]
    mask = raw_row.notna() & r_row.notna() & (raw_row > 0)
    if mask.sum() < 50:
        continue
    eligible_raw = raw_row[mask]
    eligible_rank = eligible_raw.rank(pct=True)
    n_pick = max(int(len(eligible_rank) * TOP_PCT), 5)
    top = eligible_rank.nlargest(n_pick).index
    sig_ret = r_row[top].mean()

    rand_idx = rng_bt.choice(eligible_rank.index, size=n_pick, replace=False)
    rand_ret = r_row[rand_idx].mean()

    bt_records.append({
        'week': wk, 'n_pick': n_pick,
        'sig_gross': sig_ret, 'sig_net': sig_ret - COST_RT,
        'rand_gross': rand_ret, 'rand_net': rand_ret - COST_RT,
    })

bt = pd.DataFrame(bt_records)
bt.to_csv(f'{OUT}/long_only_backtest.csv', index=False)

def perf(returns, label):
    weeks = len(returns)
    cagr = (1 + returns).prod() ** (52 / weeks) - 1
    vol = returns.std() * np.sqrt(52)
    sharpe = cagr / vol if vol > 0 else np.nan
    win = (returns > 0).mean()
    return cagr, vol, sharpe, win

print(f"\n{'':15} {'CAGR':>10} {'Vol':>8} {'Sharpe':>8} {'Win%':>6}")
for label, col in [('Signal gross', 'sig_gross'), ('Signal net', 'sig_net'),
                    ('Random gross', 'rand_gross'), ('Random net', 'rand_net')]:
    c, v, s, w = perf(bt[col], label)
    print(f"{label:15} {c*100:+9.2f}% {v*100:+7.1f}% {s:+8.2f} {w*100:5.1f}%")

# Excess
excess_g = (bt['sig_gross'] - bt['rand_gross'])
print(f"\nWeekly excess (signal - random, gross): mean={excess_g.mean()*100:+.4f}% (ann {excess_g.mean()*52*100:+.2f}%)")
print(f"  Train: {excess_g[bt.week<='2023-12-31'].mean()*100:+.4f}%")
print(f"  Test:  {excess_g[bt.week>'2023-12-31'].mean()*100:+.4f}%")
print(f"  Excess t-stat: {excess_g.mean() / (excess_g.std() / np.sqrt(len(excess_g))):+.2f}")

print("\n=== DONE ===")
