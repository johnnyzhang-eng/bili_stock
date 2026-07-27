"""
I-B1 可转债套利 data fetcher V1 (Cycle 002 §2.5, post Codex 16:05 NEEDS-FIX).

Two independent fetch modes per Codex 2acb44f:

  --mode double_low :
    selection = cov_snapshot 上市时间 ∈ [--start, --end] (default 2018-01-01..2022-12-31).
    NO redeem_jsl filter. Universe is currently-listed 转债 with adequate post-2018 history.
    Target: ≥ 50 bonds with successful post-2018 price + value.

  --mode redeem :
    selection = code ∈ bond_cb_redeem_jsl.代码 (currently 332 bonds with active 强赎 status).
    Validates 强赎触发价 + 强赎天计数 fields populated.
    For 强赎博弈 sub-strategy only.

  --mode both (default) :
    union of double_low and redeem selections. Overlapping codes fetched once (idempotent).

Outputs (all under data/bonds_cb/):
  cov_snapshot.csv          — 1012-bond listing universe (unchanged from v0)
  redeem_jsl.csv            — 332-bond 强赎 universe (unchanged from v0)
  value_analysis/<code>.csv — per-bond daily 纯债价值/转股价值/溢价率
  price/<code>.csv          — per-bond OHLCV
  coverage_manifest.csv     — Codex 16:05 evidence requirement:
    columns: code, mode, listing_date, value_first_date, value_last_date,
             value_rows, price_first_date, price_last_date, price_rows,
             has_post_2018_price, has_post_2018_value, has_redeem_fields, success

Idempotent: skip CSVs that already exist with non-empty content. Re-run with --force
to re-fetch.

Survivorship caveat: bond_zh_cov only enumerates currently-listed bonds; matured/delisted
bonds before today are NOT visible. Backtest verdict (§2.4) must document this bias.
For honest historical work, 集思录 archive or 中证转债指数成分历史 is required (out of
scope for §2.5).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd

try:
    import akshare as ak
except ImportError:
    print("akshare not installed; pip install akshare", file=sys.stderr)
    sys.exit(1)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE_DIR = os.path.join(ROOT, "data/bonds_cb")
SNAPSHOT_PATH = os.path.join(CACHE_DIR, "cov_snapshot.csv")
REDEEM_PATH = os.path.join(CACHE_DIR, "redeem_jsl.csv")
MANIFEST_PATH = os.path.join(CACHE_DIR, "coverage_manifest.csv")
VALUE_DIR = os.path.join(CACHE_DIR, "value_analysis")
PRICE_DIR = os.path.join(CACHE_DIR, "price")

SLEEP_BETWEEN_CALLS = 0.3
POST_2018 = pd.Timestamp("2018-01-01")


def ensure_dirs() -> None:
    for d in (CACHE_DIR, VALUE_DIR, PRICE_DIR):
        os.makedirs(d, exist_ok=True)


def fetch_snapshot(force: bool = False) -> pd.DataFrame:
    if not force and os.path.exists(SNAPSHOT_PATH) and os.path.getsize(SNAPSHOT_PATH) > 0:
        df = pd.read_csv(SNAPSHOT_PATH, dtype={"债券代码": str, "正股代码": str, "申购代码": str})
        print(f"[snapshot] reused cache: {len(df)} bonds")
        return df
    print("[snapshot] calling bond_zh_cov() ...")
    df = ak.bond_zh_cov()
    for c in ("债券代码", "正股代码", "申购代码"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.zfill(6)
    df.to_csv(SNAPSHOT_PATH, index=False)
    print(f"[snapshot] wrote {SNAPSHOT_PATH}: {len(df)} bonds")
    return df


def fetch_redeem(force: bool = False) -> pd.DataFrame:
    if not force and os.path.exists(REDEEM_PATH) and os.path.getsize(REDEEM_PATH) > 0:
        df = pd.read_csv(REDEEM_PATH, dtype={"代码": str, "正股代码": str})
        print(f"[redeem] reused cache: {len(df)} bonds")
        return df
    print("[redeem] calling bond_cb_redeem_jsl() ...")
    df = ak.bond_cb_redeem_jsl()
    for c in ("代码", "正股代码"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.zfill(6)
    df.to_csv(REDEEM_PATH, index=False)
    print(f"[redeem] wrote {REDEEM_PATH}: {len(df)} bonds")
    return df


def bond_prefix(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("110", "113")):
        return "sh"
    if code.startswith(("123", "127", "128", "117", "118")):
        return "sz"
    return "sh" if int(code[0]) <= 5 else "sz"


def fetch_value_analysis(code: str, force: bool = False) -> bool:
    path = os.path.join(VALUE_DIR, f"{code}.csv")
    if not force and os.path.exists(path) and os.path.getsize(path) > 100:
        return True
    try:
        df = ak.bond_zh_cov_value_analysis(symbol=code)
    except Exception as exc:
        print(f"  [value][{code}] FAIL: {exc}")
        return False
    if df is None or len(df) == 0:
        return False
    df.to_csv(path, index=False)
    return True


def fetch_price(code: str, force: bool = False) -> bool:
    path = os.path.join(PRICE_DIR, f"{code}.csv")
    if not force and os.path.exists(path) and os.path.getsize(path) > 100:
        return True
    sym = f"{bond_prefix(code)}{code}"
    try:
        df = ak.bond_zh_hs_cov_daily(symbol=sym)
    except Exception as exc:
        print(f"  [price][{code} sym={sym}] FAIL: {exc}")
        return False
    if df is None or len(df) == 0:
        return False
    df.to_csv(path, index=False)
    return True


def select_double_low(snapshot: pd.DataFrame, start: str, end: str) -> list[str]:
    df = snapshot.copy()
    df["上市时间"] = pd.to_datetime(df["上市时间"], errors="coerce")
    mask = (df["上市时间"] >= start) & (df["上市时间"] <= end)
    return df[mask]["债券代码"].astype(str).str.zfill(6).tolist()


def select_redeem(redeem: pd.DataFrame) -> list[str]:
    return redeem["代码"].astype(str).str.zfill(6).tolist()


def _read_dates(path: str, date_col: str) -> tuple[pd.Timestamp | None, pd.Timestamp | None, int]:
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        return None, None, 0
    try:
        df = pd.read_csv(path)
    except Exception:
        return None, None, 0
    if date_col not in df.columns or len(df) == 0:
        return None, None, 0
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna().sort_values()
    if len(dates) == 0:
        return None, None, 0
    return dates.iloc[0], dates.iloc[-1], len(dates)


def build_manifest(
    snapshot: pd.DataFrame,
    redeem: pd.DataFrame,
    target_codes: dict[str, set[str]],
) -> pd.DataFrame:
    """target_codes maps mode → set of codes attempted in that mode."""
    snap_idx = snapshot.set_index(snapshot["债券代码"].astype(str).str.zfill(6))
    redeem_idx = redeem.set_index(redeem["代码"].astype(str).str.zfill(6))
    all_codes = set()
    for s in target_codes.values():
        all_codes.update(s)

    rows = []
    for code in sorted(all_codes):
        modes = sorted(m for m, s in target_codes.items() if code in s)
        listing = pd.to_datetime(
            snap_idx.loc[code, "上市时间"] if code in snap_idx.index else None,
            errors="coerce",
        )
        v_first, v_last, v_rows = _read_dates(os.path.join(VALUE_DIR, f"{code}.csv"), "日期")
        p_first, p_last, p_rows = _read_dates(os.path.join(PRICE_DIR, f"{code}.csv"), "date")
        has_redeem_fields = False
        if code in redeem_idx.index:
            row = redeem_idx.loc[code]
            has_redeem_fields = bool(
                pd.notna(row.get("强赎触发价")) and pd.notna(row.get("强赎天计数"))
            )
        has_p2018_value = bool(v_last is not None and v_last >= POST_2018)
        has_p2018_price = bool(p_last is not None and p_last >= POST_2018)
        success = bool(v_rows > 0 and p_rows > 0)
        rows.append({
            "code": code,
            "mode": "+".join(modes),
            "listing_date": listing.date() if pd.notna(listing) else None,
            "value_first_date": v_first.date() if v_first is not None else None,
            "value_last_date": v_last.date() if v_last is not None else None,
            "value_rows": v_rows,
            "price_first_date": p_first.date() if p_first is not None else None,
            "price_last_date": p_last.date() if p_last is not None else None,
            "price_rows": p_rows,
            "has_post_2018_value": has_p2018_value,
            "has_post_2018_price": has_p2018_price,
            "has_redeem_fields": has_redeem_fields,
            "success": success,
        })
    manifest = pd.DataFrame(rows)
    manifest.to_csv(MANIFEST_PATH, index=False)
    print(f"[manifest] wrote {MANIFEST_PATH}: {len(manifest)} bonds")
    return manifest


def report_coverage(manifest: pd.DataFrame) -> None:
    print()
    print("=" * 60)
    print(" Coverage manifest summary")
    print("=" * 60)
    total = len(manifest)
    succ = manifest["success"].sum()
    print(f"  total bonds attempted: {total}")
    print(f"  success (both value+price non-empty): {succ}")
    p18v = manifest["has_post_2018_value"].sum()
    p18p = manifest["has_post_2018_price"].sum()
    both = (manifest["has_post_2018_value"] & manifest["has_post_2018_price"]).sum()
    print(f"  post-2018 value: {p18v}")
    print(f"  post-2018 price: {p18p}")
    print(f"  post-2018 BOTH:  {both}  ← Codex §2.5 target ≥ 50")

    dl_mask = manifest["mode"].str.contains("double_low")
    dl_p18_both = ((manifest["has_post_2018_value"] & manifest["has_post_2018_price"]) & dl_mask).sum()
    print(f"  double_low post-2018 both: {dl_p18_both}")

    rd_mask = manifest["mode"].str.contains("redeem")
    rd_with_fields = (rd_mask & manifest["has_redeem_fields"]).sum()
    print(f"  redeem mode with 强赎 fields populated: {rd_with_fields}")

    print()
    print("Sample rows (10 mid-range):")
    if len(manifest) > 10:
        mid = manifest.iloc[len(manifest) // 2 - 5 : len(manifest) // 2 + 5]
    else:
        mid = manifest
    print(mid[["code", "mode", "listing_date", "value_first_date", "value_last_date",
               "price_first_date", "price_last_date", "has_post_2018_value",
               "has_post_2018_price", "success"]].to_string(index=False))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["double_low", "redeem", "both"], default="both")
    p.add_argument("--start", default="2018-01-01", help="double_low: 上市时间 lower bound")
    p.add_argument("--end", default="2022-12-31", help="double_low: 上市时间 upper bound")
    p.add_argument("--refresh-snapshot", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    ensure_dirs()
    snapshot = fetch_snapshot(force=args.refresh_snapshot)
    redeem = fetch_redeem(force=args.refresh_snapshot)

    targets: dict[str, set[str]] = {}
    if args.mode in ("double_low", "both"):
        dl = select_double_low(snapshot, args.start, args.end)
        targets["double_low"] = set(dl)
        print(f"[double_low] selected {len(dl)} bonds with 上市时间 ∈ [{args.start}, {args.end}]")
    if args.mode in ("redeem", "both"):
        rd = select_redeem(redeem)
        targets["redeem"] = set(rd)
        print(f"[redeem] selected {len(rd)} bonds from redeem_jsl")

    all_codes = set()
    for s in targets.values():
        all_codes.update(s)
    all_codes = sorted(all_codes)
    overlap = len(targets.get("double_low", set()) & targets.get("redeem", set()))
    print(f"[plan] union: {len(all_codes)} unique bonds (double_low ∩ redeem overlap: {overlap})")

    n_ok_v, n_ok_p, n_fail_v, n_fail_p = 0, 0, 0, 0
    for i, code in enumerate(all_codes, 1):
        if i % 100 == 0 or i == 1:
            print(f"  [{i}/{len(all_codes)}] {code} ...")
        ok_v = fetch_value_analysis(code, force=args.force)
        time.sleep(SLEEP_BETWEEN_CALLS)
        ok_p = fetch_price(code, force=args.force)
        time.sleep(SLEEP_BETWEEN_CALLS)
        n_ok_v += int(ok_v)
        n_ok_p += int(ok_p)
        n_fail_v += int(not ok_v)
        n_fail_p += int(not ok_p)

    print(f"\n[result] value_analysis: ok={n_ok_v} fail={n_fail_v}")
    print(f"[result] price:           ok={n_ok_p} fail={n_fail_p}")

    manifest = build_manifest(snapshot, redeem, targets)
    report_coverage(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
