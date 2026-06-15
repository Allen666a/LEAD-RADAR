from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Mention, Prospect, Source
from app.services.signals import HIGH_VALUE_SIGNALS


AUTO_DISABLE_FAILURES = 2
LOW_YIELD_SUCCESS_RUNS = 4
LOW_YIELD_FETCHED_COUNT = 30


@dataclass(frozen=True)
class SourceQualityResult:
    score: int
    status: str
    reason: str
    should_disable: bool = False


def audit_all_sources(db: Session, auto_disable: bool = True) -> dict[str, int]:
    counters = {
        "audited": 0,
        "disabled": 0,
        "disable_candidates": 0,
        "excellent": 0,
        "good": 0,
        "low_yield": 0,
        "blocked": 0,
        "unstable": 0,
        "unchecked": 0,
    }

    for source in db.query(Source).all():
        result = evaluate_source_quality(db, source, auto_disable=auto_disable)
        counters["audited"] += 1
        counters[result.status] = counters.get(result.status, 0) + 1
        if result.should_disable:
            counters["disable_candidates"] += 1
            if auto_disable:
                counters["disabled"] += 1

    db.commit()
    return counters


def evaluate_source_quality(
    db: Session,
    source: Source,
    auto_disable: bool = True,
) -> SourceQualityResult:
    total_mentions = (
        db.query(Mention)
        .filter(Mention.source_name == source.name)
        .filter(Mention.status != "invalid")
        .count()
    )
    high_value_mentions = (
        db.query(Mention)
        .filter(Mention.source_name == source.name)
        .filter(Mention.status != "invalid")
        .filter(Mention.signal_type.in_(HIGH_VALUE_SIGNALS))
        .filter(Mention.score >= 60)
        .count()
    )
    risk_mentions = (
        db.query(Mention)
        .filter(Mention.source_name == source.name)
        .filter(Mention.signal_type == "risk_signal")
        .count()
    )
    source_prospect_ids = [
        row[0]
        for row in db.query(Mention.prospect_id)
        .filter(Mention.source_name == source.name)
        .filter(Mention.prospect_id.is_not(None))
        .distinct()
        .all()
    ]
    prospects = (
        db.query(Prospect)
        .filter(Prospect.id.in_(source_prospect_ids))
        .all()
        if source_prospect_ids
        else []
    )
    trial_count = sum(1 for prospect in prospects if prospect.status in {"trial_sent", "follow_up", "won"})
    won_count = sum(1 for prospect in prospects if prospect.status == "won")
    invalid_count = sum(1 for prospect in prospects if prospect.status == "invalid")
    invalid_mentions = (
        db.query(Mention)
        .filter(Mention.source_name == source.name)
        .filter(Mention.status == "invalid")
        .count()
    )

    result = calculate_quality(
        source,
        total_mentions,
        high_value_mentions,
        risk_mentions,
        trial_count=trial_count,
        won_count=won_count,
        invalid_count=max(invalid_count, invalid_mentions),
    )
    source.quality_score = result.score
    source.quality_status = result.status
    source.quality_reason = result.reason
    source.last_quality_at = datetime.now()

    if auto_disable and result.should_disable and source.enabled:
        source.enabled = False
        source.auto_disabled_at = datetime.now()

    return result


