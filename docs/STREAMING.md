# 盘中行情流式管道（Kafka）

```
新浪 / 腾讯多源行情
      │  轮询 + 多源比价校验（复用 core/realtime_market.py）
      ▼
  QuoteProducer ──produce──► Kafka topic  quotes.a-share  (3 分区, key = 股票代码)
                                   │
                                   ▼  consume（手动提交 offset）
                             QuoteConsumer
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
        幂等落库 quote_ticks              阈值触发 quote_signals
        (PK: code + quote_ts)             (同一跳变只发一次)
```

与仓里已有的 cron 批处理是**互补**关系：批处理管日频回测与研究，这条流管盘中的近实时观测。
两边共用同一套多源校验逻辑，避免出现两套价格口径。

## 为什么这么设计

### 1. 分区 key = 股票代码

同一只股票的所有 tick 落在同一分区，因此**它自己的时间序是有保证的**。
跨股票不保证有序——也不需要，因为所有下游计算都是按股票分组的。

这条保证很脆：**分区数一变，key→partition 的落点就全变了**。所以 `ensure_topic()`
建完还会回头核对分区数，不符就抛 `TopicMisconfigured`。

> 踩过的坑：broker 默认 `auto.create.topics.enable=true`，topic 名打错会被**静默创建成
> 1 分区**（broker 默认 `num.partitions=1`）。不报任何错，消息数也正常，
> 但有序性已经塌了。aiokafka 不支持客户端侧的 `allow_auto_create_topics`，
> 所以只能启动时自己核对。

### 2. 至少一次投递 + 幂等落库 = 端到端不重不丢

消费端 `enable_auto_commit=False`，顺序严格是 **先落库、后提交 offset**：

- 落库成功、提交前崩溃 → 重启后重放这批 → 幂等去重吃掉，**不重**
- 反过来（自动提交 / 先提交后落库）→ 崩溃时 offset 已前进但数据没写 → **永久丢失**

去重靠 `quote_ticks` 的主键 `(code, quote_ts)` + `ON CONFLICT DO NOTHING`。
这比上 Kafka 事务型 exactly-once 便宜得多，也更好解释。

整批写在一个 SQLite 事务里：要么全落、要么全回滚，避免"offset 提交了但只落了一半"。

信号也做了去重（`quote_signals` 同样按 `(code, quote_ts)` 建主键），
否则一次崩溃重放会把同一次跳变**给用户重复通知两遍**。

### 3. 事件时间 vs 处理时间

- `quote_ts`：行情自身的时间 → 用来去重、排序
- `ingest_ts`：我们抓到它的时间 → 两者之差就是数据新鲜度

混用会让"新鲜度"这个指标失去意义，所以 envelope 里两个都带。

### 4. 坏消息不能卡住分区

`decode_batch()` 遇到解不开的消息只计数并跳过。若让它抛出去，
一条脏数据会让整个消费组**永远停在同一个 offset** 上——比丢一条严重得多。
整批全是坏消息时也照常提交。

envelope 带 `v` 版本号，遇到不认识的版本**显式报错**而不是当空字段吞掉。

### 5. 滞后监控必须能报出"我瞎了"

`lag = 分区末端 offset − 消费组已提交 offset`，是这条管道唯一真正重要的健康指标：
进程活着、日志不报错、lag 却在单调上涨 = 消费追不上生产，表现为信号越来越晚。

两个刻意的设计：

- **从没提交过的分区，lag 是 `None` 不是 `0`**。当 0 算会在新建消费组时误报一次巨大 lag。
- **读不到 topic 分区信息时抛 `TopicNotVisible`，不返回空报告**。
  空报告的 `total_lag` 是 0，调用方会把"我什么都没看见"读成"一切正常"。
  监控自己瞎掉必须比滞后更响。CLI 的 `lag` 子命令对应返回退出码 2，
  好让调度器能把它当失败处理。

> 这个 bug 是自检时真抓出来的：第一版打印了 `total_lag=0`，
> 旁边却有一行 warning 说 topic 看不见。

  另外 `measure_lag()` 不订阅 topic —— 订阅会让它加入消费组、触发一次 rebalance。
  监控不该扰动被监控的对象。

## 跑起来

```bash
# 0) 起 broker（macOS / Homebrew，KRaft 模式，不需要 ZooKeeper）
brew services start kafka

# 1) 建 topic（幂等，并核对分区数）
python -m core.run_quote_stream topic

# 2) 不打网络的端到端自检：假行情源 → 真 Kafka → 落库 → 重放验幂等
python -m core.run_quote_stream selftest

# 3) 真实行情（需能访问新浪/腾讯行情接口）
python -m core.run_quote_stream produce --codes 600000,000001,600519 --rounds 20
python -m core.run_quote_stream consume --batches 5

# 4) 看消费滞后
python -m core.run_quote_stream lag
```

## 配置（全部可用环境变量覆盖）

| 变量 | 默认 | 说明 |
|---|---|---|
| `KAFKA_BOOTSTRAP` | `localhost:9092` | broker 地址 |
| `KAFKA_QUOTE_TOPIC` | `quotes.a-share` | topic 名 |
| `KAFKA_QUOTE_GROUP` | `quote-ingest.v1` | 消费组 |
| `KAFKA_QUOTE_PARTITIONS` | `3` | 分区数（**建后不要改**，会破坏有序性） |
| `QUOTE_POLL_INTERVAL_S` | `3.0` | 轮询间隔（秒） |
| `QUOTE_SINK_DB` | `data/quote_stream.db` | 落库路径 |
| `QUOTE_SIGNAL_MOVE_PCT` | `1.0` | 触发信号的变动阈值（%） |

## 测试

```bash
python -m pytest tests/test_streaming.py -q                       # 不需要 Kafka
KAFKA_BOOTSTRAP=localhost:9092 python -m pytest tests/test_streaming.py -q   # 含集成用例
```

绝大多数用例不需要 broker——它们测的是自己写的那部分（版本校验、幂等去重、
提交顺序、lag 计算）。需要真 broker 的用例带 `requires_kafka` 标记，
没设 `KAFKA_BOOTSTRAP` 时自动跳过，CI 不装 Kafka 也能跑绿。

集成用例里有一条**正向对照**：只投不消费，断言 lag 必须涨到 3。
没有它的话，"lag=0" 可能只是监控根本没在看。
