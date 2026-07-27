"""
每日市场简报生成器
==================
运行: python research/data_prep/daily_briefing.py
输出: logs/daily_briefing_latest.md  (+ logs/daily_briefing_YYYYMMDD.md 存档)

设计: 让 Claude 在下次对话开始时读取此文件即可同步最新市场状态.
数据来源: 本地 OHLCV (价格) + AKShare (指数/新闻) + 本地基本面 panel.
"""

# ── Proxy fix (必须在 import akshare 前) ─────────────────────────────────────
import os
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

import sys
import json
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(ROOT, "logs")
PANEL = os.path.join(ROOT, "data", "fundamentals", "panel_quarterly.csv")
STOCK_DIR = os.path.join(ROOT, "data", "stock_data")
LIVE_DIR = os.path.join(ROOT, "research", "factors_v2", "output", "live")
AW_OUT = os.path.join(ROOT, "research", "factors_v2", "output")

os.makedirs(LOG_DIR, exist_ok=True)

# ── 配置 (手动维护) ────────────────────────────────────────────────────────────
WATCHED_STOCKS = [
    {"code": "603659", "exchange": "SH", "name": "璞泰来", "sector": "锂电负极材料"},
    # 添加更多: {"code": "000001", "exchange": "SZ", "name": "平安银行", "sector": "银行"},
]

AW_ETFS = [
    {"code": "512890", "exchange": "SH", "name": "红利ETF",   "weight": "30%"},
    {"code": "159915", "exchange": "SZ", "name": "创业板ETF", "weight": "0% (当前 T2 切出)"},
    {"code": "511010", "exchange": "SH", "name": "国债ETF",   "weight": "30%"},
    {"code": "518880", "exchange": "SH", "name": "黄金ETF",   "weight": "40%"},
]

TODAY = datetime.today().strftime("%Y-%m-%d")
START_60 = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
START_252 = (datetime.today() - timedelta(days=400)).strftime("%Y-%m-%d")


# ── 本地价格 ───────────────────────────────────────────────────────────────────
def load_local_price(code: str, exchange: str) -> dict | None:
    fp = os.path.join(STOCK_DIR, f"{exchange}{code}.csv")
    if not os.path.exists(fp):
        return None
    try:
        df = pd.read_csv(fp, encoding="utf-8-sig")
        date_col  = next((c for c in ["date", "日期"] if c in df.columns), None)
        close_col = next((c for c in ["close", "收盘"] if c in df.columns), None)
        pct_col   = next((c for c in ["pctChg", "涨跌幅"] if c in df.columns), None)
        if date_col is None or close_col is None:
            return None
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col, close_col]).sort_values(date_col)
        if len(df) < 5:
            return None
        last = df.iloc[-1]
        last_date = last[date_col].strftime("%Y-%m-%d")
        close = float(last[close_col])
        ret_1d  = float(last[pct_col]) / 100 if pct_col and not pd.isna(last[pct_col]) else np.nan
        ret_5d  = close / df.iloc[-6][close_col]  - 1 if len(df) >= 6  else np.nan
        ret_20d = close / df.iloc[-21][close_col] - 1 if len(df) >= 21 else np.nan
        ret_60d = close / df.iloc[-61][close_col] - 1 if len(df) >= 61 else np.nan
        w52_high = df.tail(252)[close_col].max() if len(df) >= 252 else df[close_col].max()
        w52_low  = df.tail(252)[close_col].min() if len(df) >= 252 else df[close_col].min()
        return {
            "last_close": close,
            "last_date":  last_date,
            "ret_1d":  ret_1d,
            "ret_5d":  ret_5d,
            "ret_20d": ret_20d,
            "ret_60d": ret_60d,
            "w52_high": w52_high,
            "w52_low":  w52_low,
        }
    except Exception as e:
        print(f"  [WARN] 价格读取失败 {exchange}{code}: {e}")
        return None


