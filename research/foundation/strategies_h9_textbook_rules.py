"""
H9 — 教学视频规则全叠加版 (2026-04-28)
=======================================
在 H8 V2 烂板基础上叠加 5 条教学视频核心过滤, 看 alpha 能否从 -0.13% 翻正.

Base (H8 V2 烂板):
  T 日 pct >= 9.8 AND low/close < 0.999 (盘中跌破过涨停, 即开过板再封)
  前 5 日无涨停
  主板 (SH 600/601/603/605, SZ 000/001/002/003), 排 ST

5 条教学规则 (TIER 1, 日级数据可测):
  A 量能放大:    vol[i] / vol[i-5:i].mean() >= 2.0
  B 小盘低价:    close[i] < 20 AND close[i] × shares_yi < 50 (亿)
                  shares_yi = |net_profit/eps| 最近一期估算
  C 近期人气:    近 40 日有过涨停 OR 炸板 (pct>7 且 low/close<0.99)
  D 次日高开:    open[i+1] / close[i] >= 1.04
                  (T+1 集合竞价 9:25 可见 open, 决策可执行)

5 个单层 + 1 个全叠加, 共 6 个变体, 与 base 对照.

Entry: T+1 open (集合竞价)
Exit:  T+1 close
Cost:  a_share_retail_quarterly (33bp)
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from typing import Dict

import numpy as np
import pandas as pd

from research.foundation import (
    DataBundle, Universe, CostModel,
    EventDrivenStrategy, Backtest, StandardReport,
)

# 配置
LIMIT_UP            = 9.8
LOOKBACK_NO_LIMIT   = 5
LOOKBACK_HISTORY    = 40
LOW_CLOSE_RATIO     = 0.999
MAINBOARD_PREFIXES  = {"600", "601", "603", "605", "000", "001", "002", "003"}

# 教学规则阈值
VOL_RATIO_MIN       = 2.0       # A
PRICE_MAX           = 20.0      # B
MCAP_MAX_YI         = 50.0      # B (亿元)
HIST_PCT_LIMIT      = 9.8       # C 涨停
HIST_BREACH_PCT     = 7.0       # C 炸板涨幅
HIST_BREACH_RATIO   = 0.99      # C 炸板 low/close 阈
GAP_OPEN_MIN        = 0.04      # D 次日高开 4%+


def get_st_codes(panel) -> set:
    last_name = panel.sort_values("report_date").groupby("code")["name"].last()
    return set(last_name[last_name.fillna("").str.contains("ST")].index)


def estimate_shares(panel) -> Dict[str, float]:
    """估算每股最新流通股本 (亿股) = |net_profit / eps| 取最近一期"""
    p = panel[panel["eps"].notna() & (panel["eps"].abs() > 1e-3)
              & panel["net_profit"].notna()].copy()
    p["shares_yi"] = (p["net_profit"] / p["eps"]).abs() / 1e8
    last = p.sort_values("report_date").groupby("code")["shares_yi"].last()
    return last.to_dict()


def make_h9_detect(data: DataBundle, layer: str):
    """
    layer ∈ {"base", "A", "B", "C", "D", "ALL"}
      base: 仅 H8 V2 烂板, 不加任何额外过滤
      A/B/C/D: 单独加一条教学规则
      ALL: A ∩ B ∩ C ∩ D 全叠加
    """
    st_codes = get_st_codes(data.panel)
    shares_lookup = estimate_shares(data.panel)

    def detect(price_cache):
        events = {}
        for code, df in price_cache.items():
            if code[:3] not in MAINBOARD_PREFIXES: continue
            if code in st_codes: continue
            need = ["pct", "low", "close", "open", "vol"]
            if not all(c in df.columns for c in need): continue
            if len(df) < LOOKBACK_HISTORY + 2: continue

            pct   = df["pct"].values
            low   = df["low"].values
            close = df["close"].values
            open_ = df["open"].values
            vol   = df["vol"].values

            shares_yi = shares_lookup.get(code, np.nan)

            idxs = []
            for i in range(LOOKBACK_HISTORY, len(df) - 1):
                # 基础: 烂板 (T 日涨停 + 前 5 日无涨停 + 盘中开过板)
                if pct[i] < LIMIT_UP: continue
                if (pct[i - LOOKBACK_NO_LIMIT:i] >= LIMIT_UP).any(): continue
                if close[i] <= 0: continue
                if low[i] / close[i] >= LOW_CLOSE_RATIO: continue

                # Layer A: 量能放大
                if layer in ("A", "ALL"):
                    win5 = vol[i - 5:i]
                    if np.isnan(win5).all(): continue
                    vol5_mean = np.nanmean(win5)
                    if not (vol5_mean > 0 and vol[i] / vol5_mean >= VOL_RATIO_MIN): continue

                # Layer B: 小盘低价
                if layer in ("B", "ALL"):
                    if close[i] >= PRICE_MAX: continue
                    if not (np.isfinite(shares_yi) and close[i] * shares_yi < MCAP_MAX_YI): continue

                # Layer C: 近期人气 (40 日内有涨停或炸板)
                if layer in ("C", "ALL"):
                    hp = pct[i - LOOKBACK_HISTORY:i]
                    hl = low[i - LOOKBACK_HISTORY:i]
                    hc = close[i - LOOKBACK_HISTORY:i]
                    has_lim = (hp >= HIST_PCT_LIMIT).any()
                    valid_close = hc > 0
                    has_breach = ((hp > HIST_BREACH_PCT) & valid_close
                                  & (hl / np.where(valid_close, hc, 1) < HIST_BREACH_RATIO)).any()
                    if not (has_lim or has_breach): continue

                # Layer D: 次日高开 4%+
                if layer in ("D", "ALL"):
                    t1_open = open_[i + 1]
                    if not (t1_open > 0 and t1_open / close[i] >= 1 + GAP_OPEN_MIN): continue

                idxs.append(int(i))
            if idxs: events[code] = idxs
        return events
    return detect


def run_one(data, name: str, detect_fn, cost: CostModel):
    uni = Universe.broad(data, mcap_range=(5, 100000),
                          min_turnover_20d=0.0, exclude_st=True)
    strat = EventDrivenStrategy(
        name=name,
        detect_fn=detect_fn,
        entry_at="next_open",
        exit_at="next_close",
        hold_days=1,
    )
    bt = Backtest(
        strategy=strat,
        universe=uni,
        cost_model=cost,
        random_control=True,
        train_test_split=("2020-12-31", "2021-01-01"),
        seed=42,
    )
    return bt.run(verbose=False)


def main():
    print("=" * 100)
    print("  H9 — 教学规则全叠加版 (base = H8 V2 烂板)")
    print("=" * 100)
    print("  Entry: T+1 open  Exit: T+1 close  Cost: 33bp")
    print()

    print("[1/8] 加载数据...")
    data = DataBundle.load(verbose=False)
    print(f"      {len(data.price_cache):,} 股, OHLCV {data.audit.ohlcv_coverage_pct:.0f}%")
    print()

    cost = CostModel.a_share_retail_quarterly()
    variants = [
        ("base 烂板",         make_h9_detect(data, "base")),
        ("+A 量能2x",         make_h9_detect(data, "A")),
        ("+B 小盘低价",       make_h9_detect(data, "B")),
        ("+C 历史涨停40d",    make_h9_detect(data, "C")),
        ("+D 次日高开4%",     make_h9_detect(data, "D")),
        ("ALL 全叠加",        make_h9_detect(data, "ALL")),
    ]

    results = {}
    for i, (name, det) in enumerate(variants, start=2):
        ev = det(data.price_cache)
        n = sum(len(v) for v in ev.values())
        print(f"[{i}/8] {name}: 检出 {n:,} 个事件")
        if n < 100:
            print(f"        样本太少, 跳过回测")
            results[name] = (n, None)
            continue
        res = run_one(data, name, det, cost)
        results[name] = (n, res)

    # ── 总览 ──────────────────────────────────────────────────────────────
    print()
    print("=" * 100)
    print(f"  {'变体':<20s}  {'n':>7s}  {'sig%':>7s}  {'rand%':>7s}  {'alpha%':>7s}  "
          f"{'t':>6s}  {'win%':>6s}  {'净%':>7s}")
    print("=" * 100)
    base_alpha = None
    for name, (n, res) in results.items():
        if res is None:
            print(f"  {name:<20s}  {n:>7,d}  (样本太少)")
            continue
        s = res.full_summary
        if base_alpha is None: base_alpha = s["alpha_mean"]
        marker = ""
        if s["alpha_mean"] > 0 and s["t_stat"] > 2: marker = " ★"
        elif s["alpha_mean"] < 0 and s["t_stat"] < -2: marker = " ✗"
        print(f"  {name:<20s}  {n:>7,d}  "
              f"{s['signal_mean_gross']*100:>+6.2f}  "
              f"{s['random_mean_gross']*100:>+6.2f}  "
              f"{s['alpha_mean']*100:>+6.2f}  "
              f"{s['t_stat']:>+6.2f}  "
              f"{s['signal_win_pct']:>5.1f}  "
              f"{s['signal_mean_net']*100:>+6.2f}{marker}")

    # ── 报告写盘 ─────────────────────────────────────────────────────────
    out_dir = os.path.join(os.path.dirname(__file__), "..", "factors_v2", "output")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "h9_textbook_rules.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# H9 教学规则全叠加版 (2026-04-28)\n\n")
        f.write("Base = H8 V2 烂板 (盘中跌破涨停再封, T+1 open 进场).\n")
        f.write("叠加教学视频 5 条 TIER 1 规则: 量能/小盘低价/近期人气/次日高开.\n\n")
        f.write("## 总览\n\n")
        f.write("| 变体 | n | sig% | rand% | alpha% | t | win% | 净% |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for name, (n, res) in results.items():
            if res is None:
                f.write(f"| {name} | {n} | - | - | - | - | - | - |\n")
                continue
            s = res.full_summary
            f.write(f"| {name} | {n:,} | "
                    f"{s['signal_mean_gross']*100:+.2f} | "
                    f"{s['random_mean_gross']*100:+.2f} | "
                    f"{s['alpha_mean']*100:+.2f} | "
                    f"{s['t_stat']:+.2f} | "
                    f"{s['signal_win_pct']:.1f} | "
                    f"{s['signal_mean_net']*100:+.2f} |\n")
        f.write("\n## 详情\n\n")
        for name, (n, res) in results.items():
            if res is None: continue
            f.write(f"### {name}\n\n")
            f.write(StandardReport.from_result(res).render() + "\n\n")
    print()
    print(f"[+] 报告写入 {md_path}")


if __name__ == "__main__":
    main()
