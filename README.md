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
```

数据库需提前创建并授予该用户建表及读写权限。首次同步会自动创建 `matches` 和 `odds_snapshots` 表，不会在日志或输出中打印数据库密码。

## 执行同步

```bash
.venv/bin/python -m src.main sync
```

命令在标准输出打印 JSON 汇总，包括新增/更新比赛、插入赔率、回填赛果、赔率冲突和失败列表。没有单场失败时退出码为 `0`；存在失败时为 `1`，其他比赛仍会继续处理。

## 测试

```bash
.venv/bin/python -m pytest -q
```

单元测试使用本地 JSON 样本和 SQLite 内存库，不访问官网，也不会连接生产 MySQL。若补充 MySQL 集成测试，必须通过独立测试库配置运行。
