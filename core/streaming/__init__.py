"""Kafka 流式行情管道。

    行情多源轮询 ──produce──► Kafka topic quotes.a-share ──consume──► 幂等落库 + 信号
                              (key=股票代码,分区内有序)      (手动提交 offset)

与仓里已有的 cron 批处理是互补关系：批处理管日频回测与研究，这条流管盘中的近实时观测。
两边共用同一套多源校验逻辑（core/realtime_market.py），避免两套价格口径。
"""
from .config import StreamConfig
from .schema import QuoteEvent, SchemaError, SCHEMA_VERSION
from .sink import IdempotentQuoteSink, SinkResult, dedupe_by_event_key
from .producer import QuoteProducer, build_events, ensure_topic
from .consumer import QuoteConsumer, ConsumeStats, decode_batch
from .lag import measure_lag, LagReport, PartitionLag, TopicNotVisible

__all__ = [
    "StreamConfig",
    "QuoteEvent", "SchemaError", "SCHEMA_VERSION",
    "IdempotentQuoteSink", "SinkResult", "dedupe_by_event_key",
    "QuoteProducer", "build_events", "ensure_topic",
    "QuoteConsumer", "ConsumeStats", "decode_batch",
    "measure_lag", "LagReport", "PartitionLag", "TopicNotVisible",
]
