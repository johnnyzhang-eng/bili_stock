"""流式行情管道的测试。

绝大多数用例不需要 Kafka —— 它们测的是"我们自己写的那部分"：envelope 版本校验、
幂等去重、offset 提交顺序、lag 计算。需要真 broker 的集成用例单独标记，
没有 KAFKA_BOOTSTRAP 时自动跳过，这样 CI 里不装 Kafka 也能跑绿。
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.streaming.config import StreamConfig
from core.streaming.consumer import QuoteConsumer, ConsumeStats, decode_batch
from core.streaming.lag import LagReport, PartitionLag, TopicNotVisible, measure_lag
from core.streaming.producer import QuoteProducer, build_events, TopicMisconfigured
from core.streaming.schema import QuoteEvent, SchemaError, SCHEMA_VERSION
from core.streaming.sink import IdempotentQuoteSink, dedupe_by_event_key


def make_event(code="600000", price=10.0, ts="2026-01-01T00:00:00+00:00") -> QuoteEvent:
    return QuoteEvent(
        code=code, price=price, quote_ts=ts, ingest_ts=ts,
        is_valid=True, quality_score=100.0, sources=("Sina", "Tencent"),
    )


# ---------------------------------------------------------------- schema

def test_event_roundtrip_preserves_fields():
    ev = make_event()
    got = QuoteEvent.decode(ev.encode())
    assert got == ev


def test_partition_key_is_stock_code():
    # 分区 key 必须只由代码决定，否则同一只股票会散到不同分区、失去有序性
    a = make_event(price=10.0).key()
    b = make_event(price=99.0, ts="2026-06-06T00:00:00+00:00").key()
    assert a == b == b"600000"


def test_decode_rejects_unknown_schema_version():
    raw = make_event().encode().replace(b'"v":1', b'"v":99')
    with pytest.raises(SchemaError, match="不支持的 schema 版本"):
        QuoteEvent.decode(raw)


def test_decode_rejects_missing_fields():
    with pytest.raises(SchemaError, match="缺字段"):
        QuoteEvent.decode(b'{"v":1,"code":"600000"}')


def test_decode_rejects_non_json():
    with pytest.raises(SchemaError):
        QuoteEvent.decode(b"not json at all")


def test_from_validator_result_refuses_missing_price():
    with pytest.raises(SchemaError):
        QuoteEvent.from_validator_result("600000", {"price": None, "is_valid": False})


def test_from_validator_result_carries_quality_fields():
    ev = QuoteEvent.from_validator_result(
        "600519",
        {"price": 1600.5, "is_valid": True, "quality_score": 80.0,
         "source_names": ["Sina"], "pre_close": 1590.0},
    )
    assert (ev.code, ev.price, ev.quality_score, ev.sources) == ("600519", 1600.5, 80.0, ("Sina",))
    assert ev.v == SCHEMA_VERSION


# ---------------------------------------------------------------- sink 幂等

def test_sink_writes_then_dedupes_on_replay(tmp_path):
    """核心保证：至少一次投递 + 幂等落库 = 重放不产生重复行。"""
    sink = IdempotentQuoteSink(str(tmp_path / "q.db"))
    batch = [make_event(ts="2026-01-01T00:00:00+00:00"),
             make_event(ts="2026-01-01T00:00:01+00:00")]

    first = sink.write_batch(batch)
    assert (first.written, first.duplicates) == (2, 0)
    assert sink.count() == 2

    replay = sink.write_batch(batch)          # 模拟 commit 前崩溃后的重放
    assert (replay.written, replay.duplicates) == (0, 2)
    assert sink.count() == 2                  # 行数没变，这才叫幂等
    sink.close()


def test_sink_emits_signal_only_on_threshold_move(tmp_path):
    sink = IdempotentQuoteSink(str(tmp_path / "q.db"), signal_move_pct=1.0)
    sink.write_batch([make_event(price=10.0, ts="2026-01-01T00:00:00+00:00")])

    small = sink.write_batch([make_event(price=10.05, ts="2026-01-01T00:00:01+00:00")])  # +0.5%
    assert small.signals == ()

    big = sink.write_batch([make_event(price=10.5, ts="2026-01-01T00:00:02+00:00")])     # +4.5%
    assert len(big.signals) == 1 and big.signals[0][0] == "600000"
    sink.close()


def test_sink_replay_does_not_duplicate_signals(tmp_path):
    """重放不能把同一次跳变重复通知——否则一次崩溃会给用户发两遍。"""
    sink = IdempotentQuoteSink(str(tmp_path / "q.db"), signal_move_pct=1.0)
    sink.write_batch([make_event(price=10.0, ts="2026-01-01T00:00:00+00:00")])
    batch = [make_event(price=11.0, ts="2026-01-01T00:00:01+00:00")]

    assert len(sink.write_batch(batch).signals) == 1
    assert sink.write_batch(batch).signals == ()
    assert sink.count("quote_signals") == 1
    sink.close()


def test_sink_batch_is_atomic_on_failure(tmp_path):
    """整批要么全落、要么全不落；半落地会让 offset 与数据对不上。"""
    sink = IdempotentQuoteSink(str(tmp_path / "q.db"))
    bad = make_event(ts="2026-01-01T00:00:01+00:00")
    object.__setattr__(bad, "price", object())      # 绕过 frozen，制造写入期异常

    with pytest.raises(Exception):
        sink.write_batch([make_event(ts="2026-01-01T00:00:00+00:00"), bad])
    assert sink.count() == 0                        # 前一条也回滚了
    sink.close()


def test_dedupe_by_event_key_keeps_last():
    a = make_event(price=10.0)
    b = make_event(price=11.0)                      # 同 code 同 quote_ts
    assert dedupe_by_event_key([a, b]) == [b]


def test_sink_latest_returns_most_recent(tmp_path):
    sink = IdempotentQuoteSink(str(tmp_path / "q.db"))
    sink.write_batch([
        make_event(price=10.0, ts="2026-01-01T00:00:00+00:00"),
        make_event(price=12.0, ts="2026-01-01T00:00:05+00:00"),
    ])
    assert sink.latest("600000") == ("2026-01-01T00:00:05+00:00", 12.0)
    assert sink.latest("999999") is None
    sink.close()


# ---------------------------------------------------------------- producer

class FakeSource:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def get_verified_price(self, code):
        self.calls.append(code)
        out = self.results[code]
        if isinstance(out, Exception):
            raise out
        return out


def test_build_events_skips_failures_and_missing_prices():
    source = FakeSource({
        "600000": {"price": 10.0, "is_valid": True, "quality_score": 100.0},
        "000001": {"price": None, "is_valid": False, "reason": "所有数据源均不可用"},
        "600519": RuntimeError("网络超时"),
    })
    events = asyncio.run(build_events(source, ["600000", "000001", "600519"]))
    # 一只失败不能拖垮整轮
    assert [e.code for e in events] == ["600000"]


class FakeKafkaProducer:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, value, key=None):
        self.sent.append((topic, key, value))


def test_producer_sends_with_code_as_key():
    fake = FakeKafkaProducer()
    cfg = StreamConfig(topic="t.test")
    producer = QuoteProducer(cfg, producer=fake)
    asyncio.run(producer.send_events([make_event(), make_event(code="000001")]))
    assert [k for _, k, _ in fake.sent] == [b"600000", b"000001"]
    assert {t for t, _, _ in fake.sent} == {"t.test"}


def test_producer_run_forever_respects_max_rounds():
    fake = FakeKafkaProducer()
    cfg = StreamConfig(topic="t.test", poll_interval_s=0.001)
    source = FakeSource({"600000": {"price": 10.0, "is_valid": True, "quality_score": 100.0}})
    sent = asyncio.run(
        QuoteProducer(cfg, producer=fake).run_forever(source, ["600000"], max_rounds=3)
    )
    assert sent == 3 and len(fake.sent) == 3


# ---------------------------------------------------------------- consumer

class FakeMsg:
    def __init__(self, value):
        self.value = value


class FakeKafkaConsumer:
    """记录 getmany / commit 的调用顺序，用来断言"先落库后提交"。"""

    def __init__(self, batches):
        self.batches = list(batches)
        self.commits = 0
        self.events = []

    async def getmany(self, timeout_ms=None, max_records=None):
        self.events.append("getmany")
        return self.batches.pop(0) if self.batches else {}

    async def commit(self):
        self.events.append("commit")
        self.commits += 1


def test_decode_batch_skips_poison_without_raising():
    good = make_event().encode()
    events, poison = decode_batch([good, b"garbage", good.replace(b'"v":1', b'"v":7')])
    assert len(events) == 1 and poison == 2


def test_consumer_commits_after_sink_write(tmp_path):
    sink = IdempotentQuoteSink(str(tmp_path / "q.db"))
    fake = FakeKafkaConsumer([{"tp": [FakeMsg(make_event().encode())]}])
    consumer = QuoteConsumer(StreamConfig(), sink=sink, consumer=fake)

    stats = asyncio.run(consumer.consume_once())
    assert (stats.polled, stats.written, stats.commits) == (1, 1, 1)
    assert fake.events == ["getmany", "commit"]      # 顺序就是语义
    sink.close()


def test_consumer_does_not_commit_when_sink_fails(tmp_path):
    """落库炸了就不能提交 offset，否则这批数据永远丢了。"""

    class ExplodingSink(IdempotentQuoteSink):
        def write_batch(self, events):
            raise RuntimeError("磁盘满了")

    sink = ExplodingSink(str(tmp_path / "q.db"))
    fake = FakeKafkaConsumer([{"tp": [FakeMsg(make_event().encode())]}])
    consumer = QuoteConsumer(StreamConfig(), sink=sink, consumer=fake)

    with pytest.raises(RuntimeError, match="磁盘满了"):
        asyncio.run(consumer.consume_once())
    assert fake.commits == 0
    assert "commit" not in fake.events
    sink.close()


def test_consumer_empty_batch_does_not_commit(tmp_path):
    sink = IdempotentQuoteSink(str(tmp_path / "q.db"))
    fake = FakeKafkaConsumer([{}])
    stats = asyncio.run(QuoteConsumer(StreamConfig(), sink=sink, consumer=fake).consume_once())
    assert (stats.polled, fake.commits) == (0, 0)
    sink.close()


def test_consumer_poison_only_batch_still_commits(tmp_path):
    """整批都是坏消息也要提交，否则一条脏数据会把分区永久卡死。"""
    sink = IdempotentQuoteSink(str(tmp_path / "q.db"))
    fake = FakeKafkaConsumer([{"tp": [FakeMsg(b"garbage")]}])
    stats = asyncio.run(QuoteConsumer(StreamConfig(), sink=sink, consumer=fake).consume_once())
    assert (stats.poison, stats.written, fake.commits) == (1, 0, 1)
    sink.close()


# ---------------------------------------------------------------- lag

def test_lag_treats_never_committed_as_unknown_not_zero():
    report = LagReport("t", "g", (
        PartitionLag(0, end_offset=100, committed=90),
        PartitionLag(1, end_offset=50, committed=None),
    ))
    assert report.partitions[0].lag == 10
    assert report.partitions[1].lag is None          # 不能报成 50
    assert report.total_lag == 10
    assert report.uncommitted_partitions == (1,)


def test_lag_never_negative():
    # committed 可能短暂超过我们读到的 end_offset，不该出现负 lag
    assert PartitionLag(0, end_offset=10, committed=12).lag == 0


def test_measure_lag_raises_instead_of_reporting_zero_when_topic_invisible():
    """看不见 topic 时必须炸，不能返回一个 total_lag=0 的空报告。

    这条是自检里真抓出来的 bug：监控自己瞎了却报"健康"，
    比报出滞后危险得多，因为没人会去查一个绿色的指标。
    """

    class BlindConsumer:
        async def topics(self):
            return set()

        def partitions_for_topic(self, topic):
            return None

        async def stop(self):
            pass

    with pytest.raises(TopicNotVisible, match="这不是 lag=0"):
        asyncio.run(measure_lag(StreamConfig(topic="ghost.topic"), consumer=BlindConsumer()))


# ---------------------------------------------------------------- config

def test_config_rejects_bad_values():
    with pytest.raises(ValueError):
        StreamConfig(num_partitions=0)
    with pytest.raises(ValueError):
        StreamConfig(poll_interval_s=0)
    with pytest.raises(ValueError):
        StreamConfig(signal_move_pct=-1)


def test_config_reads_env(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP", "broker:19092")
    monkeypatch.setenv("KAFKA_QUOTE_TOPIC", "custom.topic")
    cfg = StreamConfig()
    assert (cfg.bootstrap_servers, cfg.topic) == ("broker:19092", "custom.topic")


# ---------------------------------------------------------------- 集成（需真 broker）

requires_kafka = pytest.mark.skipif(
    not os.environ.get("KAFKA_BOOTSTRAP"),
    reason="需要真实 Kafka；设 KAFKA_BOOTSTRAP=localhost:9092 后启用",
)


@requires_kafka
def test_end_to_end_through_real_broker(tmp_path):
    """真 broker 上跑一遍 投递→消费→落库→重放，验证端到端不重不丢。"""
    from datetime import datetime, timezone
    from core.streaming.producer import ensure_topic

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    cfg = StreamConfig(
        topic=f"itest.quotes.{stamp}", group_id=f"itest.group.{stamp}",
        num_partitions=2, poll_interval_s=0.01, consumer_batch_timeout_ms=4000,
        sink_db_path=str(tmp_path / "itest.db"),
    )

    async def run():
        await ensure_topic(cfg)
        events = [make_event(code="600000", price=10.0, ts="2026-01-01T00:00:00+00:00"),
                  make_event(code="000001", price=20.0, ts="2026-01-01T00:00:00+00:00")]
        async with QuoteProducer(cfg) as p:
            assert await p.send_events(events) == 2

        sink = IdempotentQuoteSink(cfg.sink_db_path, cfg.signal_move_pct)
        try:
            async with QuoteConsumer(cfg, sink=sink) as c:
                stats = ConsumeStats()
                for _ in range(4):
                    await c.consume_once(stats)
                    if stats.polled >= 2:
                        break
            assert stats.polled == 2 and stats.written == 2 and stats.poison == 0
            assert sink.count() == 2
            assert sink.write_batch(events).written == 0      # 重放去重
            assert sink.count() == 2
        finally:
            sink.close()

        report = await measure_lag(cfg)
        assert report.total_lag == 0                          # 全部消费完，无滞后

        # 正向对照：只投不消费，lag 必须涨起来。
        # 没有这一步的话，"lag=0" 可能只是监控根本没在看——自检里真踩过这个坑。
        async with QuoteProducer(cfg) as p:
            await p.send_events([
                make_event(code="600000", price=10.0, ts=f"2026-01-02T00:00:0{i}+00:00")
                for i in range(3)
            ])
        lagged = await measure_lag(cfg)
        assert lagged.total_lag == 3, f"预期滞后 3 条，实际 {lagged.total_lag}"

    asyncio.run(run())


@requires_kafka
def test_ensure_topic_rejects_wrong_partition_count():
    """topic 已存在但分区数不对时必须炸。

    对应的真实故障：broker 默认开着 auto.create.topics.enable，
    打错 topic 名会被静默建成 1 分区，有序性坏掉但一切看起来正常。
    """
    from datetime import datetime, timezone
    from core.streaming.producer import TopicMisconfigured, ensure_topic

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    topic = f"itest.partmismatch.{stamp}"

    async def run():
        await ensure_topic(StreamConfig(topic=topic, num_partitions=2))   # 先按 2 分区建好
        with pytest.raises(TopicMisconfigured, match="分区"):
            await ensure_topic(StreamConfig(topic=topic, num_partitions=5))  # 再按 5 分区要它

    asyncio.run(run())
