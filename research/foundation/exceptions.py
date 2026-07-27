"""
Foundation 自定义异常 — 让错误显式且可识别
"""


class FoundationError(Exception):
    """所有 foundation 错误基类"""
    pass


class DataAuditFailure(FoundationError):
    """数据完整性审计未通过, 拒绝加载

    触发: OHLCV 覆盖率过低, panel 字段缺失, 复权一致性失败等.
    """
    pass


class BenchmarkMismatch(FoundationError):
    """基准与宇宙不匹配 (如小盘宇宙用 HS300)

    触发: Benchmark.validate_against(universe) 失败.
    """
    pass


class MissingRandomControl(FoundationError):
    """回测未指定 random_control, 拒绝执行

    触发: Backtest 调用时未显式传 random_control 参数.
    项目历史教训: 反复发生 alpha 虚高源于无对照基准.
    """
    pass


class InsufficientData(FoundationError):
    """样本量不足以做统计推断"""
    pass


class LookAheadBiasDetected(FoundationError):
    """检测到前视偏差"""
    pass
