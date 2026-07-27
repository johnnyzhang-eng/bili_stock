"""
股票名称缓存工具
用法：
    from research.factors_v2.stock_names import get_name, get_name_map
    name = get_name("600036")   # -> "招商银行"
"""

import os, sys
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE_DIR = os.path.join(ROOT, "data", "market_cache")
CACHE_FILE = os.path.join(CACHE_DIR, "stock_names.csv")


def refresh_names() -> pd.DataFrame:
    """从 AKShare 拉取全量A股名称并缓存。"""
    import akshare as ak
    df = ak.stock_info_a_code_name()          # 列: 代码, 名称
    df.columns = ["code", "name"]
    df["code"] = df["code"].astype(str).str.zfill(6)
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")
    return df


def get_name_map(force_refresh: bool = False) -> dict[str, str]:
    """返回 {6位代码: 股票名称} 字典。"""
    if not force_refresh and os.path.exists(CACHE_FILE):
        df = pd.read_csv(CACHE_FILE, encoding="utf-8-sig", dtype=str)
    else:
        df = refresh_names()
    df["code"] = df["code"].str.zfill(6)
    return dict(zip(df["code"], df["name"]))


def get_name(code: str, name_map: dict | None = None) -> str:
    """根据6位代码查名称，查不到返回代码本身。"""
    m = name_map if name_map is not None else get_name_map()
    return m.get(str(code).zfill(6), code)


def is_st(name: str) -> bool:
    """判断是否ST/退市股（名称含ST、*ST、退）。"""
    n = name.upper()
    return "ST" in n or "退" in n


if __name__ == "__main__":
    print("刷新股票名称缓存...")
    df = refresh_names()
    print(f"共 {len(df)} 只，已保存 -> {CACHE_FILE}")
    print(df.head(5).to_string(index=False))
