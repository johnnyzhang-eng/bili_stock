"""
SMB sensitivity rerun for the 12-factor foundation battery.

The first foundation battery found a Test-only weak positive for "small cap
within broad 30-500亿". This script checks whether that result survives random
seed changes and size-bucket changes. It is not a production strategy runner.
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
import pandas as pd

from research.foundation import (
    Backtest,
    CostModel,
    CrossSectionalStrategy,
    DataBundle,
    Universe,
)
from research.foundation.run_factor_battery_foundation import factor_small_cap


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
OUT_CSV = os.path.join(OUT_DIR, "smb_sensitivity_foundation.csv")
OUT_MD = os.path.join(OUT_DIR, "smb_sensitivity_foundation.md")


MATRIX = [
    ("broad_30_500", (30, 500), 0.15),
    ("small_30_100", (30, 100), 0.15),
    ("mid_100_500", (100, 500), 0.15),
]
SEEDS = [1, 42, 99]


def _summary(label, seed, result):
    def get(summary, key):
        return summary.get(key, np.nan) if summary else np.nan

    return {
        "bucket": label,
        "seed": seed,
        "n_full": get(result.full_summary, "n"),
        "train_alpha": get(result.train_summary, "alpha_mean"),
        "train_t": get(result.train_summary, "t_stat"),
        "test_alpha": get(result.test_summary, "alpha_mean"),
        "test_t": get(result.test_summary, "t_stat"),
        "full_alpha": get(result.full_summary, "alpha_mean"),
        "full_t": get(result.full_summary, "t_stat"),
        "test_alpha_win_pct": get(result.test_summary, "alpha_win_pct"),
    }


def _pct(x):
    return "" if pd.isna(x) else f"{x * 100:+.2f}%"


def _flt(x):
    return "" if pd.isna(x) else f"{x:+.2f}"


def _markdown(df):
    cols = [
        "bucket", "seed", "n_full", "train_alpha", "train_t", "test_alpha",
        "test_t", "full_alpha", "full_t", "test_alpha_win_pct",
    ]
    headers = [
        "bucket", "seed", "n", "train alpha", "train t", "test alpha",
        "test t", "full alpha", "full t", "test win%",
    ]
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] + ["---:" for _ in headers[1:]]) + "|")
    for _, r in df[cols].iterrows():
        vals = [
            str(r["bucket"]),
            str(int(r["seed"])),
            str(int(r["n_full"])) if not pd.isna(r["n_full"]) else "",
            _pct(r["train_alpha"]),
            _flt(r["train_t"]),
            _pct(r["test_alpha"]),
            _flt(r["test_t"]),
            _pct(r["full_alpha"]),
            _flt(r["full_t"]),
            "" if pd.isna(r["test_alpha_win_pct"]) else f"{r['test_alpha_win_pct']:.0f}%",
        ]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 100)
    print("  SMB sensitivity — Foundation")
    print("=" * 100)
    print("  Check seeds x size buckets for factor_small_cap")
    print()

    data = DataBundle.load(verbose=False)
    rows = []
    for label, mcap_range, min_turn in MATRIX:
        universe = Universe.broad(
            data,
            mcap_range=mcap_range,
            min_turnover_20d=min_turn,
            exclude_st=True,
            exclude_new_listing_days=180,
        )
        for seed in SEEDS:
            print(f"[{label}] seed={seed}")
            strat = CrossSectionalStrategy(
                name=f"SMB sensitivity {label} seed={seed}",
                factor_fn=factor_small_cap,
                top_pct=0.20,
                n_signal_cap=30,
                hold_days=180,
            )
            bt = Backtest(
                strategy=strat,
                universe=universe,
                cost_model=CostModel.a_share_retail_quarterly(),
                random_control=True,
                train_test_split=("2020-12-31", "2021-01-01"),
                year_start=2017,
                year_end=2025,
                seed=seed,
            )
            result = bt.run(verbose=False)
            row = _summary(label, seed, result)
            rows.append(row)
            print(
                f"  Test alpha={row['test_alpha'] * 100:+.2f}% "
                f"t={row['test_t']:+.2f}; Full alpha={row['full_alpha'] * 100:+.2f}% "
                f"t={row['full_t']:+.2f}"
            )

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    md = [
        "# SMB Sensitivity — Foundation Rerun (2026-05-25)\n",
        "Execution: `.venv/bin/python -B research/foundation/run_smb_sensitivity_foundation.py`.\n",
        "Purpose: validate whether the 12-factor battery's Test-only SMB weak positive survives seed and size-bucket changes.\n",
        _markdown(out),
        "",
        "Interpretation: a production-grade SMB claim requires stable positive alpha across seeds and across adjacent size buckets, without train/test sign reversal.\n",
    ]
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md).rstrip() + "\n")

    print(f"\n[+] CSV: {OUT_CSV}")
    print(f"[+] Report: {OUT_MD}")


if __name__ == "__main__":
    main()
