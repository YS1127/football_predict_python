# 竞彩足球每日同步与手动触发设计

## 目标

在现有中国竞彩网客户端、解析器、SQLAlchemy 模型和仓储基础上，新增两条可独立执行的每日任务：当天竞彩业务日赛程及完整 HAD 赔率采集、前一竞彩业务日及历史积压比赛的赛果回填。两条任务既可由常驻调度器按配置执行，也可通过受保护的 HTTP 接口手动触发。

本次只建立数据准备流程，不实现预测算法。后续预测服务消费已入库比赛、赔率和赛果，不侵入抓取任务。

## 总体结构

新增 `DailyMatchSyncService`、`ResultSyncService` 和 `TaskRunner`。定时入口和 HTTP 入口只决定何时触发，实际业务都调用同一个 `TaskRunner`，再由它调用对应服务。

```text
APScheduler ─┐
             ├─ TaskRunner ─┬─ DailyMatchSyncService
HTTP POST ───┘              └─ ResultSyncService
```

`TaskRunner` 负责 MySQL advisory lock、任务开始/结束日志、耗时统计和异常边界。业务服务继续使用现有 `SportteryClient`、解析器、`MatchRepository` 与 `SessionLocal`。

## 配置

继续使用现有 `pydantic-settings` 从 `.env` 读取配置，不引入 YAML 或第二套配置系统：

```dotenv
SCHEDULER_TIMEZONE=Asia/Shanghai
DAILY_MATCH_SYNC_ENABLED=true
DAILY_MATCH_SYNC_CRON=0 19 * * *
DAILY_MATCH_DETAIL_INTERVAL_SECONDS=1.0
RESULT_SYNC_ENABLED=true
RESULT_SYNC_CRON=0 14 * * *
SCHEDULER_MISFIRE_GRACE_SECONDS=3600
MANUAL_TRIGGER_API_KEY=replace-with-a-random-secret
```

Cron 使用标准五段式 `分钟 小时 日期 月份 星期`。配置在调度器启动时校验；无效 cron、未知时区、负请求间隔或非正 misfire 宽限时间均阻止调度器启动并给出明确错误。

APScheduler 固定使用稳定的 3.x 主版本：`APScheduler>=3.11,<4`。调度进程使用 `BlockingScheduler`，通过独立命令运行，不嵌入 Uvicorn/FastAPI 进程。

## 当天赛程与赔率任务

`DailyMatchSyncService.run(target_business_date=None)` 默认以 `Asia/Shanghai` 当前日期作为目标竞彩业务日，也允许测试或手工内部调用显式传入日期。

流程：

1. 调用 `fetch_schedule()` 并解析赛程和联赛字典。
2. 只保留 `business_date == target_business_date` 的 HAD 比赛。
3. 首次写入尚不存在的联赛字典。
4. 按 `official_match_id ASC` 处理比赛，幂等新增或更新比赛信息。
5. 对每场比赛调用 `fetch_detail()`，解析完整 `hadList`。
6. 将所有赔率快照写入 `odds_snapshots`；重复快照忽略，同一官网发布时间赔率不同时记录冲突并保留原值。
7. 相邻详情请求使用 `DAILY_MATCH_DETAIL_INTERVAL_SECONDS` 固定间隔，完全串行，不并发访问官网。
8. 单场详情失败只记录该场失败，不阻塞其他比赛。

该任务不调用 `fetch_results()`，也不回填比分、HAD 赛果或开奖奖金。即使详情请求失败，已经取得的比赛基本信息仍保留，后续重复执行可继续补赔率。

## 前一业务日赛果任务

`ResultSyncService.run(cutoff_business_date=None)` 默认计算中国时区的前一日期作为截止竞彩业务日。

待处理集合满足：

- `business_date <= cutoff_business_date`；
- `is_valid = 1`；
- `home_goals`、`away_goals`、`had_result` 或 `had_payout` 任一为空。

这使昨天暂未开奖、延期、更早遗留的比赛以及“赛果已写入但奖金详情失败”的比赛能够在后续每日任务中继续重试。需要赛果的记录按 `match_date` 分组，因为官网赛果接口按比赛自然日期查询；每个日期只请求一次，并且只更新待处理 ID 集合中的比赛。仅缺开奖奖金的记录无需重复调用日期赛果接口，直接重试详情。

状态规则：

- 有合法全场比分：回填主客队进球、总进球和 HAD 结果。
- 官网暂时没有该比赛或没有最终比分：保持原状态，不记为任务整体失败。
- 明确返回“无效场次”：设置 `is_valid=0`，清空比分、总进球、HAD 结果、开奖奖金和赛果更新时间。
- 延期但未明确无效：保持 `is_valid=1` 和空赛果，下一次任务继续尝试。
- 官网请求或响应契约失败：记录对应日期/比赛失败，其他日期和比赛继续。

