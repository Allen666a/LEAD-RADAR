from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy.orm import Session

from app.models import Keyword, Mention, Prospect, Source
from app.services.analytics import build_keyword_attribution
from app.services.feedback import FeedbackRow, build_feedback_board
from app.services.performance import platform_from_source
from app.services.prospects import rebuild_prospects


POSITIVE_STATUSES = {"contacted", "wechat_added", "trial_sent", "follow_up", "won"}
TRIAL_STATUSES = {"trial_sent", "follow_up", "won"}
NEGATIVE_STATUSES = {"invalid"}


@dataclass(frozen=True)
class LearnedWeight:
    dimension: str
    name: str
    prospects: int
    contacted: int
    trial_sent: int
    won: int
    invalid: int
    events: int
    score: int
    confidence: float
    delta: int


@dataclass(frozen=True)
class SourceLearningRow:
    source_id: int
    source_name: str
    platform: str
    quality_score: int
    feedback_score: int
    learned_priority: int
    status: str
    reason: str
    enabled: bool


@dataclass(frozen=True)
class KeywordLearningRow:
    keyword: str
    mentions: int
    prospects: int
    contacted: int
    trial_sent: int
    won: int
    invalid: int
    avg_score: int
    current_weight: int
    new_weight: int
    delta: int
    status: str
    reason: str
    enabled: bool
    tracked: bool


@dataclass(frozen=True)
class LearningReport:
    platform_weights: list[LearnedWeight]
    customer_type_weights: list[LearnedWeight]
    source_rows: list[SourceLearningRow]
    keyword_rows: list[KeywordLearningRow]
    prospects_adjusted: int
    sources_adjusted: int
    sources_paused: int
    sources_boosted: int
    keywords_adjusted: int
    keywords_paused: int
    keywords_boosted: int


