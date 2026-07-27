"""
StandardReport — 模板化输出
==============================
固定格式的 backtest 报告: 让 alpha 数字总是带上对照、t-stat、净额.

每份报告必须包含:
  1. 元信息 (策略/宇宙/成本)
  2. Train/Test 分段统计 (强制 OOS 视角)
  3. Alpha 显著性 (t-stat, 胜率)
  4. 警告 (如 alpha vs random 显著但 t < 2)
  5. 最终判定 (✓ / ~ / ✗)
"""
from dataclasses import dataclass
from typing import Optional

from .backtest import BacktestResult


@dataclass
class StandardReport:
    """格式化 BacktestResult"""
    result: BacktestResult

    @classmethod
    def from_result(cls, result: BacktestResult) -> "StandardReport":
        return cls(result=result)

    def render(self) -> str:
        """返回 markdown 字符串"""
        r = self.result
        lines = []
        lines.append(f"# Backtest Report: {r.strategy_name}\n")
        lines.append(f"**宇宙**: {r.universe_desc}")
        lines.append(f"**成本**: {r.cost_desc}")
        lines.append(f"**期数**: {r.n_periods}")
        if r.train_test_split:
            lines.append(f"**OOS Split**: train ≤ {r.train_test_split[0]}  /  test ≥ {r.train_test_split[1]}")
        lines.append("")

        for label, summary in [("Train", r.train_summary),
                                ("Test", r.test_summary),
                                ("Full", r.full_summary)]:
            if not summary: continue
            lines.append(f"## {label} 段")
            lines.append(f"- 期数: {summary['n']}")
            lines.append(f"- 信号 gross 均值: {summary['signal_mean_gross']*100:+.2f}%/期")
            lines.append(f"- 信号 net 均值: {summary['signal_mean_net']*100:+.2f}%/期")
            lines.append(f"- 信号胜率 (>0): {summary['signal_win_pct']:.1f}%")
            if "alpha_mean" in summary:
                lines.append(f"- Random 对照 gross: {summary['random_mean_gross']*100:+.2f}%/期")
                lines.append(f"- **Alpha vs random**: {summary['alpha_mean']*100:+.2f}%/期")
                lines.append(f"- **t-stat**: {summary['t_stat']:.2f}")
                lines.append(f"- Alpha 胜率: {summary['alpha_win_pct']:.0f}%")
            if "alpha_ci_lo" in summary:
                lines.append(
                    f"- **Alpha CI95 (cluster bootstrap, {summary['alpha_n_clusters']} 簇)**: "
                    f"[{summary['alpha_ci_lo']*100:+.2f}%, {summary['alpha_ci_hi']*100:+.2f}%] "
                    f"p(>0)={summary['alpha_p_boot']:.4f}")
            if "frame_alpha_mean" in summary:
                lines.append(f"- Frame 对照 gross: {summary['frame_mean_gross']*100:+.2f}%/期")
                lines.append(f"- **Alpha vs frame**: {summary['frame_alpha_mean']*100:+.2f}%/期")
                if "frame_alpha_ci_lo" in summary:
                    lines.append(
                        f"- **Frame-alpha CI95**: [{summary['frame_alpha_ci_lo']*100:+.2f}%, "
                        f"{summary['frame_alpha_ci_hi']*100:+.2f}%] "
                        f"p(>0)={summary['frame_alpha_p_boot']:.4f}")
            lines.append("")

        # 判定
        lines.append("## 判定")
        s = r.test_summary if r.test_summary else r.full_summary
        if not s or "alpha_mean" not in s:
            lines.append("- 缺 random control 或样本不足, 无法判定 alpha")
        else:
            t = s["t_stat"]
            net_alpha = s["alpha_mean"]  # 同 alpha_net 因为成本两边都扣了
            if abs(t) > 3.5 and net_alpha > 0.005:
                lines.append("- ✓ **强信号**: t > 3.5 (Harvey 多重检验通过), net α > 0.5%/期")
            elif abs(t) > 2.0 and net_alpha > 0.005:
                lines.append("- ~ **弱信号**: 2 < |t| < 3.5, 经济意义存在但需谨慎")
            elif net_alpha < 0:
                lines.append("- ✗ **负 alpha**: 不可作系统策略")
            else:
                lines.append("- - **不显著**: |t| < 2 或 net α 接近 0")
            # v2: bootstrap CI 与朴素 t 冲突时以 CI 为准 (朴素 t 假设独立, 会虚高)
            if "alpha_boot_significant" in s:
                if abs(t) > 2.0 and not s["alpha_boot_significant"]:
                    lines.append(
                        "- ⚠ **朴素 t 显著但 cluster CI 含 0** — 期间相关性夸大了 t. "
                        "以 CI 为准: 不显著.")
            if "frame_alpha_mean" in s and "frame_alpha_boot_significant" in s:
                if not s["frame_alpha_boot_significant"] and s["frame_alpha_mean"] <= 0:
                    lines.append(
                        "- ⚠ **未击败朴素框架对照** — 即使 vs random 有 alpha, "
                        "也可能只是框架 beta (参见因子反向教训).")

        return "\n".join(lines)

    def print(self):
        print()
        print(self.render())

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.render())
