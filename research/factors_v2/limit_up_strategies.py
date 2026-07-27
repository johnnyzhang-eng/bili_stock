"""
A 股短线战法回测 — 一进二 / 龙头战法
========================================
基于本地 OHLCV 检测涨停 (pctChg > 9.8%) 进行严格回测.

测试:
  T1. 首板次日: 今日首次涨停 (前 5 日无涨停) → 次日开盘买, 次日收盘卖
  T2. 首板进二板: 同 T1, 次日是否涨停 (≥9.8%)
  T3. 连板龙头: 已连板 N 板的票, 续 1 天的胜率
  T4. 涨停后期表现 (5/20/60 日): 看长期是反转还是延续

成本假设 (散户实盘):
  - 涨停尾盘买: 滑点 +1% (你只能挂单, 实际成交价比预期差)
  - 次日卖: 滑点 -0.5% (开盘抛压或破板, 你被迫低卖)
  - 印花税 + 佣金: 0.13%
  - 单次往返实际成本 ≈ 1.6%
"""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

import numpy as np
import pandas as pd

ROOT      = os.path.abspath(".")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
OUT_DIR   = os.path.join(ROOT, "research", "factors_v2", "output")

# 涨跌停阈值 (主板 ±10%)
LIMIT_UP_THRESHOLD = 9.8   # pct
LIMIT_DOWN_THRESHOLD = -9.8

# 散户实盘成本
SLIPPAGE_BUY = 0.010   # 1% (尾盘抢板)
SLIPPAGE_SELL = 0.005  # 0.5% (次日抛压/破板)
COMMISSION = 0.0013    # 0.13% 单边
ROUND_TRIP_COST_REALISTIC = SLIPPAGE_BUY + SLIPPAGE_SELL + 2*COMMISSION  # ≈ 1.76%


def load_all_prices():
    """加载所有股票, 标记涨停日"""
    cache = {}
    files = glob.glob(os.path.join(STOCK_DIR, "*.csv"))
    print(f"[+] 加载 {len(files)} 只股票...")
    for fp in files:
        code = os.path.basename(fp)[2:8]
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
            dc = next((c for c in ["date","日期"] if c in df.columns), None)
            cc = next((c for c in ["close","收盘"] if c in df.columns), None)
            oc = next((c for c in ["open","开盘"] if c in df.columns), None)
            pc = next((c for c in ["pctChg","涨跌幅"] if c in df.columns), None)
            tc = next((c for c in ["turn","换手率"] if c in df.columns), None)
            if not (dc and cc and pc): continue
            df[dc] = pd.to_datetime(df[dc], errors="coerce")
            df = df.dropna(subset=[dc,cc,pc]).sort_values(dc).reset_index(drop=True)
            renames = {dc:"date", cc:"close", pc:"pct"}
            if oc: renames[oc] = "open"
            if tc: renames[tc] = "turn"
            df = df.rename(columns=renames)
            keep = ["date","close","pct"] + (["open"] if oc else []) + (["turn"] if tc else [])
            cache[code] = df[keep]
        except Exception:
            continue
    return cache


def detect_first_limit_up_signals(cache, lookback=5):
    """
    检测首板信号 (今日涨停, 前 lookback 日无涨停).
    返回: DataFrame [code, date, close_today, pct_today]
    """
    print(f"[+] 检测首板信号 (前 {lookback} 日无涨停)...")
    signals = []
    for code, df in cache.items():
        if len(df) < lookback + 2: continue
        # 今日涨停 + 前 lookback 日无涨停
        for i in range(lookback, len(df)):
            today = df.iloc[i]
            if today["pct"] < LIMIT_UP_THRESHOLD: continue
            prev = df.iloc[i-lookback:i]
            if (prev["pct"] >= LIMIT_UP_THRESHOLD).any(): continue
            signals.append({
                "code": code,
                "idx": i,
                "date": today["date"],
                "close_today": today["close"],
                "pct_today": today["pct"],
                "turn_today": today.get("turn", np.nan),
            })
    print(f"    发现 {len(signals)} 个首板信号 (跨所有股 + 全期)")
    return pd.DataFrame(signals)