def run_feedback_learning(db: Session, apply: bool = True) -> dict[str, object]:
    if apply:
        rebuild_prospects(db)
    report = build_learning_report(db, apply=apply)
    return {
        "platform_weights": [weight.__dict__ for weight in report.platform_weights[:20]],
        "customer_type_weights": [weight.__dict__ for weight in report.customer_type_weights[:20]],
        "top_sources": [row.__dict__ for row in report.source_rows[:30]],
        "top_keywords": [row.__dict__ for row in report.keyword_rows[:30]],
        "prospects_adjusted": report.prospects_adjusted,
        "sources_adjusted": report.sources_adjusted,
        "sources_paused": report.sources_paused,
        "sources_boosted": report.sources_boosted,
        "keywords_adjusted": report.keywords_adjusted,
        "keywords_paused": report.keywords_paused,
        "keywords_boosted": report.keywords_boosted,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_learning_report(db: Session, apply: bool = False) -> LearningReport:
    board = build_feedback_board(db)
    platform_weights = [learned_weight("platform", row) for row in board.platform_rows]
    customer_type_weights = [learned_weight("customer_type", row) for row in board.customer_type_rows]
    platform_map = {weight.name: weight for weight in platform_weights}
    customer_type_map = {weight.name: weight for weight in customer_type_weights}

    prospects_adjusted = 0
    if apply:
        prospects_adjusted = apply_prospect_learning(db, platform_map, customer_type_map)

    source_rows = build_source_learning_rows(db, platform_map)
    sources_adjusted = 0
    sources_paused = 0
    sources_boosted = 0
    if apply:
        sources_adjusted, sources_paused, sources_boosted = apply_source_learning(db, source_rows)

    keyword_rows = build_keyword_learning_rows(db)
    keywords_adjusted = 0
    keywords_paused = 0
    keywords_boosted = 0
    if apply:
        keywords_adjusted, keywords_paused, keywords_boosted = apply_keyword_learning(db, keyword_rows)

    return LearningReport(
        platform_weights=sorted(platform_weights, key=lambda item: (item.delta, item.score), reverse=True),
        customer_type_weights=sorted(customer_type_weights, key=lambda item: (item.delta, item.score), reverse=True),
        source_rows=sorted(source_rows, key=lambda item: item.learned_priority, reverse=True),
        keyword_rows=sorted(
            keyword_rows,
            key=lambda item: (item.status == "boost", item.delta, item.won, item.trial_sent, item.prospects),
            reverse=True,
        ),
        prospects_adjusted=prospects_adjusted,
        sources_adjusted=sources_adjusted,
        sources_paused=sources_paused,
        sources_boosted=sources_boosted,
        keywords_adjusted=keywords_adjusted,
        keywords_paused=keywords_paused,
        keywords_boosted=keywords_boosted,
    )


def learned_weight(dimension: str, row: FeedbackRow) -> LearnedWeight:
    evidence = row.events + row.contacted + row.trial_sent * 2 + row.won * 4 + row.invalid
    confidence = min(1.0, evidence / 20)
    if evidence == 0:
        return LearnedWeight(
            dimension=dimension,
            name=row.name,
            prospects=row.prospects,
            contacted=row.contacted,
            trial_sent=row.trial_sent,
            won=row.won,
            invalid=row.invalid,
            events=row.events,
            score=row.score,
            confidence=0,
            delta=0,
        )
    raw_delta = (row.score - 50) / 2.5
    if row.prospects >= 10 and row.contacted == 0:
        raw_delta -= 6
    if row.invalid_rate >= 0.35 and row.prospects >= 5:
        raw_delta -= 8
    if row.trial_sent or row.won:
        raw_delta += min(row.trial_sent * 2 + row.won * 5, 12)
    delta = round(clamp(raw_delta * max(confidence, 0.25), -14, 18))
    if row.prospects < 3 and row.events == 0:
        delta = 0
        confidence = 0
    return LearnedWeight(
        dimension=dimension,
        name=row.name,
        prospects=row.prospects,
        contacted=row.contacted,
        trial_sent=row.trial_sent,
        won=row.won,
        invalid=row.invalid,
        events=row.events,
        score=row.score,
        confidence=round(confidence, 2),
        delta=delta,
    )


def apply_prospect_learning(
    db: Session,
    platform_weights: dict[str, LearnedWeight],
    customer_type_weights: dict[str, LearnedWeight],
) -> int:
    adjusted = 0
    for prospect in db.query(Prospect).all():
        platform_delta = platform_weights.get(prospect.platform)
        type_delta = customer_type_weights.get(prospect.customer_type)
        delta = 0
        if platform_delta:
            delta += round(platform_delta.delta * 0.6)
        if type_delta:
            delta += round(type_delta.delta * 0.4)
        if prospect.status == "won":
            delta += 10
        elif prospect.status == "trial_sent":
            delta += 6
        elif prospect.status == "invalid":
            delta -= 18
        previous_delta = previous_learning_delta(prospect.next_action)
        if delta == 0 and previous_delta == 0:
            continue
        old_score = prospect.lead_score or 0
        base_score = old_score - previous_delta
        prospect.lead_score = int(clamp(base_score + delta, 0, 100))
        prospect.next_action = append_learning_note(prospect.next_action, delta)
        prospect.updated_at = datetime.now()
        adjusted += 1
    db.commit()
    return adjusted


def build_source_learning_rows(
    db: Session,
    platform_weights: dict[str, LearnedWeight],
) -> list[SourceLearningRow]:
    mentions_by_source: dict[str, list[Mention]] = defaultdict(list)
    for mention in db.query(Mention).all():
        mentions_by_source[mention.source_name].append(mention)
    prospects_by_id = {prospect.id: prospect for prospect in db.query(Prospect).all()}

    rows: list[SourceLearningRow] = []
    for source in db.query(Source).all():
        platform = platform_from_source(source.name, source.kind, source.url)
        prospects = [
            prospects_by_id[mention.prospect_id]
            for mention in mentions_by_source.get(source.name, [])
            if mention.prospect_id in prospects_by_id
        ]
        rows.append(build_source_row(source, platform, prospects, platform_weights.get(platform)))
    return rows


def build_source_row(
    source: Source,
    platform: str,
    prospects: list[Prospect],
    platform_weight: LearnedWeight | None,
) -> SourceLearningRow:
    unique_prospects = list({prospect.id: prospect for prospect in prospects}.values())
    status_counts = Counter(prospect.status for prospect in unique_prospects)
    contacted = sum(status_counts.get(status, 0) for status in POSITIVE_STATUSES)
    trial_sent = sum(status_counts.get(status, 0) for status in TRIAL_STATUSES)
    won = status_counts.get("won", 0)
    invalid = status_counts.get("invalid", 0)
    total = len(unique_prospects)
    quality_score = source.quality_score or 50
    platform_delta = platform_weight.delta if platform_weight else 0
    evidence = contacted + trial_sent * 2 + won * 4 + invalid
    if evidence:
        direct_delta = min(won * 22 + trial_sent * 10 + contacted * 4, 42) - min(invalid * 12, 30)
        if total >= 10 and contacted == 0:
            direct_delta -= 12
    else:
        direct_delta = 0
    feedback_score = int(clamp(50 + platform_delta + direct_delta, 0, 100))
    learned_priority = int(
        clamp(
            quality_score * 0.58
            + feedback_score * 0.30
            + min(source.last_inserted_count or 0, 12)
            - min(source.consecutive_failures or 0, 4) * 6,
            0,
            100,
        )
    )
    status = "neutral"
    if learned_priority >= 76:
        status = "boost"
    elif learned_priority <= 32 and (source.success_count or 0) >= 2:
        status = "cooldown"
    elif learned_priority >= 56:
        status = "keep"
    return SourceLearningRow(
        source_id=source.id,
        source_name=source.name,
        platform=platform,
        quality_score=quality_score,
        feedback_score=feedback_score,
        learned_priority=learned_priority,
        status=status,
        reason=build_source_reason(
            quality_score=quality_score,
            feedback_score=feedback_score,
            platform_delta=platform_delta,
            contacted=contacted,
            trial_sent=trial_sent,
            won=won,
            invalid=invalid,
            prospects=total,
        ),
        enabled=source.enabled,
    )


def apply_source_learning(db: Session, rows: list[SourceLearningRow]) -> tuple[int, int, int]:
    adjusted = 0
    paused = 0
    boosted = 0
    for row in rows:
        source = db.get(Source, row.source_id)
        if source is None:
            continue
        source.feedback_score = row.feedback_score
        source.learned_priority = row.learned_priority
        source.learning_status = row.status
        source.learning_reason = row.reason
        source.learning_updated_at = datetime.now()
        if row.status == "cooldown" and source.enabled:
            source.enabled = False
            source.auto_disabled_at = datetime.now()
            paused += 1
        elif row.status == "boost" and not source.enabled and row.learned_priority >= 82:
            source.enabled = True
            boosted += 1
        adjusted += 1
    db.commit()
    return adjusted, paused, boosted


def build_keyword_learning_rows(db: Session) -> list[KeywordLearningRow]:
    tracked_keywords = {keyword.phrase: keyword for keyword in db.query(Keyword).all()}
    rows: list[KeywordLearningRow] = []
    for row in build_keyword_attribution(db):
        tracked = tracked_keywords.get(row.keyword)
        current_weight = tracked.weight if tracked else 10
        delta, status, reason = keyword_delta_reason(row)
        new_weight = int(clamp(current_weight + delta, 1, 100))
        rows.append(
            KeywordLearningRow(
                keyword=row.keyword,
                mentions=row.mentions,
                prospects=row.prospects,
                contacted=row.contacted,
                trial_sent=row.trial_sent,
                won=row.won,
                invalid=row.invalid,
                avg_score=row.avg_score,
                current_weight=current_weight,
                new_weight=new_weight,
                delta=delta,
                status=status,
                reason=reason,
                enabled=tracked.enabled if tracked else True,
                tracked=tracked is not None,
            )
        )
    return rows


def keyword_delta_reason(row) -> tuple[int, str, str]:
    invalid_rate = row.invalid / row.prospects if row.prospects else 0
    contact_rate = row.contacted / row.prospects if row.prospects else 0
    delta = 0
    reasons: list[str] = []

    if row.won:
        add = min(row.won * 12, 24)
        delta += add
        reasons.append(f"成交 {row.won} 个")
    if row.trial_sent:
        add = min(row.trial_sent * 6, 18)
        delta += add
        reasons.append(f"测试/试用 {row.trial_sent} 个")
    if row.contacted and contact_rate >= 0.2:
        delta += 4
        reasons.append(f"可推进率 {contact_rate:.0%}")
    if row.high_value_mentions >= 3 and row.avg_score >= 60:
        delta += 5
        reasons.append(f"高意向信号 {row.high_value_mentions} 条")

    if row.prospects >= 5 and row.contacted == 0 and row.won == 0 and row.trial_sent == 0:
        delta -= 8
        reasons.append("有线索但没有推进")
    if invalid_rate >= 0.35 and row.prospects >= 3:
        delta -= 10
        reasons.append(f"无效率 {invalid_rate:.0%}")
    if row.mentions >= 8 and row.prospects == 0:
        delta -= 12
        reasons.append("只带来噪音，没有形成客户")
    if row.avg_score < 35 and row.mentions >= 5:
        delta -= 5
        reasons.append(f"平均线索分 {row.avg_score}")

    delta = round(clamp(delta, -18, 24))
    if delta >= 8:
        status = "boost"
    elif delta <= -8:
        status = "cooldown"
    elif delta > 0:
        status = "raise"
    elif delta < 0:
        status = "lower"
    else:
        status = "keep"
        reasons.append("反馈不足，先保持")

    return delta, status, "；".join(reasons)


def apply_keyword_learning(db: Session, rows: list[KeywordLearningRow]) -> tuple[int, int, int]:
    keywords = {keyword.phrase: keyword for keyword in db.query(Keyword).all()}
    adjusted = 0
    paused = 0
    boosted = 0
    for row in rows:
        keyword = keywords.get(row.keyword)
        if keyword is None or row.delta == 0:
            continue
        keyword.weight = row.new_weight
        if row.status == "cooldown" and row.mentions >= 5 and row.prospects == 0:
            keyword.enabled = False
            paused += 1
        elif row.status == "cooldown" and row.invalid >= 3 and row.new_weight <= 12:
            keyword.enabled = False
            paused += 1
        elif row.status == "boost":
            if not keyword.enabled:
                boosted += 1
            keyword.enabled = True
        adjusted += 1
    db.commit()
    return adjusted, paused, boosted


def build_source_reason(
    quality_score: int,
    feedback_score: int,
    platform_delta: int,
    contacted: int,
    trial_sent: int,
    won: int,
    invalid: int,
    prospects: int,
) -> str:
    return (
        f"质量分 {quality_score}，反馈分 {feedback_score}，平台学习 {platform_delta:+d}；"
        f"客户 {prospects}，触达 {contacted}，测试 {trial_sent}，成交 {won}，无效 {invalid}。"
    )


def append_learning_note(old: str, delta: int) -> str:
    marker = "学习权重"
    old = (old or "").strip()
    lines = [line for line in old.splitlines() if marker not in line]
    if delta == 0:
        return "\n".join(line for line in lines if line).strip()
    note = f"{marker}{delta:+d}：根据平台和客户类型反馈自动微调优先级。"
    lines.append(note)
    return "\n".join(line for line in lines if line).strip()


def previous_learning_delta(value: str | None) -> int:
    if not value or "学习权重" not in value:
        return 0
    match = re.search(r"学习权重([+-]\d+)", value)
    if not match:
        return 0
    return int(match.group(1))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
