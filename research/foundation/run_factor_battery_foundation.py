"""
12-factor battery rerun under research.foundation.

This replaces the legacy factors_v2/factor_battery_test.py backtest loop for
audit purposes. The factor definitions are kept close to the legacy script, but
execution goes through Foundation: DataBundle, Universe, CostModel, Backtest,
random_control=True, and explicit OOS split.
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
    StandardReport,
    Universe,
)


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
OUT_CSV = os.path.join(OUT_DIR, "factor_battery_foundation_results.csv")
OUT_MD = os.path.join(OUT_DIR, "factor_battery_foundation_report.md")


def _price_history(price_cache, code, sig_date, n):
    if code not in price_cache:
        return None
    pf = price_cache[code]
    sub = pf[pf["date"] <= sig_date].tail(n)
    return sub if len(sub) >= n else None


def factor_momentum_12_1(row, price_cache, sig_date):
    """12-1M momentum: past 12M return excluding latest 1M."""
    sub = _price_history(price_cache, row["code"], sig_date, 252)
    if sub is None or len(sub) < 252:
        return np.nan
    ret_12m = sub.iloc[-1]["close"] / sub.iloc[0]["close"] - 1
    ret_1m = sub.iloc[-1]["close"] / sub.iloc[-21]["close"] - 1
    return ret_12m - ret_1m


def factor_short_term_reversal(row, price_cache, sig_date):
    """1M reversal: buy recent losers."""
    sub = _price_history(price_cache, row["code"], sig_date, 21)
    if sub is None:
        return np.nan
    ret_1m = sub.iloc[-1]["close"] / sub.iloc[0]["close"] - 1
    return -ret_1m


def factor_low_vol(row, price_cache, sig_date):
    """60d low volatility."""
    sub = _price_history(price_cache, row["code"], sig_date, 61)
    if sub is None or len(sub) < 40:
        return np.nan
    vol = sub["close"].pct_change().std() * np.sqrt(252)
    if pd.isna(vol) or vol <= 0:
        return np.nan
    return -float(vol)


def factor_low_turnover(row, price_cache, sig_date):
    return -row.get("turn20", np.nan)


def factor_high_turnover(row, price_cache, sig_date):
    return row.get("turn20", np.nan)


def factor_value_bm(row, price_cache, sig_date):
    return row.get("bm_ratio", np.nan)


def factor_low_pe(row, price_cache, sig_date):
    eps = row.get("eps", np.nan)
    price = row.get("price", np.nan)
    rpt = row.get("report_date")
    if pd.isna(eps) or pd.isna(price) or eps <= 0 or price <= 0:
        return np.nan
    q = int(pd.Timestamp(rpt).quarter) if rpt is not None else 4
    q_factor = {1: 4.0, 2: 2.0, 3: 4.0 / 3.0, 4: 1.0}.get(q, 1.0)
    eps_ann = eps * q_factor
    if eps_ann <= 0:
        return np.nan
    pe = price / eps_ann
    if pe <= 0 or pe > 200:
        return np.nan
    return -pe


def factor_quality_roe(row, price_cache, sig_date):
    roe = row.get("roe", np.nan)
    if pd.isna(roe) or roe < -100 or roe > 200:
        return np.nan
    return roe


def factor_small_cap(row, price_cache, sig_date):
    return -row.get("mcap_yi", np.nan)


def factor_big_cap(row, price_cache, sig_date):
    return row.get("mcap_yi", np.nan)


def factor_fundamental_reversal(row, price_cache, sig_date):
    np_single = row.get("np_single", np.nan)
    np_yoy = row.get("np_yoy", np.nan)
    if pd.isna(np_single) or np_single <= 0 or pd.isna(np_yoy):
        return np.nan
    return np_yoy


def factor_composite(row, price_cache, sig_date):
    """Legacy simple composite: momentum + value - volatility."""
    m = factor_momentum_12_1(row, price_cache, sig_date)
    v = factor_low_vol(row, price_cache, sig_date)
    bm = factor_value_bm(row, price_cache, sig_date)
    if pd.isna(m) or pd.isna(v) or pd.isna(bm):
        return np.nan
    # factor_low_vol already returns -vol, so this is m - vol + bm.
    return m + v + bm


FACTOR_SPECS = [
    ("动量 12-1M", factor_momentum_12_1),
    ("短期反转 1M", factor_short_term_reversal),
    ("低波动 60d", factor_low_vol),
    ("低换手 20d", factor_low_turnover),
    ("价值 BM ratio", factor_value_bm),
    ("低 PE", factor_low_pe),
    ("质量 ROE", factor_quality_roe),
    ("小盘 SMB", factor_small_cap),
    ("基本面反转", factor_fundamental_reversal),
    ("多因子合成", factor_composite),
    ("对照 高换手", factor_high_turnover),
    ("对照 大盘", factor_big_cap),
]


def _summary_row(name, result):
    s_train = result.train_summary
    s_test = result.test_summary
    s_full = result.full_summary

    def get(summary, key):
        return summary.get(key, np.nan) if summary else np.nan

    return {
        "factor": name,
        "n_full": get(s_full, "n"),
        "train_alpha": get(s_train, "alpha_mean"),
        "train_t": get(s_train, "t_stat"),
        "test_alpha": get(s_test, "alpha_mean"),
        "test_t": get(s_test, "t_stat"),
        "full_alpha": get(s_full, "alpha_mean"),
        "full_t": get(s_full, "t_stat"),
        "test_signal_net": get(s_test, "signal_mean_net"),
        "test_random_gross": get(s_test, "random_mean_gross"),
        "test_alpha_win_pct": get(s_test, "alpha_win_pct"),
        "verdict": _verdict(s_test if s_test else s_full),
    }


def _verdict(summary):
    if not summary or "alpha_mean" not in summary:
        return "INSUFFICIENT"
    alpha = summary.get("alpha_mean", np.nan)
    t_stat = summary.get("t_stat", np.nan)
    if pd.isna(alpha) or pd.isna(t_stat):
        return "INSUFFICIENT"
    if alpha > 0.005 and t_stat > 3.5:
        return "STRONG_POSITIVE"
    if alpha > 0.005 and t_stat > 2.0:
        return "WEAK_POSITIVE"
    if alpha < 0:
        return "REJECT_NEGATIVE"
    return "REJECT_NOT_SIGNIFICANT"


def _format_pct(x):
    return "" if pd.isna(x) else f"{x * 100:+.2f}%"


def _format_float(x):
    return "" if pd.isna(x) else f"{x:+.2f}"


def _summary_markdown(df):
    cols = [
        "factor", "n_full", "train_alpha", "train_t", "test_alpha", "test_t",
        "full_alpha", "full_t", "verdict",
    ]
    headers = [
        "factor", "n", "train alpha", "train t", "test alpha", "test t",
        "full alpha", "full t", "verdict",
    ]
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] + ["---:" for _ in headers[1:-1]] + ["---"]) + "|")
    for _, r in df[cols].iterrows():
        vals = [
            str(r["factor"]),
            str(int(r["n_full"])) if not pd.isna(r["n_full"]) else "",
            _format_pct(r["train_alpha"]),
            _format_float(r["train_t"]),
            _format_pct(r["test_alpha"]),
            _format_float(r["test_t"]),
            _format_pct(r["full_alpha"]),
            _format_float(r["full_t"]),
            str(r["verdict"]),
        ]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 100)
    print("  12-factor battery — Foundation rerun")
    print("=" * 100)
    print("  Universe: broad 30-500亿, min_turnover_20d=0.15%, top 20% capped at 30")
    print("  Hold: 180d, Cost: a_share_retail_quarterly, Random control: True")
    print("  OOS split: train <= 2020-12-31 / test >= 2021-01-01")
    print()

    data = DataBundle.load(verbose=False)
    print(f"  Data loaded: OHLCV coverage {data.audit.ohlcv_coverage_pct:.0f}%")

    universe = Universe.broad(
        data,
        mcap_range=(30, 500),
        min_turnover_20d=0.15,
        exclude_st=True,
        exclude_new_listing_days=180,
    )

    rows = []
    report_parts = [
        "# 12-factor Battery — Foundation Rerun (2026-05-25)\n",
        "Execution: `.venv/bin/python -B research/foundation/run_factor_battery_foundation.py`.\n",
        "Rules: DataBundle audit, broad 30-500亿 universe, 180d hold, quarterly retail cost, random_control=True, OOS split 2021-01-01.\n",
    ]

    for i, (name, fn) in enumerate(FACTOR_SPECS, start=1):
        print(f"\n[{i}/{len(FACTOR_SPECS)}] {name}")
        strat = CrossSectionalStrategy(
            name=f"FactorBattery::{name}",
            factor_fn=fn,
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
            seed=42,
        )
        result = bt.run(verbose=False)
        row = _summary_row(name, result)
        rows.append(row)
        print(
            f"  Test alpha={row['test_alpha'] * 100:+.2f}%/期 "
            f"t={row['test_t']:+.2f} verdict={row['verdict']}"
        )
        report_parts.append(f"## {name}\n")
        report_parts.append(StandardReport.from_result(result).render())
        report_parts.append("")

    out = pd.DataFrame(rows)
    out = out.sort_values(["test_t", "test_alpha"], ascending=[False, False])
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    report_parts.insert(3, "## Summary\n")
    report_parts.insert(4, _summary_markdown(out) + "\n")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(report_parts).rstrip() + "\n")

    print()
    print("=" * 100)
    print("  Summary sorted by test t-stat")
    print("=" * 100)
    for _, r in out.iterrows():
        print(
            f"  {r['factor']:<18s} "
            f"test_alpha={r['test_alpha'] * 100:+6.2f}% "
            f"test_t={r['test_t']:+6.2f} "
            f"full_alpha={r['full_alpha'] * 100:+6.2f}% "
            f"{r['verdict']}"
        )
    print(f"\n[+] CSV: {OUT_CSV}")
    print(f"[+] Report: {OUT_MD}")


if __name__ == "__main__":
    main()
