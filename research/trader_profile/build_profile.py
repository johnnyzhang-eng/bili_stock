"""
Task 015 — Trader Profile Database

Build a 20-dimension feature table per cube. Each cube becomes a 'trader' with:
- Skill: track record (gain, vol, drawdown proxy)
- Style: holding period, concentration, turnover, cash level
- Specialty: industry/market-cap preferences
- Influence: follower count, follower growth proxy

This is the foundation for all 6 alpha experiments. Smart-cube filter, owner attribution,
anti-signal — all start here.

Output:
  research/trader_profile/output/
    trader_profile.csv         # per cube, 20 columns
    owner_profile.csv          # aggregated to owner_id level (a person may have multiple cubes)
    audit_report.md
"""
import json
import os
import sqlite3
import glob
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = '/Users/johnnyzhang/jz_code/bili_stock'
DB = f'{ROOT}/data/cubes.db'
REB_DIR = f'{ROOT}/research/attention_orj/cache/rebalancing'
OUT = f'{ROOT}/research/trader_profile/output'
os.makedirs(OUT, exist_ok=True)

print("=== Loading cube metadata ===")
conn = sqlite3.connect(DB)
meta = pd.read_sql("""
    SELECT symbol, name, owner_id, owner_name, total_gain, annualized_gain_rate,
           monthly_gain, daily_gain, followers_count, created_at, updated_at
    FROM cubes
    WHERE total_gain IS NOT NULL
""", conn)
conn.close()
print(f"  {len(meta):,} cubes in metadata")

# Limit to cubes we have JSONs for
available = set(os.path.basename(f).replace('.json', '') for f in glob.glob(f'{REB_DIR}/ZH*.json'))
meta = meta[meta['symbol'].isin(available)].copy()
print(f"  {len(meta):,} cubes with rebalance JSON")

# ─── Parse each cube's rebalancing JSON into features ─────────────────────────
print("\n=== Building per-cube features ===")

def parse_cube(symbol):
    """Extract behavior features from one cube's rebalance history."""
    path = f'{REB_DIR}/{symbol}.json'
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        return None

    user_events = [e for e in data if e.get('category') == 'user_rebalancing'
                                       and e.get('status') == 'success']
    if len(user_events) < 5:
        return None

    # Timestamps
    timestamps = sorted([e['created_at'] for e in user_events if e.get('created_at')])
    if not timestamps:
        return None
    first_ts = datetime.fromtimestamp(timestamps[0] / 1000)
    last_ts = datetime.fromtimestamp(timestamps[-1] / 1000)
    active_days = (last_ts - first_ts).days

    # Inter-event spacing (median holding period proxy)
    spacings_days = [(t2 - t1) / 1000 / 86400 for t1, t2 in zip(timestamps, timestamps[1:])]

    # Cash level distribution
    cash_pcts = [e.get('cash') for e in user_events if e.get('cash') is not None]
    cash_pcts = [c for c in cash_pcts if 0 <= c <= 100]

    # Position concentration per event
    top1_weights = []
    top3_weights = []
    n_positions = []
    industry_stocks = Counter()  # stock symbols across all events (specialty proxy)

    for e in user_events:
        h = e.get('holdings') or []
        weights = sorted([(h_i.get('weight') or 0) for h_i in h], reverse=True)
        if weights:
            top1_weights.append(weights[0])
            top3_weights.append(sum(weights[:3]))
            n_positions.append(sum(1 for w in weights if w > 1))
        for h_i in h:
            stock = (h_i.get('stock_symbol') or '').upper()
            if stock.startswith(('SZ', 'SH')) and len(stock) == 8:
                industry_stocks[stock[2:]] += 1

    # Turnover: count of position changes
    total_changes = 0
    n_proactive_changes = 0
    weight_deltas = []
    new_buys = 0  # full new positions
    for e in user_events:
        rh = e.get('rebalancing_histories') or []
        for r in rh:
            total_changes += 1
            tw = r.get('target_weight') or 0
            ptw = r.get('prev_target_weight') or 0
            weight_deltas.append(tw - ptw)
            if ptw == 0 and tw > 0:
                new_buys += 1

    # Specialty: top-10 most-held stocks
    top_stocks = [s for s, _ in industry_stocks.most_common(10)]

    return {
        'symbol': symbol,
        'n_user_events': len(user_events),
        'first_event': first_ts.strftime('%Y-%m-%d'),
        'last_event': last_ts.strftime('%Y-%m-%d'),
        'active_days': active_days,
        'events_per_year': len(user_events) / max(active_days / 365.0, 0.1),

        # Style
        'median_spacing_days': float(np.median(spacings_days)) if spacings_days else np.nan,
        'mean_spacing_days': float(np.mean(spacings_days)) if spacings_days else np.nan,
        'median_top1_weight': float(np.median(top1_weights)) if top1_weights else np.nan,
        'median_top3_weight': float(np.median(top3_weights)) if top3_weights else np.nan,
        'median_n_positions': float(np.median(n_positions)) if n_positions else np.nan,
        'median_cash_pct': float(np.median(cash_pcts)) if cash_pcts else np.nan,
        'std_cash_pct': float(np.std(cash_pcts)) if cash_pcts else np.nan,
        'pct_events_high_cash': sum(1 for c in cash_pcts if c > 50) / len(cash_pcts) if cash_pcts else np.nan,

        # Turnover
        'total_position_changes': total_changes,
        'changes_per_year': total_changes / max(active_days / 365.0, 0.1),
        'new_buys': new_buys,
        'mean_abs_weight_delta': float(np.mean(np.abs(weight_deltas))) if weight_deltas else np.nan,

        # Specialty
        'top10_stocks': ','.join(top_stocks),
        'unique_stocks_held': len(industry_stocks),
    }

