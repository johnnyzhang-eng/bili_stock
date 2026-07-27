"""
模拟盘追踪器 — 记录买入、更新当前价格、推送P&L到钉钉
==========================================================
用法:
    # 添加持仓（名称自动查询，股数可选）
    python research/factors_v2/paper_trade.py add SH600036 42.50 [1000] [板块]

    # 查看当前P&L
    python research/factors_v2/paper_trade.py show

    # 平仓（价格可选，不填用最新收盘）
    python research/factors_v2/paper_trade.py close SH600036 [43.80]

    # 推送P&L到钉钉
    python research/factors_v2/paper_trade.py show --push

持仓记录保存在 research/factors_v2/output/paper_trade.json
买入含费: +13bp；卖出含费: -43bp
"""

import json
import os
import sys
from datetime import datetime

BUY_COST_BPS  = 13   # 买入含佣金+过户费+滑点
SELL_COST_BPS = 43   # 卖出含佣金+印花税+过户费+滑点+冲击

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
OUT_DIR        = os.path.join(ROOT, "research", "factors_v2", "output")
LIVE_DIR       = os.path.join(OUT_DIR, "live")
TRADE_LOG      = os.path.join(LIVE_DIR, "paper_trade.json")


# ── 持仓存取 ────────────────────────────────────────────────────────────── #

def _load_log() -> dict:
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, encoding="utf-8") as f:
            return json.load(f)
    return {"positions": [], "closed": []}


def _save_log(log: dict):
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(TRADE_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2, default=str)


def _lookup_name(sym: str) -> str:
    try:
        from research.factors_v2.stock_names import get_name
        return get_name(sym[2:])
    except Exception:
        return sym


# ── 读取本地最新收盘价 ─────────────────────────────────────────────────── #

def _get_latest_price(sym: str) -> tuple[float, str]:
    """返回 (最新收盘价, 日期字符串)，失败返回 (nan, '')。"""
    fp = os.path.join(STOCK_DATA_DIR, sym.upper() + ".csv")
    if not os.path.exists(fp):
        return float("nan"), ""
    try:
        df = pd.read_csv(fp, encoding="utf-8-sig")
        col_map = {}
        for col in df.columns:
            lc = col.strip()
            if lc == "日期":   col_map[col] = "date"
            elif lc == "收盘": col_map[col] = "close"
        df = df.rename(columns=col_map)
        if "date" not in df.columns or "close" not in df.columns:
            return float("nan"), ""
        df["date"]  = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna().sort_values("date")
        if df.empty:
            return float("nan"), ""
        row = df.iloc[-1]
        return float(row["close"]), str(row["date"].date())
    except Exception:
        return float("nan"), ""


# ── 命令：添加持仓 ────────────────────────────────────────────────────── #

def cmd_add(sym: str, entry_price: float | None = None, shares: int = 100,
            name: str = "", entry_date: str = "", sector: str = ""):
    log = _load_log()
    sym = sym.upper()
    if not entry_date:
        entry_date = str(datetime.today().date())

    # 如已有同代码持仓则提示
    existing = next((p for p in log["positions"] if p["sym"] == sym), None)
    if existing:
        print(f"  [!] {sym} 已有开仓记录，先 close 再 add")
        return

    # 自动查名称
    if not name:
        name = _lookup_name(sym)

    # 价格：若未指定则取最新收盘
    if entry_price is None:
        p, _ = _get_latest_price(sym)
        if np.isnan(p):
            print(f"  [!] 无法获取 {sym} 价格，请手动指定")
            return
        entry_price = p
        print(f"  自动取最新收盘价: {entry_price:.2f}")

    # 含买入成本
    entry_cost = entry_price * (1 + BUY_COST_BPS / 10000)

    pos = {
        "sym":         sym,
        "name":        name,
        "entry_date":  entry_date,
        "entry_price": round(entry_cost, 4),
        "entry_raw":   entry_price,
        "shares":      shares,
        "sector":      sector,
    }
    log["positions"].append(pos)
    _save_log(log)
    cost = entry_cost * shares
    print(f"  已记录: {sym} {name}  买入 {shares}股 @ {entry_price:.2f}(+{BUY_COST_BPS}bp)"
          f" = 成本价 {entry_cost:.2f}  ({entry_date})")


