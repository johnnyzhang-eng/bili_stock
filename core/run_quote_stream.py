"""流式行情管道的命令行入口。

    python -m core.run_quote_stream topic                      # 建 topic
    python -m core.run_quote_stream produce --codes 600000,000001 --rounds 5
    python -m core.run_quote_stream consume --batches 3
    python -m core.run_quote_stream lag                        # 看消费滞后
    python -m core.run_quote_stream selftest                   # 不打网络的端到端自检

selftest 用内置的假行情源跑通"投递→消费→落库→重放去重"，
用来验证管道本身；真实行情要走 produce（需要能访问新浪/腾讯行情接口）。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from core.streaming import (
    ConsumeStats,
    IdempotentQuoteSink,
    QuoteConsumer,
    QuoteProducer,
    StreamConfig,
    TopicNotVisible,
    ensure_topic,
    measure_lag,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("quote_stream")

DEFAULT_CODES = ["600000", "000001", "600519"]


def _parse_codes(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_CODES
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    if not codes:
        raise SystemExit("--codes 解析后为空")
    return codes


async def cmd_topic(args: argparse.Namespace) -> int:
    await ensure_topic(StreamConfig())
    return 0


async def cmd_produce(args: argparse.Namespace) -> int:
    from core.realtime_market import get_market_validator

    config = StreamConfig()
    await ensure_topic(config)
    codes = _parse_codes(args.codes)
    async with QuoteProducer(config) as producer:
        total = await producer.run_forever(
            get_market_validator(), codes, max_rounds=args.rounds
        )
    logger.info("共投递 %d 条事件", total)
    return 0


async def cmd_consume(args: argparse.Namespace) -> int:
    config = StreamConfig()
    with IdempotentQuoteSink(config.sink_db_path, config.signal_move_pct) as sink:
        async with QuoteConsumer(config, sink=sink) as consumer:
            stats = await consumer.run(max_batches=args.batches)
    logger.info(
        "拉取 %d 条｜新写 %d｜去重 %d｜坏消息 %d｜提交 %d 次｜信号 %d 条",
        stats.polled, stats.written, stats.duplicates, stats.poison,
        stats.commits, len(stats.signals),
    )
    for code, move in stats.signals[:10]:
        logger.info("  信号 %s 变动 %.2f%%", code, move)
    return 0


async def cmd_lag(args: argparse.Namespace) -> int:
    try:
        report = await measure_lag(StreamConfig())
    except TopicNotVisible as exc:
        # 非零退出码：让调度器能把"监控瞎了"当失败处理，而不是当 lag=0 放过
        logger.error("%s", exc)
        return 2
    print(report.format())
    if report.uncommitted_partitions:
        print(f"注意：分区 {report.uncommitted_partitions} 还没提交过 offset（新消费组是正常的）")
    return 0


async def cmd_selftest(args: argparse.Namespace) -> int:
    """端到端自检：假行情源 → 真 Kafka → 落库 → 重放验证幂等。"""
    import tempfile
    import os
    from datetime import datetime, timezone

    from core.streaming import QuoteEvent

    class FakeSource:
        """价格按轮次递增，好让信号阈值能被触发。"""

        def __init__(self) -> None:
            self.round = 0

        async def get_verified_price(self, code: str) -> dict:
            self.round += 1
            return {
                "price": 10.0 + self.round * 0.2,
                "is_valid": True,
                "quality_score": 100.0,
                "source_names": ["FakeA", "FakeB"],
                "pre_close": 10.0,
            }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    config = StreamConfig()
    # 用独立 topic + 独立 group，绝不碰真实管道的消费进度
    config = StreamConfig(
        bootstrap_servers=config.bootstrap_servers,
        topic=f"selftest.quotes.{stamp}",
        group_id=f"selftest.group.{stamp}",
        num_partitions=2,
        replication_factor=1,
        poll_interval_s=0.05,
        consumer_batch_timeout_ms=3000,
        consumer_max_records=500,
        sink_db_path=os.path.join(tempfile.mkdtemp(prefix="quote_selftest_"), "selftest.db"),
        signal_move_pct=1.0,
    )
    logger.info("自检 topic=%s db=%s", config.topic, config.sink_db_path)

    await ensure_topic(config)

    codes = ["600000", "000001"]
    async with QuoteProducer(config) as producer:
        sent = await producer.run_forever(FakeSource(), codes, max_rounds=3)
    logger.info("已投递 %d 条", sent)

    with IdempotentQuoteSink(config.sink_db_path, config.signal_move_pct) as sink:
        async with QuoteConsumer(config, sink=sink) as consumer:
            stats = ConsumeStats()
            for _ in range(3):
                await consumer.consume_once(stats)
                if stats.polled >= sent:
                    break
        first_rows = sink.count()
        logger.info(
            "首轮消费：拉 %d｜写 %d｜去重 %d｜信号 %d｜库中 %d 行",
            stats.polled, stats.written, stats.duplicates, len(stats.signals), first_rows,
        )

        # 幂等验证：把同一批事件再喂一次，行数必须不变
        replay = [
            QuoteEvent(
                code=c, price=11.0, quote_ts=f"2026-01-01T00:00:0{i}+00:00",
                ingest_ts="2026-01-01T00:00:00+00:00", is_valid=True,
                quality_score=100.0, sources=("FakeA",),
            )
            for i, c in enumerate(codes)
        ]
        r1 = sink.write_batch(replay)
        rows_after_first = sink.count()
        r2 = sink.write_batch(replay)          # 完全相同的一批，模拟 offset 未提交导致的重放
        rows_after_replay = sink.count()

    ok = (
        sent == 6
        and stats.polled == sent
        and stats.poison == 0
        and r1.written == 2
        and r2.written == 0
        and r2.duplicates == 2
        and rows_after_first == rows_after_replay
    )
    logger.info(
        "幂等验证：首次写 %d 行、重放写 %d 行（去重 %d）；重放前后行数 %d → %d",
        r1.written, r2.written, r2.duplicates, rows_after_first, rows_after_replay,
    )
    report = await measure_lag(config)
    print(report.format())
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A 股行情 Kafka 流式管道")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("topic", help="创建 topic（幂等）")

    p_prod = sub.add_parser("produce", help="轮询真实行情并投递")
    p_prod.add_argument("--codes", help="逗号分隔的股票代码，默认 600000,000001,600519")
    p_prod.add_argument("--rounds", type=int, default=None, help="轮询多少轮后退出，默认一直跑")

    p_cons = sub.add_parser("consume", help="消费并落库")
    p_cons.add_argument("--batches", type=int, default=None, help="消费多少批后退出，默认一直跑")

    sub.add_parser("lag", help="打印消费滞后")
    sub.add_parser("selftest", help="不打网络的端到端自检")

    args = parser.parse_args(argv)
    handlers = {
        "topic": cmd_topic, "produce": cmd_produce, "consume": cmd_consume,
        "lag": cmd_lag, "selftest": cmd_selftest,
    }
    return asyncio.run(handlers[args.cmd](args))


if __name__ == "__main__":
    sys.exit(main())
