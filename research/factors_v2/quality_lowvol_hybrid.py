"""
Quality + LowVol Hybrid
=======================
基本面硬门槛 → 低波 Top K (不用情绪, 不用基本面打分).
对比不同门槛宽严 & 不同 K, 看是否能比纯 low_vol / 纯 Layer3 更强.
基准: DIV70/GEM30 (目前最优), 纯 DIV, HS300.
"""
import glob
import os
import sys
import warnings
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PANEL     = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
MARKET    = os.path.join(ROOT, "data", "market_cache")
OUT_DIR   = os.path.join(ROOT, "research", "factors_v2", "output")

START      = "2019-01-18"    # 与 DIV ETF 对齐, 方便比基准
HOLD_STEP  = 20
BUY_BP, SELL_BP = 13, 43
MIN_AMT    = 200e6


def is_main(code: str) -> bool:
    c = str(code).zfill(6)
    if c.startswith(("43","83","87","88","92","4","8","9")): return False
    if c.startswith(("159","510","511","512","513","514","515","516","517","518","519","520","588","18","200","201","900")): return False
    if c.startswith(("30","301","302","688","689")): return False
    return c.startswith(("60","000","001","002","003"))


def load_fund():
    df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
    df["report_date"]   = pd.to_datetime(df["report_date"])
    df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce").fillna(df["report_date"] + pd.Timedelta(days=45))
    for c in ["roe","np_yoy","rev_yoy","gross_margin"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["code"].apply(is_main)].copy()
    df = df[~df["name"].astype(str).str.contains("ST|退", na=False)]
    return df.sort_values(["code","announce_date"])


def load_prices():
    files = glob.glob(os.path.join(STOCK_DIR, "S[HZ]*.csv"))
    frames = []
    start_buffer = pd.Timestamp(START) - pd.Timedelta(days=180)
    for fp in files:
        sym = os.path.splitext(os.path.basename(fp))[0].upper()
        code = sym[2:]
        if not is_main(code): continue
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig", usecols=["日期","收盘","成交额"])
        except Exception: continue
        df.columns = ["date","close","amount"]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        df = df.dropna(subset=["date","close"]).sort_values("date")
        df = df[df["date"] >= start_buffer]
        if len(df) < 40: continue
        df["code"] = code
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def get_fund_snapshot(fund, as_of, thresh):
    valid = fund[fund["announce_date"] <= as_of]
    if len(valid) == 0: return pd.DataFrame()
    latest = valid.groupby("code").tail(1)
    # 最新披露距 as_of 不超过 270 天 (3 季度)
    latest = latest[latest["announce_date"] >= as_of - pd.Timedelta(days=270)]
    # 应用基本面硬门槛
    latest = latest[latest["roe"] >= thresh["roe"]]
    latest = latest[latest["np_yoy"] >= thresh["np_yoy"]]
    latest = latest[latest["rev_yoy"] >= thresh["rev_yoy"]]
    latest = latest[latest["gross_margin"] >= thresh["gross"]]
    return latest


