"""
因子批量测试 — 小盘 Alpha 验证
===============================
专注散户可实施的行为偏差型因子 (不依赖基本面信息差).
所有因子用同一宇宙 + 同期 + 同 random control 测试.

输出: research/factors_v2/output/factor_battery_results.csv
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd

from alpha_study_framework import (
    build_universe, run_factor_study, _momentum_12_1, _vol_60d,
    _get_price_at, OUT_DIR
)


# ── 因子定义 ───────────────────────────────────────────────────────────────────
# 每个因子返回: 越大越好 (框架会取 top 20%)

def factor_momentum_12_1(row, price_cache, sig_date):
    """12-1M 动量: 经典 Jegadeesh-Titman"""
    return _momentum_12_1(price_cache, row["code"], sig_date)


def factor_short_term_reversal(row, price_cache, sig_date):
    """短期反转: 过去 1 月跌得越狠, 未来反弹越可能 (越大越好 → 取负的最后1月收益)"""
    if row["code"] not in price_cache: return np.nan
    pf = price_cache[row["code"]]
    end = pf[pf["date"] <= sig_date]
    if len(end) < 21: return np.nan
    ret_1m = end.iloc[-1]["close"] / end.iloc[-21]["close"] - 1
    return -ret_1m  # 越跌 → 因子越大 → 被买入


def factor_low_vol(row, price_cache, sig_date):
    """低波动: 过去 60 日波动率越低, 因子越大 (越好)"""
    v = _vol_60d(price_cache, row["code"], sig_date)
    if v is None or np.isnan(v): return np.nan
    return -v  # 波动越低 → 因子越大


def factor_low_turnover(row, price_cache, sig_date):
    """低换手: 过去 20 日换手率越低越好 (非热门股)"""
    return -row.get("turn20", np.nan)  # 换手越低 → 因子越大


def factor_high_turnover(row, price_cache, sig_date):
    """高换手: 热门股 (对照组, 理论上效果相反)"""
    return row.get("turn20", np.nan)


def factor_value_bm(row, price_cache, sig_date):
    """价值: BM 越高越好 (BPS/Price)"""
    return row.get("bm_ratio", np.nan)


def factor_low_pe(row, price_cache, sig_date):
    """低 PE: 市盈率越低越好. PE = Price / EPS_ann"""
    eps = row.get("eps", np.nan)
    q   = int(row.get("report_date").quarter) if row.get("report_date") is not None else 0
    q_factor = {1: 4.0, 2: 2.0, 3: 4/3, 4: 1.0}.get(q, 1.0)
    eps_ann = eps * q_factor
    if eps_ann <= 0: return np.nan
    pe = row["price"] / eps_ann
    if pe <= 0 or pe > 200: return np.nan
    return -pe  # 低 PE → 因子大


def factor_quality_roe(row, price_cache, sig_date):
    """高 ROE 质量因子"""
    roe = row.get("roe", np.nan)
    if pd.isna(roe) or roe < -100 or roe > 200: return np.nan
    return roe


def factor_small_cap(row, price_cache, sig_date):
    """小盘: 市值越小, 因子越大"""
    return -row.get("mcap_yi", np.nan)


def factor_big_cap(row, price_cache, sig_date):
    """大盘 (对照)"""
    return row.get("mcap_yi", np.nan)


def factor_reversal_fundamental(row, price_cache, sig_date):
    """基本面反转 (本项目原版, 已知 alpha≈0, 作为基准对照)"""
    np_single = row.get("np_single", np.nan)
    if pd.isna(np_single) or np_single <= 0: return np.nan
    # 找去年同季单季
    # 简化: 用 np_yoy (累计 YoY) 作代理
    np_yoy = row.get("np_yoy", np.nan)
    if pd.isna(np_yoy): return np.nan
    return np_yoy


# ── 多因子合成 ────────────────────────────────────────────────────────────────
def factor_composite(row, price_cache, sig_date, cache={}):
    """
    3 因子 z-score 合成: 动量 + 低波 + 价值
    (都是行为型, 互相低相关)
    """
    m = _momentum_12_1(price_cache, row["code"], sig_date)
    v = _vol_60d(price_cache, row["code"], sig_date)
    bm = row.get("bm_ratio", np.nan)
    if pd.isna(m) or pd.isna(v) or pd.isna(bm) or v == 0: return np.nan
    return m - v + bm  # Simple combination (非 z-score, 但方向一致)


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print("  因子批量测试 — 基于 CLAUDE.md QC 规则 (内置 random control)")
    print("=" * 80)
    panel_df, price_cache, meta = build_universe(verbose=True)
    print()
    print(f"样本期: 2017Q1 → 2024Q4 (警告: 2017-2024 含 2019-2021 小盘牛, 结果乐观)")
    print(f"持仓期: 6 月  宇宙过滤: 市值 30-500亿, turn20>=0.15%")
    print(f"信号组: top 20% of 30 只  对照组: 同宇宙随机 30 只")
    print(f"成本: 56bp 单次换手 (每期扣除 gross->net)")
    print()

    factor_list = [
        ("动量 12-1M",         factor_momentum_12_1),
        ("短期反转 1M",         factor_short_term_reversal),
        ("低波动 60d",          factor_low_vol),
        ("低换手 20d",          factor_low_turnover),
        ("价值 BM ratio",       factor_value_bm),
        ("低 PE",               factor_low_pe),
        ("质量 ROE",            factor_quality_roe),
        ("小盘 (SMB)",          factor_small_cap),
        ("基本面反转 (原版)",    factor_reversal_fundamental),
        ("多因子合成 (动量+低波+价值)", factor_composite),
        # Negative controls — should show NO alpha or negative
        ("[对照] 高换手",       factor_high_turnover),
        ("[对照] 大盘",         factor_big_cap),
    ]

    all_summaries = []
    for name, fn in factor_list:
        result = run_factor_study(
            panel_df, price_cache, meta,
            factor_fn=fn,
            factor_name=name,
            top_pct=0.20,
            n_signal_cap=30,
            n_random=30,
            hold_days=180,
            mcap_range=(30, 500),
            year_start=2017,
            year_end=2025,
            verbose=True,
        )
        if result:
            all_summaries.append(result["summary"])

    print()
    print("=" * 80)
    print("  汇总表 (按 net alpha 降序)")
    print("=" * 80)
    sdf = pd.DataFrame(all_summaries)
    sdf = sdf.sort_values("alpha_6m_net", ascending=False)

    print(f"{'因子':<35s} {'信号6M':>8s} {'随机6M':>8s} {'α gross':>9s} {'α net':>8s} {'t-stat':>6s} {'胜率':>5s}")
    print("-" * 85)
    for _, r in sdf.iterrows():
        tag = "✓" if (r["t_stat"] > 2.0 and r["alpha_6m_net"] > 0.005) else \
              ("✗" if r["alpha_6m_net"] < 0 else "~")
        print(f"  {r['factor']:<32s} "
              f"{r['signal_ret_6m_gross']*100:>+6.2f}% "
              f"{r['random_ret_6m_gross']*100:>+6.2f}% "
              f"{r['alpha_6m_gross']*100:>+7.2f}% "
              f"{r['alpha_6m_net']*100:>+6.2f}% "
              f"{r['t_stat']:>5.2f} "
              f"{r['win_pct_vs_random']:>4.0f}%  {tag}")
    print()
    print("  判定规则: ✓ = t>2 且 net α>0.5%/6M (真 alpha)")
    print("          ~ = t<2 或 α 边缘 (不够显著)")
    print("          ✗ = net α<0 (因子方向错或被成本吃掉)")
    print()

    out_fp = os.path.join(OUT_DIR, "factor_battery_results.csv")
    sdf.to_csv(out_fp, index=False, encoding="utf-8-sig")
    print(f"[+] 写入 {out_fp}")

    # Action items
    winners = sdf[(sdf["t_stat"] > 2.0) & (sdf["alpha_6m_net"] > 0.005)]
    print()
    print("=" * 80)
    if len(winners) > 0:
        print(f"  发现 {len(winners)} 个显著因子:")
        for _, r in winners.iterrows():
            ann_net = ((1 + r["alpha_6m_net"])**2 - 1) * 100
            print(f"    • {r['factor']}: net α {r['alpha_6m_net']*100:+.1f}%/6M (年化 {ann_net:+.1f}%)")
        print()
        print("  下一步: 对这些因子做敏感性测试 (改持仓期/宇宙/top_pct) 验证鲁棒性")
    else:
        print("  未发现显著因子 (t>2 & net α>0.5%/6M)")
        print("  含义: 在当前宇宙与成本下, 单因子无法稳定跑赢随机对照")
        print("  建议: 放弃单因子量化, 接受小资金是'参与权'而非'收益源'")
    print("=" * 80)


if __name__ == "__main__":
    main()
