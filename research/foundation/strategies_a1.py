"""
A1 — Smart Cube Avoidance, foundation implementation (cycle 001).

Thesis (original): stocks held by "smart" cubes systematically underperform.
Implementation: factor returns HIGHER score for stocks with LOWER smart-cube
exposure ("avoid the held"). top quintile of the score = pick stocks that the
smart cubes avoid or hold lightly.

Foundation specifics (per PHASE_1_PLAN.md §4.1 + Codex review):
- factor reads pre-computed signal panel `smart_consensus_ffill.csv` (built by
  build_signal.py with rolling skill + clean mask + CB filter + B2 entry shift).
- For stocks with raw signal > 0 (cube-held this bucket): factor = -raw_signal
  (more exposure → lower score → less likely picked).
- For stocks with raw signal == 0 (no smart-cube exposure): factor =
  1.0 + stable_jitter(code, sig_date) * 1e-6. The jitter breaks ties so
  CrossSectionalStrategy.select() doesn't fall back to DataFrame index order
  (B7 attack registry; same trick self_test.factor_null uses).
- Quarterly cadence imposed by foundation Backtest; original verdict was
  weekly. The verdict must label this as "quarterly foundation variant" not
  imply weekly reproduction.
"""
import hashlib
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
SIG_PATH = os.path.join(ROOT, "research", "smart_consensus", "output", "smart_consensus_ffill.csv")

_SIG_CACHE: dict = {}


def _load_signal() -> pd.DataFrame:
    if "df" not in _SIG_CACHE:
        df = pd.read_csv(SIG_PATH, index_col=0)
        df.index = pd.to_datetime(df.index)
        df = df[~df.index.duplicated(keep="first")].sort_index()
        # Stock columns are 6-digit codes; ensure string type
        df.columns = [str(c).zfill(6) for c in df.columns]
        _SIG_CACHE["df"] = df
    return _SIG_CACHE["df"]


def _stable_jitter(code: str, sig_date) -> float:
    """Deterministic [0, 1) jitter keyed by (code, signal_date).

    Breaks tie-order bias in CrossSectionalStrategy.select() when multiple
    stocks share the same factor value. Same hash → same value → reproducible.
    Cf. attack_registry.yaml B7 and self_test.factor_null.
    """
    key = f"{code}|{pd.Timestamp(sig_date).strftime('%Y-%m-%d')}".encode()
    return (int(hashlib.md5(key).hexdigest()[:12], 16) % 10**9) / 10**9


def factor_a1_avoid(row, price_cache, sig_date) -> float:
    """A1 factor — higher = more avoidable (lower smart-cube exposure)."""
    sig = _load_signal()
    code = str(row["code"]).zfill(6)
    if code not in sig.columns:
        return float("nan")
    col = sig[code].loc[:sig_date]
    if col.empty:
        return float("nan")
    raw = float(col.iloc[-1])
    if raw > 0:
        # Cube-held: more exposure → lower factor → less likely picked
        return -raw
    # Zero exposure: top tier with deterministic jitter to avoid tie-order bias
    return 1.0 + _stable_jitter(code, sig_date) * 1e-6


def make_strategy(
    *,
    top_pct: float = 0.20,
    n_signal_cap: int = 30,
    hold_days: int = 63,
) -> CrossSectionalStrategy:
    return CrossSectionalStrategy(
        name=(
            "A1 smart-cube avoidance (quarterly foundation variant; "
            f"top {int(top_pct * 100)}% avoidable, hold={hold_days}d)"
        ),
        factor_fn=factor_a1_avoid,
        top_pct=top_pct,
        n_signal_cap=n_signal_cap,
        hold_days=hold_days,
    )


def run(data: DataBundle | None = None, verbose: bool = True):
    if data is None:
        data = DataBundle.load(verbose=False)

    # Universe: broad A-share, mcap 30亿-500亿 (covers most of cubes' universe).
    # min_turnover_20d=0.15 enforces minimum liquidity per CLAUDE.md hard rail.
    universe = Universe.broad(
        data,
        mcap_range=(30, 500),
        min_turnover_20d=0.15,
        exclude_st=True,
        exclude_new_listing_days=180,
    )
    strategy = make_strategy()
    cost = CostModel.a_share_retail_quarterly()
    bt = Backtest(
        strategy=strategy,
        universe=universe,
        cost_model=cost,
        random_control=True,
        # OOS split per PHASE_1_PLAN.md §4.2 (foundation framework standard).
        # Signal panel index from build_signal.py covers 2016-2026 via bucket dates.
        train_test_split=("2021-12-31", "2022-01-01"),
        year_start=2017,
        year_end=2026,
        seed=42,
    )
    return bt.run(verbose=verbose)


def main():
    print("=" * 80)
    print("  A1 — Smart Cube Avoidance (quarterly foundation variant)")
    print("=" * 80)
    print("  NOTE: this is NOT the original weekly verdict. Codex review locked")
    print("  that the verdict file must state 'quarterly foundation variant'.")
    print()
    result = run(verbose=True)
    report = StandardReport.from_result(result)
    report.print()

    out_dir = os.path.join(os.path.dirname(__file__), "..", "smart_consensus", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "a1_foundation_quarterly.md")
    report.save(out_path)
    print(f"\n[+] Report written to {out_path}")


if __name__ == "__main__":
    main()