# ── 命令：平仓 ──────────────────────────────────────────────────────────── #

def cmd_close(sym: str, exit_price: float | None = None, exit_date: str = ""):
    log = _load_log()
    sym = sym.upper()
    if not exit_date:
        exit_date = str(datetime.today().date())

    if exit_price is None:
        p, _ = _get_latest_price(sym)
        if np.isnan(p):
            print(f"  [!] 无法获取 {sym} 价格，请手动指定")
            return
        exit_price = p
        print(f"  自动取最新收盘价: {exit_price:.2f}")

    # 扣卖出成本
    exit_net = exit_price * (1 - SELL_COST_BPS / 10000)

    kept, closed_now = [], []
    for pos in log["positions"]:
        if pos["sym"] == sym:
            ret = exit_net / pos["entry_price"] - 1.0
            pnl = (exit_net - pos["entry_price"]) * pos["shares"]
            record = {**pos, "exit_date": exit_date, "exit_price": round(exit_net, 4),
                      "exit_raw": exit_price, "ret": ret, "pnl": pnl}
            log["closed"].append(record)
            closed_now.append(record)
            print(f"  已平仓: {sym} {pos['name']}  {pos['entry_price']:.2f} -> {exit_net:.2f}(-{SELL_COST_BPS}bp)"
                  f"  收益 {ret:+.2%}  ({pnl:+.0f}元)")
        else:
            kept.append(pos)

    if not closed_now:
        print(f"  [!] 未找到 {sym} 的持仓记录")
        return
    log["positions"] = kept
    _save_log(log)


# ── 命令：查看 ──────────────────────────────────────────────────────────── #

def cmd_show(push: bool = False):
    log = _load_log()
    today = str(datetime.today().date())

    print(f"\n{'='*65}")
    print(f"模拟盘 — {today}")
    print(f"{'='*65}\n")

    if not log["positions"]:
        print("  暂无持仓\n")
    else:
        rows = []
        for pos in log["positions"]:
            cur_price, cur_date = _get_latest_price(pos["sym"])
            if not np.isnan(cur_price):
                ret = cur_price / pos["entry_price"] - 1.0
                pnl = (cur_price - pos["entry_price"]) * pos["shares"]
            else:
                ret = float("nan")
                pnl = float("nan")
                cur_date = "无数据"
            rows.append({**pos, "cur_price": cur_price, "cur_date": cur_date,
                         "ret": ret, "pnl": pnl})

        df = pd.DataFrame(rows)
        total_cost = (df["entry_price"] * df["shares"]).sum()
        valid = df.dropna(subset=["pnl"])
        total_pnl  = valid["pnl"].sum()
        total_ret  = total_pnl / total_cost if total_cost > 0 else float("nan")
        wins = (valid["ret"] > 0).sum()
        n    = len(valid)

        print(f"  持仓 {len(df)} 只  |  胜率 {wins}/{n}  |  总成本 {total_cost:.0f}元"
              f"  |  总盈亏 {total_pnl:+.0f}元  ({total_ret:+.2%})\n")
        print(f"  {'代码':<10s} {'名称':<10s} {'买入':>7s} {'现价':>7s} {'股数':>6s} {'收益':>8s} {'盈亏(元)':>10s}  {'板块'}")
        print(f"  {'-'*75}")
        for _, r in df.iterrows():
            ret_str = f"{r['ret']:+.2%}" if not np.isnan(r['ret']) else "  --"
            pnl_str = f"{r['pnl']:+.0f}" if not np.isnan(r['pnl']) else "--"
            arrow   = " ^" if (not np.isnan(r['ret']) and r['ret'] > 0) else " v"
            print(f"  {r['sym']:<10s} {r['name']:<10s} {r['entry_price']:>7.2f} "
                  f"{r['cur_price'] if not np.isnan(r['cur_price']) else 0:>7.2f} "
                  f"{r['shares']:>6d} {ret_str:>8s} {pnl_str:>10s}  {r['sector']}{arrow}")
        print()

        if push and not df.empty:
            _push_summary(df, total_cost, total_pnl, total_ret, wins, n, today)

    # 历史平仓统计
    if log["closed"]:
        closed_df = pd.DataFrame(log["closed"])
        c_win  = (closed_df["ret"] > 0).sum()
        c_n    = len(closed_df)
        c_avg  = closed_df["ret"].mean()
        c_pnl  = closed_df["pnl"].sum()
        print(f"  历史平仓: {c_n} 笔  |  胜率 {c_win}/{c_n}={c_win/c_n:.0%}"
              f"  |  平均收益 {c_avg:+.2%}  |  累计盈亏 {c_pnl:+.0f}元\n")


