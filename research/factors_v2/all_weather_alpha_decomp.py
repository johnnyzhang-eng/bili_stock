"""
T2 全天候 Alpha 解构 (2026-04-28)
=====================================
问题: T2 双动量 overlay 在 2018-2026 OOS 段没赢基线静态 30/30/40
      → momentum 择时是真有 alpha, 还是 fortuitous timing?

解构维度:
  Layer 0: 4 资产单独跑 (DIV / GEM / BOND / GOLD) — alpha 上限参考
  Layer 1: 静态 30/30/40 季度再平衡 — 配比 alpha
  Layer 2: T2 with momentum (生产配置)  — 配比 + 择时 alpha
  Layer 3: T2 反向 momentum (counterfactual) — 验证择时是否真的"看对方向"
  Layer 4: T2 randomized signal (噪音对照) — 50% 概率开关 STK/GOLD

判定:
  - 若 T2 vs Static 在 OOS 段 ΔCalmar > 0 且 反向 < 0: momentum 择时真有 alpha
  - 若 T2 vs Static 接近 0 或 < 0: 加 momentum 等于白做
  - 若反向 ≈ 正向: 信号是噪音, 择时无方向性 alpha

输出:
  - 各层 NAV / CAGR / MDD / Calmar / Sharpe (Train / Test / Full)
  - momentum 决策日志 (每次切换时间, 切换前后资产, T+1 季度实际收益)
  - 报告: research/factors_v2/output/all_weather_alpha_decomp.md
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

COST = (13 + 43) / 10000   # 56bp 单边
SPLIT = pd.Timestamp("2018-06-30")

W_BASE = {"STK": 0.30, "BOND": 0.30, "GOLD": 0.40}
STK_DIV = 0.7
STK_GEM = 0.3


# ── 数据加载 ─────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    df = pd.read_csv(LONG_HIST, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for c in ["DIV", "GEM", "BOND", "GOLD"]:
        df[f"r_{c}"] = df[c].pct_change().fillna(0.0)
    df["STK"] = STK_DIV * df["DIV"] + STK_GEM * df["GEM"]
    df["r_STK"] = STK_DIV * df["r_DIV"] + STK_GEM * df["r_GEM"]
    df["STK_sma200"] = df["STK"].rolling(200).mean()
    df["STK_ret12m"] = df["STK"].pct_change(252)
    df["GOLD_ret12m"] = df["GOLD"].pct_change(252)
    return df


def metrics(nav: pd.Series, dates: pd.Series, mask: pd.Series) -> dict:
    sub_nav = nav[mask.values]
    sub_dates = dates[mask.values]
    if len(sub_nav) < 100 or sub_nav.iloc[0] <= 0:
        return None
    sub = sub_nav / sub_nav.iloc[0]
    yrs = (sub_dates.iloc[-1] - sub_dates.iloc[0]).days / 365.25
    cagr = (sub.iloc[-1] / sub.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    dr = sub.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sh = (dr.mean() * 252 - 0.02) / vol if vol > 0 else 0
    mdd = (sub / sub.cummax() - 1).min()
    cal = cagr / abs(mdd) if mdd < 0 else 0
    return {"CAGR": cagr, "Vol": vol, "MDD": mdd, "Calmar": cal, "Sharpe": sh, "years": yrs}


# ── 模拟器 (扩展自 all_weather_oos.simulate) ─────────────────────────────
def simulate_single_asset(df: pd.DataFrame, asset: str) -> pd.Series:
    """单资产 NAV (无再平衡, 纯持有)"""
    nav = df[asset] / df[asset].iloc[0]
    return nav


def simulate_static(df: pd.DataFrame) -> pd.Series:
    """静态 30/30/40 季度再平衡, 不含 momentum"""
    return _simulate_with_overlay(df, mode="static")


def simulate_t2(df: pd.DataFrame) -> tuple[pd.Series, list]:
    """T2 双动量 overlay, 返回 (nav, decisions)"""
    return _simulate_with_overlay(df, mode="t2", track_decisions=True)


def simulate_t2_reverse(df: pd.DataFrame) -> pd.Series:
    """T2 反向 momentum (信号反着做)"""
    return _simulate_with_overlay(df, mode="t2_reverse")[0]


def simulate_t2_random(df: pd.DataFrame, seed: int = 42) -> pd.Series:
    """T2 随机 momentum (50% 概率开关)"""
    return _simulate_with_overlay(df, mode="t2_random", seed=seed)[0]


def _simulate_with_overlay(df: pd.DataFrame, mode: str,
                            track_decisions: bool = False,
                            seed: int = 42) -> tuple[pd.Series, list]:
    """
    通用模拟器.
    mode:
      static       — 仅静态 30/30/40, 季度 rebal
      t2           — T2 双动量
      t2_reverse   — T2 信号反向
      t2_random    — T2 信号 random
    """
    rng = np.random.RandomState(seed)
    dt = df["date"]
    mask_q = dt.dt.to_period("Q") != dt.dt.to_period("Q").shift()

    vals = {"DIV": W_BASE["STK"] * STK_DIV, "GEM": W_BASE["STK"] * STK_GEM,
            "BOND": W_BASE["BOND"], "GOLD": W_BASE["GOLD"]}
    series = np.zeros(len(df))
    decisions = []

    for i in range(len(df)):
        if i > 0:
            for k in vals:
                vals[k] *= (1 + df[f"r_{k}"].iloc[i])

        if not (mask_q.iloc[i] and i >= 252):
            if i == 0:
                series[i] = sum(vals.values())
            else:
                series[i] = sum(vals.values())
            continue

        w = dict(W_BASE)

        if mode == "static":
            pass  # 不动 weights
            stk_on, gold_on = True, True
        else:
            rm = df["STK_ret12m"].iloc[i]
            above = df["STK"].iloc[i] > df["STK_sma200"].iloc[i]
            rg = df["GOLD_ret12m"].iloc[i]

            stk_signal = (not pd.isna(rm)) and rm > 0 and above
            gold_signal = (not pd.isna(rg)) and rg > 0

            if mode == "t2":
                stk_on, gold_on = stk_signal, gold_signal
            elif mode == "t2_reverse":
                stk_on, gold_on = (not stk_signal), (not gold_signal)
            elif mode == "t2_random":
                stk_on = rng.rand() > 0.3   # 70% on (匹配真实 T2 STK 开启率)
                gold_on = rng.rand() > 0.2  # 80% on
            else:
                raise ValueError(f"unknown mode: {mode}")

            if not stk_on:
                w["BOND"] += w["STK"]; w["STK"] = 0.0
            if not gold_on:
                w["BOND"] += w["GOLD"]; w["GOLD"] = 0.0

        # 季度再平衡
        tot = sum(vals.values())
        tgt = {"DIV": tot * w["STK"] * STK_DIV,
               "GEM": tot * w["STK"] * STK_GEM,
               "BOND": tot * w["BOND"],
               "GOLD": tot * w["GOLD"]}
        tov = sum(abs(tgt[k] - vals[k]) for k in tgt) / tot if tot > 0 else 0
        cost = tot * tov * COST * 0.5
        vals = dict(tgt)
        scale = 1 - cost / tot if tot > 0 else 1
        for k in vals: vals[k] *= scale
        series[i] = sum(vals.values())

        if track_decisions and mode in ("t2", "t2_reverse"):
            decisions.append({
                "date": dt.iloc[i],
                "stk_on": stk_on,
                "gold_on": gold_on,
                "stk_ret12m": float(rm) if not pd.isna(rm) else None,
                "gold_ret12m": float(rg) if not pd.isna(rg) else None,
                "stk_above_sma200": bool(above),
                "nav": float(sum(vals.values())),
            })

    return pd.Series(series, index=df.index), decisions


# ── decision forensics ──────────────────────────────────────────────────
def annotate_decisions(decisions: list, df: pd.DataFrame) -> pd.DataFrame:
    """对每次决策, 算 T+1 季度实际收益 (vs 假如不切的 counterfactual)"""
    out = []
    dates = df["date"].values
    for j, d in enumerate(decisions):
        idx = df.index[df["date"] == d["date"]][0]
        # 找下一季度末
        if j + 1 < len(decisions):
            next_idx = df.index[df["date"] == decisions[j + 1]["date"]][0]
        else:
            next_idx = len(df) - 1

        # 这一段实际 STK / GOLD / BOND 收益
        stk_ret = df["STK"].iloc[next_idx] / df["STK"].iloc[idx] - 1
        bond_ret = df["BOND"].iloc[next_idx] / df["BOND"].iloc[idx] - 1
        gold_ret = df["GOLD"].iloc[next_idx] / df["GOLD"].iloc[idx] - 1

        # 切 STK 决策的对错: stk_on=False 但 STK 实际涨 → 切错
        if not d["stk_on"]:
            stk_call = "切对" if stk_ret < bond_ret else "切错"
        else:
            stk_call = "持(对)" if stk_ret > bond_ret else "持(错)"

        if not d["gold_on"]:
            gold_call = "切对" if gold_ret < bond_ret else "切错"
        else:
            gold_call = "持(对)" if gold_ret > bond_ret else "持(错)"

        out.append({
            "date": d["date"].date(),
            "stk_on": d["stk_on"],
            "gold_on": d["gold_on"],
            "next_stk_ret": stk_ret,
            "next_bond_ret": bond_ret,
            "next_gold_ret": gold_ret,
            "stk_call": stk_call,
            "gold_call": gold_call,
        })
    return pd.DataFrame(out)


# ── main ───────────────────────────────────────────────────────────────
def main():
    print("=" * 100)
    print("  T2 全天候 Alpha 解构 (2026-04-28)")
    print("=" * 100)

    df = load_data()
    mask_train = df["date"] <= SPLIT
    mask_test = df["date"] > SPLIT
    mask_full = pd.Series(True, index=df.index)
    print(f"  数据: {df['date'].min().date()} → {df['date'].max().date()}  ({len(df):,} 天)")
    print(f"  Train: ≤ {SPLIT.date()}  Test: > {SPLIT.date()}")
    print()

    # Layer 0: 单资产
    print("[Layer 0] 4 资产单独 (无配置, 纯持有)")
    layers = []
    for asset in ["DIV", "GEM", "BOND", "GOLD"]:
        nav = simulate_single_asset(df, asset)
        layers.append((f"  {asset}", nav))

    # Layer 1: 静态 30/30/40
    print("[Layer 1] 静态 30/30/40 季度再平衡")
    nav_static = simulate_static(df)[0] if isinstance(simulate_static(df), tuple) else simulate_static(df)
    # 重新跑 (避免上面被 .[0] 卡住, 直接重算)
    nav_static, _ = _simulate_with_overlay(df, mode="static")
    layers.append(("Static 30/30/40", nav_static))

    # Layer 2: T2
    print("[Layer 2] T2 双动量 overlay (生产配置)")
    nav_t2, decs_t2 = _simulate_with_overlay(df, mode="t2", track_decisions=True)
    layers.append(("T2 momentum", nav_t2))

    # Layer 3: T2 反向
    print("[Layer 3] T2 反向 momentum (counterfactual)")
    nav_rev, _ = _simulate_with_overlay(df, mode="t2_reverse")
    layers.append(("T2 reverse", nav_rev))

    # Layer 4: T2 random (跑 5 个 seed 取中位数)
    print("[Layer 4] T2 random 信号 (5 seeds)")
    rand_navs = []
    for sd in [42, 7, 13, 99, 314]:
        n, _ = _simulate_with_overlay(df, mode="t2_random", seed=sd)
        rand_navs.append(n)
    nav_rand_med = pd.concat(rand_navs, axis=1).median(axis=1)
    layers.append(("T2 random (med 5)", nav_rand_med))

    # ── 总览表 ──────────────────────────────────────────────────────────
    print()
    print("=" * 130)
    print(f"{'层':<22s} | {'Full':^32s} | {'Train':^32s} | {'Test':^32s}")
    print(f"{'':22s} | {'CAGR':>7s} {'MDD':>7s} {'Cal':>5s} {'Shp':>5s} | "
          f"{'CAGR':>7s} {'MDD':>7s} {'Cal':>5s} {'Shp':>5s} | "
          f"{'CAGR':>7s} {'MDD':>7s} {'Cal':>5s} {'Shp':>5s}")
    print("-" * 130)

    rows = []
    for name, nav in layers:
        mf = metrics(nav, df["date"], mask_full)
        mt = metrics(nav, df["date"], mask_train)
        mx = metrics(nav, df["date"], mask_test)
        rows.append((name, mf, mt, mx))
        def fmt(m):
            if m is None: return f"{'-':>7s} {'-':>7s} {'-':>5s} {'-':>5s}"
            return f"{m['CAGR']:>+6.2%} {m['MDD']:>+6.1%} {m['Calmar']:>5.2f} {m['Sharpe']:>5.2f}"
        print(f"  {name:<20s} | {fmt(mf)} | {fmt(mt)} | {fmt(mx)}")

    # ── Alpha 解构 ──────────────────────────────────────────────────────
    print()
    print("=" * 130)
    print("  Alpha 解构 (Calmar)")
    print("=" * 130)
    static_row = next(r for r in rows if r[0] == "Static 30/30/40")
    t2_row     = next(r for r in rows if r[0] == "T2 momentum")
    rev_row    = next(r for r in rows if r[0] == "T2 reverse")
    rand_row   = next(r for r in rows if r[0] == "T2 random (med 5)")

    def delta_cal(a, b):
        if a is None or b is None: return None
        return a["Calmar"] - b["Calmar"]

    print(f"\n  Train 段:")
    print(f"    Static Calmar = {static_row[2]['Calmar']:.2f}")
    print(f"    T2 vs Static  = {delta_cal(t2_row[2], static_row[2]):+.2f}")
    print(f"    Reverse vs Static = {delta_cal(rev_row[2], static_row[2]):+.2f}  (期望 < 0 验证 momentum 真方向性)")
    print(f"    Random vs Static  = {delta_cal(rand_row[2], static_row[2]):+.2f}  (期望 ≈ 0 噪音 baseline)")

    print(f"\n  Test 段 (OOS):")
    print(f"    Static Calmar = {static_row[3]['Calmar']:.2f}")
    print(f"    T2 vs Static  = {delta_cal(t2_row[3], static_row[3]):+.2f}")
    print(f"    Reverse vs Static = {delta_cal(rev_row[3], static_row[3]):+.2f}")
    print(f"    Random vs Static  = {delta_cal(rand_row[3], static_row[3]):+.2f}")

    # ── 决策日志 ────────────────────────────────────────────────────────
    print()
    print("=" * 130)
    print("  T2 momentum 决策日志 (每个季度末)")
    print("=" * 130)
    dec_df = annotate_decisions(decs_t2, df)
    n_total = len(dec_df)
    n_stk_off = (~dec_df["stk_on"]).sum()
    n_gold_off = (~dec_df["gold_on"]).sum()
    n_stk_correct = ((dec_df["stk_call"] == "切对") | (dec_df["stk_call"] == "持(对)")).sum()
    n_gold_correct = ((dec_df["gold_call"] == "切对") | (dec_df["gold_call"] == "持(对)")).sum()
    print(f"  总决策: {n_total} 季")
    print(f"  STK off (转债): {n_stk_off} ({n_stk_off/n_total*100:.0f}%)")
    print(f"  GOLD off (转债): {n_gold_off} ({n_gold_off/n_total*100:.0f}%)")
    print(f"  STK 决策对: {n_stk_correct}/{n_total} = {n_stk_correct/n_total*100:.0f}%")
    print(f"  GOLD 决策对: {n_gold_correct}/{n_total} = {n_gold_correct/n_total*100:.0f}%")

    # 拆 Train / Test
    dec_df["dt"] = pd.to_datetime(dec_df["date"])
    dec_train = dec_df[dec_df["dt"] <= SPLIT]
    dec_test = dec_df[dec_df["dt"] > SPLIT]
    print(f"\n  Train (≤ {SPLIT.date()}): {len(dec_train)} 决策")
    print(f"    STK 对 {((dec_train['stk_call']=='切对')|(dec_train['stk_call']=='持(对)')).sum()}/{len(dec_train)} = "
          f"{((dec_train['stk_call']=='切对')|(dec_train['stk_call']=='持(对)')).mean()*100:.0f}%")
    print(f"    GOLD 对 {((dec_train['gold_call']=='切对')|(dec_train['gold_call']=='持(对)')).sum()}/{len(dec_train)} = "
          f"{((dec_train['gold_call']=='切对')|(dec_train['gold_call']=='持(对)')).mean()*100:.0f}%")
    print(f"  Test (> {SPLIT.date()}): {len(dec_test)} 决策")
    print(f"    STK 对 {((dec_test['stk_call']=='切对')|(dec_test['stk_call']=='持(对)')).sum()}/{len(dec_test)} = "
          f"{((dec_test['stk_call']=='切对')|(dec_test['stk_call']=='持(对)')).mean()*100:.0f}%")
    print(f"    GOLD 对 {((dec_test['gold_call']=='切对')|(dec_test['gold_call']=='持(对)')).sum()}/{len(dec_test)} = "
          f"{((dec_test['gold_call']=='切对')|(dec_test['gold_call']=='持(对)')).mean()*100:.0f}%")

    # 列出"切错"的决策
    wrong = dec_df[(dec_df["stk_call"] == "切错") | (dec_df["gold_call"] == "切错")]
    print(f"\n  显著切错的决策 (T+1Q 收益反着):")
    print(f"  {'date':<12s} {'STK':<5s} {'GOLD':<5s} {'STK次Q':>8s} {'BOND次Q':>8s} {'GOLD次Q':>8s} {'STK判':<8s} {'GOLD判':<8s}")
    for _, r in wrong.iterrows():
        print(f"  {str(r['date']):<12s} "
              f"{'OFF' if not r['stk_on'] else 'ON':<5s} "
              f"{'OFF' if not r['gold_on'] else 'ON':<5s} "
              f"{r['next_stk_ret']*100:>+7.1f}% "
              f"{r['next_bond_ret']*100:>+7.1f}% "
              f"{r['next_gold_ret']*100:>+7.1f}% "
              f"{r['stk_call']:<8s} {r['gold_call']:<8s}")

    # ── 写报告 ─────────────────────────────────────────────────────────
    md_path = os.path.join(OUT_DIR, "all_weather_alpha_decomp.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# T2 全天候 Alpha 解构 (2026-04-28)\n\n")
        f.write(f"数据: {df['date'].min().date()} → {df['date'].max().date()}  "
                f"({len(df):,} 天)\n")
        f.write(f"Train ≤ {SPLIT.date()}  /  Test > {SPLIT.date()}\n\n")
        f.write("## 总览\n\n")
        f.write("| 层 | Full CAGR | Full MDD | Full Cal | Train Cal | Test Cal | Cal 保留 |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for name, mf, mt, mx in rows:
            if mf is None or mt is None or mx is None:
                f.write(f"| {name} | - | - | - | - | - | - |\n")
                continue
            ret = mx["Calmar"] / mt["Calmar"] if mt["Calmar"] > 0 else float("nan")
            f.write(f"| {name} | {mf['CAGR']*100:+.2f}% | {mf['MDD']*100:+.1f}% | "
                    f"{mf['Calmar']:.2f} | {mt['Calmar']:.2f} | {mx['Calmar']:.2f} | "
                    f"{ret*100:.0f}% |\n")

        f.write("\n## Alpha 解构 (T2 momentum 真贡献?)\n\n")
        f.write("**Train 段:**\n\n")
        f.write(f"- Static Calmar = {static_row[2]['Calmar']:.2f}\n")
        f.write(f"- T2 vs Static  = {delta_cal(t2_row[2], static_row[2]):+.2f}\n")
        f.write(f"- Reverse vs Static = {delta_cal(rev_row[2], static_row[2]):+.2f}  (期望 < 0 验证方向性)\n")
        f.write(f"- Random vs Static  = {delta_cal(rand_row[2], static_row[2]):+.2f}  (噪音 baseline)\n\n")
        f.write("**Test 段 (OOS):**\n\n")
        f.write(f"- Static Calmar = {static_row[3]['Calmar']:.2f}\n")
        f.write(f"- T2 vs Static  = {delta_cal(t2_row[3], static_row[3]):+.2f}\n")
        f.write(f"- Reverse vs Static = {delta_cal(rev_row[3], static_row[3]):+.2f}\n")
        f.write(f"- Random vs Static  = {delta_cal(rand_row[3], static_row[3]):+.2f}\n\n")

        f.write("## 决策准确率\n\n")
        f.write(f"- 总 {n_total} 季度决策\n")
        f.write(f"- STK 切换次数: {n_stk_off} ({n_stk_off/n_total*100:.0f}%)\n")
        f.write(f"- GOLD 切换次数: {n_gold_off} ({n_gold_off/n_total*100:.0f}%)\n")
        f.write(f"- STK 决策对: {n_stk_correct}/{n_total} = {n_stk_correct/n_total*100:.0f}%\n")
        f.write(f"- GOLD 决策对: {n_gold_correct}/{n_total} = {n_gold_correct/n_total*100:.0f}%\n\n")
        f.write(f"切对 = 切走的资产次 Q 实际跑输 BOND, 持仓的资产次 Q 实际跑赢 BOND.\n\n")

        # full decisions table
        f.write("## 完整决策日志\n\n")
        f.write("| date | STK | GOLD | STK次Q | BOND次Q | GOLD次Q | STK判 | GOLD判 |\n")
        f.write("|---|---|---|---:|---:|---:|---|---|\n")
        for _, r in dec_df.iterrows():
            f.write(f"| {r['date']} | "
                    f"{'OFF' if not r['stk_on'] else 'ON'} | "
                    f"{'OFF' if not r['gold_on'] else 'ON'} | "
                    f"{r['next_stk_ret']*100:+.1f}% | "
                    f"{r['next_bond_ret']*100:+.1f}% | "
                    f"{r['next_gold_ret']*100:+.1f}% | "
                    f"{r['stk_call']} | {r['gold_call']} |\n")

    print()
    print(f"[+] 报告写入 {md_path}")

    # 同时存决策 csv
    dec_csv = os.path.join(OUT_DIR, "all_weather_t2_decisions.csv")
    dec_df.to_csv(dec_csv, index=False, encoding="utf-8-sig")
    print(f"[+] 决策 CSV: {dec_csv}")


if __name__ == "__main__":
    main()
