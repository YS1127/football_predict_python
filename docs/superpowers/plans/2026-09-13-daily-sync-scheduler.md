# 竞彩足球每日同步与手动触发实施计划

> **供智能体执行：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行本计划。所有步骤均使用复选框跟踪。

**目标：** 在现有同步代码上增加可配置的每日赛程/赔率任务、赛果回填任务、独立 APScheduler 进程，以及受 API Key 保护的手动触发接口。

**架构：** 两个聚焦业务服务复用现有客户端、解析器和仓储；`TaskRunner` 统一 MySQL advisory lock 与执行边界；CLI、APScheduler 和 FastAPI 只作为触发适配层。调度器独立于 Uvicorn 运行。

**技术栈：** Python 3.12、SQLAlchemy 2、FastAPI、APScheduler 3.11、pytest

**设计文档：** `docs/superpowers/specs/2026-09-13-daily-sync-scheduler-design.md`

## 全局约束

- 使用 `Asia/Shanghai` 解释业务日期。
- Cron 为标准五段式表达式。
- 官网详情请求串行且有可配置间隔。
- 单场失败不阻塞其他比赛；暂未开奖、延期和无效场次不算任务整体失败。
- 所有新增公共方法和复杂判断提供中文注释。
- 单元测试不访问官网或生产 MySQL。

### 任务 1：配置与仓储查询边界

**文件：** 修改 `src/config/settings.py`、`src/database/repository.py`；测试 `tests/test_settings.py`、`tests/test_repository.py`。

- [ ] 先写失败测试：校验 cron/时区/间隔；查询目标业务日比赛；查询截止日前缺赛果或奖金的有效比赛；无效场次清空。
- [ ] 运行定向测试并确认因接口缺失失败。
- [ ] 最小实现配置字段、验证器和仓储方法。
- [ ] 运行定向测试及完整回归。

### 任务 2：当天赛程与赔率服务

**文件：** 新建 `src/services/daily_match_sync_service.py`、`tests/test_daily_match_sync_service.py`。

- [ ] 先写失败测试：只处理目标业务日、不调用赛果接口、完整赔率幂等、请求间隔、单场失败隔离。
- [ ] 确认测试因服务缺失失败。
- [ ] 实现 `DailyMatchSyncService.run(target_business_date=None)`，按 official ID 串行处理。
- [ ] 运行定向测试及完整回归。

### 任务 3：积压赛果回填服务

**文件：** 新建 `src/services/result_sync_service.py`、`tests/test_result_sync_service.py`；修改 `src/parsers.py`。

- [ ] 先写失败测试：只选截止日前未完成记录、按 match_date 合并请求、无结果保留、无效场次终止、赛果后补赔率和奖金、详情失败保留赛果。
- [ ] 确认测试因服务/状态解析缺失失败。
- [ ] 实现赛果状态解析与 `ResultSyncService.run(cutoff_business_date=None)`。
- [ ] 运行定向测试及完整回归。

### 任务 4：任务运行器与数据库锁

**文件：** 新建 `src/services/task_runner.py`、`tests/test_task_runner.py`。

- [ ] 先写失败测试：依次获取全局锁和任务锁、占锁返回 busy、异常时释放、来源与耗时日志上下文。
- [ ] 确认测试失败。
- [ ] 使用 MySQL `GET_LOCK(name, 0)` / `RELEASE_LOCK(name)` 实现运行边界，并提供可注入锁用于 SQLite 单测。
- [ ] 运行定向测试及完整回归。

### 任务 5：APScheduler 独立入口

**文件：** 新建 `src/scheduler.py`、`tests/test_scheduler.py`；修改 `requirements.txt`。

- [ ] 先写失败测试：enabled 控制注册、CronTrigger 时区、max_instances=1、coalesce、misfire grace。
- [ ] 确认测试失败。
- [ ] 固定 `APScheduler>=3.11,<4`，实现模块级任务函数及 BlockingScheduler 装配。
- [ ] 运行定向测试及完整回归。

### 任务 6：CLI 与受保护 HTTP 入口

**文件：** 修改 `src/main.py`、`src/api.py`、`tests/test_main.py`、`tests/test_api.py`、`README.md`。

- [ ] 先写失败测试：两个单次 CLI、scheduler 命令、API Key 503/401、锁冲突 409、成功汇总 200。
- [ ] 确认测试失败。
- [ ] 接入共享 TaskRunner，不复制业务逻辑；使用常量时间比较 API Key。
- [ ] 更新 `.env` 示例、运行方式和 curl 示例。
- [ ] 运行完整测试、编译、CLI help、OpenAPI 和 diff 检查。

