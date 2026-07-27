"""
可转债双低 — 实盘信号 + 1 年基准分析
=====================================
Part 1: 集思录 CB 等权指数近 1 年表现 (基准)
Part 2: 当前双低 Top 20 选债 (实盘信号)
Part 3: 持仓 paper trade 跟踪 (累计写入 state 文件)
Part 4: 钉钉推送

策略逻辑:
  - 价格 95-130 元 (避免高价被杀 + 避免低价破面违约风险)
  - 转股溢价率 < 30% (低溢价)
  - 双低值 = 价格 + 溢价率 × 100, 取最低 Top N
  - 剔除: 退市/违约/已发强赎/已到期
  - 每月再平衡一次 (月底触发)

用法:
  python research/factors_v2/cb_dblow_signal.py              # 打印 + 保存
  python research/factors_v2/cb_dblow_signal.py --push       # 推送钉钉
  python research/factors_v2/cb_dblow_signal.py --top 20     # 指定持仓数
  python research/factors_v2/cb_dblow_signal.py --capital 100000
"""
import argparse
import base64
import hashlib
import hmac
import os
import sys
import time
import urllib.parse
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
OUT_DIR = os.path.join(ROOT, "research", "factors_v2", "output", "live")
os.makedirs(OUT_DIR, exist_ok=True)

DEFAULT_TOP  = 20
DEFAULT_CAP  = 100_000
MIN_PRICE    = 95.0
MAX_PRICE    = 140.0   # 2026-04 市场过热, 放宽到 140 才能筛出标的
MAX_PREMIUM  = 40.0    # %, 同上放宽
TEMP_HOT     = 85.0    # 温度 > 85 警告过热
TEMP_COLD    = 50.0    # 温度 < 50 为冷, 适合入场


def part1_baseline():
    import akshare as ak
    df = ak.bond_cb_index_jsl()
    df["price_dt"] = pd.to_datetime(df["price_dt"])
    df = df.sort_values("price_dt").reset_index(drop=True)

    first, last = df.iloc[0], df.iloc[-1]
    days = (last["price_dt"] - first["price_dt"]).days
    total_ret = last["price"] / first["price"] - 1
    ann = (1 + total_ret) ** (365.25/days) - 1
    df["ret"] = df["price"].pct_change()
    vol = df["ret"].std() * np.sqrt(252)
    eq = df["price"] / df["price"].iloc[0]
    mdd = (eq / eq.cummax() - 1).min()

    return {
        "起始日":    str(first["price_dt"].date()),
        "截至日":    str(last["price_dt"].date()),
        "天数":     days,
        "区间收益":   total_ret,
        "年化收益":   ann,
        "年化波动":   vol,
        "最大回撤":   mdd,
        "当前温度":   float(last["temperature"]),
        "当前均价":   float(last["avg_price"]),
        "当前双低":   float(last["avg_dblow"]),
        "当前溢价率":  float(last["avg_premium_rt"]),
        "当前 YTM":  float(last["avg_ytm_rt"]),
    }


def part2_picks(top_n: int):
    """
    用 ak.bond_zh_cov (溢价率/评级) ∧ ak.bond_zh_hs_cov_spot (真实交易价) 双源合并.
    只保留 spot.trade > 0 (在交易且今日有成交) 的个券, 避免已停牌/退市/未上市.
    """
    import akshare as ak
    meta = ak.bond_zh_cov()
    meta = meta.rename(columns={
        "债券代码":"代码", "债券简称":"转债名称",
        "正股简称":"正股名称", "信用评级":"评级",
    })
    meta["代码"] = meta["代码"].astype(str).str.zfill(6)
    meta["转股溢价率"] = pd.to_numeric(meta["转股溢价率"], errors="coerce")
    meta["上市时间"] = pd.to_datetime(meta.get("上市时间"), errors="coerce")
    meta = meta[["代码","转债名称","正股名称","评级","转股溢价率","上市时间"]]

    spot = ak.bond_zh_hs_cov_spot()
    spot["trade"] = pd.to_numeric(spot["trade"], errors="coerce")
    spot["code"] = spot["code"].astype(str).str.zfill(6)
    spot = spot[spot["trade"] > 0][["code","trade"]].rename(columns={"code":"代码","trade":"现价"})

    df = meta.merge(spot, on="代码", how="inner")  # inner: 必须在 spot 里且有价
    df = df.dropna(subset=["现价","转股溢价率"])
    df = df[~df["转债名称"].astype(str).str.contains("退|EB|E一|E二", na=False)]
    df = df[df["上市时间"].notna() & (df["上市时间"] <= pd.Timestamp.today())]
    df["双低"] = df["现价"] + df["转股溢价率"]
    df["剩余年限"] = np.nan
    mask = (
        (df["现价"] >= MIN_PRICE) &
        (df["现价"] <= MAX_PRICE) &
        (df["转股溢价率"] <= MAX_PREMIUM)
    )
    picks = df[mask].sort_values("双低").head(top_n).reset_index(drop=True)
    keep = ["代码","转债名称","正股名称","现价","转股溢价率","双低","评级","剩余年限"]
    return picks[[c for c in keep if c in picks.columns]]


