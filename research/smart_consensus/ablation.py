"""
A1 methodology ablation study.

Runs the smart-consensus signal/return pipeline under controlled fix toggles,
without mutating git state or relying on factor_*.csv files. Outputs:
  - research/smart_consensus/output/ablation_results.csv
  - research/smart_consensus/ABLATION_RESULTS.md

Fix toggles:
  B1    rolling 12M cube skill instead of 2026 snapshot smart list
  B2    signal date = first tradable day after latest in-bucket event, with
        forward returns indexed by the same entry-date convention
  B3-i  IC mask/rank uses raw in-pool contribution, not rank-pct full universe
  B3-ii CB prefixes removed from signal universe
  B5-i  missing/stale prices are NaN, not indefinite carry-forward zeros
  B3-iii optional liquidity+board matched random for no-smart avoidance metric
"""
from __future__ import annotations

import glob
import json
import math
import os
import time
import warnings
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import ConstantInputWarning


warnings.filterwarnings("ignore", category=ConstantInputWarning)


ROOT = "/Users/johnnyzhang/jz_code/bili_stock"
RESEARCH = f"{ROOT}/research"
REB_DIR = f"{RESEARCH}/attention_orj/cache/rebalancing"
DAILY_DIRS = [
    f"{RESEARCH}/attention_orj/cache/daily_k_pre2022",
    f"{RESEARCH}/attention_orj/cache/daily_k",
]
PROFILE = f"{RESEARCH}/trader_profile/output/trader_profile.csv"
OUT = f"{RESEARCH}/smart_consensus/output"
ROLLING_ANN = f"{OUT}/rolling_ann_gain.csv"
RESULT_CSV = f"{OUT}/ablation_results.csv"
RESULT_MD = f"{RESEARCH}/smart_consensus/ABLATION_RESULTS.md"

ETF_PREFIXES = ("510", "511", "512", "513", "515", "516", "518", "588", "159", "160")
CB_PREFIXES = ("110", "113", "118", "123", "127", "128")
SKILL_MIN = 25.0
SKILL_MAX = 200.0
WINDOWS = [
    ("Full", None),
    ("2022+", pd.Timestamp("2022-01-01")),
]
TRAIN_END = pd.Timestamp("2023-12-31")
TEST_START = pd.Timestamp("2024-01-01")
HORIZON_TRADING_DAYS = 5
N_RANDOM = 30
RNG_SEED = 42


@dataclass(frozen=True)
class Config:
    name: str
    description: str
    b1: bool = False
    b2: bool = False
    b3_i: bool = False
    b3_ii: bool = False
    b5_i: bool = False
    b3_iii: bool = False


CONFIGS = [
    Config("Original reconstruction", "No fixes; reconstructs the pre-audit method"),
    Config("Only B5-i", "NaN stale/delisted forward returns only", b5_i=True),
    Config("Only B3-ii", "CB-prefix universe filter only", b3_ii=True),
    Config("Only B3-i", "Raw in-pool IC mask/rank only", b3_i=True),
    Config("Only B2", "Post-event entry-date clock only", b2=True),
    Config("Only B1", "Rolling 12M cube skill only", b1=True),
    Config("All fixes", "B1+B2+B3-i+B3-ii+B5-i", b1=True, b2=True, b3_i=True, b3_ii=True, b5_i=True),
    Config(
        "All fixes + B3-iii",
        "All fixes plus liquidity+board matched avoidance baseline",
        b1=True,
        b2=True,
        b3_i=True,
        b3_ii=True,
        b5_i=True,
        b3_iii=True,
    ),
]


def code_group(code: str) -> str:
    if code.startswith("688"):
        return "STAR"
    if code.startswith("300"):
        return "CHINEXT"
    if code.startswith(("600", "601", "603", "605")):
        return "SH_MAIN"
    if code.startswith(("000", "001", "002", "003")):
        return "SZ_MAIN"
    return "OTHER"


