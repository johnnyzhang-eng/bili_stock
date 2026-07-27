"""
探查 AKShare 基本面数据源 — 找到最快、字段最全的批量接口
"""

import os
import sys
import time

# 关闭可能拖慢的系统代理
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
        print(f"  前2行:")
        print(df.head(2).to_string(max_colwidth=20))
        return df
    except Exception as e:
        print(f"  失败: {type(e).__name__}: {str(e)[:180]}")
        return None


def main():
    # 批量：东财业绩报表/业绩快报（按季度返回全A）
    probe("业绩报表批量(东财)", ak.stock_yjbb_em, date="20240930")
    probe("业绩快报批量(东财)", ak.stock_yjkb_em, date="20240930")

    # 单股财务指标
    probe("财务摘要(新浪)", ak.stock_financial_abstract, symbol="600519")
    probe("财务分析指标(新浪)", ak.stock_financial_analysis_indicator,
          symbol="600519", start_year="2022")
    probe("财务分析指标(东财)", ak.stock_financial_analysis_indicator_em,
          symbol="600519", indicator="按报告期")
    probe("财务摘要(同花顺)", ak.stock_financial_abstract_ths,
          symbol="600519", indicator="按报告期")

    # 估值：乐咕/eniu
    for fn_name in ["stock_a_lg_indicator", "stock_a_indicator", "stock_hk_indicator_eniu"]:
        if hasattr(ak, fn_name):
            probe(f"估值 {fn_name}", getattr(ak, fn_name), symbol="600519")

    # 实时行情（含 PE/PB/总市值）
    probe("实时行情(东财)", ak.stock_zh_a_spot_em)


if __name__ == "__main__":
    main()