def run(thresh, top_k):
    prices = PRICES  # cached
    fund = FUND
    wide_close = prices.pivot(index="date", columns="code", values="close")
    wide_amt   = prices.pivot(index="date", columns="code", values="amount")
    log_ret = np.log(wide_close / wide_close.shift(1))
    wide_vol = log_ret.rolling(60, min_periods=40).std()

    dates = wide_close.index[wide_close.index >= pd.Timestamp(START)]
    rebal_dates = [dates[i] for i in range(0, len(dates), HOLD_STEP)]

    rows = []
    prev = None
    for i, t in enumerate(rebal_dates):
        if i+1 >= len(rebal_dates): break
        t_next = rebal_dates[i+1]
        recent_amt = wide_amt.loc[:t].tail(20).mean()
        vol60 = wide_vol.loc[t] if t in wide_vol.index else pd.Series(dtype=float)
        snap = get_fund_snapshot(fund, t, thresh)
        if len(snap) == 0: continue
        snap = snap[snap["code"].map(recent_amt) >= MIN_AMT]
        snap["vol60"] = snap["code"].map(vol60)
        snap = snap.dropna(subset=["vol60"])
        if len(snap) < 5: continue
        hold = snap.nsmallest(top_k, "vol60")["code"].tolist()
        p_t, p_next = wide_close.loc[t, hold], wide_close.loc[t_next, hold]
        r = (p_next/p_t - 1).replace([np.inf,-np.inf], np.nan).dropna()
        if len(r) == 0: continue
        pr = float(r.mean())
        turn = 1.0 if prev is None else len(set(hold)-prev)/len(hold)
        cost = turn*(BUY_BP+SELL_BP)/10000
        rows.append({"date":t,"n":len(hold),"pr":pr,"pr_net":pr-cost,"turn":turn})
        prev = set(hold)

    log = pd.DataFrame(rows)
    if len(log) == 0: return None
    r_net = np.clip(log["pr_net"].values, -0.99, None)
    eq = np.cumprod(1 + r_net)
    years = (log["date"].iloc[-1] - log["date"].iloc[0]).days / 365.25
    cagr = eq[-1]**(1/years) - 1
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    vol = log["pr_net"].std() * np.sqrt(252/HOLD_STEP)
    sharpe = (cagr - 0.02) / vol if vol > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd<0 else np.nan
    return {"cagr":cagr,"mdd":mdd,"calmar":calmar,"sharpe":sharpe,
            "turn":float(log["turn"].mean()),"n_periods":len(log),
            "avg_hold":float(log["n"].mean())}


print("加载基本面...", flush=True)
FUND = load_fund()
print(f"  {len(FUND):,} 行 × {FUND['code'].nunique()} 股")
print("加载股价...", flush=True)
PRICES = load_prices()
print(f"  {len(PRICES):,} 行 × {PRICES['code'].nunique()} 股")

configs = [
    # (标签, roe门槛, np_yoy, rev_yoy, gross, top_k)
    ("无门槛_LV20",       -999, -999, -999, -999, 20),
    ("无门槛_LV30",       -999, -999, -999, -999, 30),
    ("宽松_LV20",             5,  -10,  -10,  10, 20),
    ("中等_LV20",            10,    0,   -5,  15, 20),
    ("中等_LV30",            10,    0,   -5,  15, 30),
    ("严格_LV20",            15,    5,    0,  20, 20),
    ("严格_LV15",            15,    5,    0,  20, 15),
    ("超严_LV10",            20,   10,    5,  25, 10),
    ("质量优先_LV20",         12,    5,    0,  20, 20),
]

print(f"\n{'标签':<16s} {'ROE/NP/REV/GM':>16s} {'K':>3s} {'期数':>5s} {'持仓':>5s} "
      f"{'CAGR_net':>9s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s} {'换手':>5s}")
print("-"*104)
rows_out = []
for cfg in configs:
    label, roe, np_y, rev, gross, k = cfg
    thresh = {"roe":roe,"np_yoy":np_y,"rev_yoy":rev,"gross":gross}
    m = run(thresh, k)
    if m is None:
        print(f"  {label:<14s}  失败")
        continue
    t = f"{roe}/{np_y}/{rev}/{gross}"
    print(f"  {label:<14s} {t:>16s} {k:>3d} {m['n_periods']:>5d} {m['avg_hold']:>5.1f} "
          f"{m['cagr']:>+9.2%} {m['mdd']:>+8.2%} {m['calmar']:>7.2f} {m['sharpe']:>7.2f} {m['turn']*100:>4.0f}%")
    rows_out.append({"label":label,"roe":roe,"np_yoy":np_y,"rev_yoy":rev,"gross":gross,"top_k":k,**m})

print("\n对比:")
print("  DIV 买入持有:         +12.74%  -16.53%    0.77    0.63")
print("  DIV70/GEM30 月再平衡:  +14.78%  -17.29%    0.85    0.73  ← 当前最优")
print("  GEM 买入持有:         +16.29%  -56.58%    0.29    0.47")

pd.DataFrame(rows_out).to_csv(os.path.join(OUT_DIR, "quality_lowvol_hybrid.csv"),
                               index=False, encoding="utf-8-sig")