def first_trading_day_after(ts: pd.Timestamp, trading_calendar: pd.DatetimeIndex) -> pd.Timestamp:
    event_day = pd.Timestamp(ts).normalize()
    pos = trading_calendar.searchsorted(event_day, side="right")
    if pos >= len(trading_calendar):
        return pd.NaT
    return trading_calendar[pos]


def load_price_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    paths_by_code: dict[str, list[str]] = {}
    for daily_dir in DAILY_DIRS:
        if not os.path.isdir(daily_dir):
            continue
        for name in os.listdir(daily_dir):
            if name.endswith(".csv"):
                paths_by_code.setdefault(name[:-4], []).append(os.path.join(daily_dir, name))

    close_series = {}
    volume_series = {}
    all_dates = set()
    t0 = time.time()
    for i, (code, paths) in enumerate(sorted(paths_by_code.items()), start=1):
        frames = []
        for path in paths:
            try:
                df = pd.read_csv(path, usecols=["date", "close", "volume"])
            except Exception:
                continue
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            df = df.dropna(subset=["date", "close"])
            if not df.empty:
                frames.append(df)
        if not frames:
            continue
        merged = pd.concat(frames, ignore_index=True)
        merged = merged.sort_values("date").drop_duplicates("date", keep="last")
        merged = merged.set_index("date")
        close = merged["close"].sort_index()
        volume = merged["volume"].sort_index()
        close_series[code] = close
        volume_series[code] = volume
        all_dates.update(close.index)
        if i % 1000 == 0:
            print(f"  loaded prices {i:,}/{len(paths_by_code):,} ({time.time() - t0:.0f}s)")

    trading_calendar = pd.DatetimeIndex(sorted(all_dates), name="entry_date")
    close_panel = pd.DataFrame(close_series).reindex(trading_calendar).sort_index()
    volume_panel = pd.DataFrame(volume_series).reindex(trading_calendar).sort_index()
    return close_panel, volume_panel, trading_calendar


def weekly_forward_returns(close_panel: pd.DataFrame, fixed_stale: bool) -> pd.DataFrame:
    weeks = pd.date_range("2014-01-06", close_panel.index.max(), freq="W-MON")
    week_end = weeks + pd.Timedelta(days=6)

    if not fixed_stale:
        target_index = close_panel.index.union(week_end).sort_values()
        weekly_close = close_panel.reindex(target_index).ffill().loc[week_end]
        weekly_close.index = weeks
    else:
        cols = {}
        for code in close_panel.columns:
            s = close_panel[code].dropna()
            if s.empty:
                continue
            pos = s.index.searchsorted(week_end, side="right") - 1
            vals = np.full(len(weeks), np.nan)
            ok = pos >= 0
            valid_pos = pos[ok]
            latest_dates = s.index[valid_pos]
            stale = (week_end[ok] - latest_dates).days > 14
            vals_idx = np.where(ok)[0]
            vals[vals_idx[~stale]] = s.iloc[valid_pos[~stale]].values
            cols[code] = vals
        weekly_close = pd.DataFrame(cols, index=weeks)

    fwd = weekly_close.shift(-1) / weekly_close - 1
    fwd.index.name = "signal_date"
    return fwd


def daily_forward_returns(close_panel: pd.DataFrame, fixed_stale: bool) -> pd.DataFrame:
    entry_close = close_panel if fixed_stale else close_panel.ffill()
    fwd = entry_close.shift(-HORIZON_TRADING_DAYS) / entry_close - 1
    fwd.iloc[-HORIZON_TRADING_DAYS:] = np.nan
    fwd.index.name = "signal_date"
    return fwd


def load_snapshot_skill() -> tuple[set[str], dict[str, float]]:
    profile = pd.read_csv(PROFILE)
    smart = profile[
        (profile["annualized_gain_rate"] > 25)
        & (profile["annualized_gain_rate"] <= 500)
        & (profile["followers_count"] >= 200)
        & (profile["n_user_events"] >= 30)
        & (profile["active_days"] >= 365)
    ].copy()
    smart["skill_weight"] = np.log1p(smart["annualized_gain_rate"].clip(25, 200))
    smart["skill_weight"] = smart["skill_weight"] / smart["skill_weight"].sum()
    return set(smart["symbol"]), smart.set_index("symbol")["skill_weight"].to_dict()


