"""
Clean-factor rerun under research.foundation.

Legacy source:
  research/factors_v2/run_clean_factor_backtest.py

The legacy script showed eye-catching numbers for "clean_dist A" but used its
own daily rebalance loop without Foundation random/matched control. This runner
keeps the factor definitions close to the legacy code and routes execution
through DataBundle, Universe, CostModel, Backtest, random_control=True, and an
explicit train/test split.
"""
import hashlib
import os
import sys
import warnings
import argparse

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
import pandas as pd

from research.foundation import Backtest, CostModel, DataBundle, Universe


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
OUT_CSV = os.path.join(OUT_DIR, "clean_factor_foundation.csv")
OUT_MD = os.path.join(OUT_DIR, "clean_factor_foundation.md")

TRAIN_SPLIT = ("2020-12-31", "2021-01-01")
DEFAULT_SEEDS = [1, 42, 99]
DEFAULT_MODES = ["dist_a", "hvbal_b", "combo_z"]

_COMP_CACHE = {}


def _stable_jitter(code: str) -> float:
    """Tiny deterministic tie-breaker; avoids sorted-code bias on discrete factors."""
    h = hashlib.sha1(str(code).encode("utf-8")).hexdigest()
    u = int(h[:8], 16) / 0xFFFFFFFF
    return (u - 0.5) * 1e-6


def _zscore(values: pd.Series) -> pd.Series:
    std = values.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=values.index)
    return (values - values.mean()) / std


def clean_components(row, price_cache, sig_date):
    """Return legacy clean_dist A and clean_hvbal B using only data <= sig_date."""
    code = str(row["code"])
    key = (code, pd.Timestamp(sig_date).normalize())
    if key in _COMP_CACHE:
        return _COMP_CACHE[key]

    if code not in price_cache:
        _COMP_CACHE[key] = (np.nan, np.nan)
        return _COMP_CACHE[key]

    pf = price_cache[code]
    needed = {"date", "open", "close", "vol"}
    if not needed.issubset(set(pf.columns)):
        _COMP_CACHE[key] = (np.nan, np.nan)
        return _COMP_CACHE[key]

    sub = pf[pf["date"] <= sig_date].tail(80).copy()
    if len(sub) < 56:
        _COMP_CACHE[key] = (np.nan, np.nan)
        return _COMP_CACHE[key]

    o = pd.to_numeric(sub["open"], errors="coerce")
    c = pd.to_numeric(sub["close"], errors="coerce")
    v = pd.to_numeric(sub["vol"], errors="coerce")
    prev_c = c.shift(1)

    # Factor A: clean_dist = -cnt28. Fewer high-position distribution days is better.
    hi28_o = o.rolling(28, min_periods=1).max()
    lo28_o = o.rolling(28, min_periods=1).min()
    o85 = lo28_o + 0.95 * (hi28_o - lo28_o)
    top15o = (o >= o85).astype(float)
    fd15 = ((c < prev_c) & (c <= o) & (v >= 1.15 * v.shift(1))).astype(float)
    cnt28 = (top15o * fd15).rolling(28, min_periods=1).sum()
    factor_a = -float(cnt28.iloc[-1])

    # Factor B: clean_hvbal = high-volume bullish bars minus bearish bars.
    real_yang = ((c > o) & ~(c < prev_c)).astype(float)
    real_yin = ((c < o) & ~(c > prev_c)).astype(float)
    avg_vol20 = v.rolling(20, min_periods=5).mean()
    high_vol = (v > 1.5 * avg_vol20).astype(float)
    hv_bull = (high_vol * real_yang).rolling(56, min_periods=10).sum()
    hv_bear = (high_vol * real_yin).rolling(56, min_periods=10).sum()
    factor_b = float((hv_bull - hv_bear).iloc[-1])

    if pd.isna(factor_a) or pd.isna(factor_b):
        out = (np.nan, np.nan)
    else:
        out = (factor_a, factor_b)
    _COMP_CACHE[key] = out
    return out


