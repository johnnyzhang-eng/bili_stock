"""
Build forward_returns_v2.csv with the B2 audited entry convention.

The old builder depended on factor_delta/momentum/accel matrices for its week
index, then used week-end closes. That backtest clock no longer matches the
smart-consensus signal after the B2 fix.

New convention:
  - The signal builder stamps each event bucket to the first tradable day after
    the latest event in that bucket.
  - forward_returns_v2.csv is indexed by tradable entry dates from daily_k.
  - Return = close[entry + HORIZON_TRADING_DAYS] / close[entry] - 1.
  - No as-of or forward-fill prices: if a stock has no close on entry or exit,
    the cell is NaN. Delisted/stale names stay NaN instead of becoming 0%.

This script intentionally builds from daily_k files directly and does not read
factor_*.csv, which may be absent after local data rebuilds.
"""
import os
import time

import numpy as np
import pandas as pd


ROOT = '/Users/johnnyzhang/jz_code/bili_stock/research'
OUT = f'{ROOT}/cube_attention_delta/output'
DAILY_DIRS = [
    f'{ROOT}/attention_orj/cache/daily_k_pre2022',
    f'{ROOT}/attention_orj/cache/daily_k',
]
HORIZON_TRADING_DAYS = 5

os.makedirs(OUT, exist_ok=True)


def collect_price_paths():
    """Return code -> ordered list of cache CSVs, pre-2022 first then current."""
    paths_by_code = {}
    for daily_dir in DAILY_DIRS:
        if not os.path.isdir(daily_dir):
            print(f"  missing daily dir: {daily_dir}")
            continue
        for name in os.listdir(daily_dir):
            if not name.endswith('.csv'):
                continue
            code = name[:-4]
            paths_by_code.setdefault(code, []).append(os.path.join(daily_dir, name))
    return paths_by_code


def load_close_series(paths):
    frames = []
    for path in paths:
        try:
            df = pd.read_csv(path, usecols=['date', 'close'])
        except Exception:
            continue
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['date', 'close'])
        if not df.empty:
            frames.append(df)
    if not frames:
        return None

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values('date').drop_duplicates('date', keep='last')
    merged = merged.set_index('date')['close'].sort_index()
    merged.index = merged.index.normalize()
    return merged[~merged.index.duplicated(keep='last')]


def main():
    print("=== Build forward_returns_v2 with audited entry dates ===")
    print(f"Horizon: {HORIZON_TRADING_DAYS} trading days")
    t0 = time.time()

    paths_by_code = collect_price_paths()
    print(f"Price files: {sum(len(v) for v in paths_by_code.values()):,} files, {len(paths_by_code):,} unique codes")

    series_by_code = {}
    all_dates = set()
    skipped = 0
    for i, (code, paths) in enumerate(sorted(paths_by_code.items()), start=1):
        close = load_close_series(paths)
        if close is None or len(close) <= HORIZON_TRADING_DAYS:
            skipped += 1
            continue
        series_by_code[code] = close
        all_dates.update(close.index)
        if i % 500 == 0:
            elapsed = time.time() - t0
            print(f"  loaded {i:,}/{len(paths_by_code):,} codes ({elapsed:.0f}s)")

    if not series_by_code:
        raise RuntimeError("No usable daily_k close series found")

    trading_calendar = pd.DatetimeIndex(sorted(all_dates), name='entry_date')
    close_panel = pd.DataFrame(series_by_code).reindex(trading_calendar)
    close_panel = close_panel.sort_index()

    exit_close = close_panel.shift(-HORIZON_TRADING_DAYS)
    fwd_ret = exit_close / close_panel - 1
    fwd_ret.index.name = 'entry_date'

    # Last horizon rows cannot have a fixed-horizon exit.
    fwd_ret.iloc[-HORIZON_TRADING_DAYS:] = np.nan

    out_path = f'{OUT}/forward_returns_v2.csv'
    fwd_ret.to_csv(out_path)

    meta = pd.DataFrame({
        'entry_date': trading_calendar,
        'exit_date': pd.Series(trading_calendar).shift(-HORIZON_TRADING_DAYS).values,
    })
    meta.to_csv(f'{OUT}/forward_returns_v2_entry_map.csv', index=False)

    non_null_pct = fwd_ret.notna().sum().sum() / fwd_ret.size * 100
    zero_non_null_cols = int((fwd_ret.notna().sum(axis=0) == 0).sum())
    print(f"forward_returns_v2 shape: {fwd_ret.shape}")
    print(f"entry dates: {trading_calendar.min().date()} ~ {trading_calendar.max().date()}")
    print(f"non-null cells: {non_null_pct:.1f}%")
    print(f"zero non-null columns: {zero_non_null_cols}")
    print(f"skipped codes: {skipped}")
    print(f"saved: {out_path}")
    print(f"Time: {time.time() - t0:.0f}s")


if __name__ == '__main__':
    main()