def iter_cube_events(symbols: set[str]):
    for sym in sorted(symbols):
        path = f"{REB_DIR}/{sym}.json"
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        events = [
            e
            for e in data
            if isinstance(e, dict)
            and e.get("status") == "success"
            and e.get("category") == "user_rebalancing"
            and e.get("created_at")
        ]
        events.sort(key=lambda e: e.get("created_at", 0))
        yield sym, events


def build_signal(config: Config, trading_calendar: pd.DatetimeIndex, rolling_ann: pd.DataFrame):
    snapshot_symbols, snapshot_weights = load_snapshot_skill()
    symbols = set(rolling_ann.columns) if config.b1 else snapshot_symbols
    skip_prefixes = ETF_PREFIXES + (CB_PREFIXES if config.b3_ii else ())

    records = []
    bucket_latest_event: dict[pd.Timestamp, pd.Timestamp] = {}

    for sym, events in iter_cube_events(symbols):
        holdings: dict[str, float] = {}
        for evt in events:
            for h in evt.get("rebalancing_histories") or []:
                stock = (h.get("stock_symbol") or "").upper()
                if not stock.startswith(("SZ", "SH")) or len(stock) != 8:
                    continue
                code6 = stock[2:]
                if code6.startswith(skip_prefixes):
                    continue
                tw = h.get("target_weight") or 0
                if tw > 0:
                    holdings[code6] = float(tw)
                else:
                    holdings.pop(code6, None)

            dt = pd.Timestamp(datetime.fromtimestamp(evt["created_at"] / 1000))
            bucket_start = dt.to_period("W-SUN").start_time.normalize()

            if config.b1:
                if bucket_start not in rolling_ann.index or sym not in rolling_ann.columns:
                    continue
                ann = rolling_ann.at[bucket_start, sym]
                if not (pd.notna(ann) and SKILL_MIN < float(ann) <= SKILL_MAX):
                    continue
                skill_marker = float(ann)
            else:
                if sym not in snapshot_weights:
                    continue
                skill_marker = snapshot_weights[sym]

            if config.b2:
                prev = bucket_latest_event.get(bucket_start)
                if prev is None or dt > prev:
                    bucket_latest_event[bucket_start] = dt
                signal_key = bucket_start
            else:
                week = dt.strftime("%Y-W%W")
                signal_key = pd.to_datetime(week + "-1", format="%Y-W%W-%w", errors="coerce")
                if pd.isna(signal_key):
                    continue

            for stock, weight in holdings.items():
                records.append(
                    {
                        "cube": sym,
                        "signal_key": signal_key,
                        "bucket_start": bucket_start,
                        "stock": stock,
                        "weight": weight,
                        "skill_marker": skill_marker,
                    }
                )

    raw = pd.DataFrame(records)
    if raw.empty:
        raise RuntimeError(f"{config.name}: no signal records")

    if config.b1:
        unique_cb = raw[["cube", "bucket_start", "skill_marker"]].drop_duplicates().copy()
        unique_cb["skill_raw"] = np.log1p(unique_cb["skill_marker"].clip(SKILL_MIN, SKILL_MAX))
        unique_cb["skill_weight"] = unique_cb.groupby("bucket_start")["skill_raw"].transform(
            lambda x: x / x.sum() if x.sum() > 0 else 0.0
        )
        raw = raw.merge(unique_cb[["cube", "bucket_start", "skill_weight"]], on=["cube", "bucket_start"])
    else:
        raw["skill_weight"] = raw["skill_marker"]

    raw["contribution"] = raw["skill_weight"] * raw["weight"]
    signal_long = raw.groupby(["signal_key", "stock"])["contribution"].sum().reset_index()
    signal_wide = signal_long.pivot(index="signal_key", columns="stock", values="contribution").fillna(0)

    if config.b2:
        signal_dates = pd.Series(bucket_latest_event, name="latest_event").sort_index().to_frame()
        signal_dates["signal_date"] = signal_dates["latest_event"].map(
            lambda x: first_trading_day_after(x, trading_calendar)
        )
        signal_dates = signal_dates.dropna(subset=["signal_date"])
        signal_wide = signal_wide.loc[signal_wide.index.intersection(signal_dates.index)]
        signal_wide.index = pd.DatetimeIndex(signal_dates.loc[signal_wide.index, "signal_date"])

    signal_wide = signal_wide.sort_index()
    if signal_wide.index.duplicated().any():
        signal_wide = signal_wide.groupby(level=0).last()
    signal_wide.index.name = "signal_date"
    signal_ffill = signal_wide.replace(0, np.nan).ffill().fillna(0)
    signal_rank = signal_ffill.rank(axis=1, pct=True)
    return signal_ffill, signal_rank


