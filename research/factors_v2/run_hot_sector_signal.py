"""
Hot Sector Signal — 板块热度 × Factor A干净池 × 未涨停筛选
============================================================
逻辑：
  1. 用近15日涨停记录建立 板块→股票代码 映射（覆盖更广）
  2. 近3-5日涨停集中的板块 = 热点板块
  3. 今日涨停 = 已发动，次日追高风险高
  4. 目标：热点板块 ∩ Factor A干净池 ∩ 今日未涨停 → 可能明日补涨

Run:
    python research/factors_v2/run_hot_sector_signal.py          # 只打印
    python research/factors_v2/run_hot_sector_signal.py --push   # 打印 + 推送钉钉
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STOCK_DATA_DIR = os.path.join(ROOT, "data", "stock_data")
OUT_DIR        = os.path.join(ROOT, "research", "factors_v2", "output", "live")
TOP_SECTOR_N   = 5
HISTORY_DAYS   = 15
MIN_AMOUNT_M   = 200   # 最低日成交额 200百万（2亿），过滤僵尸股

from research.factors_v2.stock_names import get_name_map, is_st
_NAME_MAP: dict = {}


# ── AKShare: 涨停原始数据 ────────────────────────────────────────────── #

def _fetch_zt_pool(date_str: str) -> pd.DataFrame:
    """获取某日涨停池，返回含 stock_code/stock_name/sector 的DataFrame。"""
    import akshare as ak
    try:
        df = ak.stock_zt_pool_em(date=date_str)
        if df is None or df.empty:
            return pd.DataFrame()
        sector_col = next((c for c in df.columns if "行业" in c or "板块" in c), None)
        code_col   = next((c for c in df.columns if c in ("代码", "股票代码")), None)
        name_col   = next((c for c in df.columns if c in ("名称", "股票名称")), None)
        if not code_col:
            return pd.DataFrame()
        out = pd.DataFrame({
            "stock_code": df[code_col].astype(str),
            "stock_name": df[name_col].astype(str) if name_col else "",
            "sector":     df[sector_col].astype(str) if sector_col else "未知",
        })
        return out
    except Exception as e:
        print(f"    涨停池 {date_str} 失败: {e}")
        return pd.DataFrame()


def _get_zt_history(days_back: int = 15) -> tuple[pd.DataFrame, set]:
    """
    返回:
      zt_all   — 近N日所有涨停记录（含日期）
      today_zt — 今日涨停代码集合 (6位纯数字)
    """
    try:
        import akshare  # noqa: F401
    except ImportError:
        print("  [!] akshare未安装")
        return pd.DataFrame(), set()

    records = []
    today_zt: set[str] = set()
    today = datetime.today().date()
    fetched_days = 0

    # 往前扫描日历天，凑够days_back个交易日
    for offset in range(days_back * 2):
        if fetched_days >= days_back:
            break
        target = today - timedelta(days=offset)
        if target.weekday() >= 5:
            continue
        date_str = target.strftime("%Y%m%d")
        df = _fetch_zt_pool(date_str)
        if df.empty:
            continue
        fetched_days += 1
        df["date"] = target
        records.append(df)
        print(f"    涨停池 {date_str}: {len(df)} 只")
        if offset == 0:
            today_zt = set(df["stock_code"].tolist())

    if not records:
        return pd.DataFrame(), today_zt
    return pd.concat(records, ignore_index=True), today_zt


# ── Factor A 干净池 ──────────────────────────────────────────────────── #

def _is_etf(sym: str) -> bool:
    s = sym.upper()
    if s.startswith("SH"):
        code = s[2:]
        return code[:3] in {"510","511","512","513","514","515","516",
                             "517","518","519","588"} or code[:2] == "56"
    if s.startswith("SZ"):
        return s[2:5] == "159"
    return False


def _build_clean_pool() -> pd.DataFrame:
    """计算Factor A干净池（cnt28=0，主板，非ST，流动性达标）。"""
    import glob
    global _NAME_MAP
    if not _NAME_MAP:
        try:
            _NAME_MAP = get_name_map()
        except Exception:
            _NAME_MAP = {}

    files  = glob.glob(os.path.join(STOCK_DATA_DIR, "S[HZ]*.csv"))
    today  = pd.Timestamp(datetime.today().date())
    cutoff = today - timedelta(days=65)

    rows = []
    for fp in files:
        sym  = os.path.splitext(os.path.basename(fp))[0].upper()
        code = sym[2:]
        if _is_etf(sym):
            continue
        # 主板过滤：排除创业板(300/301/302)、科创板(688)、北交所(8/4开头)
        if sym.startswith("SZ") and code[:3] in {"300","301","302"}:
            continue
        if sym.startswith("SH") and code[:3] in {"688","689"}:
            continue
        if code[:1] in {"8","4"}:
            continue

        # ST过滤
        name = _NAME_MAP.get(code, "")
        if is_st(name):
            continue

        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
        except Exception:
            continue

        col_map = {}
        for col in df.columns:
            lc = col.strip()
            if lc == "日期":     col_map[col] = "date"
            elif lc == "开盘":   col_map[col] = "open"
            elif lc == "收盘":   col_map[col] = "close"
            elif lc == "成交量": col_map[col] = "vol"
        df = df.rename(columns=col_map)

        needed = ["date", "open", "close", "vol"]
        if not all(c in df.columns for c in needed):
            continue

        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        for c in needed[1:]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=needed).query("close > 0").sort_values("date")
        df = df[df["date"] >= cutoff]
        if len(df) < 30:
            continue

        o, c, v = df["open"], df["close"], df["vol"]
        prev_c   = c.shift(1)
        hi28_o   = o.rolling(28, min_periods=1).max()
        lo28_o   = o.rolling(28, min_periods=1).min()
        o85      = lo28_o + 0.95 * (hi28_o - lo28_o)
        top15o   = (o >= o85).astype(float)
        fd15     = ((c < prev_c) & (c <= o) & (v >= 1.15 * v.shift(1))).astype(float)
        cnt28    = (top15o * fd15).rolling(28, min_periods=1).sum()

        # 成交额（百万）= 收盘价 × 成交量 / 1e6（BaoStock成交量单位为手=100股）
        amount_m = float(c.iloc[-1] * v.iloc[-1] * 100 / 1e6)

        rows.append({
            "stock_symbol": sym,
            "stock_code":   code,
            "stock_name":   name,
            "latest_date":  df["date"].max(),
            "cnt28":        float(cnt28.iloc[-1]) if len(cnt28) else np.nan,
            "close":        float(c.iloc[-1]),
            "amount_m":     amount_m,
        })

    if not rows:
        return pd.DataFrame()

    pool = pd.DataFrame(rows)
    pool = pool[pool["latest_date"] >= today - timedelta(days=10)]
    pool["is_clean"] = pool["cnt28"] == 0
    # 流动性过滤：干净池里再按成交额筛
    pool.loc[pool["is_clean"] & (pool["amount_m"] < MIN_AMOUNT_M), "is_clean"] = False
    return pool


# ── 主程序 ────────────────────────────────────────────────────────────── #

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.today().date()

    print(f"\n{'='*65}")
    print(f"热点板块选股信号 — {today}")
    print(f"{'='*65}\n")

    # Step 1: Factor A 干净池
    print("Step 1: 计算Factor A干净池...")
    pool = _build_clean_pool()
    clean = pool[pool["is_clean"]].copy()
    print(f"  全量股票: {len(pool)}  |  干净池(cnt28=0): {len(clean)}")
    clean_codes = set(clean["stock_code"].tolist())   # 6位纯数字

    # Step 2: 拉取近15日涨停历史
    print(f"\nStep 2: 获取近{HISTORY_DAYS}日涨停历史（建立板块→股票映射）...")
    zt_all, today_zt_codes = _get_zt_history(days_back=HISTORY_DAYS)

    if zt_all.empty:
        print("  [!] 无法获取涨停数据，退出")
        return None

    print(f"\n  历史涨停记录: {len(zt_all)} 条  |  今日涨停: {len(today_zt_codes)} 只")

    # Step 3: 识别热点板块（近5日涨停集中度）
    print(f"\nStep 3: 识别热点板块（近5日涨停集中）...")
    cutoff_5d = today - timedelta(days=7)   # ~5个交易日
    recent = zt_all[zt_all["date"] >= cutoff_5d]
    sector_heat = (recent.groupby("sector")
                   .agg(涨停次数=("stock_code","count"),
                        代表股=("stock_name", lambda x: "、".join(x.unique()[:5])))
                   .sort_values("涨停次数", ascending=False)
                   .reset_index())

    hot_sectors = sector_heat.head(TOP_SECTOR_N)["sector"].tolist()

    print(f"\n  近5日热点板块 Top {TOP_SECTOR_N}:")
    print(f"  {'板块':<16s} {'涨停次数':>6s}  代表股")
    print(f"  {'-'*60}")
    for _, row in sector_heat.head(TOP_SECTOR_N).iterrows():
        print(f"  {row['sector']:<16s} {int(row['涨停次数']):>6d}  {row['代表股']}")

    # Step 4: 建立板块→股票映射（15日覆盖更广）
    # 从15日历史涨停里，知道哪些股票属于哪个板块
    sector_stock_map: dict[str, set] = {}
    for _, row in zt_all.iterrows():
        s = str(row["sector"])
        if s not in sector_stock_map:
            sector_stock_map[s] = set()
        sector_stock_map[s].add(str(row["stock_code"]))

    # Step 5: 找热点板块 ∩ 干净池 ∩ 今日未涨停
    print(f"\nStep 4: 筛选「热点板块 × 干净池 × 未涨停」候选股...")

    candidates = []
    for sector in hot_sectors:
        sector_codes = sector_stock_map.get(sector, set())
        for code in sector_codes:
            if code not in clean_codes:
                continue
            if code in today_zt_codes:
                continue
            sym   = ("SH" + code) if code.startswith("6") else ("SZ" + code)
            row_c = clean[clean["stock_code"] == code]
            if row_c.empty:
                continue
            close_val  = float(row_c["close"].iloc[0])
            amount_val = float(row_c["amount_m"].iloc[0])
            # 优先用名称缓存，fallback 涨停历史
            name_val = row_c["stock_name"].iloc[0]
            if not name_val:
                nr = zt_all[zt_all["stock_code"] == code]
                name_val = str(nr["stock_name"].iloc[0]) if not nr.empty else code
            candidates.append({
                "stock_symbol": sym,
                "stock_code":   code,
                "stock_name":   name_val,
                "sector":       sector,
                "close":        close_val,
                "amount_m":     amount_val,
            })

    df_cand = (pd.DataFrame(candidates).drop_duplicates("stock_code")
               .sort_values("amount_m", ascending=False)
               if candidates else pd.DataFrame())

    # ── 输出 ──────────────────────────────────────────────────────────── #
    print(f"\n{'='*65}")
    print(f"候选股 — 热点板块 × 主板 × 干净 × 非ST × 今日未涨停 × 流动性>2亿")
    print(f"{'='*65}")

    if df_cand.empty:
        print("\n  暂无候选股")
    else:
        # 每个板块只展示成交额最大的3只（最易操作）
        print(f"\n  共 {len(df_cand)} 只（每板块展示成交额最大3只）\n")
        for sector in hot_sectors:
            sub = df_cand[df_cand["sector"] == sector].head(3)
            if sub.empty:
                continue
            print(f"  【{sector}】")
            print(f"  {'代码':<10s} {'名称':<10s} {'收盘':>7s}  {'日成交(亿)':>9s}")
            print(f"  {'-'*44}")
            for _, r in sub.iterrows():
                amt_yi = r["amount_m"] / 100
                print(f"  {r['stock_symbol']:<10s} {r['stock_name']:<10s} "
                      f"{r['close']:>7.2f}  {amt_yi:>8.1f}亿")
            print()

    zt_clean_ref = [c for c in today_zt_codes if c in clean_codes]

    # 保存
    out_clean = os.path.join(OUT_DIR, f"clean_pool_{today}.csv")
    clean[["stock_symbol","stock_code","cnt28","close"]].to_csv(
        out_clean, index=False, encoding="utf-8-sig")

    if not df_cand.empty:
        out_cand = os.path.join(OUT_DIR, f"hot_sector_picks_{today}.csv")
        df_cand.to_csv(out_cand, index=False, encoding="utf-8-sig")
        print(f"  候选股  → {out_cand}")
    print(f"  干净池  → {out_clean}")
    print(f"\n{'='*65}\n")

    return dict(
        today=today,
        sector_heat=sector_heat,
        df_cand=df_cand,
        zt_clean_ref=zt_clean_ref,
        zt_all=zt_all,
        clean_codes=clean_codes,
    )


# ── 钉钉推送 ──────────────────────────────────────────────────────────── #

def _ding_sign(webhook: str, secret: str) -> str:
    """HMAC-SHA256 加签，返回带时间戳+签名的完整 URL。"""
    ts = str(round(time.time() * 1000))
    msg = f"{ts}\n{secret}"
    sig = base64.b64encode(
        hmac.new(secret.encode(), msg.encode(), digestmod=hashlib.sha256).digest()
    )
    return f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(sig)}"


def _build_markdown(result: dict) -> tuple[str, str]:
    """构建钉钉 Markdown 消息（标题 + 正文）。"""
    today        = result["today"]
    sector_heat  = result["sector_heat"]
    df_cand      = result["df_cand"]
    zt_clean_ref = result["zt_clean_ref"]
    zt_all       = result["zt_all"]
    clean_codes  = result["clean_codes"]

    title = f"热点板块选股 {today} 葵花宝典"

    lines = [f"## 热点板块候选股 — {today}\n"]

    # 热点板块
    lines.append("### 近5日热点板块（涨停集中度）\n")
    for _, row in sector_heat.head(TOP_SECTOR_N).iterrows():
        lines.append(f"- **{row['sector']}** 涨停{int(row['涨停次数'])}次  {row['代表股']}")
    lines.append("")

    # 候选股（按板块，每板块最多3只，按成交额排序）
    if df_cand.empty:
        lines.append("### 候选股\n暂无符合条件的股票\n")
    else:
        hot_sectors = sector_heat.head(TOP_SECTOR_N)["sector"].tolist()
        shown_total = sum(min(3, len(df_cand[df_cand["sector"]==s])) for s in hot_sectors)
        lines.append(f"### 候选股（主板×干净×非ST×今日未涨停）Top{shown_total}\n")
        lines.append(f"| 代码 | 名称 | 收盘 | 日成交 | 板块 |")
        lines.append(f"|---|---|---|---|---|")
        for sector in hot_sectors:
            sub = df_cand[df_cand["sector"] == sector].head(3)
            for _, r in sub.iterrows():
                amt = f"{r['amount_m']/100:.1f}亿"
                lines.append(
                    f"| {r['stock_symbol']} | **{r['stock_name']}** "
                    f"| {r['close']:.2f} | {amt} | {sector} |"
                )
        lines.append("")

    # 今日涨停×干净（参考）
    if zt_clean_ref:
        lines.append(f"### 参考：今日涨停 × 干净池  {len(zt_clean_ref)}只（已发动）\n")
        shown = 0
        for code in zt_clean_ref[:8]:
            sym  = ("SH" + code) if code.startswith("6") else ("SZ" + code)
            name_rows = zt_all[zt_all["stock_code"] == code]
            name = str(name_rows["stock_name"].iloc[0]) if not name_rows.empty else ""
            lines.append(f"- {sym} {name}")
            shown += 1
        if len(zt_clean_ref) > shown:
            lines.append(f"- …共{len(zt_clean_ref)}只")
        lines.append("")

    lines.append("> 候选逻辑：板块近期有涨停（热度验证）+ 个股无出货信号(cnt28=0) + 今日未涨停（未追高）")
    lines.append("> 板块映射来自近15日涨停历史，手动确认走势后再操作")

    return title, "\n".join(lines)


def send_dingtalk(result: dict) -> bool:
    """同步推送到钉钉，读取 config.py 中的 Webhook/Secret。"""
    try:
        import requests
    except ImportError:
        print("  [!] pip install requests")
        return False

    try:
        from config import DINGTALK_WEBHOOK, DINGTALK_SECRET
    except ImportError:
        DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
        DINGTALK_SECRET  = os.environ.get("DINGTALK_SECRET", "")

    if not DINGTALK_WEBHOOK:
        print("  [!] DINGTALK_WEBHOOK 未配置（config.py 或环境变量），跳过推送")
        return False

    title, text = _build_markdown(result)
    url = _ding_sign(DINGTALK_WEBHOOK, DINGTALK_SECRET) if DINGTALK_SECRET else DINGTALK_WEBHOOK

    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"isAtAll": False},
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        body = resp.json()
        if body.get("errcode") == 0:
            print("  钉钉推送成功 OK")
            return True
        else:
            print(f"  钉钉推送失败: {body}")
            return False
    except Exception as e:
        print(f"  钉钉推送异常: {e}")
        return False


if __name__ == "__main__":
    push = "--push" in sys.argv
    result = main()
    if push and result:
        print("\n推送到钉钉...")
        send_dingtalk(result)