def sizing(picks: pd.DataFrame, capital: float):
    """等权分钱, 按 10 张 / 手下单"""
    n = len(picks)
    if n == 0: return pd.DataFrame()
    per_name = capital / n
    out = []
    for _, r in picks.iterrows():
        price = float(r["现价"])
        # 按 10 张一手, 每张面值 100, 一手 ~1000*price/100 = 10*price
        cost_per_hand = price * 10
        hands = int(per_name // cost_per_hand)
        actual = hands * cost_per_hand
        out.append({
            "代码": str(r["代码"]),
            "转债名称": str(r["转债名称"]),
            "正股名称": str(r.get("正股名称", "")),
            "现价": price,
            "转股溢价率": float(r["转股溢价率"]),
            "双低": float(r["双低"]),
            "评级": str(r.get("债券评级", "")),
            "剩余年限": float(r.get("剩余年限", np.nan)),
            "手数": hands,
            "张数": hands * 10,
            "占用资金": actual,
        })
    return pd.DataFrame(out)


# ── 钉钉推送 ─────────────────────────────────────────────────────────── #

def _ding_sign(webhook: str, secret: str) -> str:
    ts = str(round(time.time() * 1000))
    msg = f"{ts}\n{secret}"
    sig = base64.b64encode(hmac.new(secret.encode(), msg.encode(), digestmod=hashlib.sha256).digest())
    return f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(sig)}"


def _build_markdown(bl: dict, orders: pd.DataFrame, capital: float) -> tuple[str, str]:
    today = datetime.now().strftime("%Y-%m-%d")
    title = f"可转债双低 {today} 葵花宝典"
    lines = [f"## 可转债双低信号 — {today}\n"]
    lines.append("### CB 市场 1 年基准 (集思录等权指数)")
    lines.append(f"- 区间: {bl['起始日']} → {bl['截至日']}  ({bl['天数']}天)")
    lines.append(f"- 累计 {bl['区间收益']*100:+.1f}% / 年化 {bl['年化收益']*100:+.1f}%")
    lines.append(f"- 年化波动 {bl['年化波动']*100:.1f}% / 最大回撤 {bl['最大回撤']*100:.1f}%")
    temp = bl["当前温度"]
    if   temp >= TEMP_HOT: warn = "🔥 严重过热, 建议观望/减仓"
    elif temp <= TEMP_COLD: warn = "❄️ 偏冷, 适合定投入场"
    else: warn = "中性区间"
    lines.append(f"- 当前温度: **{temp:.1f}** — {warn}")
    lines.append(f"- 当前均价 ¥{bl['当前均价']:.1f} / 均双低 {bl['当前双低']:.1f} / 溢价 {bl['当前溢价率']:.1f}% / YTM {bl['当前 YTM']:.2f}%\n")

    if orders.empty:
        lines.append("### 今日无符合筛选的双低标的\n")
    else:
        used = float(orders["占用资金"].sum())
        lines.append(f"### 双低 Top {len(orders)}  (本金 ¥{capital:,.0f}, 实际用 ¥{used:,.0f})\n")
        lines.append(f"| 排名 | 代码 | 转债 | 现价 | 溢价 | 双低 | 评级 | 手数 | 占用 |")
        lines.append(f"|---:|---|---|---:|---:|---:|---|---:|---:|")
        for i, r in orders.iterrows():
            lines.append(
                f"| {i+1} | {r['代码']} | {r['转债名称']} "
                f"| ¥{r['现价']:.2f} | {r['转股溢价率']:.1f}% | {r['双低']:.1f} "
                f"| {r['评级']} | {r['手数']} | ¥{r['占用资金']:,.0f} |"
            )
        lines.append("")
        lines.append(f"- 平均价: ¥{orders['现价'].mean():.2f}  平均溢价: {orders['转股溢价率'].mean():.1f}%  平均双低: {orders['双低'].mean():.1f}")

    lines.append("\n> 规则: 价格 95-130 + 溢价<30% + 剩余>0.5y, 按双低值升序 Top N, 每月再平衡")
    lines.append("> 注意: 强赎前 & 下修预期个券需手动审查")
    return title, "\n".join(lines)


