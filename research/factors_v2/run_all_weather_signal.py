"""
全天候 30/30/40 实盘信号 (默认静态, T2 动量 overlay 可选)
==========================================================
基础组合: 30% 股 (DIV70/GEM30) + 30% 债 + 40% 金, 季度再平衡

**2026-04-28 重要变更**: 默认行为改为静态 30/30/40, T2 双动量 overlay 改为 --t2 可选.
原因: T2 alpha 解构发现 momentum 在 2018-2026 OOS 段转负 (Calmar -0.18 vs Static).
    - 2020-04 V 型反弹时 STK OFF 错过 +29.6% 季度回报
    - Train 段 alpha 主要由 2015 股灾贡献, 该 regime 后市场结构改变
    - 静态 vs T2: CAGR 8.11% vs 8.59% (-0.48pp), MDD -19.4% vs -17.4% (+2pp)
    - 操作简化: 无需算 SMA200 / 12M momentum, 季末固定权重再平衡即可
详见: research/factors_v2/output/all_weather_alpha_decomp.md

T2 动量规则 (月度检查, 季度末调仓, --t2 启用):
  - STK 过去 12M 收益 < 0 OR STK < SMA200 → 股腿权重转 BOND
  - GOLD 过去 12M 收益 < 0 → 金腿权重转 BOND

ETF 标的 (默认, 可改):
  DIV  = 512890 红利低波
  GEM  = 159915 创业板
  BOND = 511010 国债 ETF (5 年期)
  GOLD = 518880 黄金 ETF

用法:
  python research/factors_v2/run_all_weather_signal.py               # 今日诊断 (静态默认)
  python research/factors_v2/run_all_weather_signal.py --t2          # 启用 T2 动量 overlay
  python research/factors_v2/run_all_weather_signal.py --push        # 推钉钉
  python research/factors_v2/run_all_weather_signal.py --capital 200000
  python research/factors_v2/run_all_weather_signal.py --force       # 非季度末强制出调仓
"""
import argparse
import base64
import hashlib
import hmac
import os
import sys
import time
import urllib.parse

for _k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(_k, None)
# Windows 注册表可能设了系统代理 (如 clash/VPN), 强制忽略
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import pandas as pd
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path: sys.path.insert(0, ROOT)

OUT_DIR      = os.path.join(ROOT, "research", "factors_v2", "output", "live")
LONG_HIST    = os.path.join(ROOT, "research", "factors_v2", "output", "long_history_4asset.csv")
STATE_FILE   = os.path.join(OUT_DIR, "all_weather_state.csv")
os.makedirs(OUT_DIR, exist_ok=True)

# 目标权重 (基础)
W_BASE = {"STK": 0.30, "BOND": 0.30, "GOLD": 0.40}
STK_DIV_RATIO = 0.70
STK_GEM_RATIO = 0.30

TICKERS = {
    "DIV":  "512890",
    "GEM":  "159915",
    "BOND": "511010",
    "GOLD": "518880",
}
# sina 接口的前缀 (512xxx/511xxx/518xxx → sh, 159xxx → sz)
SINA_PREFIX = {"DIV":"sh","GEM":"sz","BOND":"sh","GOLD":"sh"}
NAMES = {
    "DIV":  "红利低波",
    "GEM":  "创业板",
    "BOND": "5 年国债",
    "GOLD": "黄金",
}

DEFAULT_CAPITAL = 100_000


# ── 信号计算 ──────────────────────────────────────────────────────────── #

