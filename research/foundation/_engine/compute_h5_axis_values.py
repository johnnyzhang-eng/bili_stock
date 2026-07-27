"""
H5 V2 Composite Axis — for B8 audit on PURE behavior, point-in-time, 926-cube pool.

V2 supersedes V1 (commit db3df2f) per Codex BLOCK + Johnny constraint
(2026-05-24 14:30):

  - Pool: ALL 926 cubes from rebalancing JSONs. NO smart_cubes_v1.csv,
    NO annualized_gain_rate, NO followers_count, NO owner profile inputs.
    Skill/snapshot inputs entirely removed from H5.

  - Eligibility per (cube C, week W): C has >= 8 success user_rebalancing
    events in trailing 180d (W-180d to W-1d, exclusive of W). Point-in-time;
    cubes too quiet at W are masked NaN, not zero. No future-leak.

  - 4 behavior features (each per eligible (cube, W)):
      1. turnover_count_90d         — # events in trailing 90d
      2. mean_lag_vs_leader_30d     — vs ALL 926 cubes' buys (not just 96)
      3. attention_spike_rate_90d   — fraction of cube's buys on
                                       stock-volume-spike days (volume in
                                       top decile rolling 60d)
      4. concentration_intensity_30d — mean HHI of weight CHANGES across
                                        cube's events in trailing 30d.
                                        HHI = sum(delta_w_i^2).

  - Composite: per-week z-normalize each feature across the eligible cohort,
    element-wise nanmean (NaN-safe), rank-percentile to [0, 1].
    HIGH = MORE behaviorally suspect.

Output:
  research/smart_consensus/output/H5_composite_axis.csv             (overwrite)
  research/smart_consensus/output/H5_feature_turnover.csv           (overwrite)
  research/smart_consensus/output/H5_feature_lag.csv                (overwrite)
  research/smart_consensus/output/H5_feature_attention_spike.csv    (new)
  research/smart_consensus/output/H5_feature_concentration.csv      (new)

(Directory name retains "smart_consensus" for repo continuity, but H5 code
and docs use "candidate cubes", not "smart cubes".)
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REB_DIR = os.path.join(ROOT, "research/attention_orj/cache/rebalancing")
ROLLING_ANN_PATH = os.path.join(ROOT, "research/smart_consensus/output/rolling_ann_gain.csv")
STOCK_DATA_DIR = os.path.join(ROOT, "data/stock_data")

OUT_PATH = os.path.join(ROOT, "research/smart_consensus/output/H5_composite_axis.csv")
TURNOVER_PATH = os.path.join(ROOT, "research/smart_consensus/output/H5_feature_turnover.csv")
LAG_PATH = os.path.join(ROOT, "research/smart_consensus/output/H5_feature_lag.csv")
ATTN_PATH = os.path.join(ROOT, "research/smart_consensus/output/H5_feature_attention_spike.csv")
CONC_PATH = os.path.join(ROOT, "research/smart_consensus/output/H5_feature_concentration.csv")

TRAILING_TURNOVER_DAYS = 90
TRAILING_LAG_DAYS = 30
TRAILING_ATTN_DAYS = 90
TRAILING_CONC_DAYS = 30
ELIGIBILITY_WINDOW_DAYS = 180
ELIGIBILITY_MIN_EVENTS = 8
LEADER_WINDOW_DAYS = 30
VOLUME_ROLL_DAYS = 60
SPIKE_PCT = 0.9  # top decile

NON_STOCK_PREFIXES = (
    "510", "511", "512", "513", "515", "516", "518", "588", "159", "160",
    "110", "113", "118", "123", "127", "128",
)


def discover_candidate_cubes() -> list[str]:
    """Return sorted list of cube ids from rebalancing JSONs. NO skill filter."""
    paths = sorted(glob.glob(os.path.join(REB_DIR, "*.json")))
    return [os.path.basename(p).replace(".json", "") for p in paths]


def load_weekly_index() -> pd.DatetimeIndex:
    df = pd.read_csv(ROLLING_ANN_PATH, index_col=0)
    idx = pd.to_datetime(df.index).normalize().sort_values()
    return pd.DatetimeIndex(idx)


def parse_events(cubes: list[str]) -> pd.DataFrame:
    """Return events DataFrame with: cube, stock, dt, prev_weight, target_weight, is_buy."""
    rows = []
    n_missing = 0
    for cube in cubes:
        path = os.path.join(REB_DIR, f"{cube}.json")
        if not os.path.exists(path):
            n_missing += 1
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[!] failed parsing {cube}: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, list):
            continue
        for ev in data:
            if not isinstance(ev, dict):
                continue
            if ev.get("status") != "success":
                continue
            if ev.get("category") != "user_rebalancing":
                continue
            ts_ms = ev.get("created_at")
            if not ts_ms:
                continue
            try:
                dt = pd.Timestamp(int(ts_ms) // 1000, unit="s")
            except (TypeError, ValueError):
                continue
            for h in ev.get("rebalancing_histories") or []:
                stock_raw = (h.get("stock_symbol") or "").upper()
                if not (stock_raw.startswith(("SH", "SZ")) and len(stock_raw) == 8):
                    continue
                code = stock_raw[2:]
                if code.startswith(NON_STOCK_PREFIXES):
                    continue
                try:
                    target = float(h.get("target_weight") or 0)
                    prev = float(h.get("prev_weight_adjusted") or 0)
                except (TypeError, ValueError):
                    continue
                if abs(target - prev) < 0.01:
                    continue
                rows.append({
                    "cube": cube,
                    "stock": code,
                    "exch_stock": stock_raw,
                    "dt": dt,
                    "prev_weight": prev,
                    "target_weight": target,
                    "is_buy": prev <= 0 and target > 0,
                })
    if not rows:
        raise RuntimeError("no events parsed")
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["dt"])
    print(f"[+] parsed {len(df)} events across {len(cubes)} cubes ({n_missing} JSONs missing)")
    return df


def event_dts_per_cube(events: pd.DataFrame) -> dict[str, np.ndarray]:
    """cube → sorted int64-ns dt array."""
    out = {}
    for cube, sub in events.groupby("cube"):
        out[cube] = sub["dt"].sort_values().values.astype("datetime64[ns]").astype("int64")
    return out


def compute_eligibility(cube_dts: dict[str, np.ndarray], cubes: list[str], weekly: pd.DatetimeIndex) -> pd.DataFrame:
    """Boolean DataFrame: eligible(cube, W) = (# success events in [W-180d, W-1d]) >= 8."""
    weekly_ns = weekly.values.astype("datetime64[ns]").astype("int64")
    lower_ns = (weekly - pd.Timedelta(days=ELIGIBILITY_WINDOW_DAYS)).values.astype("datetime64[ns]").astype("int64")
    one_day_ns = 86400 * 1_000_000_000
    out: dict[str, np.ndarray] = {}
    for cube in cubes:
        dts = cube_dts.get(cube)
        if dts is None or len(dts) == 0:
            out[cube] = np.zeros(len(weekly), dtype=bool)
            continue
        lo = np.searchsorted(dts, lower_ns, side="left")
        hi = np.searchsorted(dts, weekly_ns - one_day_ns, side="right")
        out[cube] = (hi - lo) >= ELIGIBILITY_MIN_EVENTS
    df = pd.DataFrame(out, index=weekly)
    df.index.name = "date"
    return df


def compute_turnover(cube_dts: dict[str, np.ndarray], cubes: list[str], weekly: pd.DatetimeIndex) -> pd.DataFrame:
    weekly_ns = weekly.values.astype("datetime64[ns]").astype("int64")
    lower_ns = (weekly - pd.Timedelta(days=TRAILING_TURNOVER_DAYS)).values.astype("datetime64[ns]").astype("int64")
    out: dict[str, np.ndarray] = {}
    for cube in cubes:
        dts = cube_dts.get(cube)
        if dts is None or len(dts) == 0:
            out[cube] = np.full(len(weekly), np.nan)
            continue
        lo = np.searchsorted(dts, lower_ns, side="left")
        hi = np.searchsorted(dts, weekly_ns, side="right")
        out[cube] = (hi - lo).astype(float)
    df = pd.DataFrame(out, index=weekly)
    df.index.name = "date"
    return df


def compute_lag(events: pd.DataFrame, cubes: list[str], weekly: pd.DatetimeIndex) -> pd.DataFrame:
    """Lag vs leader, with LEADER searched across all 926 cubes (not 96)."""
    buys = events[events["is_buy"]].copy().sort_values("dt").reset_index(drop=True)
    if buys.empty:
        return pd.DataFrame(np.nan, index=weekly, columns=cubes, dtype=float)

    stock_buyers: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for stock, sub in buys.groupby("stock"):
        sub_sorted = sub.sort_values("dt")
        stock_buyers[stock] = (
            sub_sorted["cube"].values,
            sub_sorted["dt"].values.astype("datetime64[ns]").astype("int64"),
        )

    leader_window_ns = LEADER_WINDOW_DAYS * 86400 * 1_000_000_000
    lags = np.zeros(len(buys), dtype=float)
    for i in range(len(buys)):
        stock = buys.iloc[i]["stock"]
        cube = buys.iloc[i]["cube"]
        t_ns = buys.iloc[i]["dt"].value
        cubes_arr, dts_ns = stock_buyers[stock]
        mask = (dts_ns >= t_ns - leader_window_ns) & (dts_ns <= t_ns) & (cubes_arr != cube)
        if not mask.any():
            lags[i] = 0.0
        else:
            earliest_ns = dts_ns[mask].min()
            lags[i] = max(0.0, (t_ns - earliest_ns) / (86400 * 1_000_000_000))
    buys["lag_days"] = lags
    print(f"[+] lag per-buy: mean={lags.mean():.2f}d median={float(np.median(lags)):.2f}d max={lags.max():.0f}d (over {len(buys)} buys, 926-cube leader pool)")

    weekly_ns = weekly.values.astype("datetime64[ns]").astype("int64")
    lower_ns = (weekly - pd.Timedelta(days=TRAILING_LAG_DAYS)).values.astype("datetime64[ns]").astype("int64")
    out: dict[str, np.ndarray] = {c: np.full(len(weekly), np.nan) for c in cubes}
    cubes_set = set(cubes)
    for cube, sub in buys.groupby("cube"):
        if cube not in cubes_set:
            continue
        sub_sorted = sub.sort_values("dt")
        dts_ns = sub_sorted["dt"].values.astype("datetime64[ns]").astype("int64")
        lag_vals = sub_sorted["lag_days"].values.astype(float)
        col = out[cube]
        lo = np.searchsorted(dts_ns, lower_ns, side="left")
        hi = np.searchsorted(dts_ns, weekly_ns, side="right")
        for w_i in range(len(weekly)):
            if hi[w_i] > lo[w_i]:
                col[w_i] = float(lag_vals[lo[w_i]:hi[w_i]].mean())
    df = pd.DataFrame(out, index=weekly)
    df.index.name = "date"
    return df


def build_spike_map(stocks: set[str]) -> dict[str, dict[pd.Timestamp, bool]]:
    """For each stock, compute boolean spike day map: volume_rank_60d > 0.9.

    Returns {code: {date: bool}}. Skips stocks without OHLCV file.
    """
    spike_map = {}
    n_loaded, n_missing = 0, 0
    for stock in sorted(stocks):
        # try SH or SZ prefix
        for prefix in ("SH", "SZ"):
            path = os.path.join(STOCK_DATA_DIR, f"{prefix}{stock}.csv")
            if os.path.exists(path):
                break
        else:
            n_missing += 1
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception as exc:
            print(f"[!] failed loading {path}: {exc}", file=sys.stderr)
            n_missing += 1
            continue
        # Column names are Chinese: 日期, 成交量
        if "日期" not in df.columns or "成交量" not in df.columns:
            n_missing += 1
            continue
        df["date"] = pd.to_datetime(df["日期"]).dt.normalize()
        df = df.sort_values("date").reset_index(drop=True)
        vol = df["成交量"].astype(float)
        # Rolling rank over trailing 60d (inclusive of today)
        rank = vol.rolling(VOLUME_ROLL_DAYS, min_periods=10).rank(pct=True)
        spike = (rank > SPIKE_PCT).fillna(False).values
        spike_map[stock] = dict(zip(df["date"].values, spike))
        n_loaded += 1
    print(f"[+] spike map: loaded {n_loaded} stocks, {n_missing} missing")
    return spike_map


def compute_attention_spike(events: pd.DataFrame, cubes: list[str], weekly: pd.DatetimeIndex) -> pd.DataFrame:
    """Per cube C, per week W: fraction of C's BUYS in [W-90d, W] on volume-spike days."""
    buys = events[events["is_buy"]].copy().sort_values("dt").reset_index(drop=True)
    if buys.empty:
        return pd.DataFrame(np.nan, index=weekly, columns=cubes, dtype=float)

    spike_map = build_spike_map(set(buys["stock"].unique().tolist()))

    # Annotate each buy with spike flag
    spike_flags = np.zeros(len(buys), dtype=float)
    for i in range(len(buys)):
        stock = buys.iloc[i]["stock"]
        dt = buys.iloc[i]["dt"].normalize()
        m = spike_map.get(stock)
        if m is None:
            spike_flags[i] = np.nan
            continue
        spike_flags[i] = float(m.get(dt.to_datetime64(), False))
    buys["spike"] = spike_flags
    coverage = (~np.isnan(spike_flags)).sum()
    rate = np.nanmean(spike_flags) if coverage > 0 else float("nan")
    print(f"[+] attention spike: {coverage}/{len(buys)} buys mapped, overall spike rate {rate:.3f}")

    # Aggregate per (cube, W): mean spike-flag in trailing 90d
    weekly_ns = weekly.values.astype("datetime64[ns]").astype("int64")
    lower_ns = (weekly - pd.Timedelta(days=TRAILING_ATTN_DAYS)).values.astype("datetime64[ns]").astype("int64")
    out: dict[str, np.ndarray] = {c: np.full(len(weekly), np.nan) for c in cubes}
    cubes_set = set(cubes)
    for cube, sub in buys.groupby("cube"):
        if cube not in cubes_set:
            continue
        sub_sorted = sub.sort_values("dt")
        dts_ns = sub_sorted["dt"].values.astype("datetime64[ns]").astype("int64")
        flags = sub_sorted["spike"].values.astype(float)
        col = out[cube]
        lo = np.searchsorted(dts_ns, lower_ns, side="left")
        hi = np.searchsorted(dts_ns, weekly_ns, side="right")
        for w_i in range(len(weekly)):
            if hi[w_i] > lo[w_i]:
                window = flags[lo[w_i]:hi[w_i]]
                non_nan = window[~np.isnan(window)]
                if len(non_nan) > 0:
                    col[w_i] = float(non_nan.mean())
    df = pd.DataFrame(out, index=weekly)
    df.index.name = "date"
    return df


def compute_concentration(events: pd.DataFrame, cubes: list[str], weekly: pd.DatetimeIndex) -> pd.DataFrame:
    """Per cube C, per week W: mean HHI of weight CHANGES across C's events in [W-30d, W].

    HHI per event = sum_i (target_w_i - prev_w_i)^2 over rebalancing_histories of that event.
    Since our flat events frame has one row per (cube, event, stock-delta), we group by
    (cube, dt) to recover one HHI per event.
    """
    # Group to per-event HHI
    events = events.copy()
    events["delta"] = events["target_weight"] - events["prev_weight"]
    events["delta_sq"] = events["delta"] ** 2
    per_event = events.groupby(["cube", "dt"])["delta_sq"].sum().reset_index()
    per_event = per_event.rename(columns={"delta_sq": "event_hhi"})
    per_event = per_event.sort_values(["cube", "dt"]).reset_index(drop=True)
    print(f"[+] per-event HHI: {len(per_event)} events, mean HHI={per_event['event_hhi'].mean():.4f} max={per_event['event_hhi'].max():.4f}")

    weekly_ns = weekly.values.astype("datetime64[ns]").astype("int64")
    lower_ns = (weekly - pd.Timedelta(days=TRAILING_CONC_DAYS)).values.astype("datetime64[ns]").astype("int64")
    out: dict[str, np.ndarray] = {c: np.full(len(weekly), np.nan) for c in cubes}
    cubes_set = set(cubes)
    for cube, sub in per_event.groupby("cube"):
        if cube not in cubes_set:
            continue
        dts_ns = sub["dt"].values.astype("datetime64[ns]").astype("int64")
        hhi_vals = sub["event_hhi"].values.astype(float)
        col = out[cube]
        lo = np.searchsorted(dts_ns, lower_ns, side="left")
        hi = np.searchsorted(dts_ns, weekly_ns, side="right")
        for w_i in range(len(weekly)):
            if hi[w_i] > lo[w_i]:
                col[w_i] = float(hhi_vals[lo[w_i]:hi[w_i]].mean())
    df = pd.DataFrame(out, index=weekly)
    df.index.name = "date"
    return df


def compose(features: list[pd.DataFrame], names: list[str], eligibility: pd.DataFrame) -> pd.DataFrame:
    """Per week: mask each feature to eligible cohort, z-normalize, nanmean, rank-pct."""
    z_arrays = []
    for f, name in zip(features, names):
        f_eligible = f.where(eligibility, other=np.nan)
        m = f_eligible.mean(axis=1)
        s = f_eligible.std(axis=1).replace(0, np.nan)
        z = f_eligible.sub(m, axis=0).div(s, axis=0)
        z_arrays.append(z.values)
        print(f"[+] feature {name}: eligible-cell count {int(f_eligible.notna().sum().sum())}, z-mean ~0 ({float(np.nanmean(z.values)):.3f})")
    stacked = np.stack(z_arrays, axis=0)
    with np.errstate(invalid="ignore"):
        avg_arr = np.nanmean(stacked, axis=0)
    avg = pd.DataFrame(avg_arr, index=features[0].index, columns=features[0].columns)
    pct = avg.rank(axis=1, pct=True, method="average")
    pct.index.name = "date"
    return pct


def main() -> int:
    cubes = discover_candidate_cubes()
    weekly = load_weekly_index()
    print(f"[+] candidate cube pool: {len(cubes)} (all rebalance JSONs); weeks: {len(weekly)} ({weekly.min().date()} → {weekly.max().date()})")

    events = parse_events(cubes)
    print(f"[+] buys: {int(events['is_buy'].sum())}/{len(events)}")

    cube_dts = event_dts_per_cube(events)

    eligibility = compute_eligibility(cube_dts, cubes, weekly)
    print(f"[+] eligibility: {int(eligibility.sum().sum())} (cube, week) cells eligible (>= {ELIGIBILITY_MIN_EVENTS} events in trailing {ELIGIBILITY_WINDOW_DAYS}d)")
    weekly_eligible_counts = eligibility.sum(axis=1)
    yearly_avg = weekly_eligible_counts.groupby(eligibility.index.year).mean().round(1)
    print(f"[+] avg eligible cubes/week by year:\n{yearly_avg.to_string()}")

    turnover = compute_turnover(cube_dts, cubes, weekly)
    lag = compute_lag(events, cubes, weekly)
    attn = compute_attention_spike(events, cubes, weekly)
    conc = compute_concentration(events, cubes, weekly)

    composite = compose(
        [turnover, lag, attn, conc],
        ["turnover_90d", "lag_30d", "attention_spike_90d", "concentration_30d"],
        eligibility,
    )
    eligible_non_null = int((composite.notna() & eligibility).sum().sum())
    print(f"[+] composite: {composite.shape}, non-null cells: {int(composite.notna().sum().sum())}, of which on eligible cells: {eligible_non_null}")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    composite.to_csv(OUT_PATH)
    turnover.to_csv(TURNOVER_PATH)
    lag.to_csv(LAG_PATH)
    attn.to_csv(ATTN_PATH)
    conc.to_csv(CONC_PATH)
    print(f"[+] wrote: {OUT_PATH}")
    print(f"            {TURNOVER_PATH}")
    print(f"            {LAG_PATH}")
    print(f"            {ATTN_PATH}")
    print(f"            {CONC_PATH}")

    non_empty = composite.dropna(how="all")
    if len(non_empty) == 0:
        print("[!] composite empty — diagnose before commit")
        return 1
    last = non_empty.iloc[-1]
    print(f"\n[+] last non-empty week ({last.name.date()}) distribution:")
    print(last.describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
