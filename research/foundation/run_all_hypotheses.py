"""
Cycle 001 runner for A1/H2/H3/H4 foundation backtests.

Each strategy module should expose:

    run(data: DataBundle | None = None, verbose: bool = True) -> BacktestResult

The runner loads DataBundle once, executes strategies sequentially, and writes a
combined markdown report. It intentionally fails if a strategy module is missing
unless --allow-missing is passed for smoke checks.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from dataclasses import dataclass
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from research.foundation import BacktestResult, DataBundle, StandardReport


OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smart_consensus", "output"))
OUT_PATH = os.path.join(OUT_DIR, "cycle001_foundation_reports.md")


@dataclass(frozen=True)
class HypothesisSpec:
    hypothesis_id: str
    module: str


SPECS = [
    HypothesisSpec("A1", "research.foundation.strategies_a1"),
    HypothesisSpec("H2", "research.foundation.strategies_h2_cluster_buy"),
    HypothesisSpec("H3", "research.foundation.strategies_h3_mass_exit"),
    HypothesisSpec("H4", "research.foundation.strategies_h4_buy_intensity"),
]


def _short_summary(result: BacktestResult) -> str:
    s = result.full_summary
    if not s or "alpha_mean" not in s:
        return "n/a"
    return (
        f"n={s['n']} alpha={s['alpha_mean'] * 100:+.2f}%/period "
        f"t={s['t_stat']:+.2f}"
    )


def run_one(spec: HypothesisSpec, data: DataBundle, verbose: bool) -> Optional[BacktestResult]:
    module = importlib.import_module(spec.module)
    if not hasattr(module, "run"):
        raise AttributeError(f"{spec.module} must expose run(data=None, verbose=True)")
    result = module.run(data=data, verbose=verbose)
    if not isinstance(result, BacktestResult):
        raise TypeError(f"{spec.module}.run returned {type(result)!r}, expected BacktestResult")
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-missing", action="store_true", help="Skip missing strategy modules")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-strategy verbose output")
    args = parser.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)
    print("[1/2] Loading DataBundle once...")
    data = DataBundle.load(verbose=False)
    print(f"      OHLCV coverage: {data.audit.ohlcv_coverage_pct:.0f}%")

    print("[2/2] Running Cycle 001 hypotheses...")
    reports: list[str] = ["# Cycle 001 Foundation Reports\n"]
    failures = []
    for spec in SPECS:
        print(f"\n=== {spec.hypothesis_id} ===")
        try:
            result = run_one(spec, data=data, verbose=not args.quiet)
        except ModuleNotFoundError as exc:
            if args.allow_missing and exc.name == spec.module:
                msg = f"SKIPPED: missing {spec.module}"
                print(msg)
                reports.append(f"## {spec.hypothesis_id}\n\n{msg}\n")
                continue
            failures.append((spec.hypothesis_id, repr(exc)))
            print(f"FAILED: {exc!r}")
            continue
        except Exception as exc:
            failures.append((spec.hypothesis_id, repr(exc)))
            print(f"FAILED: {exc!r}")
            continue

        print(f"summary: {_short_summary(result)}")
        reports.append(f"## {spec.hypothesis_id}\n")
        reports.append(StandardReport.from_result(result).render())
        reports.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(reports).rstrip() + "\n")
    print(f"\n[+] Combined report written to {OUT_PATH}")

    if failures:
        print("\nFailures:")
        for hid, err in failures:
            print(f"  {hid}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
