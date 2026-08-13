"""生产端：轮询多源行情 → 校验 → 投递到 Kafka。

复用已有的 RealTimePriceValidator（多源比价 / 中位数定价 / 涨跌幅与跳变检查），
Kafka 这一层只负责"把已校验的事件可靠地送出去"，不重复实现校验逻辑。

投递侧的两个选择：
- acks="all"：等所有同步副本确认，避免 leader 挂掉时丢已确认的消息。
- enable_idempotence=True：broker 端按 (producer_id, seq) 去重，
  网络重试不会在 topic 里留下重复消息。配合消费端的幂等落库，两头都不怕重放。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Iterable, Protocol, Sequence

from .config import StreamConfig
from .schema import QuoteEvent, SchemaError

logger = logging.getLogger(__name__)


class PriceSource(Protocol):
    """只要有这个方法就能当行情源，方便测试时塞假源、不打网络。"""

    async def get_verified_price(self, code: str) -> dict: ...


async def build_events(source: PriceSource, codes: Sequence[str]) -> list[QuoteEvent]:
    """并发取一轮价格，返回可投递的事件。

    单只股票失败不拖垮整轮：gather 收异常，逐个记日志后跳过。
    """
    results = await asyncio.gather(
        *(source.get_verified_price(c) for c in codes), return_exceptions=True
    )
    events: list[QuoteEvent] = []
    for code, res in zip(codes, results):
        if isinstance(res, BaseException):
            logger.warning("取价失败 %s: %s", code, res)
            continue
        if not isinstance(res, dict) or res.get("price") is None:
            logger.debug("跳过 %s：无可用价格（%s）", code, (res or {}).get("reason"))
            continue
        try:
            events.append(QuoteEvent.from_validator_result(code, res))
        except SchemaError as exc:
            logger.warning("组装事件失败 %s: %s", code, exc)
    return events


class QuoteProducer:
    """把行情事件投进 topic。key=股票代码，保证单只股票分区内有序。"""

    def __init__(self, config: StreamConfig | None = None, producer=None) -> None:
        self.config = config or StreamConfig()
        self._producer = producer          # 允许注入，测试时不连真 broker
        self._owns_producer = producer is None

    async def start(self) -> None:
        if self._producer is None:
            from aiokafka import AIOKafkaProducer

            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.config.bootstrap_servers,
                acks="all",
                enable_idempotence=True,
            )
            await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None and self._owns_producer:
            await self._producer.stop()
            self._producer = None

    async def __aenter__(self) -> "QuoteProducer":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def send_events(self, events: Iterable[QuoteEvent]) -> int:
        if self._producer is None:
            raise RuntimeError("producer 未启动，先 await start()")
        sent = 0
        for ev in events:
            await self._producer.send_and_wait(
                self.config.topic, ev.encode(), key=ev.key()
            )
            sent += 1
        return sent

    async def run_forever(
        self,
        source: PriceSource,
        codes: Sequence[str],
        max_rounds: int | None = None,
        should_stop: Callable[[], bool] | Callable[[], Awaitable[bool]] | None = None,
    ) -> int:
        """按 poll_interval_s 轮询投递。

        max_rounds 让测试能跑有限轮；生产上不传，靠 should_stop 或进程信号退出。
        """
        total = 0
        rounds = 0
        while max_rounds is None or rounds < max_rounds:
            events = await build_events(source, codes)
            if events:
                total += await self.send_events(events)
                logger.info("投递 %d 条（累计 %d）", len(events), total)
            rounds += 1
            if should_stop is not None:
                stop = should_stop()
                if asyncio.iscoroutine(stop):
                    stop = await stop
                if stop:
                    break
            if max_rounds is None or rounds < max_rounds:
                await asyncio.sleep(self.config.poll_interval_s)
        return total


class TopicMisconfigured(RuntimeError):
    """topic 的实际分区数和配置不符。"""


async def ensure_topic(config: StreamConfig) -> None:
    """建 topic（已存在则跳过），并核对分区数。

    为什么要显式建、还要回头核对：broker 默认开着 auto.create.topics.enable，
    一个打错的 topic 名会被**静默创建成 1 分区**（broker 默认 num.partitions=1）。
    这不会报任何错，但 key→partition 的分布从此塌成一个分区，
    "同一只股票分区内有序"这个前提就没了 —— 而且看日志、看消息数都完全正常。
    所以宁可在启动时炸掉，也不要带着一个坏掉的有序性跑下去。
    """
    from aiokafka.admin import AIOKafkaAdminClient, NewTopic

    admin = AIOKafkaAdminClient(bootstrap_servers=config.bootstrap_servers)
    await admin.start()
    try:
        try:
            await admin.create_topics(
                [NewTopic(config.topic, num_partitions=config.num_partitions,
                          replication_factor=config.replication_factor)]
            )
            logger.info("已建 topic %s（%d 分区）", config.topic, config.num_partitions)
        except Exception as exc:                  # TopicAlreadyExistsError 及其变体
            if "AlreadyExists" not in type(exc).__name__ and "already exists" not in str(exc).lower():
                raise
            logger.info("topic %s 已存在", config.topic)

        described = await admin.describe_topics([config.topic])
        actual = len(described[0].get("partitions", []))
        if actual != config.num_partitions:
            raise TopicMisconfigured(
                f"topic {config.topic!r} 实际有 {actual} 个分区，配置要求 {config.num_partitions} 个。"
                f"{'常见原因：topic 名打错，被 broker 自动建成了单分区。' if actual == 1 else ''}"
                f"分区数决定 key→partition 落点，不一致会破坏同一只股票的分区内有序。"
            )
    finally:
        await admin.close()