def compute_signal(use_t2: bool = False) -> dict:
    """
    计算最新信号状态.
    use_t2=False (默认): 静态 30/30/40, 直接返回 W_BASE
    use_t2=True: T2 双动量 overlay (12M 收益 + SMA200), 信号失效切 BOND

    返回 {"stk_on": bool, "gold_on": bool, "weights": {...}, "mode": str, "diag": {...}}
    """
    if not os.path.exists(LONG_HIST):
        raise FileNotFoundError(f"{LONG_HIST} 不存在, 请先跑 fetch_long_history.py + fetch_bond_gold.py")

    df = pd.read_csv(LONG_HIST, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    df["STK"] = 0.7 * df["DIV"] + 0.3 * df["GEM"]
    df["STK_sma200"] = df["STK"].rolling(200).mean()
    df["STK_ret12m"] = df["STK"].pct_change(252)
    df["GOLD_ret12m"] = df["GOLD"].pct_change(252)

    last = df.iloc[-1]
    stk_ret12m = float(last["STK_ret12m"]) if not pd.isna(last["STK_ret12m"]) else None
    gold_ret12m = float(last["GOLD_ret12m"]) if not pd.isna(last["GOLD_ret12m"]) else None
    stk_sma_ok = bool(last["STK"] > last["STK_sma200"])

    diag = {
        "latest_date": str(last["date"].date()),
        "stk_ret12m": stk_ret12m,
        "stk_above_sma200": stk_sma_ok,
        "gold_ret12m": gold_ret12m,
    }

    if not use_t2:
        # 静态 30/30/40 (生产默认), 不读动量, 永远 ON
        return {"stk_on": True, "gold_on": True, "weights": dict(W_BASE),
                "mode": "static", "diag": diag}

    # T2 双动量 overlay (--t2 启用)
    stk_mom_ok = stk_ret12m is not None and stk_ret12m > 0
    stk_on = stk_mom_ok and stk_sma_ok
    gold_on = gold_ret12m is not None and gold_ret12m > 0

    w = dict(W_BASE)
    if not stk_on:
        w["BOND"] += w["STK"]; w["STK"] = 0.0
    if not gold_on:
        w["BOND"] += w["GOLD"]; w["GOLD"] = 0.0

    return {"stk_on": stk_on, "gold_on": gold_on, "weights": w,
            "mode": "t2", "diag": diag}


# 向后兼容: 保留旧名 (内部调度可能引用)
def compute_t2_signal() -> dict:
    return compute_signal(use_t2=True)


# ── 价格获取 ──────────────────────────────────────────────────────────── #

def fetch_price(key: str, ticker: str) -> tuple[float, str]:
    """抓 ETF 最新价. 优先 sina (国内直连稳定), 失败回退 eastmoney."""
    import akshare as ak
    # 1) sina
    try:
        sym = f"{SINA_PREFIX[key]}{ticker}"
        raw = ak.fund_etf_hist_sina(symbol=sym)
        last = raw.sort_values("date").tail(1).iloc[0]
        return float(last["close"]), str(last["date"])
    except Exception as e:
        print(f"  [!] {ticker} sina 源失败: {str(e)[:80]}; 试 eastmoney...")
    # 2) eastmoney fallback
    try:
        raw = ak.fund_etf_hist_em(symbol=ticker, period="daily")
        date_col  = next((c for c in raw.columns if "日期" in c), raw.columns[0])
        close_col = next((c for c in raw.columns if "收盘" in c), None)
        raw[date_col] = pd.to_datetime(raw[date_col])
        last = raw.sort_values(date_col).tail(1).iloc[0]
        return float(pd.to_numeric(last[close_col])), str(pd.Timestamp(last[date_col]).date())
    except Exception as e:
        print(f"  [!] {ticker} 两个源都失败: {str(e)[:80]}")
        return None, None


# ── 日历 ──────────────────────────────────────────────────────────────── #

def is_quarter_end(today: pd.Timestamp) -> tuple[bool, str]:
    if today.month not in (3,6,9,12): return False, ""
    if today.weekday() >= 5: return False, ""
    last_of_month = today + pd.offsets.MonthEnd(0)
    more_bdays = pd.bdate_range(today + pd.Timedelta(days=1), last_of_month)
    if len(more_bdays) == 0:
        return True, f"Q{today.month//3} 季度末 ({today.date()})"
    return False, ""


# ── 状态文件 ──────────────────────────────────────────────────────────── #

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"last_rebalance": None, "shares": {k: 0 for k in TICKERS}}
    try:
        df = pd.read_csv(STATE_FILE, encoding="utf-8-sig")
        r = df.tail(1).iloc[0]
        s = {}
        for k in TICKERS:
            col = f"shares_{k}"
            s[k] = int(r.get(col, 0) or 0)
        return {"last_rebalance": str(r.get("date","")), "shares": s}
    except Exception:
        return {"last_rebalance": None, "shares": {k: 0 for k in TICKERS}}


