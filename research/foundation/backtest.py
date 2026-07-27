"""
Backtest — 强制 random control 的统一回测引擎
================================================
**设计意图**: random_control 是必填参数, 没传直接报错. 这是项目反复犯错的根因.
              execution_mode 和 live_capital_enabled 从类型上阻止 live 交易,
              强制 foundation 只做 research/paper.

API 示例:
    bt = Backtest(
        strategy=my_strategy,
        universe=uni,
        cost_model=CostModel.a_share_retail_quarterly(),
        random_control=True,                        # 必填!
        train_test_split=("2010-01-01", "2018-06-30"),  # OOS 必填
        n_random_repeats=30,
        seed=42,
    )
    result = bt.run()
    result.report.print()
"""
import warnings
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Literal
import datetime as dt

import numpy as np
import pandas as pd

from .data import DataBundle, REPORT_DELAY_DAYS
from .universe import Universe
from .strategies import Strategy, CrossSectionalStrategy, EventDrivenStrategy
from .costs import CostModel
from .exceptions import MissingRandomControl, InsufficientData
from .stats import cluster_bootstrap_mean


REQUIRED_RANDOM_CONTROL_DOC = """
random_control 必须显式指定 (True 或 False).

True 表示自动生成同宇宙随机对照组 (推荐).
False 表示明确放弃对照 (仅用于诊断, 不可作生产策略).

如果你不知道选哪个, 选 True. 这条规则源自项目历史:
反转信号曾经因为没跑 random control, alpha 虚高 +5pp 被识别.
""".strip()


@dataclass
class PeriodResult:
    """单个回测期的结果"""
    period_label: str               # '2017Q1' 或 'event_2017-03-15'
    signal_date: pd.Timestamp
    fwd_date: pd.Timestamp
    universe_size: int
    signal_picks: List[str]
    signal_ret_gross: float
    signal_ret_net: float
    random_ret_gross: Optional[float]   # None 如 random_control=False
    random_ret_net: Optional[float]
    alpha_gross: Optional[float]
    alpha_net: Optional[float]
    # v2 (2026-07-02): naive frame control — 策略必须击败它的"最笨版本"
    # 教训来源: polyFIFA2026 Tier 3 — 策略赢了同宇宙随机对照 (Tier 2 PASS),
    # 却输给朴素框架 (尾盘买 favorite); 本项目因子反向 (Top30 0.7% vs
    # Bottom30 7.5%) 是同一类幻觉, 手工发现花了数月.
    frame_ret_gross: Optional[float] = None
    frame_alpha_gross: Optional[float] = None   # signal - frame


@dataclass
class BacktestResult:
    """回测全部结果"""
    strategy_name: str
    universe_desc: str
    cost_desc: str
    n_periods: int
    train_test_split: Optional[Tuple[str, str]]

    train_periods: List[PeriodResult]
    test_periods: List[PeriodResult]

    # 在 finalize() 时填充
    train_summary: Dict = field(default_factory=dict)
    test_summary: Dict = field(default_factory=dict)
    full_summary: Dict = field(default_factory=dict)

    # Patch from WW-shan: execution mode tracking
    execution_mode: str = "research"
    live_capital_enabled: bool = False


