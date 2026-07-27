"""
事件驱动策略标准框架 — 短线/特定事件类策略
================================================
区别于 alpha_study_framework.py (cross-sectional 6M 因子),
本框架处理: 涨停板、龙虎榜、财报披露、突发新闻 等事件触发型策略.

强制规则 (CLAUDE.md backtest QC):
  1. 调用前先跑 data_integrity_audit.audit_data()
  2. 强制 random control: 同股票随机非事件日 next-day return
  3. 所有成本透明 (尾盘抢板/次日开盘/印花税/佣金)
  4. 报告: 胜率, EV, t-stat, 收益分布 p1/p10/p50/p90/p99
  5. 拒绝 'avg ret > 0' 单一指标判定 (要看分布)

接口:
  from event_study_framework import detect_events, evaluate_event, randomize_baseline

  events = detect_events(price_cache, detect_fn=is_first_limit_up)
  result = evaluate_event(price_cache, events,
                           hold_days=1, entry_at='next_open', exit_at='next_close')
  baseline = randomize_baseline(price_cache, events, n_random_per_event=5)
"""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")

# ── 散户实盘成本模型 (透明, 不藏) ────────────────────────────────────────────
COST_MODEL = {
    "尾盘抢板买入": {
        "slippage": 0.010,      # 1% (挂涨停价, 实际成交价高 1%)
        "commission": 0.00013,
        "stamp_tax": 0.0,        # 买入无印花税
    },
    "次日开盘买入": {
        "slippage": 0.005,      # 0.5% (开盘溢价)
        "commission": 0.00013,
        "stamp_tax": 0.0,
    },
    "次日收盘卖出": {
        "slippage": 0.003,      # 0.3% (流动性折价)
        "commission": 0.00013,
        "stamp_tax": 0.001,     # 卖出 0.1% 印花税
    },
    "次日开盘卖出": {
        "slippage": 0.005,      # 0.5% 开盘可能跳空
        "commission": 0.00013,
        "stamp_tax": 0.001,
    },
}


def cost_for_path(entry_method: str, exit_method: str) -> float:
    """计算一次完整买卖的成本 (gross-net)"""
    e = COST_MODEL[entry_method]
    x = COST_MODEL[exit_method]
    return e["slippage"] + e["commission"] + e["stamp_tax"] + \
           x["slippage"] + x["commission"] + x["stamp_tax"]


# ── 数据加载 (只 SH/SZ, BJ 缺数据) ────────────────────────────────────────────
def load_price_cache(verbose=True, exclude_st=True):
    cache = {}
    files = glob.glob(os.path.join(STOCK_DIR, "*.csv"))
    if verbose: print(f"[+] 加载 OHLCV ({len(files)} 文件)...")
    for fp in files:
        code = os.path.basename(fp)[2:8]
        if exclude_st:
            # ST 股代码无规律, 通过名称判断需 panel; 简化: 先跳过
            pass
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
            dc = next((c for c in ["date","日期"] if c in df.columns), None)
            cc = next((c for c in ["close","收盘"] if c in df.columns), None)
            oc = next((c for c in ["open","开盘"] if c in df.columns), None)
            hc = next((c for c in ["high","最高"] if c in df.columns), None)
            pc = next((c for c in ["pctChg","涨跌幅"] if c in df.columns), None)
            tc = next((c for c in ["turn","换手率"] if c in df.columns), None)
            if not (dc and cc and pc): continue
            df[dc] = pd.to_datetime(df[dc], errors="coerce")
            df = df.dropna(subset=[dc, cc, pc]).sort_values(dc).reset_index(drop=True)
            renames = {dc:"date", cc:"close", pc:"pct"}
            if oc: renames[oc] = "open"
            if hc: renames[hc] = "high"
            if tc: renames[tc] = "turn"
            df = df.rename(columns=renames)
            keep = ["date","close","pct"] + \
                   ["open"] * (1 if oc else 0) + \
                   ["high"] * (1 if hc else 0) + \
                   ["turn"] * (1 if tc else 0)
            cache[code] = df[keep]
        except Exception:
            continue
    if verbose: print(f"    缓存 {len(cache)} 只股")
    return cache


# ── 事件检测器 (示例: 首板) ───────────────────────────────────────────────────
def detect_first_limit_up(df, lookback=5, threshold=9.8):
    """返回 idx 列表: 今日涨停 + 前 lookback 日无涨停"""
    if len(df) < lookback + 2: return []
    events = []
    for i in range(lookback, len(df)):
        if df.iloc[i]["pct"] < threshold: continue
        prev_pct = df.iloc[i-lookback:i]["pct"]
        if (prev_pct >= threshold).any(): continue
        events.append(i)
    return events


