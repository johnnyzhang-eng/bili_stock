"""消费端落地层：幂等写入 + 信号触发。

为什么要幂等：consumer 用手动提交 offset，语义是 at-least-once —— 处理成功但 commit 前进程挂了，
重启会重放同一批。只要写入本身按 (code, quote_ts) 去重，重放就不会产生重复行，
端到端等价于 effectively-once。这是"至少一次 + 幂等 = 恰好一次"的标准做法，
比追求 Kafka 事务型 exactly-once 便宜得多，也更好解释。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Iterable, Sequence

from .schema import QuoteEvent

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quote_ticks (
    code          TEXT    NOT NULL,
    quote_ts      TEXT    NOT NULL,
    price         REAL    NOT NULL,
    pre_close     REAL,
    is_valid      INTEGER NOT NULL,
    quality_score REAL    NOT NULL,
    sources       TEXT,
    reason        TEXT,
    ingest_ts     TEXT    NOT NULL,
    PRIMARY KEY (code, quote_ts)
);
CREATE INDEX IF NOT EXISTS idx_quote_ticks_code_ts ON quote_ticks(code, quote_ts DESC);

CREATE TABLE IF NOT EXISTS quote_signals (
    code       TEXT NOT NULL,
    quote_ts   TEXT NOT NULL,
    prev_price REAL NOT NULL,
    price      REAL NOT NULL,
    move_pct   REAL NOT NULL,
    PRIMARY KEY (code, quote_ts)
);
"""


@dataclass(frozen=True)
class SinkResult:
    written: int
    duplicates: int
    signals: tuple[tuple[str, float], ...] = ()   # (code, move_pct)


class IdempotentQuoteSink:
    """按 (code, quote_ts) 去重写入 SQLite，并在价格跳变超阈值时落一条信号。"""

    def __init__(self, db_path: str, signal_move_pct: float = 1.0) -> None:
        if signal_move_pct <= 0:
            raise ValueError("signal_move_pct 必须为正")
        self.db_path = db_path
        self.signal_move_pct = signal_move_pct
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "IdempotentQuoteSink":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _last_price_before(self, code: str, quote_ts: str) -> float | None:
        row = self._conn.execute(
            "SELECT price FROM quote_ticks WHERE code = ? AND quote_ts < ? "
            "ORDER BY quote_ts DESC LIMIT 1",
            (code, quote_ts),
        ).fetchone()
        return float(row[0]) if row else None

    def write_batch(self, events: Sequence[QuoteEvent]) -> SinkResult:
        """整批写在一个事务里。

        要么整批落地、要么整批回滚，这样"已提交 offset"和"已落库"不会各自成功一半。
        """
        written = 0
        signals: list[tuple[str, float]] = []
        try:
            with self._conn:  # 事务边界：异常自动 rollback
                for ev in events:
                    prev = self._last_price_before(ev.code, ev.quote_ts)
                    cur = self._conn.execute(
                        "INSERT INTO quote_ticks "
                        "(code, quote_ts, price, pre_close, is_valid, quality_score, sources, reason, ingest_ts) "
                        "VALUES (?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(code, quote_ts) DO NOTHING",
                        (
                            ev.code, ev.quote_ts, ev.price, ev.pre_close,
                            1 if ev.is_valid else 0, ev.quality_score,
                            ",".join(ev.sources) or None, ev.reason, ev.ingest_ts,
                        ),
                    )
                    if cur.rowcount == 0:
                        continue          # 重放命中去重，什么都不做
                    written += 1

                    # 信号只在"这条是新数据"时算，避免重放把同一次跳变重复通知
                    if prev and prev > 0:
                        move_pct = (ev.price - prev) / prev * 100.0
                        if abs(move_pct) >= self.signal_move_pct:
                            self._conn.execute(
                                "INSERT INTO quote_signals (code, quote_ts, prev_price, price, move_pct) "
                                "VALUES (?,?,?,?,?) ON CONFLICT(code, quote_ts) DO NOTHING",
                                (ev.code, ev.quote_ts, prev, ev.price, move_pct),
                            )
                            signals.append((ev.code, move_pct))
        except sqlite3.Error:
            logger.exception("落库失败，整批回滚；offset 不会提交，这批会被重放")
            raise

        return SinkResult(written=written, duplicates=len(events) - written, signals=tuple(signals))

    def count(self, table: str = "quote_ticks") -> int:
        if table not in ("quote_ticks", "quote_signals"):
            raise ValueError(f"未知表名 {table!r}")
        return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def latest(self, code: str) -> tuple[str, float] | None:
        row = self._conn.execute(
            "SELECT quote_ts, price FROM quote_ticks WHERE code = ? ORDER BY quote_ts DESC LIMIT 1",
            (code,),
        ).fetchone()
        return (str(row[0]), float(row[1])) if row else None


def dedupe_by_event_key(events: Iterable[QuoteEvent]) -> list[QuoteEvent]:
    """同一批里同 (code, quote_ts) 只保留最后一条。

    生产端轮询快于行情更新时，同一个 tick 会被重复抓到；先在内存里收掉，
    省得每条都去撞一次数据库主键。
    """
    seen: dict[tuple[str, str], QuoteEvent] = {}
    for ev in events:
        seen[(ev.code, ev.quote_ts)] = ev
    return list(seen.values())