# ── 钉钉推送 ────────────────────────────────────────────────────────────── #

def _push_summary(df, total_cost, total_pnl, total_ret, wins, n, today):
    try:
        import requests
    except ImportError:
        print("  [!] pip install requests")
        return

    try:
        from config import DINGTALK_WEBHOOK, DINGTALK_SECRET
    except ImportError:
        DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
        DINGTALK_SECRET  = ""

    if not DINGTALK_WEBHOOK:
        print("  [!] 未配置 DINGTALK_WEBHOOK")
        return

    title = f"模拟盘 {today} 葵花宝典"
    lines = [f"## 模拟盘 — {today}\n"]
    lines.append(f"**持仓 {len(df)} 只** | 胜率 {wins}/{n} | 总盈亏 **{total_pnl:+.0f}元** ({total_ret:+.2%})\n")
    lines.append("| 代码 | 名称 | 买入 | 现价 | 收益 | 板块 |")
    lines.append("|---|---|---|---|---|---|")
    for _, r in df.iterrows():
        ret_str = f"{r['ret']:+.2%}" if not np.isnan(r["ret"]) else "--"
        cur_str = f"{r['cur_price']:.2f}" if not np.isnan(r["cur_price"]) else "--"
        lines.append(f"| {r['sym']} | **{r['name']}** | {r['entry_price']:.2f} | {cur_str} | {ret_str} | {r['sector']} |")
    lines.append("")
    lines.append("> 模拟盘，不构成投资建议")

    text = "\n".join(lines)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"isAtAll": False},
    }
    import base64, hashlib, hmac, time, urllib.parse
    if DINGTALK_SECRET:
        ts  = str(round(time.time() * 1000))
        msg = f"{ts}\n{DINGTALK_SECRET}"
        sig = base64.b64encode(
            hmac.new(DINGTALK_SECRET.encode(), msg.encode(), digestmod=hashlib.sha256).digest()
        )
        url = f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={urllib.parse.quote_plus(sig)}"
    else:
        url = DINGTALK_WEBHOOK

    try:
        resp = requests.post(url, json=payload, timeout=10)
        body = resp.json()
        if body.get("errcode") == 0:
            print("  钉钉推送成功 OK")
        else:
            print(f"  钉钉推送失败: {body}")
    except Exception as e:
        print(f"  钉钉推送异常: {e}")


# ── CLI 入口 ─────────────────────────────────────────────────────────────── #

def _usage():
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    args = sys.argv[1:]
    push = "--push" in args
    args = [a for a in args if a != "--push"]

    if not args:
        cmd_show(push=push)
    elif args[0] == "show":
        cmd_show(push=push)
    elif args[0] == "add":
        if len(args) < 2:
            print("用法: add <代码> [买入价] [股数] [板块]")
            sys.exit(1)
        sym    = args[1]
        price  = float(args[2]) if len(args) > 2 else None
        shares = int(args[3])   if len(args) > 3 else 100
        sector = args[4]        if len(args) > 4 else ""
        cmd_add(sym, price, shares, sector=sector)
    elif args[0] == "close":
        if len(args) < 2:
            print("用法: close <代码> [卖出价]")
            sys.exit(1)
        price = float(args[2]) if len(args) > 2 else None
        cmd_close(args[1], price)
    else:
        _usage()