def detect_consecutive_n_boards(df, n_boards, threshold=9.8):
    """返回 idx: 已连 n_boards 板的次日索引"""
    if len(df) < n_boards + 2: return []
    events = []
    for i in range(n_boards, len(df)):
        window = df.iloc[i-n_boards:i]["pct"]
        if (window >= threshold).all():
            events.append(i)  # i 是 "建仓日" (即第 n+1 日)
    return events


# ── 事件回测核心 ─────────────────────────────────────────────────────────────
def evaluate_events(price_cache, events_dict,
                     hold_days=1,
                     entry_at="next_open", exit_at="next_close"):
    """
    events_dict: {code: [idx, idx, ...]}  事件信号日索引
    entry_at: 'next_open' (T+1开盘) | 'today_close' (T 尾盘)
    exit_at:  'next_close' (T+1 收盘) | 'next_open' (T+1 开盘) | 'after_n' (n 天后收盘)
    """
    rows = []
    for code, idx_list in events_dict.items():
        df = price_cache.get(code)
        if df is None: continue
        for idx in idx_list:
            # entry
            if entry_at == "today_close":
                if idx >= len(df): continue
                entry_price = df.iloc[idx]["close"]
                entry_date = df.iloc[idx]["date"]
                t_offset = 0
            elif entry_at == "next_open":
                if idx + 1 >= len(df): continue
                entry_price = df.iloc[idx + 1].get("open", df.iloc[idx + 1]["close"])
                entry_date = df.iloc[idx + 1]["date"]
                t_offset = 1
            else:
                continue
            # exit
            exit_idx = idx + t_offset + hold_days
            if exit_idx >= len(df): continue
            if exit_at == "next_close":
                exit_price = df.iloc[exit_idx]["close"]
            elif exit_at == "next_open":
                exit_price = df.iloc[exit_idx].get("open", df.iloc[exit_idx]["close"])
            else:
                exit_price = df.iloc[exit_idx]["close"]
            gross_ret = exit_price / entry_price - 1
            rows.append({
                "code": code,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_ret": gross_ret,
                "next_pct": df.iloc[idx + 1]["pct"] if idx + 1 < len(df) else np.nan,
            })
    return pd.DataFrame(rows)


# ── 关键: Random Control (同股+随机日) ──────────────────────────────────────
def randomize_baseline(price_cache, events_dict, hold_days=1,
                        entry_at="next_open", exit_at="next_close",
                        n_random_per_event=5, exclude_event_window=10, seed=42):
    """
    对每个事件, 在同股票随机抽 n_random_per_event 个非事件日做 baseline.
    确保事件邻近窗口不被选中 (避免 leakage).

    返回 baseline DataFrame, 同列 evaluate_events 的输出.
    """
    np.random.seed(seed)
    rows = []
    for code, event_idxs in events_dict.items():
        df = price_cache.get(code)
        if df is None or len(df) < 50: continue
        n = len(df)
        # 排除事件日 ± exclude_event_window
        excluded = set()
        for ei in event_idxs:
            for offset in range(-exclude_event_window, exclude_event_window + 1):
                excluded.add(ei + offset)
        # 可选 idx: 既不在 excluded, 也要保证 idx + hold_days + 1 < n
        candidates = [i for i in range(20, n - hold_days - 2) if i not in excluded]
        if not candidates: continue
        # 每个事件抽 n_random_per_event 个
        n_to_pick = min(len(event_idxs) * n_random_per_event, len(candidates))
        if n_to_pick == 0: continue
        picks = np.random.choice(candidates, size=n_to_pick, replace=False)
        for idx in picks:
            if entry_at == "today_close":
                entry_price = df.iloc[idx]["close"]
                t_offset = 0
            elif entry_at == "next_open":
                if idx + 1 >= n: continue
                entry_price = df.iloc[idx + 1].get("open", df.iloc[idx + 1]["close"])
                t_offset = 1
            else: continue
            exit_idx = idx + t_offset + hold_days
            if exit_idx >= n: continue
            if exit_at == "next_close":
                exit_price = df.iloc[exit_idx]["close"]
            elif exit_at == "next_open":
                exit_price = df.iloc[exit_idx].get("open", df.iloc[exit_idx]["close"])
            else:
                exit_price = df.iloc[exit_idx]["close"]
            rows.append({
                "code": code,
                "entry_date": df.iloc[idx + t_offset]["date"],
                "gross_ret": exit_price / entry_price - 1,
            })
    return pd.DataFrame(rows)


