"""
Foundation 补丁回归测试 (Patch 1-2 from WW-shan)
=================================================
独立于 self_test.py (不加载全量数据), 只验证新加的逻辑.
"""
import sys, os, warnings
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pandas as pd
import numpy as np

from research.foundation.backtest import Backtest, BacktestResult, PeriodResult
from research.foundation.data import DataBundle
from research.foundation.exceptions import LookAheadBiasDetected


# ── helpers ──────────────────────────────────────────────────────────────────
class FakeStrategy:
    """模拟 Strategy, 不依赖数据"""
    def __init__(self):
        self.name = "FakeStrategy"
    def kind(self):
        return "cross_sectional"


class FakeUniverse:
    def __init__(self):
        pass
    def describe(self):
        return "FakeUniverse"
    def at(self, *a, **kw):
        return pd.DataFrame()


class FakeCostModel:
    def __init__(self):
        self.total_round_trip = 0.001
    def describe(self):
        return "FakeCost"


# ── Patch 1: execution_mode / live_capital_enabled ───────────────────────────

class TestExecutionMode:

    def test_research_default(self):
        """默认 execution_mode='research'"""
        bt = Backtest(
            strategy=FakeStrategy(),
            universe=FakeUniverse(),
            cost_model=FakeCostModel(),
            random_control=True,
            random_control_reason="test",
        )
        assert bt.execution_mode == "research"
        assert bt.live_capital_enabled is False

    def test_paper_allowed(self):
        """execution_mode='paper' 不抛异常"""
        bt = Backtest(
            strategy=FakeStrategy(),
            universe=FakeUniverse(),
            cost_model=FakeCostModel(),
            random_control=True,
            random_control_reason="test",
            execution_mode="paper",
        )
        assert bt.execution_mode == "paper"

    def test_live_capital_assertion_runtime_defense(self):
        """通过 type: ignore 传 live_capital_enabled=True → runtime AssertionError"""
        with pytest.raises(AssertionError, match="research-only"):
            Backtest(
                strategy=FakeStrategy(),
                universe=FakeUniverse(),
                cost_model=FakeCostModel(),
                random_control=True,
                random_control_reason="test",
                live_capital_enabled=True,  # type: ignore
            )

    def test_backtest_result_carries_mode(self):
        """BacktestResult 携带 execution_mode + live_capital_enabled"""
        result = BacktestResult(
            strategy_name="test",
            universe_desc="test",
            cost_desc="test",
            n_periods=0,
            train_test_split=None,
            train_periods=[],
            test_periods=[],
            execution_mode="paper",
            live_capital_enabled=False,
        )
        assert result.execution_mode == "paper"
        assert result.live_capital_enabled is False


# ── Patch 2: gap_days + train_test_split warning ─────────────────────────────

class TestTrainTestSplit:

    def _make_backtest(self):
        return Backtest(
            strategy=FakeStrategy(),
            universe=FakeUniverse(),
            cost_model=FakeCostModel(),
            random_control=True,
            random_control_reason="test",
            train_test_split=("2020-12-31", "2021-01-01"),
        )

    def test_short_gap_warns(self):
        """train/test 间隔 1 天 < min_gap_days=60 → warning"""
        bt = self._make_backtest()
        results = [
            PeriodResult(
                period_label="p1", signal_date=pd.Timestamp("2020-12-31"),
                fwd_date=pd.Timestamp("2021-01-04"), universe_size=100,
                signal_picks=[], signal_ret_gross=0.01,
                signal_ret_net=0.009, random_ret_gross=0.0,
                random_ret_net=-0.001, alpha_gross=0.01, alpha_net=0.01,
            ),
            PeriodResult(
                period_label="p2", signal_date=pd.Timestamp("2021-01-01"),
                fwd_date=pd.Timestamp("2021-01-05"), universe_size=100,
                signal_picks=[], signal_ret_gross=0.02,
                signal_ret_net=0.019, random_ret_gross=0.0,
                random_ret_net=-0.001, alpha_gross=0.02, alpha_net=0.02,
            ),
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            train, test = bt._split_train_test(results, min_gap_days=60)
            gap_warnings = [x for x in w if "间隔" in str(x.message)]
            assert len(gap_warnings) >= 1, "应抛 gap 不足 warning"
            assert len(train) == 1
            assert len(test) == 1

    def test_long_gap_clean(self):
        """train/test 间隔 100 天 > min_gap_days → 无 warning"""
        bt = Backtest(
            strategy=FakeStrategy(),
            universe=FakeUniverse(),
            cost_model=FakeCostModel(),
            random_control=True,
            random_control_reason="test",
            train_test_split=("2020-09-01", "2021-01-01"),
        )
        results = [
            PeriodResult(
                period_label="p1", signal_date=pd.Timestamp("2020-09-01"),
                fwd_date=pd.Timestamp("2020-09-04"), universe_size=100,
                signal_picks=[], signal_ret_gross=0.01,
                signal_ret_net=0.009, random_ret_gross=0.0,
                random_ret_net=-0.001, alpha_gross=0.01, alpha_net=0.01,
            ),
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            train, test = bt._split_train_test(results, min_gap_days=60)
            gap_warnings = [x for x in w if "间隔" in str(x.message)]
            assert len(gap_warnings) == 0, f"不应有 warning: {[str(x.message) for x in gap_warnings]}"


# ── assert_no_feature_lookahead ─────────────────────────────────────────────

class TestFeatureLookahead:

    def test_normal_factor_does_not_raise(self):
        """因子值与自身 shift(1) 不高度相关 → no-op"""
        np.random.seed(42)
        n = 500
        panel = pd.DataFrame({
            "code": ["A"] * n,
            "report_date": pd.date_range("2020-01-01", periods=n, freq="D"),
            "factor": np.random.randn(n) * 0.1,
        })
        # 加一个微弱的自相关, 但不超阈值
        panel["factor"] += panel.groupby("code")["factor"].shift(1).fillna(0) * 0.3
        DataBundle.assert_no_feature_lookahead(panel, "factor")  # should not raise

    def test_forward_lookahead_raises(self):
        """因子高度自相关 (>0.95) 表示很可能有前视"""
        np.random.seed(42)
        n = 500
        base = np.random.randn(n).cumsum()  # 随机游走, 天然高自相关
        df = pd.DataFrame({
            "code": ["A"] * n,
            "report_date": pd.date_range("2020-01-01", periods=n, freq="D"),
            "factor": base,
        })
        with pytest.raises(LookAheadBiasDetected, match="前视"):
            DataBundle.assert_no_feature_lookahead(df, "factor", threshold=0.99)

    def test_short_data_skips(self):
        """数据太少 (< 100) 跳过检测"""
        panel = pd.DataFrame({
            "code": ["A"] * 10,
            "report_date": pd.date_range("2020-01-01", periods=10, freq="D"),
            "factor": range(10),
        })
        DataBundle.assert_no_feature_lookahead(panel, "factor")  # should not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