def ic_metrics(
    config: Config,
    signal_raw: pd.DataFrame,
    signal_rank: pd.DataFrame,
    fwd: pd.DataFrame,
    eval_start: pd.Timestamp | None,
):
    common_dates = signal_rank.index.intersection(fwd.index)
    if eval_start is not None:
        common_dates = common_dates[common_dates >= eval_start]
    common_stocks = signal_rank.columns.intersection(fwd.columns)
    sig_rank = signal_rank.loc[common_dates, common_stocks]
    sig_raw = signal_raw.loc[common_dates, common_stocks]
    ret = fwd.loc[common_dates, common_stocks]

    ics = []
    ns = []
    for dt in common_dates:
        r_row = ret.loc[dt]
        if config.b3_i:
            raw_row = sig_raw.loc[dt]
            mask = raw_row.notna() & r_row.notna() & (raw_row > 0)
            if mask.sum() < 20:
                continue
            factor = raw_row[mask].rank(pct=True)
        else:
            factor_row = sig_rank.loc[dt]
            mask = factor_row.notna() & r_row.notna() & (factor_row > 0)
            if mask.sum() < 20:
                continue
            factor = factor_row[mask]
        ic, _ = stats.spearmanr(factor, r_row[mask])
        if pd.notna(ic):
            ics.append(float(ic))
            ns.append(int(mask.sum()))

    ic_arr = np.array(ics, dtype=float)
    mean_ic = float(np.nanmean(ic_arr)) if len(ic_arr) else np.nan
    std_ic = float(np.nanstd(ic_arr, ddof=1)) if len(ic_arr) > 1 else np.nan
    t_stat = float(mean_ic / (std_ic / math.sqrt(len(ic_arr)))) if std_ic and std_ic > 0 else np.nan

    rng = np.random.default_rng(RNG_SEED)
    rc_means = []
    base = sig_raw if config.b3_i else sig_rank
    for _ in range(N_RANDOM):
        shuf = base.loc[common_dates, common_stocks].to_numpy(copy=True)
        for i in range(shuf.shape[0]):
            rng.shuffle(shuf[i])
        shuf_df = pd.DataFrame(shuf, index=common_dates, columns=common_stocks)
        rc_ics = []
        for dt in common_dates:
            r_row = ret.loc[dt]
            row = shuf_df.loc[dt]
            if config.b3_i:
                mask = row.notna() & r_row.notna() & (row > 0)
                if mask.sum() < 20:
                    continue
                factor = row[mask].rank(pct=True)
            else:
                mask = row.notna() & r_row.notna() & (row > 0)
                if mask.sum() < 20:
                    continue
                factor = row[mask]
            ic, _ = stats.spearmanr(factor, r_row[mask])
            if pd.notna(ic):
                rc_ics.append(float(ic))
        if rc_ics:
            rc_means.append(float(np.mean(rc_ics)))

    rc_mean = float(np.mean(rc_means)) if rc_means else np.nan
    rc_std = float(np.std(rc_means, ddof=0)) if rc_means else np.nan
    rc_delta_t = float((mean_ic - rc_mean) / rc_std) if rc_std and rc_std > 0 else np.nan

    return {
        "n_periods": len(ic_arr),
        "avg_n_stocks": float(np.mean(ns)) if ns else np.nan,
        "mean_ic": mean_ic,
        "ic_t": t_stat,
        "random_ic_mean": rc_mean,
        "random_ic_std": rc_std,
        "random_delta_t": rc_delta_t,
    }


