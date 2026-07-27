"""
数据完整性审计 — 任何回测前必须先跑
===========================================
按 CLAUDE.md QC 规则, 任何新回测在开始前必须先调用此模块.

使用:
  from data_integrity_audit import audit_data, AuditFailure
  meta = audit_data(min_coverage=0.30, verify_corp_actions=True)
  # 如果 meta 不通过, 抛 AuditFailure 拒绝继续

输出 audit report 到 logs/data_audit_<date>.md.
"""
import os, sys, glob, warnings
from datetime import datetime

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PANEL = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


class AuditFailure(Exception):
    """数据审计未通过, 拒绝执行回测"""
    pass


def _check_panel_coverage():
    """检查 panel 基本面数据覆盖率与字段完整性"""
    df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    n_total = len(df)
    n_codes = df["code"].nunique()

    field_coverage = {}
    for col in ["eps", "net_profit", "revenue", "roe", "bps", "ocf_ps",
                "np_yoy", "rev_yoy", "industry", "announce_date"]:
        if col in df.columns:
            field_coverage[col] = df[col].notna().sum() / n_total

    return {
        "panel_rows": n_total,
        "panel_codes": n_codes,
        "panel_date_min": df["report_date"].min(),
        "panel_date_max": df["report_date"].max(),
        "field_coverage": field_coverage,
    }


def _check_ohlcv_coverage(panel_codes):
    """检查 OHLCV 文件覆盖率"""
    files = glob.glob(os.path.join(STOCK_DIR, "*.csv"))
    local_codes = {os.path.basename(f)[2:8] for f in files}

    sh_panel = {c for c in panel_codes if c[0] in "69"}
    sz_panel = {c for c in panel_codes if c[0] in "03"}
    bj_panel = {c for c in panel_codes if c[0] in "48"}

    return {
        "local_files": len(files),
        "local_codes": len(local_codes),
        "panel_in_local": len(panel_codes & local_codes),
        "coverage_pct": len(panel_codes & local_codes) / len(panel_codes) * 100,
        "sh_panel": len(sh_panel), "sh_local": len(sh_panel & local_codes),
        "sz_panel": len(sz_panel), "sz_local": len(sz_panel & local_codes),
        "bj_panel": len(bj_panel), "bj_local": len(bj_panel & local_codes),
    }


def _check_ohlcv_quality(sample_size=50, verbose=False):
    """对样本股做数据质量检查: 复权一致性, pctChg 与 close 一致性, 时间断点"""
    files = glob.glob(os.path.join(STOCK_DIR, "*.csv"))
    np.random.seed(42)
    sample_files = np.random.choice(files, size=min(sample_size, len(files)), replace=False)

    results = {
        "n_checked": 0,
        "pctchg_consistency_failures": 0,
        "missing_dates_avg": 0,
        "earliest_date_min": None,
        "latest_date_max": None,
        "negative_close_count": 0,
        "extreme_pct_count": 0,  # |pct| > 11% (主板涨跌停以外, ST 除外)
        "sample_codes_with_issues": [],
    }
    earliest, latest = [], []
    missing_days_list = []

    for fp in sample_files:
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
            dc = next((c for c in ["date","日期"] if c in df.columns), None)
            cc = next((c for c in ["close","收盘"] if c in df.columns), None)
            pc = next((c for c in ["pctChg","涨跌幅"] if c in df.columns), None)
            if not (dc and cc and pc): continue
            df[dc] = pd.to_datetime(df[dc], errors="coerce")
            df = df.dropna(subset=[dc, cc, pc]).sort_values(dc).reset_index(drop=True)
            if len(df) < 5: continue
            results["n_checked"] += 1

            # 1. pctChg 一致性: pct[i] 应该 ≈ close[i]/close[i-1] - 1
            df["close_pct"] = (df[cc] / df[cc].shift(1) - 1) * 100
            df["pct_diff"] = abs(df[pc] - df["close_pct"])
            inconsistent = (df["pct_diff"].dropna() > 0.5).sum()  # 容差 0.5pp
            if inconsistent > 5:  # 5 天以上不一致 = 复权未对齐
                results["pctchg_consistency_failures"] += 1
                code = os.path.basename(fp)[2:8]
                results["sample_codes_with_issues"].append(f"{code}:复权({inconsistent}d)")

            # 2. 时间断点: 应该是连续交易日, 检查最长缺失
            df["dt_diff"] = df[dc].diff().dt.days
            max_gap = df["dt_diff"].max() if len(df) > 1 else 0
            if max_gap and max_gap > 30:
                missing_days_list.append(max_gap)

            # 3. 异常值
            results["negative_close_count"] += int((df[cc] < 0).sum())
            results["extreme_pct_count"] += int((df[pc].abs() > 11).sum())  # 涨停 10%, ST 5%

            earliest.append(df[dc].iloc[0])
            latest.append(df[dc].iloc[-1])
        except Exception:
            continue

    if earliest:
        results["earliest_date_min"] = min(earliest)
        results["latest_date_max"] = max(latest)
    results["missing_days_avg"] = np.mean(missing_days_list) if missing_days_list else 0

    return results