def append_state(row: dict):
    df = pd.DataFrame([row])
    header = not os.path.exists(STATE_FILE)
    df.to_csv(STATE_FILE, mode="a", index=False, encoding="utf-8-sig", header=header)


# ── 核心 ──────────────────────────────────────────────────────────────── #

def compute_rebalance(capital: float, prices: dict, weights: dict, state: dict) -> dict:
    """
    给定资金、各 ETF 价格、目标权重, 计算目标持仓 / 漂移 / 订单.
    权重是 4 资产级别 (DIV/GEM/BOND/GOLD 独立), STK 权重按 7:3 拆给 DIV/GEM.
    """
    # 转成 4-ticker 权重
    w4 = {
        "DIV":  weights["STK"] * STK_DIV_RATIO,
        "GEM":  weights["STK"] * STK_GEM_RATIO,
        "BOND": weights["BOND"],
        "GOLD": weights["GOLD"],
    }
    target_val = {k: capital * w4[k] for k in w4}
    # ETF 最小 100 股 (黄金 ETF 518880 实际最小 100 份, 价格 ≈ 6-8 元一份, 约 700 元)
    target_shares = {}
    for k, v in target_val.items():
        if prices[k] is None or prices[k] <= 0:
            target_shares[k] = 0
            continue
        target_shares[k] = int(round(v / prices[k] / 100)) * 100

    # 当前
    cur_shares = state.get("shares", {})
    cur_val = {k: cur_shares.get(k, 0) * (prices[k] or 0) for k in TICKERS}
    cur_total = sum(cur_val.values())
    cur_w = {k: (cur_val[k] / cur_total if cur_total > 0 else 0) for k in TICKERS}

    orders = []
    for k in TICKERS:
        diff = target_shares[k] - cur_shares.get(k, 0)
        if diff != 0 and prices[k] is not None:
            action = "买入" if diff > 0 else "卖出"
            orders.append({
                "key": k, "ticker": TICKERS[k], "name": NAMES[k],
                "action": action, "shares": abs(diff),
                "price": prices[k], "amount": abs(diff) * prices[k],
            })

    return {
        "target_shares": target_shares,
        "target_val": {k: target_shares[k] * (prices[k] or 0) for k in TICKERS},
        "target_w4": w4,
        "cur_shares": dict(cur_shares),
        "cur_val": cur_val,
        "cur_w": cur_w,
        "orders": orders,
    }


# ── 钉钉 ──────────────────────────────────────────────────────────────── #

def ding_sign(webhook: str, secret: str) -> str:
    ts = str(round(time.time() * 1000))
    msg = f"{ts}\n{secret}"
    sig = base64.b64encode(hmac.new(secret.encode(), msg.encode(), digestmod=hashlib.sha256).digest())
    return f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(sig)}"