records = []
for i, sym in enumerate(meta['symbol'].tolist()):
    r = parse_cube(sym)
    if r:
        records.append(r)
    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{len(meta)} processed, {len(records)} valid")

features = pd.DataFrame(records)
print(f"\nValid trader profiles: {len(features)}")

# Merge with metadata
profile = meta.merge(features, on='symbol', how='inner')

# Derive: skill tier
profile['skill_tier'] = pd.cut(profile['annualized_gain_rate'].fillna(-999),
                                bins=[-1000, 0, 10, 25, 50, 10000],
                                labels=['NEG', 'POOR', 'AVG', 'GOOD', 'TOP'])

# Style buckets
profile['style_horizon'] = pd.cut(profile['median_spacing_days'].fillna(9999),
                                   bins=[0, 7, 30, 90, 365, 99999],
                                   labels=['SCALP', 'SHORT', 'MEDIUM', 'LONG', 'VERY_LONG'])

profile['style_concentration'] = pd.cut(profile['median_top1_weight'].fillna(-1),
                                         bins=[-2, 10, 20, 35, 100],
                                         labels=['DIVERSE', 'BALANCED', 'CONCENTRATED', 'ALL_IN'])

profile.to_csv(f'{OUT}/trader_profile.csv', index=False)
print(f"Saved: {OUT}/trader_profile.csv ({len(profile)} rows × {len(profile.columns)} cols)")

# ─── Owner-level aggregation ─────────────────────────────────────────────────
print("\n=== Owner-level aggregation ===")

owner = profile.groupby('owner_id').agg(
    owner_name=('owner_name', 'first'),
    n_cubes=('symbol', 'count'),
    cubes=('symbol', lambda x: ','.join(x.tolist())),
    mean_gain=('total_gain', 'mean'),
    max_gain=('total_gain', 'max'),
    mean_ann_gain=('annualized_gain_rate', 'mean'),
    total_followers=('followers_count', 'sum'),
    max_followers=('followers_count', 'max'),
    total_events=('n_user_events', 'sum'),
    median_spacing=('median_spacing_days', 'median'),
    mean_top1_weight=('median_top1_weight', 'mean'),
    mean_cash_pct=('median_cash_pct', 'mean'),
).sort_values('mean_ann_gain', ascending=False).reset_index()

owner.to_csv(f'{OUT}/owner_profile.csv', index=False)
print(f"Saved: {OUT}/owner_profile.csv ({len(owner)} owners)")

# ─── Stats / Audit ───────────────────────────────────────────────────────────
print("\n=== Distribution Stats ===")
print(f"Skill tier:")
print(profile['skill_tier'].value_counts().sort_index())

print(f"\nStyle horizon:")
print(profile['style_horizon'].value_counts())

print(f"\nStyle concentration:")
print(profile['style_concentration'].value_counts())

# Smart cube candidates: TOP or GOOD skill + reasonable activity
smart = profile[(profile['skill_tier'].isin(['TOP', 'GOOD'])) &
                (profile['n_user_events'] >= 30) &
                (profile['followers_count'] > 200)]
print(f"\nSmart cube candidates: {len(smart)}")
print(smart[['symbol', 'name', 'owner_name', 'annualized_gain_rate', 'followers_count', 'n_user_events']].head(20).to_string(index=False))

# Dumb cube candidates: AVG/POOR skill but high followers
dumb = profile[(profile['skill_tier'].isin(['POOR', 'AVG'])) &
               (profile['followers_count'] > 500) &
               (profile['n_user_events'] >= 30)]
print(f"\nDumb cube candidates: {len(dumb)}")

# Save subset CSVs for easy reuse
smart.to_csv(f'{OUT}/smart_cubes.csv', index=False)
dumb.to_csv(f'{OUT}/dumb_cubes.csv', index=False)

print("\n=== DONE ===")
