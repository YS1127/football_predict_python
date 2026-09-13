# 竞彩足球胜平负数据同步实施计划

> **供智能体执行：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行本计划。所有步骤均使用复选框（`- [ ]`）跟踪。

**目标：** 实现一个单次执行命令，将中国竞彩网 HAD 比赛、完整赔率历史和已开奖赛果幂等同步到 MySQL。

**架构：** 带有限重试的 HTTP 客户端负责获取并初步验证 JSON，纯解析模块负责转换和严格校验。SQLAlchemy 模型与仓储层隔离持久化细节；与数据库实现解耦的同步服务按比赛组织事务，并向 CLI 暴露可复用接口。

**技术栈：** Python 3.12、requests、SQLAlchemy 2、PyMySQL、pydantic-settings、pytest

**设计文档：** `docs/superpowers/specs/2026-09-13-football-had-sync-design.md`

## 全局约束

- 仅处理 HAD，不采集 HHAD、CRS、TTG 或 HAFU 赔率。
- 官网时间按中国时区解释，写入 MySQL 时保存为无时区的 `DATETIME`。
- 当前赛程来自 `getMatchCalculatorV1.qry`，完整赔率历史和开奖固定奖金来自 `getFixedBonusV1.qry`，权威全场比分来自 `getUniformMatchResultV1.qry`。
- 日志不得包含数据库密码或完整的官网响应。
- 单元测试只读取本地固定样本，不访问官网。

---

### 任务 1：领域数据结构与严格响应解析

**文件：**
- 新建：`src/domain.py`
- 新建：`src/parsers.py`
- 新建：`tests/fixtures/schedule.json`
- 新建：`tests/fixtures/detail.json`
- 新建：`tests/fixtures/results.json`
- 新建：`tests/test_parsers.py`

**接口：**
- 产出：不可变数据结构 `MatchData`、`OddsSnapshotData` 和 `MatchResultData`。
- 产出：`parse_schedule(payload)`、`parse_detail(payload, expected_match_id)` 和 `parse_results(payload)`。

- [ ] **步骤 1：先编写失败的解析测试**

```python
def test_schedule_parses_had_match(load_fixture):
    match = parse_schedule(load_fixture("schedule.json"))[0]
    assert (match.official_match_id, match.match_number) == (2041387, "周五002")

def test_detail_parses_every_had_snapshot(load_fixture):
    _, odds, payout = parse_detail(load_fixture("detail.json"), 2041387)
    assert [(x.home, x.draw, x.away) for x in odds] == [
        (Decimal("4.95"), Decimal("4.05"), Decimal("1.47")),
        (Decimal("5.75"), Decimal("4.45"), Decimal("1.37")),
    ]
    assert payout == Decimal("1.37")

def test_result_uses_regular_time_score(load_fixture):
    result = parse_results(load_fixture("results.json"))[2041387]
    assert (result.home_goals, result.away_goals, result.had_result) == (1, 3, "A")
```

- [ ] **步骤 2：** 运行 `pytest tests/test_parsers.py -q`，确认测试因解析模块尚不存在而失败。
- [ ] **步骤 3：** 实现响应外壳、必填字段、Decimal、时间、比分和比赛身份的严格校验，并拆分为小型纯函数。
- [ ] **步骤 4：** 运行 `pytest tests/test_parsers.py -q`，确认全部解析测试通过。
- [ ] **步骤 5：** 提交：`git commit -m "feat: parse Sporttery HAD data"`。

### 任务 2：带重试的官网 HTTP 客户端

**文件：**
- 修改：`src/config/settings.py`
- 替换：`src/crawler/match_crawler.py`
- 新建：`tests/test_client.py`

**接口：**
- 使用：抓取超时、重试次数、基础 URL、User-Agent 和退避配置。
- 产出：`SportteryClient.fetch_schedule()`、`fetch_detail(match_id)` 和 `fetch_results(begin, end)`。

