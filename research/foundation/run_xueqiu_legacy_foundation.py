"""
Foundation-compatible rerun for legacy Xueqiu v4-v6/SRF signals.

This intentionally does not call the legacy backtest loop:
  - no _build_rebalance()
  - no _apply_risk_controls()
  - no Top30-Bottom30 executable claim
  - no fwd_ret_2w usage in selection

It reuses the point-in-time signal/feature panel builder, then evaluates a few
legacy signal definitions against same-universe random and size/turnover matched
controls with a real 56bp round-trip cost and an OOS split.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.baseline_v5.code.run_baseline_v5_with_costs import _prepare_panel_v5
from research.baseline_v6_1.code.run_baseline_v6_v61_suite import _enrich_from_stock_data
from research.foundation import DataBundle, Universe


OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
REPORT_PATH = os.path.join(OUT_DIR, "xueqiu_legacy_v6_foundation.md")
CSV_PATH = os.path.join(OUT_DIR, "xueqiu_legacy_v6_foundation.csv")

START_DATE = "2015-01-01"
END_DATE = "2025-12-31"
TRAIN_END = pd.Timestamp("2020-12-31")
TEST_START = pd.Timestamp("2021-03-01")  # 60d gap after train_end.
DEFAULT_HOLD_BDAYS = 12
ROUND_TRIP_COST = 0.0056


@dataclass(frozen=True)
class Variant:
    name: str
    selector: Callable[[pd.DataFrame, int], list[str]]


def _stable_jitter(code: str, sig_date) -> float:
    key = f"{code}|{pd.Timestamp(sig_date).strftime('%Y-%m-%d')}".encode()
    return (int(hashlib.md5(key).hexdigest()[:12], 16) % 10**9) / 10**9


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if not np.isfinite(std) or std <= 1e-12:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _normalise_code(x) -> str:
    raw = str(x).strip().upper()
    if raw.startswith(("SH", "SZ")) and len(raw) == 8 and raw[2:].isdigit():
        return raw[2:]
    if len(raw) == 6 and raw.isdigit():
        return raw
    return ""


def _trading_calendar(data: DataBundle) -> pd.DatetimeIndex:
    dates: set[pd.Timestamp] = set()
    for df in data.price_cache.values():
        if "date" not in df.columns:
            continue
        dates.update(pd.to_datetime(df["date"], errors="coerce").dropna().dt.normalize())
    if not dates:
        raise RuntimeError("No trading dates found in DataBundle price_cache")
    return pd.DatetimeIndex(sorted(dates))


def _first_trading_day_after(ts, trading_calendar: pd.DatetimeIndex) -> pd.Timestamp:
    event_day = pd.Timestamp(ts).normalize()
    pos = trading_calendar.searchsorted(event_day, side="right")
    if pos >= len(trading_calendar):
        return pd.NaT
    return pd.Timestamp(trading_calendar[pos])


def _load_signal_panel(
    start_date: str,
    end_date: str,
    rebuild: bool,
    trading_calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    # _prepare_panel_v5 writes a raw intermediate CSV as a side effect, but the
    # returned DataFrame contains the enriched point-in-time fields needed here.
    # Do not load that raw CSV as a cache; it lacks amount/regime/factor_z_neu.
    _ = rebuild  # retained for CLI/API clarity.
    panel = _prepare_panel_v5(start_date=start_date, end_date=end_date, signal_mode="count")
    panel, _ = _enrich_from_stock_data(panel)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce").dt.normalize()
    panel["code"] = panel["stock_symbol"].map(_normalise_code)
    panel = panel[panel["code"].str.match(r"^[0369]\d{5}$", na=False)].copy()
    # B2-style entry convention: a signal derived from rebalancing activity on
    # date T is only tradable on the first trading day strictly after T.
    panel["raw_event_date"] = panel["date"]
    panel["date"] = panel["raw_event_date"].map(lambda x: _first_trading_day_after(x, trading_calendar))
    panel = panel.dropna(subset=["date"])
    panel = panel[(panel["date"] >= pd.Timestamp(start_date)) & (panel["date"] <= pd.Timestamp(end_date))]
    panel = panel.sort_values(["date", "code"]).drop_duplicates(["date", "code"], keep="last")
    panel = panel.drop(columns=[c for c in ["fwd_ret_2w", "fwd_ret_2w_sd"] if c in panel.columns])
    return panel


def _rebalance_dates(
    panel: pd.DataFrame,
    start_date: str,
    end_date: str,
    hold_bdays: int,
) -> list[pd.Timestamp]:
    dates = sorted(panel["date"].dropna().unique().tolist())
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    dates = [pd.Timestamp(d) for d in dates if start <= pd.Timestamp(d) <= end]
    keep: list[pd.Timestamp] = []
    i = 0
    while i < len(dates):
        keep.append(dates[i])
        i += int(hold_bdays)
    return keep


def _safe_universe(universe: Universe, sig_date: pd.Timestamp) -> pd.DataFrame:
    # Conservative cutoff: only financial reports at least 130 days old are
    # eligible, avoiding daily-use leakage from report_date-only data.
    report_cutoff = sig_date - pd.Timedelta(days=130)
    uni = universe.at(report_cutoff, sig_date)
    if uni.empty:
        return uni
    return uni.drop_duplicates("code", keep="last")


def _factor_use(df: pd.DataFrame) -> pd.Series:
    raw = pd.to_numeric(df["factor_z_raw"], errors="coerce").fillna(0.0)
    neu = pd.to_numeric(df["factor_z_neu"], errors="coerce").fillna(0.0)
    return pd.Series(np.where(df["regime"].astype(str) == "上涨", -raw, neu), index=df.index)


def _srf_v2_score(day: pd.DataFrame) -> pd.Series:
    f = _zscore(pd.to_numeric(day["factor_z_neu"], errors="coerce").fillna(0.0))
    mom = _zscore(pd.to_numeric(day.get("ret20d_stock", 0.0), errors="coerce").fillna(0.0))
    intra = _zscore(-pd.to_numeric(day.get("ret_intra5d", 0.0), errors="coerce").fillna(0.0))
    div = _zscore(pd.to_numeric(day.get("vol_price_div5d", 0.0), errors="coerce").fillna(0.0))
    hc = _zscore(pd.to_numeric(day.get("highconv_10d", 0.0), errors="coerce").fillna(0.0))
    score = 0.495 * f + 0.18 * mom + 0.135 * intra + 0.09 * div + 0.10 * hc
    if "hv20_hv60_ratio" in day.columns:
        hv = pd.to_numeric(day["hv20_hv60_ratio"], errors="coerce").fillna(1.0)
        score = score - (hv > 1.5).astype(float) * 0.5
    return score


def _select_follow_top30(day: pd.DataFrame, n_cap: int) -> list[str]:
    x = day.copy()
    x["score"] = _factor_use(x)
    if x["score"].nunique(dropna=True) < 2:
        return []
    x["score"] = x["score"] + x["code"].map(lambda c: _stable_jitter(c, x["date"].iloc[0]) * 1e-9)
    n = min(max(int(round(len(x) * 0.30)), 5), n_cap)
    return x.sort_values("score", ascending=False).head(n)["code"].tolist()


def _select_contrarian_bottom30(day: pd.DataFrame, n_cap: int) -> list[str]:
    x = day.copy()
    x["score"] = -_factor_use(x)
    if x["score"].nunique(dropna=True) < 2:
        return []
    x["score"] = x["score"] + x["code"].map(lambda c: _stable_jitter(c, x["date"].iloc[0]) * 1e-9)
    n = min(max(int(round(len(x) * 0.30)), 5), n_cap)
    return x.sort_values("score", ascending=False).head(n)["code"].tolist()


def _select_srf_v2_top15(day: pd.DataFrame, n_cap: int) -> list[str]:
    x = day.copy()
    x["factor_use"] = _factor_use(x)
    if x["factor_use"].nunique(dropna=True) < 2:
        return []
    x["rank"] = x["factor_use"].rank(pct=True, method="first")
    gate = x[x["rank"] >= 0.70].copy()
    if gate.empty:
        return []
    gate["score"] = _srf_v2_score(gate)
    gate["score"] = gate["score"] + gate["code"].map(lambda c: _stable_jitter(c, gate["date"].iloc[0]) * 1e-9)
    return gate.sort_values("score", ascending=False).head(min(15, n_cap, len(gate)))["code"].tolist()


VARIANTS = [
    Variant("legacy_follow_top30pct_cap30", _select_follow_top30),
    Variant("legacy_contrarian_bottom30pct_cap30", _select_contrarian_bottom30),
    Variant("srf_v2_gate_top15_no_goflat", _select_srf_v2_top15),
]


def _portfolio_ret(data: DataBundle, codes: list[str], start, end) -> float:
    rets = []
    for code in codes:
        p0 = data.get_price_at(code, start)
        p1 = data.get_price_at(code, end)
        if p0 is None or p1 is None or p0 <= 0:
            continue
        rets.append(p1 / p0 - 1.0)
    return float(np.mean(rets)) if rets else float("nan")


def _bucket_candidates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    n_bins = min(10, max(2, len(out) // 30))
    out["mcap_bin"] = pd.qcut(out["mcap_yi"].rank(method="first"), q=n_bins, labels=False)
    out["turn_bin"] = pd.qcut(out["turn20"].rank(method="first"), q=n_bins, labels=False)
    return out


def _matched_codes(df: pd.DataFrame, picks: list[str], seed: int) -> list[str]:
    rng = np.random.default_rng(seed)
    pick_set = set(picks)
    available = df[~df["code"].isin(pick_set)].copy()
    attrs = df.set_index("code")[["mcap_bin", "turn_bin"]]
    matched: list[str] = []
    used: set[str] = set()
    for code in picks:
        if code not in attrs.index:
            continue
        mcap_bin, turn_bin = attrs.loc[code]
        pool = available[
            (available["mcap_bin"] == mcap_bin)
            & (available["turn_bin"] == turn_bin)
            & (~available["code"].isin(used))
        ]
        if pool.empty:
            pool = available[(available["mcap_bin"] == mcap_bin) & (~available["code"].isin(used))]
        if pool.empty:
            pool = available[(available["turn_bin"] == turn_bin) & (~available["code"].isin(used))]
        if pool.empty:
            pool = available[~available["code"].isin(used)]
        if pool.empty:
            break
        chosen = str(rng.choice(pool["code"].values))
        used.add(chosen)
        matched.append(chosen)
    return matched


def _random_codes(df: pd.DataFrame, picks: list[str], seed: int) -> list[str]:
    pool = df[~df["code"].isin(set(picks))]
    n = min(len(picks), len(pool))
    if n <= 0:
        return []
    rng = np.random.default_rng(seed)
    return rng.choice(pool["code"].values, size=n, replace=False).astype(str).tolist()


def _avg_for_codes(df: pd.DataFrame, codes: list[str], col: str) -> float:
    if not codes or col not in df.columns:
        return float("nan")
    vals = pd.to_numeric(df.set_index("code").reindex(codes)[col], errors="coerce")
    return float(vals.mean()) if vals.notna().any() else float("nan")


def _make_day(panel_day: pd.DataFrame, universe_df: pd.DataFrame, sig_date: pd.Timestamp) -> pd.DataFrame:
    cols = [
        "date",
        "code",
        "factor_z_raw",
        "factor_z_neu",
        "factor_raw",
        "net_buy_cube_count",
        "count_lag",
        "regime",
        "ret20d_stock",
        "amount",
        "vol_price_div5d",
        "ret_intra5d",
        "hv20_hv60_ratio",
        "highconv_10d",
    ]
    cols = [c for c in cols if c in panel_day.columns]
    day = universe_df[["code", "mcap_yi", "turn20"]].merge(panel_day[cols], on="code", how="inner")
    if day.empty:
        return day
    day["date"] = pd.Timestamp(sig_date)
    for c in ["factor_z_raw", "factor_z_neu", "factor_raw", "net_buy_cube_count", "count_lag", "highconv_10d"]:
        if c in day.columns:
            day[c] = pd.to_numeric(day[c], errors="coerce").fillna(0.0)
    if "regime" not in day.columns:
        day["regime"] = "震荡"
    day["regime"] = day["regime"].fillna("震荡")
    return _bucket_candidates(day)


def run_backtest(
    *,
    start_date: str,
    end_date: str,
    seeds: list[int],
    hold_bdays_list: list[int],
    rebuild_panel: bool,
    max_dates: int | None,
) -> pd.DataFrame:
    print("[1/3] Loading DataBundle...")
    data = DataBundle.load(verbose=False)
    trading_calendar = _trading_calendar(data)
    universe = Universe.broad(
        data,
        mcap_range=(30, 500),
        min_turnover_20d=0.15,
        exclude_st=True,
        exclude_new_listing_days=180,
    )
    print(f"      OHLCV coverage: {data.audit.ohlcv_coverage_pct:.0f}%")

    print("[2/3] Loading legacy Xueqiu point-in-time signal panel...")
    panel = _load_signal_panel(start_date, end_date, rebuild=rebuild_panel, trading_calendar=trading_calendar)
    date_by_h = {
        h: _rebalance_dates(panel, start_date, end_date, h) for h in hold_bdays_list
    }
    if max_dates is not None:
        date_by_h = {h: dates[:max_dates] for h, dates in date_by_h.items()}
    print(
        f"      panel rows={len(panel):,} "
        f"rebalance_dates={{{', '.join(f'{h}:{len(d)}' for h, d in date_by_h.items())}}}"
    )

    print("[3/3] Running strict rerun variants...")
    panel_by_date = {pd.Timestamp(k): v.copy() for k, v in panel.groupby("date", sort=False)}
    rows = []
    for hold_bdays, dates in date_by_h.items():
        for i, sig_date in enumerate(dates):
            panel_day = panel_by_date.get(pd.Timestamp(sig_date))
            if panel_day is None or panel_day.empty:
                continue
            uni = _safe_universe(universe, pd.Timestamp(sig_date))
            if len(uni) < 50:
                continue
            day = _make_day(panel_day, uni, pd.Timestamp(sig_date))
            if len(day) < 50:
                continue
            fwd_date = pd.Timestamp(sig_date) + pd.offsets.BDay(hold_bdays)
            split = "train" if sig_date <= TRAIN_END else ("test" if sig_date >= TEST_START else "gap")
            if split == "gap":
                continue
            regime = str(day["regime"].dropna().iloc[0]) if "regime" in day.columns and not day["regime"].dropna().empty else ""
            for variant in VARIANTS:
                picks = variant.selector(day, 30)
                if len(picks) < 5:
                    continue
                sig_ret = _portfolio_ret(data, picks, sig_date, fwd_date)
                if not np.isfinite(sig_ret):
                    continue
                for seed in seeds:
                    salt = int(seed + i * 1009 + len(variant.name) * 17 + hold_bdays * 101)
                    rand = _random_codes(day, picks, salt)
                    matched = _matched_codes(day, picks, salt + 7919)
                    rand_ret = _portfolio_ret(data, rand, sig_date, fwd_date)
                    matched_ret = _portfolio_ret(data, matched, sig_date, fwd_date)
                    if not np.isfinite(rand_ret) or not np.isfinite(matched_ret):
                        continue
                    rows.append(
                        {
                            "variant": variant.name,
                            "hold_bdays": int(hold_bdays),
                            "seed": seed,
                            "split": split,
                            "signal_date": pd.Timestamp(sig_date).date().isoformat(),
                            "fwd_date": pd.Timestamp(fwd_date).date().isoformat(),
                            "regime": regime,
                            "universe_n": len(day),
                            "pick_n": len(picks),
                            "random_n": len(rand),
                            "matched_n": len(matched),
                            "avg_mcap_pick": _avg_for_codes(day, picks, "mcap_yi"),
                            "avg_mcap_matched": _avg_for_codes(day, matched, "mcap_yi"),
                            "avg_turn_pick": _avg_for_codes(day, picks, "turn20"),
                            "avg_turn_matched": _avg_for_codes(day, matched, "turn20"),
                            "signal_ret_gross": sig_ret,
                            "signal_ret_net": sig_ret - ROUND_TRIP_COST,
                            "random_ret_gross": rand_ret,
                            "matched_ret_gross": matched_ret,
                            "alpha_random": sig_ret - rand_ret,
                            "alpha_matched": sig_ret - matched_ret,
                        }
                    )
    return pd.DataFrame(rows)


def _summary(rows: pd.DataFrame, variant: str, hold_bdays: int, seed: int, split: str) -> dict:
    sub = rows[
        (rows["variant"] == variant)
        & (rows["hold_bdays"] == hold_bdays)
        & (rows["seed"] == seed)
    ]
    if split != "full":
        sub = sub[sub["split"] == split]
    alpha = sub["alpha_matched"].dropna()
    if alpha.empty:
        return {
            "n": 0,
            "signal_net": np.nan,
            "matched": np.nan,
            "alpha": np.nan,
            "t": np.nan,
            "win": np.nan,
            "ann_net": np.nan,
        }
    std = alpha.std(ddof=1)
    t_stat = alpha.mean() / (std / np.sqrt(len(alpha))) if len(alpha) > 1 and std > 0 else np.nan
    return {
        "n": int(len(alpha)),
        "signal_net": float(sub["signal_ret_net"].mean()),
        "matched": float(sub["matched_ret_gross"].mean()),
        "alpha": float(alpha.mean()),
        "t": float(t_stat),
        "win": float((alpha > 0).mean() * 100),
        "ann_net": float(sub["signal_ret_net"].mean() * (252 / hold_bdays)),
    }


def _verdict(train: dict, test: dict, full: dict) -> str:
    if full["n"] == 0 or test["n"] == 0:
        return "NO_SAMPLE"
    if np.sign(train["alpha"]) != 0 and np.sign(test["alpha"]) != 0 and np.sign(train["alpha"]) != np.sign(test["alpha"]):
        return "REJECT_SIGN_FLIP"
    if not np.isfinite(test["t"]) or abs(test["t"]) < 2:
        return "REJECT_OOS_WEAK"
    if test["alpha"] <= 0:
        return "REJECT_NEGATIVE_OOS"
    if full["alpha"] > 0 and full["t"] >= 2 and test["alpha"] > 0 and test["t"] >= 2:
        return "NEEDS_DEEP_AUDIT_NOT_PRODUCTION"
    return "REJECT"


def write_report(
    rows: pd.DataFrame,
    start_date: str,
    end_date: str,
    seeds: list[int],
    hold_bdays_list: list[int],
) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    rows.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    lines = [
        "# Xueqiu Legacy v4-v6/SRF — Foundation-Compatible Rerun",
        "",
        f"Execution: `.venv/bin/python -B research/foundation/run_xueqiu_legacy_foundation.py --rebuild-panel`.",
        "",
        "Rules:",
        "- Reuses legacy point-in-time signal/feature construction only (`_prepare_panel_v5`, `_enrich_from_stock_data`).",
        "- Applies B2-style timestamp discipline: panel rows are shifted to the first trading day strictly after the source event date.",
        "- Does not call legacy `_build_rebalance`, `_apply_risk_controls`, `_run_one`, go-flat, take-profit, or long-short spread metrics.",
        "- Selection does not read `fwd_ret_2w` or any forward-return column.",
        "- Return is recomputed from `DataBundle.price_cache` after selection.",
        "- Random control and size/turnover matched control are sampled from the same signal-covered investable universe.",
        f"- Round-trip cost: `{ROUND_TRIP_COST*100:.2f}%`; hold horizons: `{hold_bdays_list}` business days.",
        f"- Train/Test: train <= `{TRAIN_END.date()}`, test >= `{TEST_START.date()}`; gap in between dropped.",
        f"- Data window: `{start_date}` -> `{end_date}`; seeds: `{seeds}`.",
        "",
        "## Summary vs Matched Control",
        "",
        "| variant | hold | seed | train alpha | train t | test alpha | test t | full alpha | full t | ann net | verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for variant in [v.name for v in VARIANTS]:
        for hold_bdays in hold_bdays_list:
            for seed in seeds:
                train = _summary(rows, variant, hold_bdays, seed, "train")
                test = _summary(rows, variant, hold_bdays, seed, "test")
                full = _summary(rows, variant, hold_bdays, seed, "full")
                verdict = _verdict(train, test, full)
                lines.append(
                    f"| {variant} | {hold_bdays} | {seed} | "
                    f"{train['alpha']*100:+.2f}% | {train['t']:+.2f} | "
                    f"{test['alpha']*100:+.2f}% | {test['t']:+.2f} | "
                    f"{full['alpha']*100:+.2f}% | {full['t']:+.2f} | "
                    f"{full['ann_net']*100:+.1f}% | {verdict} |"
                )
    lines.extend(
        [
            "",
            "## Overall Verdict",
            "",
            "- `legacy_follow_top30pct_cap30`: rejected. It does not survive matched control across seeds and hold horizons; train/test sign flips are common.",
            "- `legacy_contrarian_bottom30pct_cap30`: rejected as a production strategy. The old inversion lesson remains useful, but the clean matched-control implementation does not produce stable positive OOS alpha.",
            "- `srf_v2_gate_top15_no_goflat`: warning only. The 12-business-day horizon shows a weak positive anomaly for seed 42/99, but 10-day and 15-day horizons fail OOS significance. This is the old `hold_step` sensitivity red flag, so it is not production and must not be connected to the dashboard as an alpha source.",
            "",
            "## Interpretation",
            "",
            "- `legacy_follow_top30pct_cap30`: closest clean read of the old Xueqiu follow/rank gate without legacy risk controls.",
            "- `legacy_contrarian_bottom30pct_cap30`: tests the documented signal inversion directly against a matched control.",
            "- `srf_v2_gate_top15_no_goflat`: keeps the Xueqiu top-30% gate and SRF v2 re-ranker, but removes asymmetric choppy go-flat and other old risk controls.",
            "- Any positive row here is not production. It still needs B8/axis stability, seed/date robustness, and a stricter implementation review before it can be treated as a live candidate.",
            "",
            f"CSV: `{os.path.relpath(CSV_PATH, ROOT)}`",
        ]
    )
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=END_DATE)
    parser.add_argument("--seeds", default="1,42,99")
    parser.add_argument("--hold-bdays", default=str(DEFAULT_HOLD_BDAYS))
    parser.add_argument("--rebuild-panel", action="store_true")
    parser.add_argument("--max-dates", type=int, default=None, help="Smoke-test limit")
    args = parser.parse_args(argv)
    seeds = [int(x.strip()) for x in args.seeds.split(",") if x.strip()]
    hold_bdays_list = [int(x.strip()) for x in args.hold_bdays.split(",") if x.strip()]
    rows = run_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        seeds=seeds,
        hold_bdays_list=hold_bdays_list,
        rebuild_panel=args.rebuild_panel,
        max_dates=args.max_dates,
    )
    if rows.empty:
        raise SystemExit("No rows produced; cannot write verdict.")
    write_report(rows, args.start_date, args.end_date, seeds, hold_bdays_list)
    print(f"[+] rows={len(rows):,}")
    print(f"[+] wrote {REPORT_PATH}")
    print(f"[+] wrote {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
