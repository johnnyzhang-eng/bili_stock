"""
DIV70/GEM30 季度再平衡信号 — 生产版
======================================
基于 v2_findings_2026_04 的结论:
  70% 红利低波 (512890) + 30% 创业板 (159915), 季度再平衡
  回测 CAGR 15.15% / MDD -17.61% / Calmar 0.86 / Sharpe 0.74

用法:
  python research/factors_v2/run_etf_rebalance_signal.py               # 今日诊断
  python research/factors_v2/run_etf_rebalance_signal.py --push        # 推钉钉
  python research/factors_v2/run_etf_rebalance_signal.py --force       # 非季度末强制输出调仓
  python research/factors_v2/run_etf_rebalance_signal.py --capital 200000  # 指定资金规模

再平衡日: 季度最后一个交易日 (3/31, 6/30, 9/30, 12/31 对应的最近交易日)
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path: sys.path.insert(0, ROOT)

MARKET_CACHE = os.path.join(ROOT, "data", "market_cache")
OUT_DIR      = os.path.join(ROOT, "research", "factors_v2", "output", "live")
STATE_FILE   = os.path.join(OUT_DIR, "etf_portfolio_state.csv")
os.makedirs(OUT_DIR, exist_ok=True)

# 目标组合
TARGET_DIV = 0.70
TARGET_GEM = 0.30
TICKER_DIV = "512890"   # 红利低波 ETF
TICKER_GEM = "159915"   # 创业板 ETF
DRIFT_TOL  = 0.03        # 权重偏离 ≥3% 强建议调仓 (季度末触发)

# 可配资金规模 (缺省 10 万, 可 --capital 覆盖, 或从 config.py 读 PORTFOLIO_CAPITAL)
DEFAULT_CAPITAL = 100_000


# ── 价格加载 ──────────────────────────────────────────────────────────── #

def _load_etf_cache(ticker: str) -> pd.DataFrame:
    fp = os.path.join(MARKET_CACHE, f"etf_{ticker}.csv")
    if not os.path.exists(fp): return pd.DataFrame()
    df = pd.read_csv(fp, encoding="utf-8-sig")
    df.columns = [c.strip().replace("\ufeff","") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


def _fetch_live_price(ticker: str) -> tuple[float, str]:
    """尝试实时抓最新行情. 失败回退到缓存."""
    try:
        import akshare as ak
        raw = ak.fund_etf_hist_em(symbol=ticker, period="daily", adjust="hfq")
        date_col  = next((c for c in raw.columns if "日期"  in c), raw.columns[0])
        close_col = next((c for c in raw.columns if "收盘"  in c), None)
        raw[date_col]  = pd.to_datetime(raw[date_col])
        last = raw.sort_values(date_col).tail(1).iloc[0]
        return float(pd.to_numeric(last[close_col])), str(pd.Timestamp(last[date_col]).date())
    except Exception as e:
        print(f"  [!] 实时行情 {ticker} 获取失败 ({e}), 回退本地缓存")
        df = _load_etf_cache(ticker)
        if df.empty: return None, None
        last = df.tail(1).iloc[0]
        return float(last["close"]), str(last["date"].date())


# ── 日历判定 ──────────────────────────────────────────────────────────── #

def _is_quarter_end(today: pd.Timestamp) -> tuple[bool, str]:
    """是否是季度最后一个交易日 (近似: 3/6/9/12月倒数第 3 个工作日之后)."""
    # 简单规则: 今天是 3/6/9/12 月, 且月末前 3 天内, 且周一~周五
    if today.month not in (3,6,9,12): return False, ""
    if today.weekday() >= 5: return False, ""
    # 检查从今天到月底之间是否还有其他工作日
    last_of_month = (today + pd.offsets.MonthEnd(0))
    # 若今天到月底的工作日只有自己, 判为季度末
    more_bdays = pd.bdate_range(today + pd.Timedelta(days=1), last_of_month)
    if len(more_bdays) == 0:
        return True, f"Q{today.month//3} 季度末 ({today.date()})"
    return False, ""


# ── 状态文件: 跟踪上次调仓后的实际持仓 ───────────────────────────────── #

def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"last_rebalance": None, "shares_div": 0, "shares_gem": 0, "capital_at_rebal": 0}
    try:
        df = pd.read_csv(STATE_FILE, encoding="utf-8-sig")
        if df.empty: raise ValueError
        r = df.tail(1).iloc[0]
        return {
            "last_rebalance": str(r.get("date", "")),
            "shares_div":     int(r.get("shares_div", 0) or 0),
            "shares_gem":     int(r.get("shares_gem", 0) or 0),
            "capital_at_rebal": float(r.get("capital_at_rebal", 0) or 0),
        }
    except Exception:
        return {"last_rebalance": None, "shares_div": 0, "shares_gem": 0, "capital_at_rebal": 0}


def _append_state(row: dict):
    df_row = pd.DataFrame([row])
    header = not os.path.exists(STATE_FILE)
    df_row.to_csv(STATE_FILE, mode="a", index=False, encoding="utf-8-sig", header=header)


# ── 核心逻辑 ──────────────────────────────────────────────────────────── #

def compute_rebalance(capital: float, price_div: float, price_gem: float, state: dict):
    """
    给定总资金 + 当前 ETF 价格, 计算目标持仓 / 当前漂移 / 下单指令.
    ETF 按 100 股最小单位下单.
    """
    target_val_div = capital * TARGET_DIV
    target_val_gem = capital * TARGET_GEM
    target_shares_div = int(round(target_val_div / price_div / 100)) * 100
    target_shares_gem = int(round(target_val_gem / price_gem / 100)) * 100

    cur_shares_div = state.get("shares_div", 0)
    cur_shares_gem = state.get("shares_gem", 0)
    cur_val_div = cur_shares_div * price_div
    cur_val_gem = cur_shares_gem * price_gem
    cur_total = cur_val_div + cur_val_gem
    cur_w_div = (cur_val_div / cur_total) if cur_total > 0 else 0
    cur_w_gem = (cur_val_gem / cur_total) if cur_total > 0 else 0

    orders = []
    diff_div = target_shares_div - cur_shares_div
    diff_gem = target_shares_gem - cur_shares_gem
    if diff_div != 0:
        action = "买入" if diff_div > 0 else "卖出"
        orders.append({
            "ticker": TICKER_DIV, "name":"红利低波",
            "action": action, "shares": abs(diff_div),
            "price": price_div, "amount": abs(diff_div) * price_div,
        })
    if diff_gem != 0:
        action = "买入" if diff_gem > 0 else "卖出"
        orders.append({
            "ticker": TICKER_GEM, "name":"创业板",
            "action": action, "shares": abs(diff_gem),
            "price": price_gem, "amount": abs(diff_gem) * price_gem,
        })

    return {
        "target_shares_div": target_shares_div,
        "target_shares_gem": target_shares_gem,
        "target_val_div": target_shares_div * price_div,
        "target_val_gem": target_shares_gem * price_gem,
        "cur_shares_div": cur_shares_div,
        "cur_shares_gem": cur_shares_gem,
        "cur_val_div": cur_val_div,
        "cur_val_gem": cur_val_gem,
        "cur_w_div": cur_w_div,
        "cur_w_gem": cur_w_gem,
        "drift_div": cur_w_div - TARGET_DIV if cur_total>0 else 0.0,
        "drift_gem": cur_w_gem - TARGET_GEM if cur_total>0 else 0.0,
        "orders": orders,
    }


# ── 钉钉推送 ──────────────────────────────────────────────────────────── #

def _ding_sign(webhook: str, secret: str) -> str:
    ts = str(round(time.time() * 1000))
    msg = f"{ts}\n{secret}"
    sig = base64.b64encode(hmac.new(secret.encode(), msg.encode(), digestmod=hashlib.sha256).digest())
    return f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(sig)}"


def _build_markdown(today: str, rebal: dict, capital: float,
                    price_div: float, date_div: str,
                    price_gem: float, date_gem: str,
                    is_rebal_day: bool, reason: str) -> tuple[str, str]:
    title = f"ETF 季度调仓 {today} 葵花宝典" if is_rebal_day else f"ETF 持仓诊断 {today} 葵花宝典"

    lines = [f"## DIV70/GEM30 ETF 组合 — {today}\n"]
    lines.append(f"**策略**: 70% 红利低波 (512890) + 30% 创业板 (159915), 季度末再平衡")
    lines.append(f"**回测**: CAGR 15.15% / MDD -17.61% / Calmar 0.86 (2019-2026)\n")

    if is_rebal_day:
        lines.append(f"### 今日触发调仓: {reason}\n")
    else:
        lines.append(f"### 今日非季度末, 仅诊断当前漂移\n")

    lines.append(f"### 最新价格")
    lines.append(f"| ETF | 代码 | 最新价 | 数据日期 |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| 红利低波 | {TICKER_DIV} | ¥{price_div:.3f} | {date_div} |")
    lines.append(f"| 创业板 | {TICKER_GEM} | ¥{price_gem:.3f} | {date_gem} |\n")

    lines.append(f"### 目标持仓 (本金 ¥{capital:,.0f})")
    lines.append(f"| ETF | 目标股数 | 目标市值 | 目标权重 |")
    lines.append(f"|---|---:|---:|---:|")
    lines.append(f"| 红利低波 | {rebal['target_shares_div']:,d} | ¥{rebal['target_val_div']:,.0f} | 70% |")
    lines.append(f"| 创业板 | {rebal['target_shares_gem']:,d} | ¥{rebal['target_val_gem']:,.0f} | 30% |\n")

    cur_total = rebal["cur_val_div"] + rebal["cur_val_gem"]
    if cur_total > 0:
        lines.append(f"### 当前实际持仓")
        lines.append(f"| ETF | 当前股数 | 当前市值 | 当前权重 | 漂移 |")
        lines.append(f"|---|---:|---:|---:|---:|")
        lines.append(f"| 红利低波 | {rebal['cur_shares_div']:,d} | ¥{rebal['cur_val_div']:,.0f} "
                     f"| {rebal['cur_w_div']*100:.1f}% | {rebal['drift_div']*100:+.1f}pp |")
        lines.append(f"| 创业板 | {rebal['cur_shares_gem']:,d} | ¥{rebal['cur_val_gem']:,.0f} "
                     f"| {rebal['cur_w_gem']*100:.1f}% | {rebal['drift_gem']*100:+.1f}pp |\n")

    if rebal["orders"]:
        if is_rebal_day:
            lines.append(f"### 调仓指令")
        else:
            lines.append(f"### 如果现在调仓, 需要的指令")
        lines.append(f"| 操作 | ETF | 股数 | 单价 | 金额 |")
        lines.append(f"|---|---|---:|---:|---:|")
        for o in rebal["orders"]:
            lines.append(f"| **{o['action']}** | {o['name']} {o['ticker']} "
                         f"| {o['shares']:,d} | ¥{o['price']:.3f} | ¥{o['amount']:,.0f} |")
        lines.append("")
    else:
        lines.append(f"### 当前已是 70/30 目标, 无需调仓\n")

    lines.append(f"> 数据: 本地 ETF 行情缓存. 下次调仓: 下一季度末.")
    return title, "\n".join(lines)


def send_dingtalk(title: str, text: str) -> bool:
    try:
        import requests
    except ImportError:
        print("  [!] 需要 requests: pip install requests")
        return False
    try:
        from config import DINGTALK_WEBHOOK, DINGTALK_SECRET
    except ImportError:
        DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
        DINGTALK_SECRET  = os.environ.get("DINGTALK_SECRET", "")
    if not DINGTALK_WEBHOOK:
        print("  [!] DINGTALK_WEBHOOK 未配置, 跳过推送")
        return False
    url = _ding_sign(DINGTALK_WEBHOOK, DINGTALK_SECRET) if DINGTALK_SECRET else DINGTALK_WEBHOOK
    payload = {"msgtype":"markdown","markdown":{"title":title,"text":text},"at":{"isAtAll":False}}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        body = resp.json()
        if body.get("errcode") == 0:
            print("  钉钉推送成功 OK"); return True
        else:
            print(f"  钉钉推送失败: {body}"); return False
    except Exception as e:
        print(f"  钉钉推送异常: {e}"); return False


# ── main ──────────────────────────────────────────────────────────────── #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push",    action="store_true", help="推送钉钉")
    ap.add_argument("--force",   action="store_true", help="非季度末也输出调仓指令")
    ap.add_argument("--capital", type=float, default=None, help="投资金额 (¥), 默认 100,000 或 config.PORTFOLIO_CAPITAL")
    ap.add_argument("--confirm-rebalance", action="store_true",
                    help="确认执行后更新 state 文件 (记录已按目标持仓成交)")
    args = ap.parse_args()

    # 资金规模
    capital = args.capital
    if capital is None:
        try:
            from config import PORTFOLIO_CAPITAL
            capital = float(PORTFOLIO_CAPITAL)
        except Exception:
            capital = DEFAULT_CAPITAL
    print(f"[+] 本金: ¥{capital:,.0f}")

    # 价格
    print(f"[+] 抓取最新 ETF 行情...")
    price_div, date_div = _fetch_live_price(TICKER_DIV)
    price_gem, date_gem = _fetch_live_price(TICKER_GEM)
    if price_div is None or price_gem is None:
        print("  [!] 无法获取 ETF 价格, 退出"); return None
    print(f"  红利低波 {TICKER_DIV}: ¥{price_div:.3f}  ({date_div})")
    print(f"  创业板 {TICKER_GEM}: ¥{price_gem:.3f}  ({date_gem})")

    # 日历
    today = pd.Timestamp.today().normalize()
    is_qe, reason = _is_quarter_end(today)
    is_rebal = is_qe or args.force
    if is_rebal:
        print(f"[+] 触发调仓: {reason or '手动 --force'}")
    else:
        print(f"[+] 今日非季度末 ({today.date()}), 仅诊断漂移")

    # 计算
    state = _load_state()
    if state["last_rebalance"]:
        print(f"[+] 上次调仓: {state['last_rebalance']}  持仓 DIV {state['shares_div']:,d} / GEM {state['shares_gem']:,d}")
    else:
        print(f"[+] 状态文件为空, 视为首次建仓")

    rebal = compute_rebalance(capital, price_div, price_gem, state)

    # 打印报告
    print("\n" + "="*72)
    print(f"目标: 70% {TICKER_DIV} ({rebal['target_shares_div']:,d} 股, ¥{rebal['target_val_div']:,.0f})  "
          f"+ 30% {TICKER_GEM} ({rebal['target_shares_gem']:,d} 股, ¥{rebal['target_val_gem']:,.0f})")
    if rebal["cur_val_div"] + rebal["cur_val_gem"] > 0:
        print(f"当前: {rebal['cur_shares_div']:,d} / {rebal['cur_shares_gem']:,d}  "
              f"权重 {rebal['cur_w_div']*100:.1f}% / {rebal['cur_w_gem']*100:.1f}%  "
              f"漂移 {rebal['drift_div']*100:+.1f}pp / {rebal['drift_gem']*100:+.1f}pp")
    if rebal["orders"]:
        print("\n调仓指令:")
        for o in rebal["orders"]:
            print(f"  {o['action']} {o['name']} {o['ticker']}  "
                  f"{o['shares']:,d} 股 × ¥{o['price']:.3f} = ¥{o['amount']:,.0f}")
    else:
        print("已在目标, 无需调仓")
    print("="*72)

    # 推送
    title, text = _build_markdown(str(today.date()), rebal, capital,
                                   price_div, date_div, price_gem, date_gem,
                                   is_rebal, reason)
    if args.push:
        print("\n推送到钉钉...")
        send_dingtalk(title, text)

    # 更新 state (仅在 --confirm-rebalance)
    if args.confirm_rebalance and is_rebal:
        _append_state({
            "date": str(today.date()),
            "shares_div": rebal["target_shares_div"],
            "shares_gem": rebal["target_shares_gem"],
            "price_div": price_div, "price_gem": price_gem,
            "capital_at_rebal": capital,
        })
        print(f"[+] 已更新 state: {STATE_FILE}")

    return {
        "today": str(today.date()),
        "is_rebal_day": is_rebal,
        "capital": capital,
        "price_div": price_div, "price_gem": price_gem,
        "rebal": rebal,
    }


if __name__ == "__main__":
    main()
