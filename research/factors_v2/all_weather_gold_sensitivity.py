"""
全天候黄金权重敏感性分析 (2026-04-28)
==========================================
问题: 黄金现在历史峰值, 周期可能进入熊市. 30/30/40 仓位是否会被拖垮?

测试维度:
  - 6 种配置 (黄金 0% / 25% / 30% / 40% / 50%)
  - 4 个时间段:
    * Full 2010-2026 (基线)
    * 2010-2015 ★ 核心: 黄金 2011 峰→ 2015 谷, 含 -44.8% MDD, 类比"今天 4 月开始未来 5 年黄金跌"
    * 2015-2018 (黄金熊 + 股灾期, 极端压力)
    * 2018-2026 (黄金从 2018 谷再涨到 2026 新峰)
    * 2024-2026 (最近 2 年, 验证当前金价上行段的表现)

判定:
  - 若 30/30/40 在 2010-2015 段 Calmar > 0 且不输 30/40/30: 静态可信, 守住主推
  - 若 2010-2015 30/30/40 显著输给低黄金配置: 该考虑降仓至 30%

输出:
  research/factors_v2/output/all_weather_gold_sensitivity.md
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output")
LONG_HIST = os.path.join(OUT_DIR, "long_history_4asset.csv")
COST = (13 + 43) / 10000


CONFIGS = [
    # name, STK, BOND, GOLD
    ("A. 30/30/40 (主推)",   0.30, 0.30, 0.40),
    ("B. 30/40/30",          0.30, 0.40, 0.30),
    ("C. 30/45/25 (低金)",   0.30, 0.45, 0.25),
    ("D. 25/50/25 (Browne 类)", 0.25, 0.50, 0.25),
    ("E. 40/40/20 (轻金)",   0.40, 0.40, 0.20),
    ("F. 50/50/0  (无金)",   0.50, 0.50, 0.00),
    ("G. 20/30/50 (重金)",   0.20, 0.30, 0.50),
]

PERIODS = [
    ("Full 2010-2026",    "2010-06-01", "2026-04-20"),
    ("2010-2015 黄金峰→谷", "2011-09-01", "2015-12-31"),  # 黄金 2011-09 真峰
    ("2015-2018 双熊",     "2015-06-15", "2018-12-31"),
    ("2018-2026 复苏+新峰", "2019-01-01", "2026-04-20"),
    ("2024-2026 近 2 年",  "2024-01-01", "2026-04-20"),
]


def load_data() -> pd.DataFrame:
    df = pd.read_csv(LONG_HIST, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for c in ["DIV", "GEM", "BOND", "GOLD"]:
        df[f"r_{c}"] = df[c].pct_change().fillna(0.0)
    df["STK"] = 0.7 * df["DIV"] + 0.3 * df["GEM"]
    df["r_STK"] = 0.7 * df["r_DIV"] + 0.3 * df["r_GEM"]
    return df


def simulate_static(df: pd.DataFrame, w_stk: float, w_bond: float, w_gold: float) -> pd.Series:
    """静态配比, 季度再平衡."""
    dt = df["date"]
    mask_q = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()

    vals = {"DIV": w_stk * 0.7, "GEM": w_stk * 0.3, "BOND": w_bond, "GOLD": w_gold}
    series = np.zeros(len(df))
    for i in range(len(df)):
        if i > 0:
            for k in vals:
                vals[k] *= (1 + df[f"r_{k}"].iloc[i])
        if mask_q.iloc[i] and i > 0:
            tot = sum(vals.values())
            tgt = {"DIV": tot * w_stk * 0.7, "GEM": tot * w_stk * 0.3,
                   "BOND": tot * w_bond, "GOLD": tot * w_gold}
            tov = sum(abs(tgt[k] - vals[k]) for k in tgt) / tot if tot > 0 else 0
            cost = tot * tov * COST * 0.5
            vals = dict(tgt)
            scale = 1 - cost / tot if tot > 0 else 1
            for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())
    return pd.Series(series, index=df.index)


def metrics(nav: pd.Series, dates: pd.Series, mask: pd.Series) -> dict:
    sub_nav = nav[mask.values]
    sub_dates = dates[mask.values]
    if len(sub_nav) < 30 or sub_nav.iloc[0] <= 0:
        return None
    sub = sub_nav / sub_nav.iloc[0]
    yrs = (sub_dates.iloc[-1] - sub_dates.iloc[0]).days / 365.25
    cagr = (sub.iloc[-1] / sub.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    dr = sub.pct_change().dropna()
    vol = dr.std() * np.sqrt(252) if len(dr) > 1 else 0
    sh = (dr.mean() * 252 - 0.02) / vol if vol > 0 else 0
    mdd = (sub / sub.cummax() - 1).min()
    cal = cagr / abs(mdd) if mdd < 0 else 0
    return {"CAGR": cagr, "Vol": vol, "MDD": mdd, "Calmar": cal, "Sharpe": sh, "years": yrs}


def main():
    print("=" * 130)
    print("  全天候黄金权重敏感性分析")
    print("=" * 130)
    df = load_data()
    print(f"  数据: {df['date'].min().date()} → {df['date'].max().date()}")
    print()

    # Pre-compute NAVs
    navs = {}
    for name, ws, wb, wg in CONFIGS:
        navs[name] = simulate_static(df, ws, wb, wg)

    # Per-period table
    md_lines = ["# 全天候黄金权重敏感性 (2026-04-28)\n"]
    md_lines.append("背景: 黄金 2026-04 处于历史峰值, 用户担心未来 5 年进入熊市. ")
    md_lines.append("用 5 个时间段切片测 7 种配比, 重点看 2010-2015 (上一轮黄金峰→谷) 表现.\n")

    print(f"\n{'配置':<24s} ", end="")
    for pname, _, _ in PERIODS:
        print(f" | {pname:^28s}", end="")
    print()
    print(f"{'':24s} ", end="")
    for _ in PERIODS:
        print(f" | {'CAGR':>6s} {'MDD':>6s} {'Cal':>5s} {'Shp':>5s}", end="")
    print()
    print("-" * 200)

    table_data = {}
    for name, ws, wb, wg in CONFIGS:
        row = {}
        print(f"  {name:<22s}", end="")
        for pname, dstart, dend in PERIODS:
            mask = (df["date"] >= pd.Timestamp(dstart)) & (df["date"] <= pd.Timestamp(dend))
            m = metrics(navs[name], df["date"], mask)
            row[pname] = m
            if m:
                print(f"  | {m['CAGR']*100:>+5.1f}% {m['MDD']*100:>+5.1f}% {m['Calmar']:>5.2f} {m['Sharpe']:>5.2f}", end="")
            else:
                print(f"  | {'-':>6s} {'-':>6s} {'-':>5s} {'-':>5s}", end="")
        print()
        table_data[name] = row

    # Markdown tables — one per period
    for pname, dstart, dend in PERIODS:
        md_lines.append(f"\n## {pname}  ({dstart} → {dend})\n")
        md_lines.append("| 配置 | CAGR | MDD | Calmar | Sharpe |\n")
        md_lines.append("|---|---:|---:|---:|---:|\n")
        for name, _, _, _ in CONFIGS:
            m = table_data[name][pname]
            if m:
                md_lines.append(f"| {name} | {m['CAGR']*100:+.1f}% | {m['MDD']*100:+.1f}% | "
                                f"{m['Calmar']:.2f} | {m['Sharpe']:.2f} |\n")
            else:
                md_lines.append(f"| {name} | - | - | - | - |\n")

    # ── 解读 ────────────────────────────────────────────────────────────
    print()
    print("=" * 130)
    print("  解读 (2010-2015 黄金峰→谷段, 类比当前)")
    print("=" * 130)
    md_lines.append("\n## 关键解读\n")

    p_test = "2010-2015 黄金峰→谷"
    a_30_40 = table_data["A. 30/30/40 (主推)"][p_test]
    b_30_30 = table_data["B. 30/40/30"][p_test]
    c_30_25 = table_data["C. 30/45/25 (低金)"][p_test]
    d_browne = table_data["D. 25/50/25 (Browne 类)"][p_test]
    e_no_gold = table_data["F. 50/50/0  (无金)"][p_test]

    print(f"\n  {p_test} 段:")
    print(f"    30/30/40 (主推):   CAGR {a_30_40['CAGR']*100:+.1f}% MDD {a_30_40['MDD']*100:+.1f}% Cal {a_30_40['Calmar']:.2f}")
    print(f"    30/40/30:          CAGR {b_30_30['CAGR']*100:+.1f}% MDD {b_30_30['MDD']*100:+.1f}% Cal {b_30_30['Calmar']:.2f}")
    print(f"    30/45/25 (低金):   CAGR {c_30_25['CAGR']*100:+.1f}% MDD {c_30_25['MDD']*100:+.1f}% Cal {c_30_25['Calmar']:.2f}")
    print(f"    25/50/25 (Browne): CAGR {d_browne['CAGR']*100:+.1f}% MDD {d_browne['MDD']*100:+.1f}% Cal {d_browne['Calmar']:.2f}")
    print(f"    50/50/0  (无金):   CAGR {e_no_gold['CAGR']*100:+.1f}% MDD {e_no_gold['MDD']*100:+.1f}% Cal {e_no_gold['Calmar']:.2f}")

    delta = a_30_40["CAGR"] - b_30_30["CAGR"]
    delta_cal = a_30_40["Calmar"] - b_30_30["Calmar"]
    print(f"\n  Δ(主推 - 30/40/30): CAGR {delta*100:+.1f}pp, Calmar {delta_cal:+.2f}")

    if delta > 0 and delta_cal > -0.05:
        verdict = "✓ 主推 30/30/40 在黄金熊段未明显输给低金配置, 静态再平衡机制有效"
    elif delta > -0.005 and delta_cal > -0.10:
        verdict = "⚠️ 接近平手, 主推可保留但建议 DCA 进场降低择时风险"
    else:
        verdict = "✗ 主推在黄金熊段明显落后低金配置, 应考虑降至 30/40/30 或 DCA 进场"

    print(f"\n  判定: {verdict}")
    md_lines.append(f"\n**{p_test} 段对比** (黄金 2011 峰 → 2015 谷):\n\n")
    md_lines.append(f"- 30/30/40 (主推): CAGR {a_30_40['CAGR']*100:+.1f}% / MDD {a_30_40['MDD']*100:+.1f}% / Calmar {a_30_40['Calmar']:.2f}\n")
    md_lines.append(f"- 30/40/30 (低金): CAGR {b_30_30['CAGR']*100:+.1f}% / MDD {b_30_30['MDD']*100:+.1f}% / Calmar {b_30_30['Calmar']:.2f}\n")
    md_lines.append(f"- 50/50/0 (无金): CAGR {e_no_gold['CAGR']*100:+.1f}% / MDD {e_no_gold['MDD']*100:+.1f}% / Calmar {e_no_gold['Calmar']:.2f}\n\n")
    md_lines.append(f"**判定**: {verdict}\n\n")

    # 写报告
    md_path = os.path.join(OUT_DIR, "all_weather_gold_sensitivity.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(md_lines)
    print(f"\n[+] 报告写入 {md_path}")


if __name__ == "__main__":
    main()