# ── Backtest 引擎 ────────────────────────────────────────────────────────────
class Backtest:
    """
    Args:
        strategy: Strategy 实例
        universe: Universe 实例 (含 DataBundle)
        cost_model: CostModel 实例
        random_control: True 强制内置随机对照, False 明确放弃 (须给 reason)
        random_control_reason: 当 random_control=False 时, 必须给理由 (留痕)
        train_test_split: (train_end, test_start) 元组. 强制 OOS 拆分.
        n_random_repeats: 每期 random control 重抽次数. 默认 1.
            **重要**: >1 会把 random 噪音平均掉, 系统性抬高 t-stat (alpha 方差只剩
            signal 一侧). 1 = 单次抽样, alpha_i = sig_i - rand_i 带完整噪音, t-stat
            真实. 如果想做稳健性检查, 请用不同 seed 跑多次完整 backtest 取均值, 而
            不是把 n_random_repeats 调高.
        frame_control: 可选的"朴素框架对照"策略 (CrossSectionalStrategy).
            random control 回答 "策略比随机选股强吗"; frame control 回答
            "策略比它的最笨版本强吗" — 后者才能识破"框架 beta 假扮选择 alpha"
            (polyFIFA2026 Tier 3 / 本项目因子反向都是这类). 例: double_low
            排名的 frame 是"等权全部转债". Cycle 003 起新策略建议必传.
        year_start, year_end: 回测年份范围
        seed: 随机种子
    """
    def __init__(self,
                 strategy: Strategy,
                 universe: Universe,
                 cost_model: CostModel,
                 random_control,                         # bool, 必填
                 random_control_reason: Optional[str] = None,
                 train_test_split: Optional[Tuple[str, str]] = None,
                 n_random_repeats: int = 1,
                 frame_control: Optional[Strategy] = None,
                 year_start: int = 2017,
                 year_end: int = 2025,
                 seed: int = 42,
                 # Patch from WW-shan: type-level dry-run enforcement
                 execution_mode: Literal["research", "paper"] = "research",
                 live_capital_enabled: Literal[False] = False):
        # 强制 random_control 显式
        if not isinstance(random_control, bool):
            raise MissingRandomControl(REQUIRED_RANDOM_CONTROL_DOC)
        if random_control is False and not random_control_reason:
            raise MissingRandomControl(
                "选择 random_control=False 必须提供 random_control_reason. " +
                REQUIRED_RANDOM_CONTROL_DOC
            )

        # Runtime defense-in-depth: foundation 不做 live
        assert live_capital_enabled is False, (
            "Foundation is research-only. Live trading must go through a separate "
            "execution layer with its own audit pipeline."
        )

        # frame_control 目前只支持 cross-sectional (event-driven 的"朴素框架"
        # 是另一个事件检测器, 语义不同, 后续版本支持)
        if frame_control is not None and frame_control.kind() != "cross_sectional":
            raise ValueError(
                "frame_control 目前仅支持 CrossSectionalStrategy. "
                f"收到: {frame_control.kind()}")
        if frame_control is not None and strategy.kind() != "cross_sectional":
            raise ValueError("frame_control 需要主策略也是 cross_sectional.")
        self.frame_control = frame_control

        self.strategy = strategy
        self.universe = universe
        self.cost_model = cost_model
        self.random_control = random_control
        self.random_control_reason = random_control_reason
        self.train_test_split = train_test_split
        self.n_random_repeats = n_random_repeats
        self.year_start = year_start
        self.year_end = year_end
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.execution_mode = execution_mode
        self.live_capital_enabled = live_capital_enabled

    def run(self, verbose: bool = True) -> BacktestResult:
        """主回测流程"""
        if verbose:
            self._print_header()

        if self.strategy.kind() == "cross_sectional":
            results = self._run_cross_sectional(verbose=verbose)
        else:
            results = self._run_event_driven(verbose=verbose)

        # 拆 train/test
        train, test = self._split_train_test(results)

        backtest_result = BacktestResult(
            strategy_name=self.strategy.name,
            universe_desc=self.universe.describe(),
            cost_desc=self.cost_model.describe(),
            n_periods=len(results),
            train_test_split=self.train_test_split,
            train_periods=train,
            test_periods=test,
            execution_mode=self.execution_mode,
            live_capital_enabled=self.live_capital_enabled,
        )
        self._finalize(backtest_result)
        return backtest_result

    def _print_header(self):
        print("=" * 80)
        print(f"  Backtest: {self.strategy.name}")
        print("=" * 80)
        print(f"  策略类型: {self.strategy.kind()}")
        print(f"  宇宙:    {self.universe.describe()}")
        print(f"  成本:    {self.cost_model.describe()}")
        print(f"  Execution mode: {self.execution_mode}", end="")
        print(f"  (live_capital_enabled={self.live_capital_enabled})")
        print(f"  Random control: {self.random_control}", end="")
        if not self.random_control:
            print(f"  (理由: {self.random_control_reason})")
        else:
            print(f"  ({self.n_random_repeats} 次重抽)")
        if self.train_test_split:
            print(f"  Train/Test: <= {self.train_test_split[0]} / >= {self.train_test_split[1]}")
        print()

    # ── Cross-sectional 回测 ──────────────────────────────────────────────────
    def _run_cross_sectional(self, verbose: bool) -> List[PeriodResult]:
        s: CrossSectionalStrategy = self.strategy
        results = []
        # 季度信号日
        Q_MONTH = [3, 6, 9, 12]; Q_DAY = [31, 30, 30, 31]
        for yr in range(self.year_start, self.year_end):
            for q in [1, 2, 3, 4]:
                rpt_date = pd.Timestamp(yr, Q_MONTH[q-1], Q_DAY[q-1])
                sig_date = self.universe.data.get_signal_date(rpt_date)
                fwd_date = sig_date + pd.Timedelta(days=s.hold_days)

                universe_df = self.universe.at(rpt_date, sig_date)
                if len(universe_df) < 50: continue

                # 信号组
                picks = s.select(universe_df, self.universe.data.price_cache, sig_date)
                if not picks: continue
                sig_ret = self._portfolio_fwd_ret(picks, sig_date, fwd_date)
                if np.isnan(sig_ret): continue

                # Random control
                # B2: n_random_repeats=1 (默认) → 单次抽样, alpha 带真实噪音, t-stat 不被夸大
                # B4: 从 universe 里排除 picks 后再抽 (避免 random 与 signal 重叠)
                rand_ret = None
                if self.random_control:
                    pool = universe_df[~universe_df["code"].isin(picks)]
                    rand_returns = []
                    for i in range(self.n_random_repeats):
                        rng = np.random.default_rng(self.seed + yr*4 + q + i*100)
                        n_picks = min(len(picks), len(pool))
                        if n_picks <= 0: break
                        rand_codes = rng.choice(pool["code"].values,
                                                 size=n_picks, replace=False).tolist()
                        rr = self._portfolio_fwd_ret(rand_codes, sig_date, fwd_date)
                        if not np.isnan(rr): rand_returns.append(rr)
                    rand_ret = float(np.mean(rand_returns)) if rand_returns else None

                # Frame control: 同宇宙跑"最笨版本"策略
                frame_ret = None
                if self.frame_control is not None:
                    frame_picks = self.frame_control.select(
                        universe_df, self.universe.data.price_cache, sig_date)
                    if frame_picks:
                        fr = self._portfolio_fwd_ret(frame_picks, sig_date, fwd_date)
                        if not np.isnan(fr):
                            frame_ret = fr

                cost = self.cost_model.total_round_trip
                pr = PeriodResult(
                    period_label=f"{yr}Q{q}",
                    signal_date=sig_date,
                    fwd_date=fwd_date,
                    universe_size=len(universe_df),
                    signal_picks=picks,
                    signal_ret_gross=sig_ret,
                    signal_ret_net=sig_ret - cost,
                    random_ret_gross=rand_ret,
                    random_ret_net=(rand_ret - cost) if rand_ret is not None else None,
                    alpha_gross=(sig_ret - rand_ret) if rand_ret is not None else None,
                    alpha_net=(sig_ret - rand_ret) if rand_ret is not None else None,
                    frame_ret_gross=frame_ret,
                    frame_alpha_gross=(sig_ret - frame_ret) if frame_ret is not None else None,
                )
                results.append(pr)
                if verbose:
                    a = f" α={pr.alpha_gross*100:+.2f}%" if pr.alpha_gross is not None else ""
                    print(f"  {pr.period_label}  uni={len(universe_df):>4}  "
                          f"picks={len(picks):>3}  sig={sig_ret*100:>+5.2f}%{a}")
        return results

    # ── Event-driven 回测 ─────────────────────────────────────────────────────
    def _run_event_driven(self, verbose: bool) -> List[PeriodResult]:
        s: EventDrivenStrategy = self.strategy
        events_dict = s.detect_events(self.universe.data.price_cache)
        if verbose:
            print(f"  检测到事件: {sum(len(v) for v in events_dict.values())} 个")

        # 每个事件 → 1 个 PeriodResult (短线特殊)
        results = []
        cost = self.cost_model.total_round_trip
        for code, idx_list in events_dict.items():
            df = self.universe.data.price_cache.get(code)
            if df is None: continue
            for idx in idx_list:
                # entry
                if s.entry_at == "today_close":
                    if idx >= len(df): continue
                    entry = df.iloc[idx]["close"]
                    entry_date = df.iloc[idx]["date"]
                    t_off = 0
                elif s.entry_at == "next_open":
                    if idx + 1 >= len(df): continue
                    entry = df.iloc[idx + 1].get("open", df.iloc[idx + 1]["close"])
                    entry_date = df.iloc[idx + 1]["date"]
                    t_off = 1
                else:
                    continue
                # exit at close of (idx + hold_days). 与 legacy limit_up_strategies.py 一致:
                #   entry=today_close, hold=1: 信号日尾盘抢板, 次日 close 卖 → 1 夜.
                #   entry=next_open,   hold=1: 次日开盘买, 次日 close 卖 → 当日 day-trade.
                # 两条都是 idx + hold_days 的 close.
                exit_idx = idx + s.hold_days
                if exit_idx >= len(df): continue
                if s.exit_at == "next_close":
                    exit_p = df.iloc[exit_idx]["close"]
                elif s.exit_at == "next_open":
                    exit_p = df.iloc[exit_idx].get("open", df.iloc[exit_idx]["close"])
                else:
                    exit_p = df.iloc[exit_idx]["close"]
                gross = exit_p / entry - 1

                # Random baseline: 同股+随机非事件日 (排除事件 ±10日)
                rand_ret = None
                if self.random_control:
                    rand_ret = self._event_random_baseline(code, idx_list, df, s, idx)

                pr = PeriodResult(
                    period_label=f"event_{code}_{entry_date.strftime('%Y%m%d')}",
                    signal_date=entry_date,
                    fwd_date=df.iloc[exit_idx]["date"],
                    universe_size=1,
                    signal_picks=[code],
                    signal_ret_gross=gross,
                    signal_ret_net=gross - cost,
                    random_ret_gross=rand_ret,
                    random_ret_net=(rand_ret - cost) if rand_ret is not None else None,
                    alpha_gross=(gross - rand_ret) if rand_ret is not None else None,
                    alpha_net=(gross - rand_ret) if rand_ret is not None else None,
                )
                results.append(pr)
        return results

    def _event_random_baseline(self, code, event_idxs, df, strategy, current_idx,
                                exclude_window=10,
                                same_regime_window=90) -> Optional[float]:
        """B3 修复: candidates 限制在 ±same_regime_window 个交易日内, 控制市场环境差异."""
        n = len(df)
        excluded = set()
        for ei in event_idxs:
            for o in range(-exclude_window, exclude_window + 1):
                excluded.add(ei + o)
        lo = max(20, current_idx - same_regime_window)
        hi = min(n - strategy.hold_days - 2, current_idx + same_regime_window)
        candidates = [i for i in range(lo, hi) if i not in excluded]
        if len(candidates) < max(self.n_random_repeats, 5): return None
        rng = np.random.default_rng(self.seed + current_idx)
        # n_random_repeats=1 → 单次抽样 (alpha 带完整噪音, t-stat 真实)
        sample_size = min(self.n_random_repeats, len(candidates))
        picks = rng.choice(candidates, size=sample_size, replace=False)
        rets = []
        for idx in picks:
            t_off = 1 if strategy.entry_at == "next_open" else 0
            entry = (df.iloc[idx + 1].get("open", df.iloc[idx + 1]["close"])
                      if t_off == 1 else df.iloc[idx]["close"])
            exit_idx = idx + strategy.hold_days   # B1 修复: 与主路径一致
            if exit_idx >= n: continue
            exit_p = df.iloc[exit_idx]["close"]
            if entry > 0:
                rets.append(exit_p / entry - 1)
        return float(np.mean(rets)) if rets else None

    # ── 工具: 投资组合前向收益 (等权) ──────────────────────────────────────
    def _portfolio_fwd_ret(self, codes: List[str],
                            start_date: pd.Timestamp,
                            end_date: pd.Timestamp) -> float:
        rets = []
        for c in codes:
            ep = self.universe.data.get_price_at(c, start_date)
            xp = self.universe.data.get_price_at(c, end_date)
            if ep and xp and ep > 0:
                rets.append(xp / ep - 1)
        return float(np.mean(rets)) if rets else float("nan")

    # ── Train/Test 拆分 ───────────────────────────────────────────────────────
    def _split_train_test(self, results: List[PeriodResult],
                           min_gap_days: int = 60) -> Tuple[List, List]:
        """
        拆 train/test, 加 gap_days 防 feature look-ahead.

        Args:
            min_gap_days: 期望 train 与 test 之间的最小间隔天数 (默认 60).
                         短于此值抛 warning (不是 error), 因为旧代码按 0 天 gap 工作.
        """
        if not self.train_test_split:
            return results, []
        train_end = pd.Timestamp(self.train_test_split[0])
        test_start = pd.Timestamp(self.train_test_split[1])
        train = [r for r in results if r.signal_date <= train_end]
        test  = [r for r in results if r.signal_date >= test_start]

        # Patch from WW-shan: gap_days 防滚动窗口因子 look-ahead
        gap_days = (test_start - train_end).days
        if gap_days < min_gap_days:
            warnings.warn(
                f"Train/test 间隔仅 {gap_days} 天 (建议 ≥ {min_gap_days} 天). "
                f"滚动窗口因子 (如 60 日动量) 可能泄漏未来信息到 train 段.",
                UserWarning, stacklevel=2,
            )

        return train, test

    # ── Summary stats ─────────────────────────────────────────────────────────
    def _finalize(self, br: BacktestResult):
        for label, periods, target in [
            ("train", br.train_periods, br.train_summary),
            ("test",  br.test_periods,  br.test_summary),
            ("full",  br.train_periods + br.test_periods, br.full_summary),
        ]:
            if not periods: continue
            sig_gross = np.array([p.signal_ret_gross for p in periods])
            sig_net   = np.array([p.signal_ret_net for p in periods])
            target["n"] = len(periods)
            target["signal_mean_gross"] = float(sig_gross.mean())
            target["signal_mean_net"] = float(sig_net.mean())
            target["signal_win_pct"] = float((sig_gross > 0).mean() * 100)

            if self.random_control:
                rand_gross = np.array([p.random_ret_gross for p in periods if p.random_ret_gross is not None])
                alpha_pairs = [(p.alpha_gross, p.signal_date) for p in periods
                               if p.alpha_gross is not None]
                alpha = np.array([a for a, _ in alpha_pairs])
                if len(alpha) >= 2:
                    target["random_mean_gross"] = float(rand_gross.mean())
                    target["alpha_mean"] = float(alpha.mean())
                    target["alpha_std"] = float(alpha.std(ddof=1))
                    se = alpha.std(ddof=1) / np.sqrt(len(alpha))
                    target["t_stat"] = float(alpha.mean() / se) if se > 0 else float("nan")
                    target["alpha_win_pct"] = float((alpha > 0).mean() * 100)

                    # v2 (2026-07-02): cluster bootstrap by signal 自然日.
                    # 朴素 t 假设期间独立 — event-driven 同日事件强相关时被夸大
                    # (self_test D2: 聚集 NULL 朴素 t 误判率 70%). CI 才是可信推断.
                    try:
                        dates = [pd.Timestamp(d).normalize() for _, d in alpha_pairs]
                        cb = cluster_bootstrap_mean(alpha, dates, seed=self.seed)
                        target["alpha_ci_lo"] = cb.ci_lo
                        target["alpha_ci_hi"] = cb.ci_hi
                        target["alpha_p_boot"] = cb.p_gt_zero
                        target["alpha_n_clusters"] = cb.n_clusters
                        target["alpha_boot_significant"] = cb.significant_95
                    except ValueError:
                        pass  # 样本/聚类不足: 保留朴素统计, 不给 CI

            if self.frame_control is not None:
                frame_pairs = [(p.frame_alpha_gross, p.signal_date) for p in periods
                               if p.frame_alpha_gross is not None]
                if len(frame_pairs) >= 2:
                    fa = np.array([a for a, _ in frame_pairs])
                    target["frame_mean_gross"] = float(np.array(
                        [p.frame_ret_gross for p in periods
                         if p.frame_ret_gross is not None]).mean())
                    target["frame_alpha_mean"] = float(fa.mean())
                    try:
                        fdates = [pd.Timestamp(d).normalize() for _, d in frame_pairs]
                        fcb = cluster_bootstrap_mean(fa, fdates, seed=self.seed)
                        target["frame_alpha_ci_lo"] = fcb.ci_lo
                        target["frame_alpha_ci_hi"] = fcb.ci_hi
                        target["frame_alpha_p_boot"] = fcb.p_gt_zero
                        target["frame_alpha_boot_significant"] = fcb.significant_95
                    except ValueError:
                        pass