# ── AKShare 指数 ───────────────────────────────────────────────────────────────
def fetch_index(symbol: str, name: str, exchange_prefix: str = "sh") -> dict | None:
    try:
        import akshare as ak
        # stock_zh_index_daily uses Sina (more reliable than East Money)
        sina_sym = f"{exchange_prefix}{symbol}"
        df = ak.stock_zh_index_daily(symbol=sina_sym)
        if df is None or len(df) < 5:
            return None
        df = df.sort_values("date").tail(65)
        last = df.iloc[-1]
        close = float(last["close"])
        prev  = float(df.iloc[-2]["close"])
        ret_1d  = close / prev - 1
        ret_20d = close / df.iloc[-21]["close"] - 1 if len(df) >= 21 else np.nan
        ret_60d = close / df.iloc[-61]["close"] - 1 if len(df) >= 61 else np.nan
        return {
            "name": name, "symbol": symbol,
            "close": close, "ret_1d": ret_1d,
            "ret_20d": ret_20d, "ret_60d": ret_60d,
            "date": str(last["date"])[:10],
        }
    except Exception as e:
        print(f"  [WARN] 指数拉取失败 {symbol}: {e}")
        return None


# ── AKShare 新闻 ───────────────────────────────────────────────────────────────
def fetch_news(code: str, name: str, n: int = 6) -> list:
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=code)
        if df is None or len(df) == 0:
            return []
        # 东方财富新闻列: 关键词/新闻标题/新闻内容/发布时间/文章来源/新闻链接
        title_col = next((c for c in ["新闻标题", "title"] if c in df.columns), None)
        time_col  = next((c for c in ["发布时间", "datetime"] if c in df.columns), None)
        src_col   = next((c for c in ["文章来源", "source"] if c in df.columns), None)
        if title_col is None:
            return []
        df = df.head(n)
        results = []
        for _, row in df.iterrows():
            title = str(row.get(title_col, ""))
            ts    = str(row.get(time_col, ""))[:16] if time_col else ""
            src   = str(row.get(src_col, "")) if src_col else ""
            results.append({"title": title, "time": ts, "source": src})
        return results
    except Exception as e:
        print(f"  [WARN] 新闻拉取失败 {code}: {e}")
        return []


# ── 本地基本面 ─────────────────────────────────────────────────────────────────
def load_fundamental(code: str) -> dict | None:
    try:
        df = pd.read_csv(PANEL, encoding="utf-8-sig", dtype={"code": str}, low_memory=False)
        df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
        sub = df[df["code"] == code].sort_values("report_date").tail(4)
        if sub.empty:
            return None
        latest = sub.iloc[-1]
        # 单季度利润 (从累计逆推)
        q_profits = []
        for i, row in sub.iterrows():
            q = row["report_date"].quarter
            if q == 1:
                q_profits.append((row["report_date"], row["net_profit"]))
            elif len(q_profits) > 0 or i > sub.index[0]:
                prev_rows = sub[sub["report_date"] < row["report_date"]]
                if prev_rows.empty or prev_rows.iloc[-1]["report_date"].year != row["report_date"].year:
                    q_profits.append((row["report_date"], row["net_profit"]))
                else:
                    q_profits.append((row["report_date"], row["net_profit"] - prev_rows.iloc[-1]["net_profit"]))
        return {
            "report_date": str(latest["report_date"])[:10],
            "roe":        float(latest.get("roe", np.nan)),
            "eps":        float(latest.get("eps", np.nan)),
            "net_profit_yi": float(latest.get("net_profit", np.nan)) / 1e8,
            "bps":        float(latest.get("bps", np.nan)),
            "report_quarter": latest["report_date"].quarter,
            "report_year":    latest["report_date"].year,
        }
    except Exception as e:
        print(f"  [WARN] 基本面读取失败 {code}: {e}")
        return None