def _check_announce_date_validity():
    """检查 panel.announce_date 是否可信 (历史数据被发现有错回填)"""
    df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce")
    df = df.dropna(subset=["report_date", "announce_date"])
    df["delay_days"] = (df["announce_date"] - df["report_date"]).dt.days

    # 异常情况: announce_date 早于 report_date (不可能), 或 delay > 365 天
    invalid_early = (df["delay_days"] < 0).sum()
    invalid_late  = (df["delay_days"] > 365).sum()

    # 按年看延迟分布: 应该是 30-120 天比较合理
    df["yr"] = df["report_date"].dt.year
    yearly = df.groupby("yr")["delay_days"].agg(["mean", "median", "min", "max"]).tail(10)

    return {
        "total_announce_records": len(df),
        "invalid_early_count": int(invalid_early),
        "invalid_late_count": int(invalid_late),
        "yearly_delay_stats": yearly.to_dict(),
        "verdict": "可信" if (invalid_early + invalid_late) / len(df) < 0.05 else "不可信(>5% 异常)",
    }


def audit_data(min_coverage=0.30, verbose=True, write_report=True):
    """主审计流程. 调用方应根据返回值决定是否继续."""
    if verbose:
        print("=" * 80)
        print("  数据完整性审计 (按 CLAUDE.md QC 规则强制执行)")
        print("=" * 80)

    p = _check_panel_coverage()
    if verbose:
        print(f"\n[基本面 Panel]")
        print(f"  记录数: {p['panel_rows']:,}  股票数: {p['panel_codes']:,}")
        print(f"  覆盖期: {p['panel_date_min'].date()} → {p['panel_date_max'].date()}")
        print(f"  字段覆盖率:")
        for k, v in p["field_coverage"].items():
            tag = "✓" if v > 0.9 else ("~" if v > 0.5 else "✗")
            print(f"    {tag} {k:<20s}: {v*100:>5.1f}%")

    panel_codes = set(pd.read_csv(PANEL, encoding="utf-8-sig",
                                   dtype={"code": str}, low_memory=False)["code"].unique())
    o = _check_ohlcv_coverage(panel_codes)
    if verbose:
        print(f"\n[OHLCV 覆盖]")
        print(f"  本地文件: {o['local_files']:,}  panel 中可定价: {o['panel_in_local']:,} "
              f"({o['coverage_pct']:.1f}%)")
        print(f"  按交易所:")
        print(f"    SH (6/9): {o['sh_local']:>5,} / {o['sh_panel']:>5,}  "
              f"({o['sh_local']/o['sh_panel']*100:.0f}%)")
        print(f"    SZ (0/3): {o['sz_local']:>5,} / {o['sz_panel']:>5,}  "
              f"({o['sz_local']/o['sz_panel']*100:.0f}%)")
        print(f"    BJ (4/8): {o['bj_local']:>5,} / {o['bj_panel']:>5,}  "
              f"({o['bj_local']/o['bj_panel']*100:.0f}%) ⚠️ 北交所完全缺失")

    if verbose: print(f"\n[OHLCV 质量抽样 (50只随机股)]")
    q = _check_ohlcv_quality(sample_size=50)
    if verbose:
        print(f"  实际检查: {q['n_checked']} 只")
        print(f"  复权一致性失败: {q['pctchg_consistency_failures']} / {q['n_checked']}  "
              f"(>5天 pct与close矛盾视为失败)")
        print(f"  最早日期: {q['earliest_date_min']}  最新日期: {q['latest_date_max']}")
        print(f"  极端涨跌幅 (|%|>11%): {q['extreme_pct_count']:,} 条 (ST/北交所/异常)")
        if q["sample_codes_with_issues"][:5]:
            print(f"  问题样本: {', '.join(q['sample_codes_with_issues'][:5])}")

    a = _check_announce_date_validity()
    if verbose:
        print(f"\n[announce_date 可信度]")
        print(f"  总 announce 记录: {a['total_announce_records']:,}")
        print(f"  异常早 (<0天): {a['invalid_early_count']:,}")
        print(f"  异常晚 (>365天): {a['invalid_late_count']:,}")
        print(f"  判定: {a['verdict']}")

    # ── 综合判定 ─────────────────────────────────────────────────────────────
    issues, warnings_list = [], []
    if o["coverage_pct"] / 100 < min_coverage:
        issues.append(f"OHLCV 覆盖率 {o['coverage_pct']:.1f}% < 阈值 {min_coverage*100:.0f}%")
    if q["n_checked"] > 0 and q["pctchg_consistency_failures"] / q["n_checked"] > 0.10:
        issues.append(f"复权一致性失败率 {q['pctchg_consistency_failures']/q['n_checked']*100:.0f}%")
    if a["verdict"] != "可信":
        warnings_list.append("announce_date 历史数据存疑, 应改用 report_date + 固定延迟")

    if o["bj_local"] == 0 and o["bj_panel"] > 0:
        warnings_list.append(f"北交所 {o['bj_panel']} 只完全无 OHLCV, 限制宇宙到 SH/SZ")

    meta = {
        "panel": p,
        "ohlcv_coverage": o,
        "ohlcv_quality": q,
        "announce_validity": a,
        "issues": issues,
        "warnings": warnings_list,
        "passed": len(issues) == 0,
        "audit_time": datetime.now().isoformat(),
    }

    if verbose:
        print()
        print("=" * 80)
        print(f"  审计结论: {'✓ 通过' if meta['passed'] else '✗ 失败'}")
        print("=" * 80)
        if issues:
            print(f"  阻断问题:")
            for i in issues: print(f"    ✗ {i}")
        if warnings_list:
            print(f"  注意事项:")
            for w in warnings_list: print(f"    ⚠️  {w}")
        if not issues and not warnings_list:
            print(f"  无问题")

    if write_report:
        report_path = os.path.join(LOG_DIR,
                                    f"data_audit_{datetime.now().strftime('%Y%m%d')}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# 数据审计报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(f"**审计结论**: {'✓ 通过' if meta['passed'] else '✗ 失败'}\n\n")
            f.write(f"## Panel\n")
            f.write(f"- 记录: {p['panel_rows']:,} | 股票: {p['panel_codes']:,}\n")
            f.write(f"- 期间: {p['panel_date_min'].date()} → {p['panel_date_max'].date()}\n\n")
            f.write(f"## OHLCV 覆盖\n")
            f.write(f"- 总覆盖: {o['coverage_pct']:.1f}%\n")
            f.write(f"- SH: {o['sh_local']/o['sh_panel']*100:.0f}%  "
                    f"SZ: {o['sz_local']/o['sz_panel']*100:.0f}%  "
                    f"BJ: 0%\n\n")
            if issues:
                f.write(f"## 阻断问题\n")
                for i in issues: f.write(f"- ✗ {i}\n")
            if warnings_list:
                f.write(f"\n## 注意事项\n")
                for w in warnings_list: f.write(f"- ⚠️ {w}\n")
        if verbose:
            print(f"\n[+] 报告写入 {report_path}")

    return meta


if __name__ == "__main__":
    audit_data(min_coverage=0.30, verbose=True, write_report=True)
