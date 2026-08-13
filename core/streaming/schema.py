"""行情事件的线上格式（envelope）。

两条硬规则：
1. 带 `v` 版本号。消费端遇到不认识的版本必须显式报错，而不是当成空字段静默吞掉——
   这个项目吃过"字段悄悄变了但下游照跑"的亏，宁可炸也别静默。
2. `quote_ts` 是行情自身的时间（事件时间），`ingest_ts` 是我们抓到它的时间（处理时间）。
   去重按事件时间，滞后统计按两者之差；混用会让"数据新鲜度"这个指标失去意义。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1


class SchemaError(ValueError):
    """事件不符合约定格式。"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class QuoteEvent:
    code: str
    price: float
    quote_ts: str          # 事件时间（ISO8601）
    ingest_ts: str         # 处理时间（ISO8601）
    is_valid: bool
    quality_score: float
    sources: tuple[str, ...] = ()
    pre_close: float | None = None
    reason: str | None = None
    v: int = SCHEMA_VERSION

    @staticmethod
    def from_validator_result(code: str, result: dict[str, Any], quote_ts: str | None = None) -> "QuoteEvent":
        """把 RealTimePriceValidator.get_verified_price() 的返回值装进 envelope。"""
        price = result.get("price")
        if price is None:
            raise SchemaError(f"{code}: 校验结果没有 price，不应产出事件")
        return QuoteEvent(
            code=code,
            price=float(price),
            quote_ts=quote_ts or _utc_now_iso(),
            ingest_ts=_utc_now_iso(),
            is_valid=bool(result.get("is_valid", False)),
            quality_score=float(result.get("quality_score", 0.0)),
            sources=tuple(result.get("source_names", ()) or ()),
            pre_close=result.get("pre_close"),
            reason=result.get("reason"),
        )

    def key(self) -> bytes:
        """分区 key = 股票代码。同一只股票永远落同一分区，保证它自己的 tick 有序。"""
        return self.code.encode("utf-8")

    def encode(self) -> bytes:
        payload = asdict(self)
        payload["sources"] = list(self.sources)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def decode(raw: bytes) -> "QuoteEvent":
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SchemaError(f"事件不是合法 UTF-8 JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise SchemaError(f"事件顶层必须是对象，实际是 {type(payload).__name__}")

        version = payload.get("v")
        if version != SCHEMA_VERSION:
            # 显式失败：宁可让消费者停下来，也不要按 v1 的假设去读 v2 的数据
            raise SchemaError(f"不支持的 schema 版本 {version!r}（本消费者只认 v{SCHEMA_VERSION}）")

        missing = [f for f in ("code", "price", "quote_ts", "ingest_ts") if payload.get(f) is None]
        if missing:
            raise SchemaError(f"事件缺字段: {missing}")

        return QuoteEvent(
            code=str(payload["code"]),
            price=float(payload["price"]),
            quote_ts=str(payload["quote_ts"]),
            ingest_ts=str(payload["ingest_ts"]),
            is_valid=bool(payload.get("is_valid", False)),
            quality_score=float(payload.get("quality_score", 0.0)),
            sources=tuple(payload.get("sources", ()) or ()),
            pre_close=payload.get("pre_close"),
            reason=payload.get("reason"),
            v=SCHEMA_VERSION,
        )