# ── 实盘日志 ───────────────────────────────────────────────────────────────────
def load_paper_trade_status() -> str:
    try:
        log_fp = os.path.join(LIVE_DIR, "paper_trade_log.csv")
        if not os.path.exists(log_fp):
            return "无实盘日志"
        df = pd.read_csv(log_fp, encoding="utf-8-sig")
        last = df.iloc[-1]
        date   = last.get("date", "?")
        regime = last.get("regime", "?")
        overlay = last.get("overlay", "?")
        action = last.get("action", "?")
        return f"最后信号 {date} | 市场: {regime} | Overlay: {overlay} | 操作: {action}"
    except Exception as e:
        return f"读取失败: {e}"


def load_high_odds_picks() -> str:
    fp = os.path.join(AW_OUT, "high_odds_picks_top.csv")
    if not os.path.exists(fp):
        return "尚无筛选结果 (运行 high_odds_stock_picker.py)"
    try:
        df = pd.read_csv(fp, encoding="utf-8-sig", dtype={"code": str})
        df = df.head(5)
        lines = []
        for _, r in df.iterrows():
            name = r.get("name", r["code"])
            roe  = r.get("roe", np.nan)
            pe   = r.get("pe_ann", np.nan)
            mcap = r.get("market_cap_yi", np.nan)
            r3m  = r.get("ret_3m", np.nan)
            score = r.get("score", np.nan)
            lines.append(
                f"  {r['code']} {name:6s}  ROE {roe:.1f}%  PE {pe:.1f}  "
                f"市值 {mcap:.0f}亿  3M {r3m*100:+.1f}%  Score {score:.2f}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"读取失败: {e}"


def _fmt_ret(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "  N/A  "
    return f"{v*100:+.1f}%"


# ── 主函数: 生成 markdown ──────────────────────────────────────────────────────
def generate_briefing():
    lines = []
    lines.append(f"# 每日简报 — {TODAY}")
    lines.append(f"> 生成时间: {datetime.now().strftime('%H:%M')}  数据来源: 本地OHLCV + AKShare\n")

    # ── 1. 市场指数 ──────────────────────────────────────────────────────────
    lines.append("## 市场概况\n")
    indices_config = [
        ("000300", "沪深300",  "sh"),
        ("000001", "上证指数", "sh"),
        ("399006", "创业板指", "sz"),
        ("000852", "中证1000", "sh"),
    ]
    for sym, name, pfx in indices_config:
        idx = fetch_index(sym, name, pfx)
        if idx:
            lines.append(
                f"- **{idx['name']}** ({idx['date']}): "
                f"{idx['close']:,.2f}  "
                f"今日 {_fmt_ret(idx['ret_1d'])}  "
                f"20日 {_fmt_ret(idx['ret_20d'])}  "
                f"60日 {_fmt_ret(idx['ret_60d'])}"
            )
        else:
            lines.append(f"- {name}: 数据获取失败")
    lines.append("")

    # ── 2. 自选股 (重点持仓) ─────────────────────────────────────────────────
    lines.append("## 自选股 / 持仓\n")
    for s in WATCHED_STOCKS:
        code, exch, name, sector = s["code"], s["exchange"], s["name"], s["sector"]
        print(f"[+] 处理 {exch}{code} {name}...")

        p = load_local_price(code, exch)
        f = load_fundamental(code)

        lines.append(f"### {name} ({exch}{code}) — {sector}")

        if p:
            stale = ""
            last_dt = datetime.strptime(p["last_date"], "%Y-%m-%d")
            days_old = (datetime.today() - last_dt).days
            if days_old > 3:
                stale = f" ⚠️ 数据停留在 {p['last_date']} ({days_old} 天前, 需更新)"
            pct_from_high = (p["last_close"] / p["w52_high"] - 1) * 100
            lines.append(
                f"- 最新价: **{p['last_close']:.2f}**{stale}  "
                f"52W高 {p['w52_high']:.2f} ({pct_from_high:+.1f}%)  "
                f"52W低 {p['w52_low']:.2f}"
            )
            lines.append(
                f"- 收益: 今日 {_fmt_ret(p['ret_1d'])}  "
                f"5日 {_fmt_ret(p['ret_5d'])}  "
                f"20日 {_fmt_ret(p['ret_20d'])}  "
                f"60日 {_fmt_ret(p['ret_60d'])}"
            )
        else:
            lines.append(f"- 价格: 本地无数据 (需运行 update_stock_data.py)")

        if f:
            q_label = f"{f['report_year']}Q{f['report_quarter']}"
            lines.append(
                f"- 最新财报: **{q_label}** ({f['report_date']})  "
                f"ROE {f['roe']:.2f}%  EPS {f['eps']:.2f}  "
                f"净利润 {f['net_profit_yi']:.2f}亿  BPS {f['bps']:.2f}"
            )
        else:
            lines.append(f"- 基本面: 无数据")

        # 新闻
        print(f"  [+] 拉取 {name} 新闻...")
        news = fetch_news(code, name, n=5)
        if news:
            lines.append(f"- **最新新闻** (最近 {len(news)} 条):")
            for n_item in news:
                lines.append(f"  - [{n_item['time']}] {n_item['title']}  _({n_item['source']})_")
        else:
            lines.append(f"- 新闻: 获取失败或无最新新闻")
        lines.append("")

    # ── 3. 全天候 ETF 状态 ───────────────────────────────────────────────────
    lines.append("## 全天候 ETF 组合\n")
    lines.append(f"低波实盘信号: {load_paper_trade_status()}\n")
    lines.append("| ETF | 代码 | 目标权重 | 最新价 | 今日 | 20日 |")
    lines.append("|-----|------|----------|--------|------|------|")
    for etf in AW_ETFS:
        p = load_local_price(etf["code"], etf["exchange"])
        if p:
            lines.append(
                f"| {etf['name']} | {etf['exchange']}{etf['code']} | {etf['weight']} "
                f"| {p['last_close']:.3f} | {_fmt_ret(p['ret_1d'])} | {_fmt_ret(p['ret_20d'])} |"
            )
        else:
            lines.append(f"| {etf['name']} | {etf['exchange']}{etf['code']} | {etf['weight']} | N/A | — | — |")
    lines.append("")
    lines.append("> T2 规则: STK 12M>0 且 >SMA200 → 持仓; 否则切债. 季末再平衡.\n")

    # ── 4. 高赔率筛选器 ──────────────────────────────────────────────────────
    lines.append("## 高赔率选股器 Top5\n")
    lines.append("```")
    lines.append(load_high_odds_picks())
    lines.append("```\n")
    lines.append("> 完整: research/factors_v2/output/high_odds_picks_top.csv\n")

    # ── 5. 每日待关注事项 ────────────────────────────────────────────────────
    lines.append("## 待关注\n")
    lines.append("- [ ] 检查 603659 2026Q1 财报是否已披露 (截止 4/30)")
    lines.append("- [ ] 下次全天候再平衡: ~2026-06 月末")
    lines.append("- [ ] 高赔率筛选器每周更新一次")
    lines.append("")

    return "\n".join(lines)


def main():
    print(f"[+] 生成每日简报 {TODAY}...")
    md = generate_briefing()

    # 写当日存档
    dated_fp = os.path.join(LOG_DIR, f"daily_briefing_{TODAY}.md")
    latest_fp = os.path.join(LOG_DIR, "daily_briefing_latest.md")

    with open(dated_fp,  "w", encoding="utf-8") as f:
        f.write(md)
    with open(latest_fp, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"[+] 写入: {latest_fp}")
    print(f"[+] 存档: {dated_fp}")
    print(f"\n{'='*60}")
    print(md[:800])
    print("... (完整内容在文件中)")


if __name__ == "__main__":
    main()