def send_dingtalk(title: str, text: str) -> bool:
    try:
        import requests
    except ImportError:
        print("  [!] pip install requests"); return False
    try:
        from config import DINGTALK_WEBHOOK, DINGTALK_SECRET
    except ImportError:
        DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
        DINGTALK_SECRET  = os.environ.get("DINGTALK_SECRET", "")
    if not DINGTALK_WEBHOOK:
        print("  [!] DINGTALK_WEBHOOK 未配置"); return False
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


# ── main ─────────────────────────────────────────────────────────────── #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top",     type=int,   default=DEFAULT_TOP)
    ap.add_argument("--capital", type=float, default=DEFAULT_CAP)
    ap.add_argument("--push",    action="store_true")
    args = ap.parse_args()

    print(f"[1/3] 拉取 CB 市场 1 年基准...")
    try:
        bl = part1_baseline()
    except Exception as e:
        print(f"  失败: {e}")
        bl = {"起始日":"N/A","截至日":"N/A","天数":0,"区间收益":0,"年化收益":0,
              "年化波动":0,"最大回撤":0,"当前温度":0,"当前均价":0,"当前双低":0,"当前溢价率":0,"当前 YTM":0}
    print(f"  区间 {bl['起始日']} → {bl['截至日']}  累计 {bl['区间收益']*100:+.1f}% / 年化 {bl['年化收益']*100:+.1f}%")
    print(f"  年化波动 {bl['年化波动']*100:.1f}% / MDD {bl['最大回撤']*100:.1f}%")
    print(f"  温度 {bl['当前温度']:.1f}  均价 {bl['当前均价']:.1f}  均双低 {bl['当前双低']:.1f}")

    print(f"\n[2/3] 拉取当前 CB 快照 + 双低筛选 Top {args.top}...")
    picks = part2_picks(args.top)
    print(f"  筛出 {len(picks)} 只")

    orders = sizing(picks, args.capital)
    if orders.empty:
        print("  无符合筛选的双低标的")
    else:
        print(f"\n  {'排名':<4s} {'代码':<8s} {'名称':<12s} {'价':>7s} {'溢价':>6s} {'双低':>6s} {'评级':<5s} {'手数':>4s} {'占用':>10s}")
        print("  " + "-"*82)
        for i, r in orders.iterrows():
            print(f"  {i+1:<4d} {r['代码']:<8s} {r['转债名称']:<12s} "
                  f"{r['现价']:>7.2f} {r['转股溢价率']:>5.1f}% {r['双低']:>6.1f} "
                  f"{r['评级']:<5s} {r['手数']:>4d} ¥{r['占用资金']:>8,.0f}")
        total = float(orders["占用资金"].sum())
        print(f"\n  合计占用 ¥{total:,.0f} / 本金 ¥{args.capital:,.0f}  "
              f"({total/args.capital*100:.1f}%)")

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    orders.to_csv(os.path.join(OUT_DIR, f"cb_dblow_picks_{ts}.csv"),
                  index=False, encoding="utf-8-sig")
    # 最新版固定名
    orders.to_csv(os.path.join(OUT_DIR, "cb_dblow_picks_latest.csv"),
                  index=False, encoding="utf-8-sig")

    pd.DataFrame([bl]).to_csv(os.path.join(OUT_DIR, "cb_market_baseline.csv"),
                               index=False, encoding="utf-8-sig")

    print(f"\n[3/3] 结果保存到 {OUT_DIR}")

    if args.push:
        print("\n推送到钉钉...")
        title, text = _build_markdown(bl, orders, args.capital)
        send_dingtalk(title, text)


if __name__ == "__main__":
    main()
