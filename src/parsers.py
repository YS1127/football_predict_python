"""将官网 JSON 严格转换为领域数据。

解析器遵循“字段不可信直到校验通过”：响应失败、关键字段缺失、赔率非法、比分格式
错误或比分与 winFlag 矛盾都会抛出 ParseError，调用方因此不会把部分脏数据写入数据库。
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.domain import LeagueData, MatchData, MatchResultData, OddsSnapshotData


class ParseError(ValueError):
    """官网响应结构或业务字段不满足预期契约。"""

    pass


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """校验所有接口共用的 success/errorCode/value 响应外壳。"""
    if not isinstance(payload, dict) or payload.get("success") is not True or str(payload.get("errorCode")) != "0":
        raise ParseError(f"官网响应失败: {payload.get('errorMessage', '未知错误') if isinstance(payload, dict) else '非对象'}")
    value = payload.get("value")
    if not isinstance(value, dict):
        raise ParseError("官网响应缺少 value")
    return value


def _required(item: dict[str, Any], key: str) -> Any:
    """读取必填字段；数字 0 是合法值，因此只拒绝 None 和空字符串。"""
    value = item.get(key)
    if value is None or value == "":
        raise ParseError(f"缺少必填字段 {key}")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    """以 Decimal 解析正数赔率，避免 float 带来的二进制精度误差。"""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ParseError(f"字段 {field} 不是有效赔率") from exc
    if result <= 0:
        raise ParseError(f"字段 {field} 必须大于零")
    return result


def parse_schedule(payload: dict[str, Any]) -> list[MatchData]:
    """解析当前赛程，仅返回确实包含 HAD 市场的比赛。"""
    groups = _envelope(payload).get("matchInfoList")
    if not isinstance(groups, list):
        raise ParseError("缺少 value.matchInfoList")
    matches: list[MatchData] = []
    for group in groups:
        items = group.get("subMatchList") if isinstance(group, dict) else None
        if not isinstance(items, list):
            raise ParseError("缺少 subMatchList")
        for item in items:
            had = item.get("had")
            if not isinstance(had, dict) or not had:
                continue
            match_date = str(_required(item, "matchDate"))
            match_time = str(_required(item, "matchTime"))
            matches.append(MatchData(
                official_match_id=int(_required(item, "matchId")),
                match_number=str(_required(item, "matchNumStr")),
                business_date=date.fromisoformat(str(_required(item, "businessDate"))),
                match_date=date.fromisoformat(match_date),
                league_id=int(_required(item, "leagueId")),
                league_name=str(_required(item, "leagueAllName")),
                home_team=str(_required(item, "homeTeamAllName")),
                away_team=str(_required(item, "awayTeamAllName")),
                kickoff_at=datetime.fromisoformat(f"{match_date} {match_time}"),
                match_status=str(_required(item, "matchStatus")),
                sale_status=int(_required(item, "sellStatus")),
                is_valid=True,
            ))
    return matches


def parse_leagues(payload: dict[str, Any]) -> list[LeagueData]:
    """从当前赛程或历史赛果响应中提取并按官网 ID 去重联赛。

    两个官网接口使用不同字段名，因此先识别响应形态，再映射为统一 LeagueData。
    同一响应重复出现同一联赛时保留第一次，契合数据库“只保存一次”的规则。
    """
    value = _envelope(payload)
    candidates: list[tuple[dict[str, Any], str, str]] = []
    groups = value.get("matchInfoList")
    if isinstance(groups, list):
        for group in groups:
            for row in group.get("subMatchList", []) if isinstance(group, dict) else []:
                candidates.append((row, "leagueAbbName", "leagueAllName"))
    rows = value.get("matchResult")
    if isinstance(rows, list):
        candidates.extend((row, "leagueNameAbbr", "leagueName") for row in rows)
    if not candidates and not isinstance(groups, list) and not isinstance(rows, list):
        raise ParseError("响应中没有可识别的比赛列表")

    leagues: dict[int, LeagueData] = {}
    for row, abbreviation_key, full_name_key in candidates:
        league_id = int(_required(row, "leagueId"))
        leagues.setdefault(league_id, LeagueData(
            official_league_id=league_id,
            abbreviation=str(_required(row, abbreviation_key)),
            full_name=str(_required(row, full_name_key)),
        ))
    return list(leagues.values())


def parse_historical_schedule(payload: dict[str, Any]) -> list[MatchData]:
    """从历史赛果响应提取可确认的赛程信息。

    官网历史接口没有 matchTime 和 businessDate，因此 kickoff_at 保持为空，
    match_date 使用官方 matchDate，business_date 同样回退为 matchDate。只有 h/d/a
    三项均存在的记录才属于本项目 HAD 范围。文字“无效场次”仍保留比赛身份，
    但由 is_valid=False 阻止任何比分、结果和奖金入库。
    """
    rows = _envelope(payload).get("matchResult")
    if not isinstance(rows, list):
        raise ParseError("缺少 value.matchResult")
    matches: list[MatchData] = []
    for row in rows:
        if any(row.get(key) in (None, "") for key in ("h", "d", "a")):
            continue
        match_date = date.fromisoformat(str(_required(row, "matchDate")))
        matches.append(MatchData(
            official_match_id=int(_required(row, "matchId")),
            match_number=str(_required(row, "matchNumStr")),
            business_date=match_date,
            match_date=match_date,
            league_id=int(_required(row, "leagueId")),
            league_name=str(_required(row, "leagueName")),
            home_team=str(_required(row, "allHomeTeam")),
            away_team=str(_required(row, "allAwayTeam")),
            kickoff_at=None,
            match_status=str(row.get("poolStatus") or "Payout"),
            sale_status=None,
            is_valid=str(row.get("sectionsNo999") or "").strip() != "无效场次",
        ))
    return matches


def parse_detail(payload: dict[str, Any], expected_match_id: int) -> tuple[list[OddsSnapshotData], Decimal | None]:
    """解析一场比赛的全部 HAD 快照和可选的 HAD 开奖固定奖金。

    官网详情接口由 matchId 查询，仍需校验响应中的 ID，以阻止缓存串场或上游异常
    导致赔率被关联到错误比赛。
    """
    value = _envelope(payload)
    history = value.get("oddsHistory")
    if not isinstance(history, dict):
        raise ParseError("缺少 value.oddsHistory")
    actual_match_id = int(_required(history, "matchId"))
    if actual_match_id != expected_match_id:
        raise ParseError(f"比赛编号不匹配: {actual_match_id}")
    rows = history.get("hadList")
    if not isinstance(rows, list):
        raise ParseError("缺少 oddsHistory.hadList")
    odds = [OddsSnapshotData(
        official_match_id=actual_match_id,
        home=_decimal(_required(row, "h"), "h"),
        draw=_decimal(_required(row, "d"), "d"),
        away=_decimal(_required(row, "a"), "a"),
        official_updated_at=datetime.fromisoformat(
            f"{_required(row, 'updateDate')} {_required(row, 'updateTime')}"
        ),
    ) for row in rows]
    payout = None
    results = value.get("matchResultList", [])
    if not isinstance(results, list):
        raise ParseError("matchResultList 必须为数组")
    for result in results:
        if str(result.get("code", "")).upper() == "HAD":
            payout = _decimal(_required(result, "odds"), "HAD payout")
            break
    return odds, payout


def parse_results(payload: dict[str, Any]) -> dict[int, MatchResultData]:
    """解析已完场赛果，并用全场比分交叉验证官网 winFlag。"""
    rows = _envelope(payload).get("matchResult")
    if not isinstance(rows, list):
        raise ParseError("缺少 value.matchResult")
    results: dict[int, MatchResultData] = {}
    for row in rows:
        score = row.get("sectionsNo999")
        final = str(row.get("matchResultStatus")) == "2" or str(row.get("poolStatus", "")).lower() == "payout"
        if not final or not score:
            continue
        # 官网会把取消或作废比赛的全场比分明确标记为“无效场次”。这类记录没有
        # 可入库的比分/HAD 结果，应跳过该场，而不能让它阻断同一日期的正常比赛。
        if str(score).strip() == "无效场次":
            continue
        parts = str(score).split(":")
        if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
            raise ParseError(f"全场比分格式无效: {score}")
        home, away = (int(part) for part in parts)
        # HAD 不含让球：直接比较常规时间全场比分即可得到 H/D/A。
        derived = "H" if home > away else "A" if home < away else "D"
        # 部分官网历史记录不返回 winFlag。HAD 本身不含让球，因此全场比分足以
        # 唯一推导赛果；仅在上游提供 winFlag 时做交叉校验，避免拒绝可信比分。
        upstream = str(row.get("winFlag") or "").upper()
        if upstream and upstream != derived:
            raise ParseError(f"比赛 {row.get('matchId')} 的比分和胜平负结果不一致")
        match_id = int(_required(row, "matchId"))
        results[match_id] = MatchResultData(match_id, home, away, home + away, derived)
    return results


def parse_invalid_match_ids(payload: dict[str, Any]) -> set[int]:
    """返回官网明确标记为“无效场次”的比赛 ID，不推断延期或暂无赛果。"""
    rows = _envelope(payload).get("matchResult")
    if not isinstance(rows, list):
        raise ParseError("缺少 value.matchResult")
    return {
        int(_required(row, "matchId"))
        for row in rows
        if str(row.get("sectionsNo999") or "").strip() == "无效场次"
    }