def calculate_quality(
    source: Source,
    total_mentions: int,
    high_value_mentions: int,
    risk_mentions: int,
    trial_count: int = 0,
    won_count: int = 0,
    invalid_count: int = 0,
) -> SourceQualityResult:
    success_count = source.success_count or 0
    failure_count = source.failure_count or 0
    consecutive_failures = source.consecutive_failures or 0
    attempts = success_count + failure_count
    last_fetched = source.last_fetched_count or 0
    last_inserted = source.last_inserted_count or 0
    error = (source.last_error or "").lower()

    if attempts == 0:
        return SourceQualityResult(50, "unchecked", "尚未采集，等待首次质量评估。")

    blocked = is_blocked_error(error)
    if blocked and consecutive_failures >= AUTO_DISABLE_FAILURES:
        return SourceQualityResult(
            5,
            "blocked",
            f"连续失败 {consecutive_failures} 次，最近错误疑似限流/权限/反爬：{short_error(source.last_error)}",
            should_disable=True,
        )

    if consecutive_failures >= 5:
        return SourceQualityResult(
            15,
            "unstable",
            f"连续失败 {consecutive_failures} 次，来源不稳定：{short_error(source.last_error)}",
            should_disable=True,
        )

    if (
        success_count >= LOW_YIELD_SUCCESS_RUNS
        and total_mentions == 0
        and last_fetched >= LOW_YIELD_FETCHED_COUNT
    ):
        return SourceQualityResult(
            25,
            "low_yield",
            f"已成功采集 {success_count} 次，但抓取 {last_fetched} 条后长期没有有效入库线索。",
            should_disable=True,
        )

    if success_count >= 1 and total_mentions == 0 and last_inserted == 0:
        score = max(20, min(45, 35 + round(source_success_rate(source) * 10) - min(failure_count * 4, 16)))
        return SourceQualityResult(
            score,
            "low_yield",
            f"已成功请求但暂无有效线索：最近抓取/入库 {last_fetched}/{last_inserted}，有效 0 条。",
        )

    if success_count >= 1 and total_mentions == 0 and invalid_count > 0:
        score = max(20, min(42, 38 + round(source_success_rate(source) * 8) - min(invalid_count * 4, 20)))
        return SourceQualityResult(
            score,
            "low_yield",
            f"最近入库主要是垃圾：最近抓取/入库 {last_fetched}/{last_inserted}，有效 0 条，垃圾 {invalid_count} 条。",
        )

    success_rate = success_count / attempts
    insert_rate = last_inserted / last_fetched if last_fetched else 0
    high_value_rate = high_value_mentions / total_mentions if total_mentions else 0

    score = 35
    score += round(success_rate * 25)
    score += min(high_value_mentions * 4, 28)
    score += min(trial_count * 8, 24)
    score += min(won_count * 18, 36)
    score += min(total_mentions, 10)
    score += round(insert_rate * 10)
    score -= min(failure_count * 4, 20)
    score -= min(risk_mentions * 3, 12)
    score -= min(invalid_count * 5, 20)
    if last_inserted and invalid_count >= max(3, last_inserted * 0.7):
        score -= 18
    score = max(0, min(100, score))

    if score >= 80:
        return SourceQualityResult(
            score,
            "excellent",
            f"稳定且有高价值线索：高价值 {high_value_mentions} 条，测试 {trial_count} 个，成交 {won_count} 个，总入库 {total_mentions} 条。",
        )

    if score >= 55:
        return SourceQualityResult(
            score,
            "good",
            f"可继续观察：成功率 {success_rate:.0%}，高价值 {high_value_mentions} 条，测试 {trial_count} 个，成交 {won_count} 个，总入库 {total_mentions} 条。",
        )

    return SourceQualityResult(
        score,
        "low_yield",
        f"产出偏低：成功率 {success_rate:.0%}，最近抓取/入库 {last_fetched}/{last_inserted}，有效 {total_mentions} 条，高价值 {high_value_mentions} 条，垃圾 {invalid_count} 条。",
    )


def source_success_rate(source: Source) -> float:
    success_count = source.success_count or 0
    failure_count = source.failure_count or 0
    attempts = success_count + failure_count
    return success_count / attempts if attempts else 0.0


def is_blocked_error(error: str) -> bool:
    patterns = [
        "403",
        "401",
        "429",
        "rate limit",
        "forbidden",
        "unauthorized",
        "connecttimeout",
        "connecterror",
        "captcha",
    ]
    return any(pattern in error for pattern in patterns)


def short_error(error: str | None) -> str:
    if not error:
        return "无错误详情"
    return error.replace("\n", " ")[:160]