def detect_consecutive_boards(cache, n_boards=2):
    """检测已连板 N 板的票, 第 N+1 日跟进的效果"""
    signals = []
    for code, df in cache.items():
        if len(df) < n_boards + 2: continue
        for i in range(n_boards, len(df)):
            window = df.iloc[i-n_boards:i]
            if (window["pct"] >= LIMIT_UP_THRESHOLD).all():
                # 已连板 n_boards 板, 第 i 天介入 (开盘买)
                signals.append({
                    "code": code,
                    "idx": i,
                    "date": df.iloc[i]["date"],
                })
    return pd.DataFrame(signals)


def evaluate_signals(cache, signals_df, hold_days=1, entry_at="open"):
    """
    评估信号: 在 idx 日买入, hold_days 后卖出
    entry_at: "open" = 信号日开盘买 (实际操作: T+1 实施)
              "close" = 信号日收盘买 (限于尾盘抢板)
    """
    results = []
    for _, sig in signals_df.iterrows():
        code = sig["code"]
        idx = int(sig["idx"])
        df = cache[code]
        if idx + hold_days >= len(df): continue
        if entry_at == "open" and idx + 1 >= len(df): continue
        # 入场: 信号日 close 抢板 OR 次日 open
        if entry_at == "close":
            entry = df.iloc[idx]["close"]
        else:  # open of next day
            if "open" in df.columns:
                entry = df.iloc[idx + 1]["open"]
            else:
                entry = df.iloc[idx]["close"] * (1 + 0.005)  # 估算次日开盘溢价
        # 出场: 持有 hold_days 后 close
        exit_idx = idx + hold_days if entry_at == "close" else idx + 1 + hold_days - 1
        if exit_idx >= len(df): continue
        exit_price = df.iloc[exit_idx]["close"]
        gross_ret = exit_price / entry - 1
        # 检查次日是否涨停 (一进二 binary)
        next_idx = idx + 1
        next_pct = df.iloc[next_idx]["pct"] if next_idx < len(df) else np.nan
        results.append({
            "code": code,
            "date": sig["date"],
            "entry": entry,
            "exit": exit_price,
            "gross_ret": gross_ret,
            "next_day_pct": next_pct,
            "next_day_limit_up": next_pct >= LIMIT_UP_THRESHOLD if not np.isnan(next_pct) else False,
        })
    return pd.DataFrame(results)