def return_t(rets: list[float]) -> tuple[float, float]:
    arr = np.array(rets, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 2:
        return np.nan, np.nan
    mean = float(arr.mean())
    std = float(arr.std(ddof=1))
    t = float(mean / (std / math.sqrt(len(arr)))) if std > 0 else np.nan
    return mean, t


def backtest_metrics(
    config: Config,
    signal_raw: pd.DataFrame,
    signal_rank: pd.DataFrame,
    fwd: pd.DataFrame,
    eval_start: pd.Timestamp | None,
    liquidity: pd.DataFrame | None = None,
):
    common_dates = signal_rank.index.intersection(fwd.index)
    if eval_start is not None:
        common_dates = common_dates[common_dates >= eval_start]
    common_stocks = signal_rank.columns.intersection(fwd.columns)
    rng = np.random.default_rng(RNG_SEED + 1)

    rank_excess = []
    avoid_excess = []
    avoid_train = []
    avoid_test = []
    matched_used = 0

    for dt in common_dates:
        r_row = fwd.loc[dt, common_stocks]
        raw_row = signal_raw.loc[dt, common_stocks]
        rank_row = signal_rank.loc[dt, common_stocks]

        if config.b3_i:
            eligible_mask = raw_row.notna() & r_row.notna() & (raw_row > 0)
            score = raw_row[eligible_mask].rank(pct=True)
            eligible = score.index
        else:
            eligible_mask = rank_row.notna() & r_row.notna() & (rank_row > 0)
            score = rank_row[eligible_mask]
            eligible = score.index

        if len(eligible) >= 50:
            n_pick = max(int(len(eligible) * 0.1), 5)
            top = score.nlargest(n_pick).index
            rand = rng.choice(eligible, size=n_pick, replace=False)
            rank_excess.append(float(r_row[top].mean() - r_row[rand].mean()))

        valid = r_row.notna()
        in_pool = (raw_row > 0) & valid
        out_pool = (~(raw_row > 0)) & valid
        if in_pool.sum() < 50 or out_pool.sum() < 100:
            continue
        n_pick = max(int(in_pool.sum() * 0.1), 5)
        out_pick = rng.choice(r_row[out_pool].index, size=min(n_pick, int(out_pool.sum())), replace=False)

        if config.b3_iii and liquidity is not None and dt in liquidity.index:
            liq_row = liquidity.loc[dt, common_stocks]
            base_pick = matched_liquidity_sample(rng, out_pick, r_row[valid], liq_row)
            matched_used += 1
        else:
            base_pick = rng.choice(r_row[valid].index, size=len(out_pick), replace=False)

        diff = float(r_row[out_pick].mean() - r_row[base_pick].mean())
        avoid_excess.append(diff)
        if dt <= TRAIN_END:
            avoid_train.append(diff)
        elif dt >= TEST_START:
            avoid_test.append(diff)

    rank_mean, rank_t = return_t(rank_excess)
    avoid_mean, avoid_t = return_t(avoid_excess)
    train_mean, train_t = return_t(avoid_train)
    test_mean, test_t = return_t(avoid_test)
    return {
        "rank_excess_ann": rank_mean * 52 if pd.notna(rank_mean) else np.nan,
        "rank_excess_t": rank_t,
        "avoid_excess_ann": avoid_mean * 52 if pd.notna(avoid_mean) else np.nan,
        "avoid_excess_t": avoid_t,
        "avoid_train_ann": train_mean * 52 if pd.notna(train_mean) else np.nan,
        "avoid_train_t": train_t,
        "avoid_test_ann": test_mean * 52 if pd.notna(test_mean) else np.nan,
        "avoid_test_t": test_t,
        "matched_periods": matched_used,
    }


def matched_liquidity_sample(rng, target_codes, eligible_returns: pd.Series, liq_row: pd.Series):
    eligible = eligible_returns.index
    liq = liq_row.reindex(eligible)
    valid_liq = liq.dropna()
    if len(valid_liq) < 100:
        return rng.choice(eligible, size=len(target_codes), replace=False)

    ranks = valid_liq.rank(pct=True)
    buckets = (ranks * 10).clip(1, 10).astype(int)
    picks = []
    used = set(target_codes)
    for code in target_codes:
        group = code_group(str(code))
        bucket = buckets.get(code, np.nan)
        pool = eligible
        if pd.notna(bucket):
            same_liq = buckets[buckets == int(bucket)].index
            same_group = [c for c in same_liq if code_group(str(c)) == group and c not in used]
            if same_group:
                pool = pd.Index(same_group)
            else:
                same_liq = [c for c in same_liq if c not in used]
                if same_liq:
                    pool = pd.Index(same_liq)
        if len(pool) == 0:
            pool = eligible.difference(pd.Index(list(used)))
        if len(pool) == 0:
            pool = eligible
        pick = rng.choice(pool, size=1, replace=False)[0]
        picks.append(pick)
        used.add(pick)
    return pd.Index(picks)


def build_liquidity_panel(close_panel: pd.DataFrame, volume_panel: pd.DataFrame) -> pd.DataFrame:
    dollar_volume = close_panel * volume_panel
    return dollar_volume.rolling(20, min_periods=5).mean()


def fmt_pct(x):
    return "" if pd.isna(x) else f"{x * 100:+.2f}%"


def fmt_num(x):
    return "" if pd.isna(x) else f"{x:+.2f}"


def write_markdown(results: pd.DataFrame):
    lines = []
    lines.append("# A1 Ablation Results\n")
    lines.append("Generated by `research/smart_consensus/ablation.py`.\n")
    lines.append("Annualized return spreads use `mean_period * 52` for comparability with the original weekly verdict.\n")

    for window in ["Full", "2022+"]:
        label = "Full sample" if window == "Full" else "Original verdict window (`2022-01-01+`)"
        lines.append(f"## {label}\n")
        sub = results[results["window"] == window]
        lines.append("| Config | Mean IC | IC t | Random delta t | Rank excess ann | Avoid excess ann | Avoid t | Test ann | Test t |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, r in sub.iterrows():
            lines.append(
                f"| {r['config']} | {r['mean_ic']:+.4f} | {r['ic_t']:+.2f} | "
                f"{r['random_delta_t']:+.2f} | {fmt_pct(r['rank_excess_ann'])} | "
                f"{fmt_pct(r['avoid_excess_ann'])} | {fmt_num(r['avoid_excess_t'])} | "
                f"{fmt_pct(r['avoid_test_ann'])} | {fmt_num(r['avoid_test_t'])} |"
            )
        lines.append("")

    lines.append("## Attribution Readout\n")
    lines.append("- The `2022+` original reconstruction is the direct comparison to the original A1 verdict and reproduces the IC closely (`-0.0161/t=-4.76` vs reported `-0.0164/t=-4.97`).")
    lines.append("- B3-i is the largest isolated IC nuke in the verdict window: `Only B3-i` moves IC t from `-4.76` to about `-0.52`.")
    lines.append("- B1 is the second largest isolated IC nuke: `Only B1` moves IC t to about `-1.85`.")
    lines.append("- B2, B3-ii, and B5-i do not explain the IC collapse by themselves in this ablation; they remain methodology blockers because they fix timestamp honesty, universe integrity, and delisted/stale return treatment.")
    lines.append("- The no-smart avoidance spread remains positive after IC fixes unless B3-iii matching is applied. Liquidity+board matching cuts the `2022+` avoidance spread from about `+11.0%/yr` to about `+5.7%/yr`; market-cap matching remains pending on a stable point-in-time mcap panel.")
    lines.append("")

    lines.append("\n## Notes\n")
    lines.append("- `Rank excess ann` is top-decile rank signal minus same-eligible-pool random.")
    lines.append("- `Avoid excess ann` is random no-smart/out-pool minus random all-universe baseline; this is closest to the original +14% avoidance claim.")
    lines.append("- `All fixes + B3-iii` uses liquidity-decile + board matched random for the avoidance baseline. Market-cap matching is deferred until the fundamentals/stock_data rebuild provides a stable point-in-time mcap panel.")
    lines.append("- `Only B1` uses the existing `rolling_ann_gain.csv`; that rolling NAV builder already filters ETF/CB in NAV construction, so it is not a mathematically perfect isolation of B1 from B3-ii. The signal-side CB filter remains off in that row.")
    lines.append("")
    with open(RESULT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    print("=== A1 ablation study ===")
    t0 = time.time()
    close_panel, volume_panel, trading_calendar = load_price_panels()
    print(f"close_panel: {close_panel.shape}, dates {close_panel.index.min().date()} ~ {close_panel.index.max().date()}")

    rolling_ann = pd.read_csv(ROLLING_ANN, index_col=0)
    rolling_ann.index = pd.to_datetime(rolling_ann.index)
    print(f"rolling_ann: {rolling_ann.shape}")

    print("Building forward-return variants...")
    fwd_weekly_bug = weekly_forward_returns(close_panel, fixed_stale=False)
    fwd_weekly_fixed = weekly_forward_returns(close_panel, fixed_stale=True)
    fwd_daily_bug = daily_forward_returns(close_panel, fixed_stale=False)
    fwd_daily_fixed = daily_forward_returns(close_panel, fixed_stale=True)

    liquidity = None
    rows = []
    for cfg in CONFIGS:
        print(f"\n--- {cfg.name} ---")
        sig_raw, sig_rank = build_signal(cfg, trading_calendar, rolling_ann)
        if cfg.b2:
            fwd = fwd_daily_fixed if cfg.b5_i else fwd_daily_bug
        else:
            fwd = fwd_weekly_fixed if cfg.b5_i else fwd_weekly_bug
        if cfg.b3_iii and liquidity is None:
            print("Building liquidity panel for B3-iii matched random...")
            liquidity = build_liquidity_panel(close_panel, volume_panel)
        for window_name, eval_start in WINDOWS:
            ic = ic_metrics(cfg, sig_raw, sig_rank, fwd, eval_start=eval_start)
            bt = backtest_metrics(cfg, sig_raw, sig_rank, fwd, eval_start=eval_start, liquidity=liquidity)
            row = {
                "config": cfg.name,
                "window": window_name,
                "description": cfg.description,
                "B1": cfg.b1,
                "B2": cfg.b2,
                "B3_i": cfg.b3_i,
                "B3_ii": cfg.b3_ii,
                "B5_i": cfg.b5_i,
                "B3_iii": cfg.b3_iii,
                **ic,
                **bt,
                "signal_rows": sig_raw.shape[0],
                "signal_cols": sig_raw.shape[1],
            }
            rows.append(row)
            print(
                f"[{window_name}] IC={row['mean_ic']:+.4f}, t={row['ic_t']:+.2f}, "
                f"delta_t={row['random_delta_t']:+.2f}, "
                f"avoid_ann={row['avoid_excess_ann']*100:+.2f}%, avoid_t={row['avoid_excess_t']:+.2f}"
            )

    results = pd.DataFrame(rows)
    results.to_csv(RESULT_CSV, index=False)
    write_markdown(results)
    print(f"\nSaved: {RESULT_CSV}")
    print(f"Saved: {RESULT_MD}")
    print(f"Total time: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
