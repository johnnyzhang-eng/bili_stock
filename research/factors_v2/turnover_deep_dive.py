"""
换手率因子深度研究 — 唯一 t=-5.37 显著的信号
===============================================
发现: 高换手 20日 是 A 股最强的负向信号 (避开即赚).
问题:
  Q1. 十分位分布: 线性还是尾部?
  Q2. 低换手的正向 alpha 有多大?
  Q3. 危险阈值: turn20 > X 就该避开?
  Q4. 年度稳定性: 牛市/熊市都有效?
  Q5. 叠加价值 BM: 能否组合成更强信号?

输出: research/factors_v2/output/turnover_deep_dive.csv
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
    build_universe, _investable_at, _get_price_at,
    ROUND_TRIP_COST, Q_MONTH, Q_DAY, CORRECT_DELAY, OUT_DIR
)


def _fwd_ret(price_cache, code, sig_date, fwd_date):
    ep = _get_price_at(price_cache, code, sig_date)
    xp = _get_price_at(price_cache, code, fwd_date)
    if ep and xp and ep > 0:
        return xp / ep - 1
    return np.nan


# ── Q1: 十分位分析 ─────────────────────────────────────────────────────────────
def decile_analysis(panel_df, price_cache, year_range=(2017, 2025)):
    print("\n" + "=" * 80)
    print("  Q1. 换手率十分位分析 (2017-2024)")
    print("=" * 80)
    all_data = []  # 收集所有 (turn, 6M return)

    for yr in range(year_range[0], year_range[1]):
        for q in [1, 2, 3, 4]:
            rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
            sig_date = rpt_date + pd.Timedelta(days=CORRECT_DELAY[q])
            fwd_date = sig_date + pd.Timedelta(days=180)
            uni = _investable_at(panel_df, price_cache, rpt_date, sig_date,
                                  mcap_range=(30, 500), min_turn=0.01)
            if len(uni) < 100: continue

            uni["fwd_6m"] = uni["code"].apply(
                lambda c: _fwd_ret(price_cache, c, sig_date, fwd_date)
            )
            uni = uni.dropna(subset=["fwd_6m", "turn20"])

            for _, r in uni.iterrows():
                all_data.append({"turn20": r["turn20"], "fwd_6m": r["fwd_6m"], "yr": yr})

    adf = pd.DataFrame(all_data)
    print(f"  全部观察: {len(adf):,} 只-季度")
    print(f"  turn20 分布:")
    print(f"    mean {adf['turn20'].mean():.2f}%  median {adf['turn20'].median():.2f}%")
    print(f"    p90 {adf['turn20'].quantile(0.9):.2f}%  p99 {adf['turn20'].quantile(0.99):.2f}%")
    print()

    # 按十分位分组
    adf["decile"] = pd.qcut(adf["turn20"], 10, labels=False, duplicates="drop")
    summary = adf.groupby("decile").agg(
        n=("fwd_6m", "count"),
        turn_min=("turn20", "min"),
        turn_max=("turn20", "max"),
        turn_mean=("turn20", "mean"),
        mean_6m=("fwd_6m", "mean"),
        median_6m=("fwd_6m", "median"),
        win_pct=("fwd_6m", lambda x: (x > 0).mean() * 100),
    ).reset_index()

    print(f"{'十分位':<6s} {'N':>7s} {'turn 区间 (%)':>20s} {'均值':>8s} "
          f"{'6M 均值':>9s} {'中位数':>8s} {'胜率':>6s}")
    print("-" * 72)
    for _, r in summary.iterrows():
        label = f"D{int(r['decile'])+1}"
        if int(r['decile']) == 0: label += " (最低)"
        if int(r['decile']) == 9: label += " (最高)"
        print(f"  {label:<6s} {r['n']:>6.0f}  "
              f"[{r['turn_min']:>5.2f} - {r['turn_max']:>5.2f}]  "
              f"{r['turn_mean']:>6.2f} "
              f"{r['mean_6m']*100:>+7.2f}%  "
              f"{r['median_6m']*100:>+6.2f}%  "
              f"{r['win_pct']:>5.1f}%")

    # 对比最高 vs 最低十分位
    d10 = summary.iloc[-1]
    d1  = summary.iloc[0]
    print(f"\n  D1 - D10 (最低 vs 最高) spread: "
          f"{(d1['mean_6m'] - d10['mean_6m'])*100:+.2f}%/6M "
          f"(年化 {((1+d1['mean_6m'])/(1+d10['mean_6m']))**2 - 1:.1%})")

    return summary, adf


# ── Q2: 危险阈值搜索 ──────────────────────────────────────────────────────────
def threshold_search(adf):
    print("\n" + "=" * 80)
    print("  Q2. 危险阈值: turn20 > X 的组收益")
    print("=" * 80)
    print(f"{'阈值':<10s} {'超过N':>8s} {'占比':>6s} {'平均6M':>9s} {'胜率':>6s} {'vs 全样本':>10s}")
    print("-" * 60)
    overall = adf["fwd_6m"].mean()
    for th in [1, 2, 3, 4, 5, 7, 10, 15, 20, 25]:
        sub = adf[adf["turn20"] > th]
        if len(sub) < 50: continue
        print(f"  turn > {th:>3}%   {len(sub):>6}  "
              f"{len(sub)/len(adf)*100:>4.1f}%  "
              f"{sub['fwd_6m'].mean()*100:>+7.2f}%  "
              f"{(sub['fwd_6m']>0).mean()*100:>5.1f}%  "
              f"{(sub['fwd_6m'].mean()-overall)*100:>+8.2f}%")


# ── Q3: 年度稳定性 ────────────────────────────────────────────────────────────
def yearly_stability(adf):
    print("\n" + "=" * 80)
    print("  Q3. 年度稳定性: 高换手效应是常年还是只在牛市")
    print("=" * 80)
    # 每年: 最高换手组 (D10) vs 最低 (D1) 的差
    print(f"{'年份':<6s} {'N':>6s} {'D1最低6M':>11s} {'D10最高6M':>12s} {'Spread':>9s}")
    print("-" * 50)
    for yr in sorted(adf["yr"].unique()):
        sub = adf[adf["yr"] == yr]
        if len(sub) < 100: continue
        sub = sub.copy()
        sub["d"] = pd.qcut(sub["turn20"], 10, labels=False, duplicates="drop")
        d1  = sub[sub["d"] == 0]["fwd_6m"].mean()
        d10 = sub[sub["d"] == 9]["fwd_6m"].mean()
        print(f"  {yr}   {len(sub):>5}  "
              f"{d1*100:>+8.1f}%   "
              f"{d10*100:>+9.1f}%   "
              f"{(d1-d10)*100:>+7.1f}%")


# ── Q4: 低换手 (D1) 作为 long-only 策略 ──────────────────────────────────────
def low_turnover_strategy(panel_df, price_cache):
    print("\n" + "=" * 80)
    print("  Q4. 低换手独立策略: 只买 D1 (最低换手 10%) 的效果")
    print("=" * 80)

    period_results = []
    for yr in range(2017, 2025):
        for q in [1, 2, 3, 4]:
            rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
            sig_date = rpt_date + pd.Timedelta(days=CORRECT_DELAY[q])
            fwd_date = sig_date + pd.Timedelta(days=180)
            uni = _investable_at(panel_df, price_cache, rpt_date, sig_date,
                                  mcap_range=(30, 500), min_turn=0.01)
            if len(uni) < 100: continue
            uni["fwd_6m"] = uni["code"].apply(
                lambda c: _fwd_ret(price_cache, c, sig_date, fwd_date)
            )
            uni = uni.dropna(subset=["fwd_6m"])
            if len(uni) < 100: continue
            n_decile = max(len(uni) // 10, 10)
            d1  = uni.nsmallest(n_decile, "turn20")["fwd_6m"].mean()
            # Random control
            np.random.seed(42 + yr*4 + q)
            rand_ret = uni["fwd_6m"].sample(n=min(30, len(uni))).mean()
            period_results.append({
                "yr": yr, "q": q,
                "d1_mean": d1,
                "rand_mean": rand_ret,
                "alpha": d1 - rand_ret,
            })

    pdf = pd.DataFrame(period_results)
    alpha = pdf["alpha"].mean()
    t_stat = alpha / (pdf["alpha"].std(ddof=1) / np.sqrt(len(pdf)))
    print(f"  D1 (最低换手) 平均 6M: {pdf['d1_mean'].mean()*100:+.2f}%")
    print(f"  随机组 平均 6M:       {pdf['rand_mean'].mean()*100:+.2f}%")
    print(f"  Alpha gross:          {alpha*100:+.2f}%/6M")
    print(f"  Alpha net (扣 56bp):   {(alpha-ROUND_TRIP_COST)*100:+.2f}%/6M")
    print(f"  t-stat: {t_stat:.2f}  胜率: {(pdf['alpha']>0).mean()*100:.0f}%")
    print(f"  年化 net alpha: {((1+alpha-ROUND_TRIP_COST)**2-1)*100:+.1f}%")
    return pdf


# ── Q5: 低换手 × BM 价值 叠加 ─────────────────────────────────────────────────
def low_turn_plus_value(panel_df, price_cache):
    print("\n" + "=" * 80)
    print("  Q5. 低换手 + 高 BM (价值) 双因子交叉")
    print("=" * 80)
    period_results = []
    for yr in range(2017, 2025):
        for q in [1, 2, 3, 4]:
            rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
            sig_date = rpt_date + pd.Timedelta(days=CORRECT_DELAY[q])
            fwd_date = sig_date + pd.Timedelta(days=180)
            uni = _investable_at(panel_df, price_cache, rpt_date, sig_date,
                                  mcap_range=(30, 500), min_turn=0.01)
            if len(uni) < 100: continue
            uni["fwd_6m"] = uni["code"].apply(
                lambda c: _fwd_ret(price_cache, c, sig_date, fwd_date)
            )
            uni = uni.dropna(subset=["fwd_6m", "bm_ratio"])
            if len(uni) < 100: continue

            # 排名: 低换手高 rank (逆序), 高 BM 高 rank
            uni["turn_rank"] = uni["turn20"].rank(ascending=True)  # 低 turn = rank 小
            uni["bm_rank"]   = uni["bm_ratio"].rank(ascending=False)  # 高 BM = rank 小
            # 合成: 越小越好
            uni["combo"] = uni["turn_rank"] + uni["bm_rank"]
            n_top = max(len(uni) // 10, 10)
            combo_ret = uni.nsmallest(n_top, "combo")["fwd_6m"].mean()
            # 对比: 单独低换手, 单独高 BM
            only_turn = uni.nsmallest(n_top, "turn_rank")["fwd_6m"].mean()
            only_bm   = uni.nsmallest(n_top, "bm_rank")["fwd_6m"].mean()
            np.random.seed(42 + yr*4 + q)
            rand = uni["fwd_6m"].sample(n=min(30, len(uni))).mean()
            period_results.append({
                "yr": yr, "q": q,
                "combo": combo_ret, "only_turn": only_turn,
                "only_bm": only_bm, "random": rand,
            })

    pdf = pd.DataFrame(period_results)
    print(f"  {'策略':<20s} {'均6M':>8s} {'vs 随机':>9s} {'t-stat':>7s} {'胜率':>6s}")
    print("-" * 55)
    for col, label in [("combo", "低换手+高BM"), ("only_turn", "仅低换手"),
                        ("only_bm", "仅高BM"), ("random", "随机")]:
        alpha = (pdf[col] - pdf["random"]).mean()
        if col == "random":
            print(f"  {label:<18s}  {pdf[col].mean()*100:>+6.2f}% {'—':>9s} {'—':>7s} {'—':>6s}")
            continue
        alpha_std = (pdf[col] - pdf["random"]).std(ddof=1)
        t = alpha / (alpha_std / np.sqrt(len(pdf))) if alpha_std > 0 else np.nan
        win = ((pdf[col] - pdf["random"]) > 0).mean() * 100
        print(f"  {label:<18s}  {pdf[col].mean()*100:>+6.2f}%  "
              f"{alpha*100:>+6.2f}%  {t:>6.2f}  {win:>4.0f}%")


# ── Q6: 603659 当前换手率检查 ─────────────────────────────────────────────────
def check_current_position(price_cache):
    print("\n" + "=" * 80)
    print("  Q6. 当前持仓 603659 换手率风险评估")
    print("=" * 80)
    if "603659" not in price_cache:
        print("  603659 不在价格缓存")
        return
    pf = price_cache["603659"]
    if "turn" not in pf.columns:
        print("  603659 无换手数据")
        return
    recent20 = pf.tail(20)
    recent60 = pf.tail(60)
    recent252 = pf.tail(252)
    print(f"  最近 20 日  换手率均值: {recent20['turn'].mean():.2f}%  中位数: {recent20['turn'].median():.2f}%")
    print(f"  最近 60 日  换手率均值: {recent60['turn'].mean():.2f}%")
    print(f"  最近 252 日 换手率均值: {recent252['turn'].mean():.2f}%")
    print(f"  最近 20 日最高: {recent20['turn'].max():.2f}%")
    # 全市场参照 (从十分位分析)
    print(f"\n  参照: 研究中 D9-D10 (高换手, 亏损区) 界限 ~ 7-10%")
    print(f"         研究中 D1 (最低换手, 最优区) < 1.2%")
    t20 = recent20['turn'].mean()
    if t20 < 2:
        risk = "低风险 (类 D1-D3)"
    elif t20 < 5:
        risk = "中等 (类 D4-D6)"
    elif t20 < 10:
        risk = "偏高 (类 D7-D8, 慎)"
    else:
        risk = "危险 (类 D9-D10, 历史净负)"
    print(f"  603659 评级: {risk}")


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    panel_df, price_cache, meta = build_universe(verbose=True)

    summary, adf = decile_analysis(panel_df, price_cache)
    threshold_search(adf)
    yearly_stability(adf)
    low_turnover_strategy(panel_df, price_cache)
    low_turn_plus_value(panel_df, price_cache)
    check_current_position(price_cache)

    # 保存十分位结果
    out_fp = os.path.join(OUT_DIR, "turnover_deep_dive.csv")
    summary.to_csv(out_fp, index=False, encoding="utf-8-sig")
    print(f"\n[+] 写入 {out_fp}")


if __name__ == "__main__":
    main()
