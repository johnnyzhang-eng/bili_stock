"""
LiveLedger — 防腐烂的 live/paper 交易台账
==========================================
**为什么存在**: 2026-05-25 truth manifest 发现 "53.76% live 胜率" 的底层数据
(battle_trades_all.csv 等) 全部遗失, 声明被迫降级为 historical undocumented
claim。14 个月的唯一真 OOS 证据就这样蒸发了。本模块保证同类事故不再发生:

1. **append-only JSONL** — 不可原地修改; 每行一笔记录.
2. **hash chain** — 每条记录携带前一条的 SHA-256, 任何删改/丢行都会
   在 verify() 时暴露 (tamper-evident, 模式取自区块链/审计日志).
3. **provenance enum 强制** — price_source 必须是白名单值; "我记得大概是
   这个价" 类记录直接拒收. 模式取自 polyFIFA2026 time-window.ts
   ("unverified clock → no trade") 与本项目 MissingRandomControl 同源.
4. **audit() 用 cluster bootstrap 出 CI** — 胜率/收益声明自带统计推断,
   不再出现裸点估计.

用法:
    from research.foundation.live_ledger import LiveLedger, LedgerEntry
    lg = LiveLedger("data/live_ledger.jsonl")
    lg.append(LedgerEntry(
        ts="2026-07-02T15:00:00+08:00",
        strategy="allweather_303040",
        code="512890", action="BUY", price=1.234, quantity=1000,
        price_source="broker_fill",       # 白名单之外直接 raise
        recorded_by="script:quarterly_rebalance.py",
        note="Q3 再平衡",
    ))
    print(lg.verify())       # (True, n) 或 (False, 首个断链位置)
    print(lg.audit())        # 胜率 CI + 收益 CI (cluster by 自然日)
"""
import hashlib
import json
import os
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Tuple

from .exceptions import FoundationError


SCHEMA_VERSION = 1

# price_source 白名单 — 加新源要在这里登记并说明验证方式
ALLOWED_PRICE_SOURCES = {
    "broker_fill",          # 券商成交回报 (最强)
    "broker_statement",     # 券商对账单
    "baostock_close",       # BaoStock 收盘价 (paper trade 定价)
    "akshare_close",        # AKShare 收盘价
    "exchange_snapshot",    # 交易所行情快照 (带时间戳)
}

ALLOWED_ACTIONS = {"BUY", "SELL", "DIVIDEND", "MARK"}   # MARK = 定期市值快照


class LedgerIntegrityError(FoundationError):
    """台账 hash chain 断裂或 schema 非法"""
    pass


class UnverifiedProvenance(FoundationError):
    """price_source 不在白名单 — 拒收. 台账只收可验证的记录."""
    pass


@dataclass
class LedgerEntry:
    ts: str                       # ISO-8601 含时区
    strategy: str                 # 如 "allweather_303040"
    code: str                     # 标的代码
    action: str                   # BUY/SELL/DIVIDEND/MARK
    price: float
    quantity: float
    price_source: str             # 必须在 ALLOWED_PRICE_SOURCES
    recorded_by: str              # "manual:johnny" 或 "script:<name>"
    note: str = ""
    # 以下由 LiveLedger 填充, 调用方不要传
    schema_version: int = SCHEMA_VERSION
    seq: Optional[int] = None
    prev_hash: Optional[str] = None
    entry_hash: Optional[str] = None

    def validate(self) -> None:
        if self.action not in ALLOWED_ACTIONS:
            raise LedgerIntegrityError(
                f"action '{self.action}' 不在 {sorted(ALLOWED_ACTIONS)}")
        if self.price_source not in ALLOWED_PRICE_SOURCES:
            raise UnverifiedProvenance(
                f"price_source '{self.price_source}' 不在白名单 "
                f"{sorted(ALLOWED_PRICE_SOURCES)}. 台账拒收无法验证来源的价格 — "
                "这是 53.76% 事故的直接教训: 不可验证的记录等于没有记录.")
        if not (self.price > 0):
            raise LedgerIntegrityError(f"price 必须 > 0, 收到 {self.price}")
        if not self.recorded_by or ":" not in self.recorded_by:
            raise LedgerIntegrityError(
                "recorded_by 必须是 'manual:<who>' 或 'script:<name>' 格式")


GENESIS_HASH = "0" * 64


def _entry_payload_for_hash(d: dict) -> str:
    """hash 覆盖除 entry_hash 外的全部字段, key 排序保证确定性"""
    clean = {k: v for k, v in d.items() if k != "entry_hash"}
    return json.dumps(clean, sort_keys=True, ensure_ascii=False)