获得有效最终赛果后，再为该场调用 `fetch_detail()`，补充可能遗漏的最终赔率历史和 HAD 开奖固定奖金。详情失败不回滚已经可信写入的赛果，但记录在任务汇总中；因为缺少 `had_payout` 的比赛仍属于待处理集合，后续任务会继续补充。

## 并发与幂等

APScheduler 对每个任务设置 `max_instances=1`、`coalesce=True` 和配置化 `misfire_grace_time`。

`TaskRunner` 获取两个层级的 MySQL advisory lock：

- 全局官网访问锁：防止赛程任务和赛果任务同时密集访问官网；
- 任务锁：防止同一个任务被定时器和 HTTP 同时执行。

锁使用立即失败模式，不等待占锁。占锁时手动接口返回 HTTP 409，定时任务记录一次跳过。锁名固定、长度受控，并在 `finally` 中释放。

数据库仍以 `matches.official_match_id`、`leagues.official_league_id` 和 `odds_snapshots(match_id, official_updated_at)` 唯一约束作为最终幂等保障。每场比赛使用独立事务。

## 调度器

新增命令：

```bash
python -m src.main scheduler
```

调度器按 enabled 配置注册任务。任务函数是模块级可导入函数，不使用 lambda 或闭包。调度器启动时记录任务 ID、cron、时区和下一次运行时间，但不记录密码或 API Key。

同时提供单次手工 CLI：

```bash
python -m src.main daily-match-sync
python -m src.main result-sync
```

CLI 单次执行也经过 `TaskRunner` 和相同数据库锁。

## HTTP 手动触发

在现有 FastAPI 应用新增同步 POST 接口：

```text
POST /api/tasks/daily-match-sync
POST /api/tasks/result-sync
```

接口不接受任意日期参数，只执行与当天定时任务相同的默认日期语义，避免公开接口被用于大范围历史抓取。历史数据仍使用已有受控 CLI。

请求必须携带 `X-API-Key`，并与 `MANUAL_TRIGGER_API_KEY` 常量时间比较：

- 未配置 Key：HTTP 503，接口禁用；
- 缺失或错误：HTTP 401；
- 同任务或全局官网锁已占用：HTTP 409；
- 正常执行结束：HTTP 200，返回统一任务汇总；
- 未捕获的任务级错误：HTTP 500，返回简短错误，不包含官网正文、数据库连接串或堆栈。

接口采用同步响应。调用端需要允许几十秒超时；如未来单次任务显著增长，再单独设计持久任务记录、`202 + run_id` 和状态查询，不在第一版提前引入任务队列。

## 日志与汇总

每次执行记录触发来源（scheduled、http、cli）、任务类型、目标日期、开始时间、结束时间、耗时和 `SyncSummary`。单场失败保留简短上下文，禁止记录数据库密码、API Key 或完整官网响应。

任务进程退出码遵循现有规则：存在不可恢复的任务级失败或单场失败时为非零；暂未开奖、延期和明确无效场次属于业务状态，不导致整体失败。

## 测试

所有测试使用固定 JSON、SQLite 内存库、假时钟和假调度器，不访问官网或生产 MySQL。覆盖：

- 当天任务只处理目标业务日且不调用赛果接口；
- 当前比赛与完整赔率幂等写入；
- 详情请求间隔和单场失败隔离；
- 赛果任务只选取截止日以前的未完成有效比赛；
- 昨日无结果、延期记录可在下次继续尝试；
- 无效场次状态与结果字段清空；
- 有效赛果后的赔率和奖金补充；
- cron、时区和 enabled 配置；
- 同任务重入与跨任务全局锁；
- API Key 的 503、401、409 和成功响应；
- CLI 单次任务及调度器命令装配。

MySQL advisory lock 使用独立测试库做窄集成测试；没有测试库配置时跳过，不连接生产库。

## 文件边界

新增：

```text
src/services/daily_match_sync_service.py
src/services/result_sync_service.py
src/services/task_runner.py
src/scheduler.py
tests/test_daily_match_sync_service.py
tests/test_result_sync_service.py
tests/test_task_runner.py
tests/test_scheduler.py
```

修改现有 `settings.py`、`repository.py`、`api.py`、`main.py`、`requirements.txt` 和 `README.md`。不重构历史回填服务、数据模型、官网客户端或无关模块；只在现有公共方法不足以支持新任务时增加聚焦接口。
