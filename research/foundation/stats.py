"""
stats — cluster bootstrap 统计层
=================================
**设计意图**: _finalize 的朴素 t-stat 假设期间独立。cross-sectional 季度信号
勉强成立; event-driven 完全不成立 — 涨停潮事件全部聚集在同几个交易日,
同日事件收益高度相关, 朴素 SE 把 N 个相关观测当 N 个独立观测, t-stat 被
系统性夸大 (方向与项目史上 5 个引擎 bug 一致: 全部朝 alpha 高估偏)。

修复: cluster bootstrap — 以 signal_date (自然日) 为聚类单元重抽, 保留
同日相关结构。B=10,000, percentile CI + 单边 p。

来源: 该模式在 polyFIFA2026 随机对照审计中验证 (Tier 2/Tier 3, 2026-06,
以 match-date 为 cluster), 此处移植回家。

用法:
    from research.foundation.stats import cluster_bootstrap_mean
    r = cluster_bootstrap_mean(alpha_values, cluster_keys)   # keys = signal dates
    r.mean, r.ci_lo, r.ci_hi, r.p_gt_zero, r.naive_t, r.n_clusters
"""
from dataclasses import dataclass
from typing import Sequence, Hashable

import numpy as np


DEFAULT_B = 10_000


@dataclass
class ClusterBootstrapResult:
    mean: float
    ci_lo: float                # percentile 2.5%
    ci_hi: float                # percentile 97.5%
    p_gt_zero: float            # 单边 p: P(bootstrap mean <= 0); 小 → mean 显著 > 0
    n_obs: int
    n_clusters: int
    naive_t: float              # 朴素 t (假设独立), 仅供对比
    cluster_size_max: int       # 最大单簇观测数 — 诊断聚集程度

    @property
    def significant_95(self) -> bool:
        """CI 不含 0 (双边 95%)"""
        return self.ci_lo > 0 or self.ci_hi < 0

    def describe(self) -> str:
        return (f"mean={self.mean*100:+.3f}% CI95=[{self.ci_lo*100:+.3f}%, "
                f"{self.ci_hi*100:+.3f}%] p(>0)={self.p_gt_zero:.4f} "
                f"n={self.n_obs} clusters={self.n_clusters} "
                f"naive_t={self.naive_t:.2f} max_cluster={self.cluster_size_max}")


def cluster_bootstrap_mean(values: Sequence[float],
                           clusters: Sequence[Hashable],
                           n_iter: int = DEFAULT_B,
                           seed: int = 0) -> ClusterBootstrapResult:
    """按 cluster 重抽估计均值分布.

    Args:
        values: 观测值 (如 per-period alpha)
        clusters: 与 values 等长的聚类键 (如 signal_date). 同键观测在重抽时
                  整簇进出, 保留簇内相关.
        n_iter: bootstrap 次数
        seed: 随机种子 (可复现)
    """
    v = np.asarray(values, dtype=float)
    c = np.asarray(clusters)
    if v.shape[0] != c.shape[0]:
        raise ValueError(f"values ({v.shape[0]}) 与 clusters ({c.shape[0]}) 长度不一致")
    mask = ~np.isnan(v)
    v, c = v[mask], c[mask]
    if v.size < 2:
        raise ValueError(f"有效观测不足 (n={v.size}), 无法 bootstrap")

    unique_clusters = np.unique(c)
    n_clusters = unique_clusters.size
    if n_clusters < 2:
        raise ValueError(f"聚类数不足 (clusters={n_clusters}), 无法 cluster bootstrap")

    # 预分组 — 避免每次迭代重新过滤
    groups = {key: v[c == key] for key in unique_clusters}
    sizes = {key: g.size for key, g in groups.items()}

    observed = float(v.mean())
    naive_se = float(v.std(ddof=1) / np.sqrt(v.size))
    naive_t = observed / naive_se if naive_se > 0 else float("nan")

    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_iter, dtype=float)
    for i in range(n_iter):
        sampled = rng.choice(unique_clusters, size=n_clusters, replace=True)
        total, count = 0.0, 0
        for key in sampled:
            g = groups[key]
            total += g.sum()
            count += g.size
        boot_means[i] = total / count if count else np.nan

    boot_means = boot_means[~np.isnan(boot_means)]
    ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])
    p_gt_zero = float((boot_means <= 0).mean())

    return ClusterBootstrapResult(
        mean=observed,
        ci_lo=float(ci_lo),
        ci_hi=float(ci_hi),
        p_gt_zero=p_gt_zero,
        n_obs=int(v.size),
        n_clusters=int(n_clusters),
        naive_t=naive_t,
        cluster_size_max=int(max(sizes.values())),
    )