class LiveLedger:
    def __init__(self, path: str):
        self.path = path

    # ── 写 ────────────────────────────────────────────────────────────────
    def append(self, entry: LedgerEntry) -> LedgerEntry:
        entry.validate()
        entries = self._read_raw()
        prev_hash = entries[-1]["entry_hash"] if entries else GENESIS_HASH
        entry.seq = len(entries)
        entry.prev_hash = prev_hash
        d = asdict(entry)
        d["entry_hash"] = hashlib.sha256(
            _entry_payload_for_hash(d).encode("utf-8")).hexdigest()
        entry.entry_hash = d["entry_hash"]

        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
        return entry

    # ── 读 + 校验 ─────────────────────────────────────────────────────────
    def _read_raw(self) -> List[dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def verify(self) -> Tuple[bool, str]:
        """校验整条 hash chain. 返回 (ok, message)."""
        entries = self._read_raw()
        prev = GENESIS_HASH
        for i, d in enumerate(entries):
            if d.get("seq") != i:
                return False, f"seq 断裂: 第 {i} 行 seq={d.get('seq')} (记录被删除或乱序)"
            if d.get("prev_hash") != prev:
                return False, f"hash chain 断裂于 seq={i}: prev_hash 不匹配 (记录被删改)"
            expected = hashlib.sha256(
                _entry_payload_for_hash(d).encode("utf-8")).hexdigest()
            if d.get("entry_hash") != expected:
                return False, f"entry_hash 不匹配于 seq={i} (记录内容被篡改)"
            prev = d["entry_hash"]
        return True, f"OK: {len(entries)} 条记录, chain 完整"

    def entries(self) -> List[dict]:
        """校验通过才返回数据 — 断链时拒绝提供, 强制先处理完整性问题"""
        ok, msg = self.verify()
        if not ok:
            raise LedgerIntegrityError(msg)
        return self._read_raw()

    # ── 审计 ──────────────────────────────────────────────────────────────
    def audit(self, min_n: int = 30) -> str:
        """闭合仓位胜率/收益 + cluster bootstrap CI (按开仓自然日聚类).

        规则: n < min_n 时拒绝给出胜率声明 — 30 笔以下的胜率没有推断价值,
        这是 53.76% 类声明的另一半教训 (点估计 + 小样本 + 无 CI).
        """
        entries = self.entries()
        # 配对 BUY→SELL (同 strategy+code, FIFO)
        open_pos: dict = {}
        closed: List[dict] = []
        for d in entries:
            key = (d["strategy"], d["code"])
            if d["action"] == "BUY":
                open_pos.setdefault(key, []).append(d)
            elif d["action"] == "SELL" and open_pos.get(key):
                buy = open_pos[key].pop(0)
                closed.append({
                    "open_ts": buy["ts"], "close_ts": d["ts"],
                    "ret": d["price"] / buy["price"] - 1.0,
                })
        if not closed:
            return f"无闭合仓位 (记录 {len(entries)} 条, 未平仓 {sum(len(v) for v in open_pos.values())} 笔)"
        n = len(closed)
        if n < min_n:
            return (f"闭合仓位 {n} 笔 < {min_n} — 样本不足, 拒绝给出胜率/收益声明. "
                    "继续积累记录.")

        import numpy as np
        from .stats import cluster_bootstrap_mean
        rets = np.array([c["ret"] for c in closed])
        days = [c["open_ts"][:10] for c in closed]
        r_ret = cluster_bootstrap_mean(rets, days)
        r_win = cluster_bootstrap_mean((rets > 0).astype(float), days)
        return (f"闭合仓位 {n} 笔 ({len(set(days))} 个开仓日):\n"
                f"  平均收益: {r_ret.describe()}\n"
                f"  胜率:     mean={r_win.mean*100:.1f}% "
                f"CI95=[{r_win.ci_lo*100:.1f}%, {r_win.ci_hi*100:.1f}%]\n"
                f"  vs 50% 抛硬币: {'区分得开' if r_win.ci_lo > 0.5 or r_win.ci_hi < 0.5 else '区分不开'}")


# ── 自检 ──────────────────────────────────────────────────────────────────
def self_test(tmp_path: str = "/tmp/live_ledger_selftest.jsonl") -> None:
    import numpy as np
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    lg = LiveLedger(tmp_path)

    # 1. 正常追加 + verify
    for i in range(3):
        lg.append(LedgerEntry(
            ts=f"2026-07-0{i+1}T10:00:00+08:00", strategy="test", code="512890",
            action="BUY" if i % 2 == 0 else "SELL", price=1.0 + i * 0.01,
            quantity=100, price_source="baostock_close", recorded_by="script:self_test"))
    ok, msg = lg.verify()
    assert ok, f"E1 FAIL: {msg}"

    # 2. 白名单外 provenance 拒收
    try:
        lg.append(LedgerEntry(ts="2026-07-04T10:00:00+08:00", strategy="test",
                              code="x", action="BUY", price=1.0, quantity=1,
                              price_source="memory", recorded_by="manual:test"))
        raise AssertionError("E2 FAIL: 非白名单 provenance 应被拒收")
    except UnverifiedProvenance:
        pass

    # 3. 篡改检测: 改一行价格
    lines = open(tmp_path, encoding="utf-8").read().strip().split("\n")
    d = json.loads(lines[1]); d["price"] = 9.99
    lines[1] = json.dumps(d, ensure_ascii=False, sort_keys=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    ok, msg = lg.verify()
    assert not ok and "篡改" in msg, f"E3 FAIL: 篡改未被检出: {msg}"

    # 4. entries() 断链拒绝服务
    try:
        lg.entries()
        raise AssertionError("E4 FAIL: 断链时 entries() 应 raise")
    except LedgerIntegrityError:
        pass

    # 5. audit 小样本拒绝声明
    os.remove(tmp_path)
    lg2 = LiveLedger(tmp_path)
    rng = np.random.default_rng(0)
    for i in range(10):
        px = float(1.0 + rng.normal(0, 0.01))
        lg2.append(LedgerEntry(ts=f"2026-06-{i+1:02d}T10:00:00+08:00", strategy="s",
                               code="c", action="BUY", price=px, quantity=1,
                               price_source="baostock_close", recorded_by="script:t"))
        lg2.append(LedgerEntry(ts=f"2026-06-{i+1:02d}T15:00:00+08:00", strategy="s",
                               code="c", action="SELL", price=px * float(1 + rng.normal(0.001, 0.02)),
                               quantity=1, price_source="baostock_close", recorded_by="script:t"))
    msg = lg2.audit(min_n=30)
    assert "样本不足" in msg, f"E5 FAIL: 10 笔应拒绝声明: {msg}"

    os.remove(tmp_path)
    print("  [E] live_ledger.py 自检: 5/5 PASS (append/verify/拒收/防篡改/小样本拒声明)")


if __name__ == "__main__":
    self_test()
