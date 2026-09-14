# 竞彩足球 HAD 数据同步

单次运行程序，从中国竞彩网同步胜平负（HAD）赛程、官网完整赔率变化和完场赛果到 MySQL。重复运行保持幂等；同步服务不依赖 CLI，可供后续 HTTP 接口直接复用。

## 数据来源

- `getMatchCalculatorV1.qry`：当前 HAD 赛程和最新状态
- `getFixedBonusV1.qry`：指定比赛的完整 HAD 赔率历史及开奖固定奖金
- `getUniformMatchResultV1.qry`：官方常规时间全场比分和胜平负结果

程序仅采集 HAD，不采集让球胜平负、比分、总进球或半全场赔率。请遵守数据源的使用条款和访问限制，控制执行频率。

## 安装

项目要求 Python 3.12：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## MySQL 配置

在项目根目录创建 `.env`：

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=predict_football
DB_USER=your_user
DB_PASSWORD=your_password

# 以下均为可选配置
CRAWLER_TIMEOUT=30
CRAWLER_RETRY_LIMIT=3
CRAWLER_BACKOFF_SECONDS=0.5
CRAWLER_USER_AGENT=Mozilla/5.0
HISTORY_ODDS_REQUEST_INTERVAL_SECONDS=1.0
SCHEDULER_TIMEZONE=Asia/Shanghai
DAILY_MATCH_SYNC_ENABLED=true
DAILY_MATCH_SYNC_CRON=0 19 * * *
DAILY_MATCH_DETAIL_INTERVAL_SECONDS=1.0
RESULT_SYNC_ENABLED=true
RESULT_SYNC_CRON=0 14 * * *
SCHEDULER_MISFIRE_GRACE_SECONDS=3600
MANUAL_TRIGGER_API_KEY=replace-with-a-random-secret
```

数据库需提前创建并授予该用户建表及读写权限。首次同步会自动创建 `matches` 和 `odds_snapshots` 表，不会在日志或输出中打印数据库密码。

## 执行同步

```bash
.venv/bin/python -m src.main sync
```

命令在标准输出打印 JSON 汇总，包括新增/更新比赛、插入赔率、回填赛果、赔率冲突和失败列表。没有单场失败时退出码为 `0`；存在失败时为 `1`，其他比赛仍会继续处理。

按闭区间回填历史 HAD 赛程和赛果：

```bash
.venv/bin/python -m src.main backfill --start 2026-01-01 --end 2026-09-13
```

历史赛果接口不提供准确开赛时刻和销售状态，因此历史记录的 `match_date` 使用官网 `matchDate`，`kickoff_at` 和 `sale_status` 为 `NULL`，`business_date` 暂回退使用官网 `matchDate`。无效场次仍保留比赛身份，`is_valid` 为 `0`，但比分、总进球、HAD 结果和奖金全部为空。查询体彩顺序时应显式使用 `ORDER BY official_match_id ASC`，不依赖数据库自增主键或物理存储顺序。命令逐日请求、逐场提交，意外中断后可直接重复执行。

为历史有效比赛补齐完整 HAD 赔率变化和开奖固定奖金：

```bash
.venv/bin/python -m src.main backfill-odds --start 2026-01-01 --end 2026-09-13
```

程序按 `official_match_id ASC` 串行请求详情，默认在相邻请求间等待 1 秒，并每 50 场向标准错误输出进度。可通过 `.env` 的 `HISTORY_ODDS_REQUEST_INTERVAL_SECONDS` 增大间隔；不建议设为 0 或使用并发请求。

## 启动 HTTP API

```bash
.venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8000
```

服务启动后提供三个只读接口，均返回程序解析后的统一结构，不连接或写入 MySQL：

- `GET /api/schedule`：当前 HAD 赛程
- `GET /api/matches/{match_id}/detail`：指定比赛的完整 HAD 赔率历史和开奖奖金
- `GET /api/results?begin=2026-09-01&end=2026-09-12`：指定日期区间赛果，单次最多 31 天

交互式接口文档地址为 `http://127.0.0.1:8000/docs`。默认仅监听本机；确需局域网访问时再将 `--host` 改为 `0.0.0.0`，并自行配置防火墙和访问控制。

需要在 PyCharm 或 VS Code 中打断点时，可直接 Debug `src/run_api.py`，或执行：

```bash
.venv/bin/python -m src.run_api
```

该调试入口使用单进程且不启用自动重载，确保 `src/api.py`、`src/parsers.py` 和 `src/crawler/match_crawler.py` 中的断点可以稳定命中。

## 每日定时任务

```bash
.venv/bin/python -m src.main scheduler
```

默认每天 19:00 同步当天竞彩业务日赛程和完整 HAD 赔率，每天 14:00 回填昨日及更早积压比赛的赛果、最终赔率和开奖奖金。两个时间均通过 `.env` 的五段式 cron 配置。

单次手工 CLI：

```bash
.venv/bin/python -m src.main daily-match-sync
.venv/bin/python -m src.main result-sync
```

启动 FastAPI 后，也可使用受 API Key 保护的接口手动触发：

```bash
curl -X POST -H "X-API-Key: $MANUAL_TRIGGER_API_KEY" http://127.0.0.1:8000/api/tasks/daily-match-sync
curl -X POST -H "X-API-Key: $MANUAL_TRIGGER_API_KEY" http://127.0.0.1:8000/api/tasks/result-sync
```

未配置 Key 时接口禁用；Key 错误返回 401，任务正在运行返回 409。定时、CLI 和 HTTP 入口共享同一 MySQL 锁和业务服务。

## 测试

```bash
.venv/bin/python -m pytest -q
```

单元测试使用本地 JSON 样本和 SQLite 内存库，不访问官网，也不会连接生产 MySQL。若补充 MySQL 集成测试，必须通过独立测试库配置运行。

## Docker Compose

使用同一镜像启动 API 和定时调度器：

```bash
docker compose up -d --build
```

当前 Compose 默认加入已有的 `docker-compose-files_shiguang-network` 网络，并通过容器名 `shiguang_mysql8:3306` 访问 MySQL。MySQL 容器必须已启动：

```bash
docker ps --filter name=shiguang_mysql8
```

如果以后 MySQL 容器名或网络名变化，可以覆盖：

```bash
DOCKER_DB_HOST=other-mysql \
MYSQL_DOCKER_NETWORK=other-network \
docker compose up -d --build
```

查看运行状态与日志：

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f scheduler
```

停止服务：

```bash
docker compose down
```

`.env` 只在容器启动时注入，不会复制进镜像。API 默认映射到宿主机 8000 端口，可通过 `API_PORT=8080` 覆盖。