def evaluate_long_horizon(cache, signals_df, horizons=(1, 5, 20, 60)):
    """评估长期持有效果 (反转 vs 延续)"""
    rows = []
    for _, sig in signals_df.iterrows():
        code = sig["code"]
        idx = int(sig["idx"])
        df = cache[code]
        entry = df.iloc[idx]["close"]
        rec = {"code": code, "date": sig["date"]}
        for h in horizons:
            if idx + h < len(df):
                rec[f"ret_{h}d"] = df.iloc[idx + h]["close"] / entry - 1
            else:
                rec[f"ret_{h}d"] = np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    cache = load_all_prices()

    # ── T1+T2: 首板信号检测 + 一进二 ─────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  测试 T1: 首板进二板")
    print("=" * 80)
    fb = detect_first_limit_up_signals(cache, lookback=5)
    if len(fb) == 0:
        print("无首板信号"); return

    # 评估: 次日开盘买, 次日收盘卖 (1 天持仓)
    res = evaluate_signals(cache, fb, hold_days=1, entry_at="open")
    print(f"  有效记录: {len(res)} 条 (排除停牌/最后一日)")
    print(f"\n  策略: 首板次日开盘买, 次日收盘卖 (持仓 1 日)")
    print(f"  毛收益均值: {res['gross_ret'].mean()*100:>+5.2f}%")
    print(f"  毛收益中位数: {res['gross_ret'].median()*100:>+5.2f}%")
    print(f"  胜率 (>0): {(res['gross_ret']>0).mean()*100:.1f}%")
    print(f"  净收益 (扣 1.76% 成本): {res['gross_ret'].mean()*100 - 176:>+.2f}%")
    print()
    print(f"  次日涨停率 (一进二): {res['next_day_limit_up'].mean()*100:.1f}%")
    print(f"  次日涨幅分布:")
    print(f"    p10 {res['next_day_pct'].quantile(0.10):>+5.1f}%")
    print(f"    p25 {res['next_day_pct'].quantile(0.25):>+5.1f}%")
    print(f"    p50 {res['next_day_pct'].quantile(0.50):>+5.1f}%")
    print(f"    p75 {res['next_day_pct'].quantile(0.75):>+5.1f}%")
    print(f"    p90 {res['next_day_pct'].quantile(0.90):>+5.1f}%")
    print(f"  最差 1%: {res['next_day_pct'].quantile(0.01):>+5.1f}%")

    # 期望值计算
    win = res[res["gross_ret"] > 0]
    lose = res[res["gross_ret"] <= 0]
    print(f"\n  赢家 ({len(win)} 笔): 平均 +{win['gross_ret'].mean()*100:.2f}%")
    print(f"  输家 ({len(lose)} 笔): 平均 {lose['gross_ret'].mean()*100:.2f}%")
    if len(win) > 0 and len(lose) > 0:
        ev_gross = win['gross_ret'].mean() * (len(win)/len(res)) + lose['gross_ret'].mean() * (len(lose)/len(res))
        print(f"  EV gross: {ev_gross*100:+.2f}%/笔")
        print(f"  EV net: {(ev_gross - 0.0176)*100:+.2f}%/笔")

    # 累计 P&L (假设每笔 1000 元)
    print(f"\n  累计回测 P&L (假设每信号 投 1000 元, 共 {len(res)} 信号):")
    total_gross = res['gross_ret'].sum() * 1000
    total_net = (res['gross_ret'] - 0.0176).sum() * 1000
    print(f"    毛利累计: {total_gross:+,.0f} 元")
    print(f"    净利累计: {total_net:+,.0f} 元 (扣每笔 17.6 元成本)")

    # ── T3: 连板龙头跟进 ────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  测试 T3: 连板跟进 (二板 / 三板)")
    print("=" * 80)
    for n in [2, 3]:
        cb = detect_consecutive_boards(cache, n_boards=n)
        if len(cb) == 0: continue
        res_cb = evaluate_signals(cache, cb, hold_days=1, entry_at="open")
        print(f"\n  已连 {n} 板, 次日开盘买入 (T+1):")
        print(f"  信号数: {len(res_cb)}")
        print(f"  毛收益: {res_cb['gross_ret'].mean()*100:>+5.2f}%   "
              f"胜率: {(res_cb['gross_ret']>0).mean()*100:.0f}%   "
              f"次日涨停率: {res_cb['next_day_limit_up'].mean()*100:.0f}%")
        print(f"  净收益 (扣成本): {(res_cb['gross_ret'].mean() - 0.0176)*100:>+5.2f}%")

    # ── T4: 涨停后长期表现 ──────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  测试 T4: 首板后长期表现 (反转 vs 延续)")
    print("=" * 80)
    longh = evaluate_long_horizon(cache, fb)
    print(f"\n  首板日收盘价为基准:")
    for col in ["ret_1d", "ret_5d", "ret_20d", "ret_60d"]:
        v = longh[col].dropna()
        print(f"    持有 {col[4:]:<5s}: 均值 {v.mean()*100:>+5.2f}%  "
              f"中位 {v.median()*100:>+5.2f}%  胜率 {(v>0).mean()*100:.0f}%")

    print()
    print("  解读: 如果 ret_1d 均值 > 0 而 ret_20d 均值 ≤ 0,")
    print("        说明涨停股的 1 日动量真实存在, 但持有越久越坏.")

    # ── 保存详细结果 ────────────────────────────────────────────────────────
    res.to_csv(os.path.join(OUT_DIR, "first_board_results.csv"),
                index=False, encoding="utf-8-sig")
    longh.to_csv(os.path.join(OUT_DIR, "first_board_long_horizon.csv"),
                  index=False, encoding="utf-8-sig")
    print(f"\n[+] 写入 first_board_results.csv ({len(res)} 笔)")

    # ── 最终判定 ────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  最终判定 (适合 2万 小资金?)")
    print("=" * 80)
    fb_net = res["gross_ret"].mean() - 0.0176
    print(f"  一进二 净 EV: {fb_net*100:+.2f}%/笔")
    print(f"  胜率: {(res['gross_ret']>0).mean()*100:.0f}%")
    print(f"  最差 1% 单笔: {res['gross_ret'].quantile(0.01)*100:+.1f}%")
    if fb_net > 0:
        print(f"  → 数学上正期望值, 但实施门槛极高 (尾盘抢板 + 信息差)")
    else:
        print(f"  → 数学上为负, 不适合作为系统性策略")


if __name__ == "__main__":
    main()
