"""消费滞后监控。

lag = 分区末端 offset − 消费组已提交 offset。它回答的是"我们落后行情多少条"，
是这条管道唯一真正重要的健康指标：进程活着、日志不报错、lag 却在单调上涨，
说明消费速度追不上生产速度，最终表现为信号越来越晚。

注意 committed 可能是 None（该分区还没提交过任何 offset），
此时不能当 0 算——那会把"从没消费过"报成"滞后等于全部数据"，
在刚建组时误报一次巨大 lag。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import StreamConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PartitionLag:
    partition: int
    end_offset: int
    committed: int | None

    @property
    def lag(self) -> int | None:
        if self.committed is None:
            return None
        return max(0, self.end_offset - self.committed)


class TopicNotVisible(RuntimeError):
    """拿不到 topic 的分区信息。

    单独立一个异常而不是返回空报告：空报告的 total_lag 是 0，
    调用方会把"我什么都没看见"读成"一切正常"。监控瞎掉必须比滞后更响。
    """


@dataclass(frozen=True)
class LagReport:
    topic: str
    group_id: str
    partitions: tuple[PartitionLag, ...]

    @property
    def total_lag(self) -> int:
        return sum(p.lag or 0 for p in self.partitions)

    @property
    def uncommitted_partitions(self) -> tuple[int, ...]:
        return tuple(p.partition for p in self.partitions if p.committed is None)

    def format(self) -> str:
        lines = [f"topic={self.topic} group={self.group_id} total_lag={self.total_lag}"]
        for p in sorted(self.partitions, key=lambda x: x.partition):
            shown = "未提交过" if p.lag is None else str(p.lag)
            lines.append(f"  p{p.partition}: end={p.end_offset} committed={p.committed} lag={shown}")
        return "\n".join(lines)


async def _partitions_for(consumer, topic: str) -> set[int] | None:
    """拿 topic 的分区号集合。

    这里不能用 `consumer.partitions_for_topic()`：一个没订阅任何 topic 的 consumer，
    它的本地元数据缓存里就没有这个 topic，实测**永远返回 None**——
    `topics()` 能看见 topic 名、`partitions_for_topic` 照样是 None，
    连 `force_metadata_update()` 都不填（客户端只跟踪它"感兴趣"的 topic）。
    `fetch_all_metadata()` 返回的是一份新的 cluster 元数据对象，直接问它才拿得到。

    走这条路而不是订阅 topic，是因为订阅会让这个 consumer 加入消费组、
    触发一次 rebalance —— 监控绝不该扰动被监控的对象。
    """
    if hasattr(consumer, "_client") and hasattr(consumer._client, "fetch_all_metadata"):
        metadata = await consumer._client.fetch_all_metadata()
        return metadata.partitions_for_topic(topic)
    # 注入的假 consumer（测试用）只需实现这两个方法
    if hasattr(consumer, "topics"):
        await consumer.topics()
    return consumer.partitions_for_topic(topic)


async def measure_lag(config: StreamConfig | None = None, consumer=None) -> LagReport:
    """量一次 lag。

    用一个和线上同 group_id 的 consumer 去读 committed —— 只读不消费，
    不会动到真实消费进度（没有 poll，也就不会触发自动位移）。
    """
    config = config or StreamConfig()
    owns = consumer is None
    if consumer is None:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            bootstrap_servers=config.bootstrap_servers,
            group_id=config.group_id,
            enable_auto_commit=False,
        )
        await consumer.start()

    try:
        from aiokafka.structs import TopicPartition

        parts = await _partitions_for(consumer, config.topic)
        if not parts:
            raise TopicNotVisible(
                f"读不到 topic {config.topic!r} 的分区信息（topic 不存在，或 broker "
                f"{config.bootstrap_servers} 不可达）——这不是 lag=0"
            )

        tps = [TopicPartition(config.topic, p) for p in sorted(parts)]
        end_offsets = await consumer.end_offsets(tps)

        rows: list[PartitionLag] = []
        for tp in tps:
            committed = await consumer.committed(tp)
            rows.append(
                PartitionLag(
                    partition=tp.partition,
                    end_offset=int(end_offsets[tp]),
                    committed=None if committed is None else int(committed),
                )
            )
        return LagReport(config.topic, config.group_id, tuple(rows))
    finally:
        if owns:
            await consumer.stop()