class CleanFactorStrategy:
    def __init__(self, mode: str, top_pct: float = 0.20, n_signal_cap: int = 30, hold_days: int = 17):
        self.mode = mode
        self.name = f"clean_factor_{mode}"
        self.top_pct = top_pct
        self.n_signal_cap = n_signal_cap
        self.hold_days = hold_days

    def kind(self):
        return "cross_sectional"

    def select(self, universe_df, price_cache, signal_date):
        rows = []
        for _, r in universe_df.iterrows():
            a, b = clean_components(r.to_dict(), price_cache, signal_date)
            if pd.isna(a) or pd.isna(b):
                continue
            rows.append({
                "code": str(r["code"]),
                "a": a,
                "b": b,
                "jitter": _stable_jitter(str(r["code"])),
            })
        df = pd.DataFrame(rows)
        if df.empty:
            return []

        if self.mode == "dist_a":
            df["factor"] = df["a"] + df["jitter"]
        elif self.mode == "hvbal_b":
            df["factor"] = df["b"] + df["jitter"]
        elif self.mode == "combo_z":
            df["factor"] = _zscore(df["a"]) + _zscore(df["b"]) + df["jitter"]
        else:
            raise ValueError(f"unknown clean factor mode: {self.mode}")

        df = df.dropna(subset=["factor"]).sort_values("factor", ascending=False)
        if df.empty:
            return []
        n_top = max(int(len(df) * self.top_pct), 5)
        n_top = min(n_top, self.n_signal_cap)
        return df.head(n_top)["code"].tolist()


def _get(summary, key):
    return summary.get(key, np.nan) if summary else np.nan


def _verdict(summary):
    alpha = _get(summary, "alpha_mean")
    t_stat = _get(summary, "t_stat")
    if pd.isna(alpha) or pd.isna(t_stat):
        return "INSUFFICIENT"
    if alpha > 0.005 and t_stat > 3.0:
        return "STRONG_POSITIVE"
    if alpha > 0.005 and t_stat > 2.0:
        return "WEAK_POSITIVE"
    if alpha < 0:
        return "REJECT_NEGATIVE"
    return "REJECT_NOT_SIGNIFICANT"


def _row(mode, seed, result):
    return {
        "factor": mode,
        "seed": seed,
        "n_full": _get(result.full_summary, "n"),
        "train_alpha": _get(result.train_summary, "alpha_mean"),
        "train_t": _get(result.train_summary, "t_stat"),
        "test_alpha": _get(result.test_summary, "alpha_mean"),
        "test_t": _get(result.test_summary, "t_stat"),
        "full_alpha": _get(result.full_summary, "alpha_mean"),
        "full_t": _get(result.full_summary, "t_stat"),
        "test_signal_net": _get(result.test_summary, "signal_mean_net"),
        "test_random_gross": _get(result.test_summary, "random_mean_gross"),
        "verdict": _verdict(result.test_summary),
    }


def _fmt_pct(x):
    return "" if pd.isna(x) else f"{x * 100:+.2f}%"


def _fmt_float(x):
    return "" if pd.isna(x) else f"{x:+.2f}"


