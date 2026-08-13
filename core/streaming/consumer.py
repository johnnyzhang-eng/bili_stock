"""消费端：拉批 → 幂等落库 → 成功后才手动提交 offset。

提交顺序是这个模块唯一重要的事：**先落库、后提交**。
反过来（自动提交 / 先提交后落库）在进程崩溃时会丢数据——offset 已经前进，
但那批数据从没写进库，而且永远不会被重放。所以 enable_auto_commit 必须是 False。

坏消息（decode 失败）不能卡住整个分区：单独计数并跳过，
否则一条脏数据会让消费组永远停在同一个 offset 上。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import StreamConfig
from .schema import QuoteEvent, SchemaError
from .sink import IdempotentQuoteSink, SinkResult, dedupe_by_event_key

logger = logging.getLogger(__name__)


@dataclass
class ConsumeStats:
    polled: int = 0
    written: int = 0
    duplicates: int = 0
    poison: int = 0
    commits: int = 0
    signals: list[tuple[str, float]] = field(default_factory=list)

    def merge(self, result: SinkResult) -> None:
        self.written += result.written
        self.duplicates += result.duplicates
        self.signals.extend(result.signals)


def decode_batch(raw_values: list[bytes]) -> tuple[list[QuoteEvent], int]:
    """解一批消息，返回 (可用事件, 坏消息数)。坏消息跳过而不是抛出。"""
    events: list[QuoteEvent] = []
    poison = 0
    for raw in raw_values:
        try:
            events.append(QuoteEvent.decode(raw))
        except SchemaError as exc:
            poison += 1
            logger.warning("跳过坏消息: %s", exc)
    return events, poison


class QuoteConsumer:
    """至少一次投递 + 幂等落库 = 端到端不重不丢。"""

    def __init__(
        self,
        config: StreamConfig | None = None,
        sink: IdempotentQuoteSink | None = None,
        consumer=None,
    ) -> None:
        self.config = config or StreamConfig()
        self.sink = sink or IdempotentQuoteSink(
            self.config.sink_db_path, self.config.signal_move_pct
        )
        self._consumer = consumer
        self._owns_consumer = consumer is None

    async def start(self) -> None:
        if self._consumer is None:
            from aiokafka import AIOKafkaConsumer

            self._consumer = AIOKafkaConsumer(
                self.config.topic,
                bootstrap_servers=self.config.bootstrap_servers,
                group_id=self.config.group_id,
                enable_auto_commit=False,          # 关键：提交由我们自己控制
                auto_offset_reset="earliest",
            )
            await self._consumer.start()

    async def stop(self) -> None:
        if self._consumer is not None and self._owns_consumer:
            await self._consumer.stop()
            self._consumer = None

    async def __aenter__(self) -> "QuoteConsumer":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def consume_once(self, stats: ConsumeStats | None = None) -> ConsumeStats:
        """拉一批、落库、提交。返回本批统计。"""
        if self._consumer is None:
            raise RuntimeError("consumer 未启动，先 await start()")
        stats = stats or ConsumeStats()

        batch = await self._consumer.getmany(
            timeout_ms=self.config.consumer_batch_timeout_ms,
            max_records=self.config.consumer_max_records,
        )
        raw_values = [msg.value for msgs in batch.values() for msg in msgs]
        if not raw_values:
            return stats
        stats.polled += len(raw_values)

        events, poison = decode_batch(raw_values)
        stats.poison += poison
        if events:
            stats.merge(self.sink.write_batch(dedupe_by_event_key(events)))

        # 只有落库成功走到这里才提交；上面抛异常则 offset 原地不动，这批会被重放
        await self._consumer.commit()
        stats.commits += 1
        return stats

    async def run(self, max_batches: int | None = None) -> ConsumeStats:
        stats = ConsumeStats()
        batches = 0
        while max_batches is None or batches < max_batches:
            await self.consume_once(stats)
            batches += 1
        return stats
