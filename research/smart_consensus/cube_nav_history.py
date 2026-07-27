"""
Cube NAV history reconstruction (B1 fix, 2026-05-23 audit)
=========================================================
Build per-cube weekly NAV from rebalancing_histories + daily_k OHLCV, then
compute rolling 12-month annualized gain at each (cube, week).

This replaces the 2026 snapshot `annualized_gain_rate` in trader_profile.csv
with an ex-ante, point-in-time skill estimate. build_signal.py uses this to
select "smart" cubes per signal week instead of one global snapshot.

Critical conventions:
  - Weeks: Monday-anchored, generated 2014-01-06 → 2026-05-18.
  - Snapshot cutoff for cube holdings at week W: events with created_at ≤
    Monday of W. A Tuesday-W event therefore enters NAV at week W+1 (one-week
    lag, strict ex-ante).
  - Weekly close at W = last available daily close ≤ Sunday(W). NaN if last
    close is older than STALENESS_DAYS = 14 (matches B5-i convention in
    rerun_with_full_data.py).
  - Weekly return = weekly_close.pct_change(). Stale weeks → NaN return.
  - NAV[W] = NAV[W-1] * (1 + sum(weight[stock, W-1] * return[stock, W])).
    Holdings at end of W-1 realize returns over (W-1) → W.
  - Rolling ann_gain[W] = (NAV[W] / NAV[W-52] - 1) * 100 (percent). NaN if
    less than 52 weeks of NAV history.

Outputs:
  output/cube_nav_weekly.csv      weeks × cubes  (NAV series)
  output/rolling_ann_gain.csv     weeks × cubes  (trailing 52w ann gain %)
  output/cube_meta.csv            cube, first_event_ts, n_events_total
"""
import os
import json
import glob
import time
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = '/Users/johnnyzhang/jz_code/bili_stock'
REB_DIR = f'{ROOT}/research/attention_orj/cache/rebalancing'
DAILY_K = f'{ROOT}/research/attention_orj/cache/daily_k'
DAILY_K_PRE = f'{ROOT}/research/attention_orj/cache/daily_k_pre2022'
OUT = f'{ROOT}/research/smart_consensus/output'
os.makedirs(OUT, exist_ok=True)

# Match build_signal.py B3-ii fix: skip ETF/LOF + CB prefixes
NON_STOCK_PREFIXES = (
    '510', '511', '512', '513', '515', '516', '518', '588', '159', '160',
    '110', '113', '118', '123', '127', '128',
)
STALENESS_DAYS = 14
WEEK_START = '2014-01-06'  # first Monday of 2014
WEEK_END = '2026-05-18'    # match forward_returns_v2 latest week


# ─── Step 1: Load daily OHLCV for a code, merging pre2022 + main ──────────────

def load_stock_daily(code6):
    """Load + merge daily prices from daily_k_pre2022 + daily_k. None if no file."""
    parts = []
    for path in (f'{DAILY_K_PRE}/{code6}.csv', f'{DAILY_K}/{code6}.csv'):
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, usecols=['date', 'close'])
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date', 'close'])
            df = df[df['close'] > 0]
            parts.append(df)
        except Exception:
            continue
    if not parts:
        return None
    out = pd.concat(parts).drop_duplicates(subset=['date'], keep='last').sort_values('date').reset_index(drop=True)
    return out  # columns: date, close


# ─── Step 2: Build weekly_close matrix using merge_asof + staleness gate ──────

def build_weekly_close(codes, weeks_idx):
    """
    For each code: merge_asof daily close backward onto Sunday-of-week, then
    NaN out rows where (Sunday_week - daily_date) > STALENESS_DAYS.

    Returns DataFrame indexed by weeks_idx (Monday), columns = codes.
    """
    weeks_idx = pd.DatetimeIndex(weeks_idx).sort_values()
    wk_end = weeks_idx + pd.Timedelta(days=6)  # Sunday
    wk_target = pd.DataFrame({'week': weeks_idx, 'wk_end': wk_end}).sort_values('wk_end')

    cols = {}
    t0 = time.time()
    for i, code in enumerate(codes):
        daily = load_stock_daily(code)
        if daily is None:
            continue
        daily = daily.rename(columns={'date': 'daily_date'}).sort_values('daily_date')
        merged = pd.merge_asof(wk_target, daily, left_on='wk_end', right_on='daily_date', direction='backward')
        # Staleness: NaN if last daily is older than STALENESS_DAYS before Sunday
        stale = (merged['wk_end'] - merged['daily_date']).dt.days > STALENESS_DAYS
        merged.loc[stale, 'close'] = np.nan
        cols[code] = merged.set_index('week')['close'].reindex(weeks_idx).values
        if (i + 1) % 500 == 0:
            print(f'  weekly_close {i+1}/{len(codes)} ({time.time()-t0:.0f}s)')
    return pd.DataFrame(cols, index=weeks_idx)


