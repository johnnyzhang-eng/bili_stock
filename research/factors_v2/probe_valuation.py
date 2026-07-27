"""
探查 PE/PB/股息率/市值 数据源
===================================
yjbb_em 没有估值数据，需要单独抓。
目标：找到历史日频或月频的批量估值接口。
"""

import os
import sys
import time

for k in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import akshare as ak
import pandas as pd


def probe(name, fn, *args, **kwargs):
    print(f"\n{'='*70}\n【{name}】  ak.{fn.__name__}({args}, {kwargs})\n{'='*70}")
    t0 = time.time()
    try:
        df = fn(*args, **kwargs)
        dt = time.time() - t0
        if df is None or len(df) == 0:
            print(f"  空结果 ({dt:.1f}s)"); return None
        print(f"  {len(df)} 行 × {len(df.columns)} 列  耗时 {dt:.1f}s")
        print(f"  列名: {list(df.columns)}")
        print(f"  前2行:"); print(df.head(2).to_string(max_colwidth=18))
        return df
    except Exception as e:
        print(f"  失败: {type(e).__name__}: {str(e)[:160]}")
        return None


def main():
    # 单股历史估值 (乐咕 Legu)
    for fn_name in ["stock_a_lg_indicator", "stock_a_indicator", "stock_a_indicator_lg"]:
        if hasattr(ak, fn_name):
            probe(f"历史估值 {fn_name}", getattr(ak, fn_name), symbol="600519")

    # 新浪 / 东财 个股估值
    for fn_name in ["stock_value_em", "stock_a_pe_em", "stock_a_pb_em"]:
        if hasattr(ak, fn_name):
            probe(f"估值 {fn_name}", getattr(ak, fn_name))

    # 股息历史
    for fn_name in ["stock_fhps_em", "stock_history_dividend", "stock_dividend_cninfo"]:
        if hasattr(ak, fn_name):
            probe(f"分红 {fn_name}", getattr(ak, fn_name))

    # 实时行情 (含 PE/PB) 重试
    probe("实时行情东财", ak.stock_zh_a_spot_em)


if __name__ == "__main__":
    main()
