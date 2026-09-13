"""只读的 FastAPI 接口。

HTTP 层只负责参数校验、调用 SportteryClient、执行纯解析和生成稳定 JSON；它不创建
数据库连接，也不会触发 MySQL 写入。接口统一返回解析后的领域字段，避免调用方依赖
中国竞彩网未经文档化的原始响应结构。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from src.crawler.match_crawler import SportteryClient, UpstreamError
from src.parsers import ParseError, parse_detail, parse_results, parse_schedule


class ApiModel(BaseModel):
    """API 响应模型基类，允许直接从不可变领域 dataclass 读取属性。"""

    model_config = ConfigDict(from_attributes=True)


class MatchResponse(ApiModel):
    """统一赛程字段，不暴露官网内部对象结构。"""

    official_match_id: int
    match_number: str
    business_date: date
    match_date: date
    league_id: int
    league_name: str
    home_team: str
    away_team: str
    kickoff_at: datetime
    match_status: str
    sale_status: int
    is_valid: bool


class OddsSnapshotResponse(ApiModel):
    """官网某一发布时间对应的一组三项 HAD 赔率。"""

    official_match_id: int
    home: Decimal
    draw: Decimal
    away: Decimal
    official_updated_at: datetime
    source: str


class DetailResponse(ApiModel):
    """一场比赛的完整 HAD 赔率轨迹和可选开奖固定奖金。"""

    official_match_id: int
    odds_snapshots: list[OddsSnapshotResponse]
    payout: Decimal | None


class ResultResponse(ApiModel):
    """常规时间加伤停补时口径的统一赛果。"""

    official_match_id: int
    home_goals: int
    away_goals: int
    total_goals: int
    had_result: str


def _success(data) -> dict:
    """生成所有成功接口共用的响应外壳。"""
    return {"success": True, "data": data}


def create_app(
    client_factory: Callable[[], SportteryClient] = SportteryClient,
) -> FastAPI:
    """创建 FastAPI 应用。

    客户端使用工厂注入：生产环境默认创建官网客户端，测试环境可注入固定样本客户端，
    从而保证单元测试不访问官网。每个请求获得独立客户端，避免跨请求共享可变状态。
    """
    application = FastAPI(
        title="竞彩足球 HAD 数据接口",
        version="1.0.0",
        description="读取并解析中国竞彩网赛程、HAD 赔率历史和赛果。",
    )

    def get_client():
        """FastAPI 依赖函数：为当前请求构造官网客户端。"""
        return client_factory()

    @application.exception_handler(UpstreamError)
    async def handle_upstream_error(_request: Request, exc: UpstreamError):
        """将网络、限流及官网 HTTP 错误转换为稳定的 502 JSON。"""
        return JSONResponse(
            status_code=502,
            content={"success": False, "error": str(exc)},
        )

    @application.exception_handler(ParseError)
    async def handle_parse_error(_request: Request, exc: ParseError):
        """官网字段不可信时返回 502，不向调用方泄露完整原始响应。"""
        return JSONResponse(
            status_code=502,
            content={"success": False, "error": str(exc)},
        )

    @application.get("/api/schedule", summary="获取当前 HAD 赛程")
    def schedule(client=Depends(get_client)):
        """调用当前赛程接口并返回经过严格校验的统一比赛列表。"""
        matches = [MatchResponse.model_validate(item).model_dump(mode="json")
                   for item in parse_schedule(client.fetch_schedule())]
        return _success(matches)

    @application.get("/api/matches/{match_id}/detail", summary="获取比赛 HAD 赔率历史")
    def detail(
        match_id: int = Path(gt=0, description="中国官网比赛 ID"),
        client=Depends(get_client),
    ):
        """返回指定比赛的全部 HAD 快照及开奖固定奖金。"""
        snapshots, payout = parse_detail(client.fetch_detail(match_id), match_id)
        result = DetailResponse(
            official_match_id=match_id,
            odds_snapshots=[OddsSnapshotResponse.model_validate(item) for item in snapshots],
            payout=payout,
        )
        return _success(result.model_dump(mode="json"))

    @application.get("/api/results", summary="按日期范围获取赛果")
    def results(
        begin: date = Query(description="开始日期，格式 YYYY-MM-DD"),
        end: date = Query(description="结束日期，格式 YYYY-MM-DD"),
        client=Depends(get_client),
    ):
        """返回闭区间内的赛果；最多 31 天以限制单次官网请求规模。"""
        if begin > end:
            raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
        if (end - begin).days > 30:
            raise HTTPException(status_code=422, detail="日期范围最多为 31 天")
        parsed = parse_results(client.fetch_results(begin, end))
        normalized = [
            ResultResponse.model_validate(item).model_dump(mode="json")
            for item in parsed.values()
        ]
        return _success(normalized)

    return application


# Uvicorn 通过 `src.api:app` 导入此对象。这里仅构建路由，不会连接官网或 MySQL。
app = create_app()