def build_markdown(today: str, sig: dict, rebal: dict, capital: float,
                   prices: dict, price_dates: dict, is_rebal_day: bool, reason: str) -> tuple[str, str]:
    is_t2 = sig.get("mode") == "t2"
    mode_tag = "T2 动量" if is_t2 else "静态"
    title = f"全天候调仓 {today} 葵花宝典" if is_rebal_day else f"全天候诊断 {today} 葵花宝典"
    lines = [f"## 全天候 30/30/40 ({mode_tag}) — {today}\n"]
    if is_t2:
        lines.append(f"**策略**: 30% 股 (DIV70/GEM30) + 30% 债 + 40% 金, 季度再平衡, **T2 动量 overlay (--t2)**")
        lines.append(f"**T2 回测**: Full CAGR 8.59% / MDD -17.4% / Calmar 0.49 — Train +0.18 alpha, **Test OOS -0.18 alpha**")
    else:
        lines.append(f"**策略**: 30% 股 (DIV70/GEM30) + 30% 债 + 40% 金, **季度再平衡** (静态默认)")
        lines.append(f"**Static 回测**: Full CAGR 8.11% / MDD -19.4% / Calmar 0.42 — OOS Test Calmar 1.13 优于 T2 0.96")

    # 信号 / 诊断
    if is_t2:
        lines.append(f"\n### 📡 动量信号 (基于 {sig['diag']['latest_date']} 数据)")
        stk_icon = "🟢" if sig["stk_on"] else "🔴"
        gold_icon = "🟢" if sig["gold_on"] else "🔴"
        s12 = sig["diag"]["stk_ret12m"]
        g12 = sig["diag"]["gold_ret12m"]
        lines.append(f"- {stk_icon} 股腿: 12M 收益 {f'{s12*100:+.1f}%' if s12 is not None else 'N/A'}, "
                     f"{'在' if sig['diag']['stk_above_sma200'] else '跌破'} SMA200")
        lines.append(f"- {gold_icon} 金腿: 12M 收益 {f'{g12*100:+.1f}%' if g12 is not None else 'N/A'}\n")
    else:
        lines.append(f"\n### 📋 静态模式 (无动量判断, 永远 ON)")
        s12 = sig["diag"]["stk_ret12m"]
        g12 = sig["diag"]["gold_ret12m"]
        lines.append(f"- 参考: 股 12M {f'{s12*100:+.1f}%' if s12 is not None else 'N/A'}  "
                     f"金 12M {f'{g12*100:+.1f}%' if g12 is not None else 'N/A'}  (仅诊断, 不影响权重)\n")

    w = sig["weights"]
    lines.append(f"### 目标权重")
    lines.append(f"| 资产 | 基础 | 当前目标 |")
    lines.append(f"|---|---|---|")
    stk_note = "(动量OFF → 转债)" if (is_t2 and w['STK'] == 0) else ""
    gold_note = "(动量OFF → 转债)" if (is_t2 and w['GOLD'] == 0) else ""
    lines.append(f"| 股 (DIV/GEM 7:3) | 30% | **{w['STK']*100:.0f}%** {stk_note} |")
    lines.append(f"| 债 | 30% | **{w['BOND']*100:.0f}%** |")
    lines.append(f"| 金 | 40% | **{w['GOLD']*100:.0f}%** {gold_note} |\n")

    if is_rebal_day:
        lines.append(f"### ⚡ 今日调仓: {reason}\n")
    else:
        lines.append(f"### 今日非季度末, 仅诊断\n")

    lines.append(f"### 最新价格")
    lines.append(f"| ETF | 代码 | 最新价 | 数据日期 |")
    lines.append(f"|---|---|---|---|")
    for k in ["DIV","GEM","BOND","GOLD"]:
        p = prices[k]
        d = price_dates.get(k, "-")
        lines.append(f"| {NAMES[k]} | {TICKERS[k]} | {f'¥{p:.3f}' if p else 'N/A'} | {d} |")
    lines.append("")

    lines.append(f"### 目标持仓 (本金 ¥{capital:,.0f})")
    lines.append(f"| 资产 | 目标股数 | 目标市值 | 目标权重 |")
    lines.append(f"|---|---:|---:|---:|")
    for k in ["DIV","GEM","BOND","GOLD"]:
        lines.append(f"| {NAMES[k]} {TICKERS[k]} | {rebal['target_shares'][k]:,d} | "
                     f"¥{rebal['target_val'][k]:,.0f} | {rebal['target_w4'][k]*100:.1f}% |")
    lines.append("")

    cur_total = sum(rebal["cur_val"].values())
    if cur_total > 0:
        lines.append(f"### 当前持仓")
        lines.append(f"| 资产 | 股数 | 市值 | 权重 |")
        lines.append(f"|---|---:|---:|---:|")
        for k in ["DIV","GEM","BOND","GOLD"]:
            lines.append(f"| {NAMES[k]} | {rebal['cur_shares'].get(k,0):,d} | "
                         f"¥{rebal['cur_val'][k]:,.0f} | {rebal['cur_w'][k]*100:.1f}% |")
        lines.append("")

    if rebal["orders"]:
        lines.append(f"### {'调仓指令' if is_rebal_day else '如果现在调仓, 需要的指令'}")
        lines.append(f"| 操作 | ETF | 股数 | 单价 | 金额 |")
        lines.append(f"|---|---|---:|---:|---:|")
        for o in rebal["orders"]:
            lines.append(f"| **{o['action']}** | {o['name']} {o['ticker']} | {o['shares']:,d} "
                         f"| ¥{o['price']:.3f} | ¥{o['amount']:,.0f} |")
        lines.append("")
    else:
        lines.append(f"### 当前已匹配目标, 无需调仓\n")

    lines.append(f"> ETF: 512890 红利低波 / 159915 创业板 / 511010 5Y国债 / 518880 黄金")
    return title, "\n".join(lines)