def self_test(n_seeds: int = 30) -> None:
    """合成数据自检 — 框架变更后必跑 (research/foundation/self_test.py 调用).

    单 seed 断言 "NULL 不显著" 在统计上就错 5% 的时间 (95% CI 定义如此),
    所以这里断言的是多 seed 的**拒绝率**:

    D1: 独立零均值噪音 → 拒绝率 ≈ 5% (断言 ≤ 20%)
    D2: 同簇强相关零均值 → 朴素 t 拒绝率虚高 (>30%), cluster CI 拒绝率正常 (≤20%)
        这正是 event-driven 涨停潮的结构 — 本测试证明 stats 层修复了它.
    D3: 真信号 (mean=1%, sd=0.5%, n=100) → 检验力: 拒绝率 ≥ 95%
    """
    d1_reject = d2_naive_reject = d2_cluster_reject = d3_reject = 0
    d2_last = None

    for s in range(n_seeds):
        rng = np.random.default_rng(1000 + s)

        # D1 独立 NULL
        v1 = rng.normal(0, 0.02, size=200)
        r1 = cluster_bootstrap_mean(v1, np.arange(200), n_iter=1000, seed=s)
        d1_reject += int(r1.significant_95)

        # D2 聚集 NULL: 20 簇 × 30 观测共享簇效应 (朴素 SE 被低估 ~sqrt(30) 倍)
        n_clusters, per = 20, 30
        cluster_effect = rng.normal(0, 0.03, size=n_clusters)
        v2 = np.concatenate([
            cluster_effect[k] + rng.normal(0, 0.002, size=per)
            for k in range(n_clusters)
        ])
        c2 = np.repeat(np.arange(n_clusters), per)
        r2 = cluster_bootstrap_mean(v2, c2, n_iter=1000, seed=s)
        d2_naive_reject += int(abs(r2.naive_t) > 2)
        d2_cluster_reject += int(r2.significant_95)
        d2_last = r2

        # D3 真信号
        v3 = rng.normal(0.01, 0.005, size=100)
        r3 = cluster_bootstrap_mean(v3, np.arange(100), n_iter=1000, seed=s)
        d3_reject += int(r3.significant_95 and r3.ci_lo > 0)

    d1_rate = d1_reject / n_seeds
    d2_naive_rate = d2_naive_reject / n_seeds
    d2_cluster_rate = d2_cluster_reject / n_seeds
    d3_rate = d3_reject / n_seeds

    assert d1_rate <= 0.20, f"D1 FAIL: 独立 NULL 拒绝率 {d1_rate:.0%} > 20%"
    assert d2_naive_rate > 0.30, (
        f"D2 FAIL: 聚集 NULL 朴素 t 拒绝率仅 {d2_naive_rate:.0%} — "
        f"合成数据没有产生预期的 t 虚高, 测试本身失效")
    assert d2_cluster_rate <= 0.20, f"D2 FAIL: 聚集 NULL cluster 拒绝率 {d2_cluster_rate:.0%} > 20%"
    assert d3_rate >= 0.95, f"D3 FAIL: 真信号检验力仅 {d3_rate:.0%} < 95%"

    print(f"  [D] stats.py cluster bootstrap 自检 ({n_seeds} seeds): PASS")
    print(f"      D1 独立 NULL 拒绝率:       {d1_rate:.0%}  (期望 ~5%, 上限 20%)")
    print(f"      D2 聚集 NULL 朴素 t 误判率: {d2_naive_rate:.0%}  ← 朴素法的系统性 alpha 虚报")
    print(f"      D2 聚集 NULL cluster 拒绝率: {d2_cluster_rate:.0%}  (修复后, 上限 20%)")
    print(f"      D3 真信号检验力:            {d3_rate:.0%}  (下限 95%)")
    if d2_last is not None:
        print(f"      D2 样例: {d2_last.describe()}")


if __name__ == "__main__":
    self_test()