# ─── Step 3: Parse cube events into per-week holdings dict ────────────────────

def parse_cube_events(path):
    """Return sorted list of (timestamp_ms, target_weights_dict, cash_frac, n_events_so_far).
    target_weights_dict: code6 -> fraction (0-1).
    State is cumulative — each entry reflects state AFTER applying that event.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    events = [e for e in data if isinstance(e, dict)
              and e.get('status') == 'success'
              and e.get('category') == 'user_rebalancing']
    events.sort(key=lambda e: e.get('created_at', 0))

    snapshots = []
    holdings = {}
    cash_frac = 1.0
    for n, evt in enumerate(events, start=1):
        ts = evt.get('created_at', 0)
        if not ts:
            continue
        for h in evt.get('rebalancing_histories') or []:
            sym = (h.get('stock_symbol') or '').upper()
            if not sym.startswith(('SH', 'SZ')) or len(sym) != 8:
                continue
            code6 = sym[2:]
            if code6.startswith(NON_STOCK_PREFIXES):
                continue
            tw = h.get('target_weight')
            if tw is None:
                continue
            tw_frac = float(tw) / 100.0
            if tw_frac > 0:
                holdings[code6] = tw_frac
            else:
                holdings.pop(code6, None)
        cash = evt.get('cash')
        cash_frac = (float(cash) if cash is not None else 0.0) / 100.0
        snapshots.append((ts, dict(holdings), cash_frac, n))
    return snapshots


def cube_weekly_state(snapshots, weeks_idx):
    """
    For each week W, find the latest snapshot with ts ≤ Monday(W).
    Return: holdings_df (weeks × stocks) of weight fractions, n_events_so_far series.
    """
    weeks_idx = pd.DatetimeIndex(weeks_idx).sort_values()
    # Use pandas DatetimeIndex.searchsorted to avoid pandas-3 dtype gotcha
    # (default datetime64[us] vs [ns] makes raw int64 comparisons unreliable).
    snap_ts = pd.DatetimeIndex(pd.to_datetime([s[0] for s in snapshots], unit='ms'))
    idx = snap_ts.searchsorted(weeks_idx, side='right') - 1
    # idx[i] = -1 means no snapshot before wk[i]

    stocks_ever = set()
    for _, h, _, _ in snapshots:
        stocks_ever.update(h.keys())
    stocks_ever = sorted(stocks_ever)
    if not stocks_ever:
        empty = pd.DataFrame(index=weeks_idx, columns=[], dtype=float)
        n_evt_series = pd.Series(0, index=weeks_idx)
        return empty, n_evt_series

    weights = pd.DataFrame(0.0, index=weeks_idx, columns=stocks_ever, dtype=float)
    n_evt_series = pd.Series(0, index=weeks_idx)
    for i, snap_idx in enumerate(idx):
        if snap_idx < 0:
            continue
        _, holdings, _, n_evt = snapshots[snap_idx]
        for code, w in holdings.items():
            weights.iat[i, weights.columns.get_loc(code)] = w
        n_evt_series.iat[i] = n_evt
    return weights, n_evt_series


# ─── Step 4: Compute cube NAV ─────────────────────────────────────────────────

def cube_nav_from_weights(weights, returns):
    """
    NAV[T] = NAV[T-1] * (1 + sum(weights[T-1, stock] * returns[T, stock])).
    weights at T-1 realize returns over (T-1)→T.
    Cash earns 0.

    weights: weeks × stocks DataFrame (subset of all stocks)
    returns: weeks × ALL_STOCKS DataFrame (returns at week T)
    """
    if weights.empty:
        return pd.Series(np.nan, index=returns.index)
    # Align columns: only the stocks this cube ever held
    held_stocks = weights.columns.tolist()
    avail = [s for s in held_stocks if s in returns.columns]
    if not avail:
        return pd.Series(np.nan, index=returns.index)
    w = weights[avail].values            # weeks × held_stocks
    r = returns[avail].fillna(0).values  # weeks × held_stocks (NaN return → 0 contribution)

    # port_ret[t] = sum(w[t-1, k] * r[t, k]) for k in held_stocks
    w_prev = np.vstack([np.zeros((1, w.shape[1])), w[:-1, :]])  # lag by 1 week
    port_ret = (w_prev * r).sum(axis=1)
    # NAV starts at 1.0
    nav = np.cumprod(1 + port_ret)
    return pd.Series(nav, index=weights.index)


def rolling_ann_gain(nav_series, window=52):
    """Trailing window-week ann gain as percent.
    ann = (nav[T] / nav[T-window] - 1) * (52 / window)  -- annualized when window=52 is identity.
    """
    base = nav_series.shift(window)
    pct = (nav_series / base - 1) * 100.0
    return pct  # window=52 ⇒ already annualized


# ─── Main pipeline ────────────────────────────────────────────────────────────

def main(limit=None):
    print('=== Cube NAV history reconstruction (B1 fix) ===')
    t_start = time.time()

    weeks_idx = pd.date_range(start=WEEK_START, end=WEEK_END, freq='W-MON')
    print(f'Weeks: {len(weeks_idx)} from {weeks_idx[0].date()} to {weeks_idx[-1].date()}')

    cube_files = sorted(glob.glob(f'{REB_DIR}/*.json'))
    if limit:
        cube_files = cube_files[:limit]
    print(f'\nStep 1: scan cube events for stock universe ({len(cube_files)} cubes)...')

    # Pre-parse all cubes to collect held stocks + snapshots
    cube_snapshots = {}
    all_codes = set()
    t1 = time.time()
    for i, f in enumerate(cube_files):
        cube_id = os.path.basename(f).replace('.json', '')
        snaps = parse_cube_events(f)
        if not snaps:
            continue
        cube_snapshots[cube_id] = snaps
        for _, h, _, _ in snaps:
            all_codes.update(h.keys())
        if (i + 1) % 200 == 0:
            print(f'  parsed {i+1}/{len(cube_files)} ({time.time()-t1:.0f}s)')
    print(f'  cubes with events: {len(cube_snapshots)}, unique stocks ever held: {len(all_codes)}')

    print('\nStep 2: build weekly close matrix...')
    all_codes_sorted = sorted(all_codes)
    weekly_close = build_weekly_close(all_codes_sorted, weeks_idx)
    cov = weekly_close.notna().sum().sum() / weekly_close.size * 100
    print(f'  weekly_close shape: {weekly_close.shape}, non-null: {cov:.1f}%')

    weekly_returns = weekly_close.pct_change()

    print('\nStep 3: per-cube NAV + rolling ann_gain...')
    nav_dict = {}
    ann_dict = {}
    meta_rows = []
    t2 = time.time()
    for i, (cube_id, snaps) in enumerate(cube_snapshots.items()):
        weights, n_evts = cube_weekly_state(snaps, weeks_idx)
        nav = cube_nav_from_weights(weights, weekly_returns)
        ann = rolling_ann_gain(nav)
        nav_dict[cube_id] = nav
        ann_dict[cube_id] = ann
        meta_rows.append({
            'cube': cube_id,
            'first_event_ts_ms': snaps[0][0],
            'first_event_date': datetime.fromtimestamp(snaps[0][0] / 1000).date(),
            'last_event_ts_ms': snaps[-1][0],
            'last_event_date': datetime.fromtimestamp(snaps[-1][0] / 1000).date(),
            'n_events': len(snaps),
            'n_stocks_ever_held': len(weights.columns),
            'nav_final': float(nav.iloc[-1]) if not nav.isna().all() else float('nan'),
            'ann_gain_final': float(ann.dropna().iloc[-1]) if ann.dropna().size > 0 else float('nan'),
        })
        if (i + 1) % 100 == 0:
            print(f'  {i+1}/{len(cube_snapshots)} cubes ({time.time()-t2:.0f}s)')

    nav_df = pd.DataFrame(nav_dict)
    ann_df = pd.DataFrame(ann_dict)
    meta_df = pd.DataFrame(meta_rows)

    nav_df.to_csv(f'{OUT}/cube_nav_weekly.csv')
    ann_df.to_csv(f'{OUT}/rolling_ann_gain.csv')
    meta_df.to_csv(f'{OUT}/cube_meta.csv', index=False)

    print(f'\nOutput files:')
    print(f'  cube_nav_weekly.csv: {nav_df.shape}')
    print(f'  rolling_ann_gain.csv: {ann_df.shape}')
    print(f'  cube_meta.csv: {len(meta_df)} cubes')
    print(f'\nTotal time: {time.time()-t_start:.0f}s')

    # Sanity: how many cubes have valid ann_gain at 2022-01-03, 2024-01-01, 2026-05-18
    for probe in ['2022-01-03', '2024-01-01', '2026-05-11']:
        ts = pd.Timestamp(probe)
        if ts in ann_df.index:
            valid = ann_df.loc[ts].dropna()
            print(f'  {probe}: {len(valid)} cubes with valid 52w ann_gain, '
                  f'in (25%,200%]: {((valid > 25) & (valid <= 200)).sum()}')


if __name__ == '__main__':
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=limit)