def send_dingtalk(title: str, text: str) -> bool:
    try: import requests
    except ImportError:
        print("  [!] 需要 requests"); return False
    try:
        from config import DINGTALK_WEBHOOK, DINGTALK_SECRET
    except ImportError:
        DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK","")
        DINGTALK_SECRET  = os.environ.get("DINGTALK_SECRET","")
    if not DINGTALK_WEBHOOK:
        print("  [!] DINGTALK_WEBHOOK 未配置"); return False
    url = ding_sign(DINGTALK_WEBHOOK, DINGTALK_SECRET) if DINGTALK_SECRET else DINGTALK_WEBHOOK
    payload = {"msgtype":"markdown","markdown":{"title":title,"text":text},"at":{"isAtAll":False}}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        body = resp.json()
        if body.get("errcode") == 0:
            print("  钉钉推送 OK"); return True
        print(f"  钉钉推送失败: {body}"); return False
    except Exception as e:
        print(f"  钉钉推送异常: {e}"); return False


# ── main ──────────────────────────────────────────────────────────────── #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--capital", type=float, default=None)
    ap.add_argument("--t2", action="store_true",
                    help="启用 T2 双动量 overlay (默认静态 30/30/40, 因 T2 OOS Calmar 低 0.18)")
    ap.add_argument("--confirm-rebalance", action="store_true",
                    help="确认已下单后更新 state 文件")
    args = ap.parse_args()

    capital = args.capital
    if capital is None:
        try:
            from config import PORTFOLIO_CAPITAL
            capital = float(PORTFOLIO_CAPITAL)
        except Exception:
            capital = DEFAULT_CAPITAL
    print(f"[+] 本金: ¥{capital:,.0f}")

    # 信号
    mode = "T2 双动量" if args.t2 else "静态 30/30/40"
    print(f"[+] 计算信号 ({mode})...")
    sig = compute_signal(use_t2=args.t2)
    print(f"  STK: {'ON' if sig['stk_on'] else 'OFF'}, GOLD: {'ON' if sig['gold_on'] else 'OFF'}")
    print(f"  目标权重: STK={sig['weights']['STK']*100:.0f}% / BOND={sig['weights']['BOND']*100:.0f}% / "
          f"GOLD={sig['weights']['GOLD']*100:.0f}%")

    # 价格
    print(f"[+] 抓取 ETF 行情...")
    prices, price_dates = {}, {}
    for k, tk in TICKERS.items():
        p, d = fetch_price(k, tk)
        prices[k] = p
        price_dates[k] = d or "-"
        print(f"  {NAMES[k]} {tk}: {f'¥{p:.3f}' if p else 'N/A'} ({d or '-'})")

    # 日历
    today = pd.Timestamp.today().normalize()
    is_qe, reason = is_quarter_end(today)
    is_rebal = is_qe or args.force
    if not reason and args.force:
        reason = f"手动 --force ({today.date()})"
    print(f"[+] {'触发调仓' if is_rebal else '今日非季度末'}: {reason or today.date()}")

    # 计算
    state = load_state()
    if state["last_rebalance"]: print(f"[+] 上次调仓: {state['last_rebalance']}")
    rebal = compute_rebalance(capital, prices, sig["weights"], state)

    # 输出
    today_str = str(today.date())
    title, md = build_markdown(today_str, sig, rebal, capital, prices, price_dates, is_rebal, reason)
    print("\n" + "=" * 70)
    print(md.replace("**","").replace("##","#"))
    print("=" * 70)

    # 推
    if args.push:
        print("\n[+] 推送钉钉...")
        send_dingtalk(title, md)

    # 确认
    if args.confirm_rebalance:
        row = {"date": today_str, "capital_at_rebal": capital,
               "stk_on": sig["stk_on"], "gold_on": sig["gold_on"]}
        for k in TICKERS:
            row[f"shares_{k}"] = rebal["target_shares"][k]
            row[f"price_{k}"] = prices[k] if prices[k] else 0
        append_state(row)
        print(f"[+] 已写 state: {STATE_FILE}")


if __name__ == "__main__":
    main()