# ── 标准报告 ─────────────────────────────────────────────────────────────────
def report_event_study(name: str,
                        signal_df: pd.DataFrame,
                        baseline_df: pd.DataFrame,
                        cost: float,
                        verbose=True):
    """生成标准化对比报告"""
    if len(signal_df) < 30 or len(baseline_df) < 30:
        print(f"[!] {name}: 样本不足"); return None

    s = signal_df["gross_ret"].values
    b = baseline_df["gross_ret"].values

    s_net = s - cost
    b_net = b - cost

    # t-stat: signal vs baseline (independent, unequal variance)
    from scipy import stats
    t_stat, p_val = stats.ttest_ind(s, b, equal_var=False)

    summary = {
        "name": name,
        "n_signal": len(s),
        "n_baseline": len(b),
        "cost": cost,
        # gross
        "signal_mean_gross": s.mean(),
        "signal_median_gross": np.median(s),
        "signal_win_pct": (s > 0).mean() * 100,
        "baseline_mean_gross": b.mean(),
        "baseline_win_pct": (b > 0).mean() * 100,
        "alpha_gross": s.mean() - b.mean(),
        # net
        "signal_mean_net": s_net.mean(),
        "alpha_net": s_net.mean() - b_net.mean(),
        # distribution
        "signal_p01": np.percentile(s, 1),
        "signal_p10": np.percentile(s, 10),
        "signal_p25": np.percentile(s, 25),
        "signal_p75": np.percentile(s, 75),
        "signal_p90": np.percentile(s, 90),
        "signal_p99": np.percentile(s, 99),
        # statistical
        "t_stat": t_stat,
        "p_value": p_val,
    }

    if verbose:
        print(f"\n{'='*72}")
        print(f"  {name}")
        print(f"{'='*72}")
        print(f"  样本 信号: {summary['n_signal']:>6,}  对照: {summary['n_baseline']:>6,}")
        print(f"  成本: {cost*100:.2f}% (单次往返)")
        print(f"\n  ── Gross (税前) ──")
        print(f"  信号 均值: {summary['signal_mean_gross']*100:>+6.2f}%  "
              f"中位: {summary['signal_median_gross']*100:>+6.2f}%  "
              f"胜率: {summary['signal_win_pct']:.1f}%")
        print(f"  对照 均值: {summary['baseline_mean_gross']*100:>+6.2f}%  "
              f"胜率: {summary['baseline_win_pct']:.1f}%")
        print(f"  Alpha vs random: {summary['alpha_gross']*100:>+6.2f}%/笔  "
              f"t={summary['t_stat']:>5.2f}  p={summary['p_value']:.4f}")
        print(f"\n  ── Net (扣成本) ──")
        print(f"  信号 净均值: {summary['signal_mean_net']*100:>+6.2f}%/笔")
        print(f"  Alpha net:   {summary['alpha_net']*100:>+6.2f}%/笔")
        print(f"\n  ── 信号 收益分布 ──")
        print(f"    p1   (灾难): {summary['signal_p01']*100:>+6.1f}%")
        print(f"    p10  (倒霉): {summary['signal_p10']*100:>+6.1f}%")
        print(f"    p25         : {summary['signal_p25']*100:>+6.1f}%")
        print(f"    p75         : {summary['signal_p75']*100:>+6.1f}%")
        print(f"    p90  (顺利): {summary['signal_p90']*100:>+6.1f}%")
        print(f"    p99  (中签): {summary['signal_p99']*100:>+6.1f}%")
        print(f"\n  ── 判定 ──")
        if abs(summary['t_stat']) > 3.5 and summary['alpha_net'] > 0:
            print(f"    ✓ 强信号: t > 3.5 通过 Harvey 多重检验, net > 0")
        elif abs(summary['t_stat']) > 2.0 and summary['alpha_net'] > 0:
            print(f"    ~ 弱信号: 2 < |t| < 3.5, 经济意义存在但需谨慎")
        elif summary['alpha_net'] < 0:
            print(f"    ✗ 负 alpha: net 收益为负, 不可作为系统策略")
        else:
            print(f"    - 不显著 (|t|<2)")

    return summary