- [ ] **步骤 1：** 使用脚本化的内存 HTTP Session 编写失败测试：500 后重试并成功；400 立即失败；非 JSON 响应抛出 `UpstreamError`。
- [ ] **步骤 2：** 运行 `pytest tests/test_client.py -q`，确认因客户端或重试行为缺失而失败。
- [ ] **步骤 3：** 对网络错误、429 和 5xx 实现有上限的指数退避；校验 JSON 响应，且不记录响应正文。
- [ ] **步骤 4：** 运行 `pytest tests/test_client.py -q`，确认客户端测试全部通过。
- [ ] **步骤 5：** 提交：`git commit -m "feat: add resilient Sporttery client"`。

### 任务 3：SQLAlchemy 模型与幂等仓储

**文件：**
- 新建：`src/database/models.py`
- 新建：`src/database/repository.py`
- 修改：`src/database/mysql.py`
- 新建：`tests/test_repository.py`

**接口：**
- 使用：任务 1 的领域数据结构和 SQLAlchemy `Session`。
- 产出：`Match`、`OddsSnapshot`、`MatchRepository.upsert_match`、`add_odds`、`apply_result`、`pending_matches`。

- [ ] **步骤 1：** 使用 SQLite 内存库编写失败测试，覆盖比赛新增/更新计数、重复赔率不操作、冲突赔率保留原值并报告，以及总进球不变量。
- [ ] **步骤 2：** 运行 `pytest tests/test_repository.py -q`，确认因模型和仓储尚不存在而失败。
- [ ] **步骤 3：** 实现两张数据表、约束、关系、时间字段和仓储返回枚举；幂等逻辑保持跨数据库方言兼容，并可安全运行于单场事务中。
- [ ] **步骤 4：** 运行 `pytest tests/test_repository.py -q`，确认仓储测试全部通过。
- [ ] **步骤 5：** 提交：`git commit -m "feat: persist matches and odds snapshots"`。

### 任务 4：单场失败隔离的同步服务

**文件：**
- 新建：`src/services/__init__.py`
- 新建：`src/services/sync_service.py`
- 新建：`tests/test_sync_service.py`

**接口：**
- 使用：客户端协议、Session 工厂、解析函数和仓储。
- 产出：`SyncService.run() -> SyncSummary`，包含新增/更新比赛数、新增赔率数、回填赛果数、赔率冲突和失败详情。

- [ ] **步骤 1：** 编写失败的行为测试，证明连续同步两次保持幂等、已开奖赛果会被回填、已从当前列表消失的未完成比赛仍会重查，以及单场异常只回滚该场。
- [ ] **步骤 2：** 运行 `pytest tests/test_sync_service.py -q`，确认因同步服务缺失而失败。
- [ ] **步骤 3：** 实现当前赛程发现、数据库待完成比赛并集、按日期批量查询赛果，以及带异常隔离的逐场事务。
- [ ] **步骤 4：** 运行 `pytest tests/test_sync_service.py -q`，确认同步服务测试全部通过。
- [ ] **步骤 5：** 提交：`git commit -m "feat: orchestrate HAD synchronization"`。

### 任务 5：CLI、建表、配置与使用文档

**文件：**
- 替换：`src/main.py`
- 修改：`requirements.txt`
- 替换：`README.md`
- 新建：`tests/test_main.py`

**接口：**
- 使用：`SyncService`、`SessionLocal`、SQLAlchemy metadata 和配置。
- 产出：`python -m src.main sync`；在标准输出打印 JSON 汇总；没有比赛失败时退出码为 0，有失败时为 1。

- [ ] **步骤 1：** 编写失败的 CLI 测试，通过注入同步服务验证 JSON 输出和成功/失败退出码。
- [ ] **步骤 2：** 运行 `pytest tests/test_main.py -q`，确认因 CLI 契约缺失而失败。
- [ ] **步骤 3：** 实现 CLI 装配、同步前建表、环境变量与执行方式文档，并把 pytest 加入开发依赖。
- [ ] **步骤 4：** 运行 `pytest -q`，确认完整测试套件通过。
- [ ] **步骤 5：** 运行 `python -m src.main --help`，确认帮助信息正常且不泄露配置秘密。
- [ ] **步骤 6：** 提交：`git commit -m "feat: expose one-shot HAD sync command"`。

