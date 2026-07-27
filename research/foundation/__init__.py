"""
Foundation — 量化策略地基
============================
**强制规则**: 所有新策略必须 from research.foundation import ...
不允许直接读 panel/OHLCV, 不允许自己写 backtest 循环.

设计意图: 用 API 和异常硬性消除项目反复犯的错:
  1. 数据审计: DataBundle.load() 自动跑, 不通过抛异常
  2. 基准匹配: Benchmark.auto_for(universe), 错配抛 BenchmarkMismatch
  3. Random control: Backtest 必填 random_control 参数
  4. OOS 验证: train_test_split 强制保留 test 段不动

参考: CLAUDE.md "Backtest QC MANDATORY" 章节
"""
from .data import DataBundle, REPORT_DELAY_DAYS
from .universe import Universe, SizeTier, DEFAULT_MCAP_RANGES
from .costs import CostModel
from .benchmark import Benchmark, BenchmarkKind
from .strategies import Strategy, CrossSectionalStrategy, EventDrivenStrategy
from .backtest import Backtest, BacktestResult, PeriodResult
from .report import StandardReport
from .exceptions import (
    FoundationError,
    DataAuditFailure,
    BenchmarkMismatch,
    MissingRandomControl,
    InsufficientData,
    LookAheadBiasDetected,
)

__all__ = [
    "DataBundle", "REPORT_DELAY_DAYS",
    "Universe", "SizeTier", "DEFAULT_MCAP_RANGES",
    "CostModel",
    "Benchmark", "BenchmarkKind",
    "Strategy", "CrossSectionalStrategy", "EventDrivenStrategy",
    "Backtest", "BacktestResult", "PeriodResult",
    "StandardReport",
    "FoundationError", "DataAuditFailure", "BenchmarkMismatch",
    "MissingRandomControl", "InsufficientData", "LookAheadBiasDetected",
]