def _markdown(df):
    lines = [
        "# Clean Factor — Foundation Rerun (2026-05-25)",
        "",
        "Execution: `.venv/bin/python -B research/foundation/run_clean_factor_foundation.py`.",
        "",
        "Legacy source: `research/factors_v2/run_clean_factor_backtest.py`.",
        "",
        "Rules: `DataBundle.load`, broad 30-500亿 universe, top 20% capped at 30, hold_days=17, `CostModel.a_share_retail_swing`, `random_control=True`, train/test split at 2021-01-01. Actual random-control seeds are shown in the table.",
        "",
        "Important caveat: Foundation cross-sectional engine rebalances quarterly. The legacy script rebalanced every 12 trading days. This rerun tests whether the signal survives strict project rails, not whether the legacy high-frequency loop is executable.",
        "",
        "| factor | seed | n | train alpha | train t | test alpha | test t | full alpha | full t | verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for _, r in df.iterrows():
        lines.append(
            "| "
            + " | ".join([
                str(r["factor"]),
                str(int(r["seed"])),
                str(int(r["n_full"])) if not pd.isna(r["n_full"]) else "",
                _fmt_pct(r["train_alpha"]),
                _fmt_float(r["train_t"]),
                _fmt_pct(r["test_alpha"]),
                _fmt_float(r["test_t"]),
                _fmt_pct(r["full_alpha"]),
                _fmt_float(r["full_t"]),
                str(r["verdict"]),
            ])
            + " |"
        )

    lines.extend([
        "",
        "## Verdict",
        "",
        "This file is an audit artifact, not a production recommendation. A positive row only means the legacy clean factor deserves deeper review: B8-style axis stability, date bootstrap, matched controls, and an implementation that can model the original 12-trading-day cadence without reintroducing legacy backtest-loop bugs.",
    ])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default=",".join(DEFAULT_MODES),
                    help="Comma-separated modes: dist_a,hvbal_b,combo_z")
    ap.add_argument("--seeds", default=",".join(str(x) for x in DEFAULT_SEEDS),
                    help="Comma-separated random-control seeds")
    ap.add_argument("--merge-existing", action="store_true",
                    help="Merge new rows with existing output CSV by factor+seed")
    args = ap.parse_args()
    modes = [x.strip() for x in args.modes.split(",") if x.strip()]
    seeds = [int(x.strip()) for x in args.seeds.split(",") if x.strip()]

    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 100, flush=True)
    print("  Clean factor — Foundation rerun", flush=True)
    print("=" * 100, flush=True)
    print(f"  Modes: {', '.join(modes)}", flush=True)
    print(f"  Seeds: {', '.join(str(x) for x in seeds)}", flush=True)
    print("  Universe: broad 30-500亿, min_turnover_20d=0.15%, top 20% capped at 30", flush=True)
    print("  Hold: 17d, Cost: a_share_retail_swing, Random control: True", flush=True)
    print("  OOS split: train <= 2020-12-31 / test >= 2021-01-01", flush=True)
    print(flush=True)

    data = DataBundle.load(verbose=False)
    print(f"  Data loaded: OHLCV coverage {data.audit.ohlcv_coverage_pct:.0f}%", flush=True)
    universe = Universe.broad(
        data,
        mcap_range=(30, 500),
        min_turnover_20d=0.15,
        exclude_st=True,
        exclude_new_listing_days=180,
    )
    cost = CostModel.a_share_retail_swing()

    rows = []
    for mode in modes:
        for seed in seeds:
            print(f"\n--- {mode} seed={seed} ---", flush=True)
            strat = CleanFactorStrategy(mode=mode)
            bt = Backtest(
                strategy=strat,
                universe=universe,
                cost_model=cost,
                random_control=True,
                train_test_split=TRAIN_SPLIT,
                year_start=2017,
                year_end=2026,
                seed=seed,
            )
            result = bt.run(verbose=False)
            row = _row(mode, seed, result)
            rows.append(row)
            print(
                f"  n={int(row['n_full']) if not pd.isna(row['n_full']) else 0} "
                f"train={_fmt_pct(row['train_alpha'])}/{_fmt_float(row['train_t'])} "
                f"test={_fmt_pct(row['test_alpha'])}/{_fmt_float(row['test_t'])} "
                f"full={_fmt_pct(row['full_alpha'])}/{_fmt_float(row['full_t'])} "
                f"{row['verdict']}",
                flush=True,
            )

    df = pd.DataFrame(rows)
    if args.merge_existing and os.path.exists(OUT_CSV):
        old = pd.read_csv(OUT_CSV, encoding="utf-8-sig")
        df = pd.concat([old, df], ignore_index=True)
        df = df.drop_duplicates(subset=["factor", "seed"], keep="last")
        df = df.sort_values(["factor", "seed"]).reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(_markdown(df))

    print(f"\nSaved CSV -> {OUT_CSV}", flush=True)
    print(f"Saved report -> {OUT_MD}", flush=True)


if __name__ == "__main__":
    main()
