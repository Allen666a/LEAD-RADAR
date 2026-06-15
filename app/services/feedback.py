from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Prospect, ProspectEvent


EVENT_LABELS = {
    "status_change": "状态变更",
    "contact_saved": "保存联系方式",
    "note_saved": "保存备注",
    "follow_up_scheduled": "安排复访",
    "outcome": "结果反馈",
}

STATUS_OUTCOMES = {
    "contacted": "已触达",
    "wechat_added": "已加微信",
    "trial_sent": "已发测试",
    "won": "已成交",
    "invalid": "无效",
    "follow_up": "待复访",
    "qualified": "已筛选",
    "new": "新客户",
}

POSITIVE_STATUSES = {"contacted", "wechat_added", "trial_sent", "follow_up", "won"}


@dataclass(frozen=True)
class FeedbackSummary:
    prospects: int
    contacted: int
    trial_sent: int
    won: int
    invalid: int
    events: int
    event_coverage: float


@dataclass(frozen=True)
class FeedbackRow:
    name: str
    prospects: int
    contacted: int
    trial_sent: int
    won: int
    invalid: int
    events: int
    score: int

    @property
    def contact_rate(self) -> float:
        return self.contacted / self.prospects if self.prospects else 0

    @property
    def trial_rate(self) -> float:
        return self.trial_sent / self.prospects if self.prospects else 0

    @property
    def win_rate(self) -> float:
        return self.won / self.prospects if self.prospects else 0

    @property
    def invalid_rate(self) -> float:
        return self.invalid / self.prospects if self.prospects else 0


@dataclass(frozen=True)
class FeedbackBoard:
    summary: FeedbackSummary
    platform_rows: list[FeedbackRow]
    customer_type_rows: list[FeedbackRow]
    recent_events: list[ProspectEvent]
    recommendations: list[str]


def record_prospect_event(
    db: Session,
    prospect: Prospect,
    event_type: str,
    value: str = "",
    note: str = "",
    commit: bool = True,
) -> ProspectEvent:
    event = ProspectEvent(
        prospect_id=prospect.id,
        identity_key=prospect.identity_key or "",
        event_type=event_type[:60],
        value=value[:160],
        note=note[:2000],
        platform=prospect.platform or "",
        customer_type=prospect.customer_type or "",
        product_fit=prospect.product_fit or "",
        lead_score=prospect.lead_score or 0,
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    return event


def load_prospect_events(db: Session, prospect_id: int, limit: int = 50) -> list[ProspectEvent]:
    return list(
        db.scalars(
            select(ProspectEvent)
            .where(ProspectEvent.prospect_id == prospect_id)
            .order_by(desc(ProspectEvent.created_at), desc(ProspectEvent.id))
            .limit(limit)
        )
    )


def build_feedback_board(db: Session) -> FeedbackBoard:
    prospects = list(db.scalars(select(Prospect)))
    events = list(db.scalars(select(ProspectEvent)))
    recent_events = list(
        db.scalars(
            select(ProspectEvent)
            .order_by(desc(ProspectEvent.created_at), desc(ProspectEvent.id))
            .limit(80)
        )
    )
    prospect_ids_with_events = {event.prospect_id for event in events}
    summary = FeedbackSummary(
        prospects=len(prospects),
        contacted=sum(1 for prospect in prospects if prospect.status in POSITIVE_STATUSES),
        trial_sent=sum(1 for prospect in prospects if prospect.status == "trial_sent"),
        won=sum(1 for prospect in prospects if prospect.status == "won"),
        invalid=sum(1 for prospect in prospects if prospect.status == "invalid"),
        events=len(events),
        event_coverage=len(prospect_ids_with_events) / len(prospects) if prospects else 0,
    )
    platform_rows = build_rows(prospects, events, "platform")
    customer_type_rows = build_rows(prospects, events, "customer_type")
    return FeedbackBoard(
        summary=summary,
        platform_rows=platform_rows,
        customer_type_rows=customer_type_rows,
        recent_events=recent_events,
        recommendations=build_recommendations(platform_rows, customer_type_rows, summary),
    )


def build_rows(
    prospects: list[Prospect],
    events: list[ProspectEvent],
    field: str,
) -> list[FeedbackRow]:
    grouped: dict[str, list[Prospect]] = defaultdict(list)
    for prospect in prospects:
        name = getattr(prospect, field) or "unknown"
        grouped[name].append(prospect)
    event_counts = Counter(getattr(event, field) or "unknown" for event in events)
    rows = [
        build_row(name, rows, event_counts.get(name, 0))
        for name, rows in grouped.items()
    ]
    return sorted(rows, key=lambda row: (row.score, row.won, row.trial_sent, row.contacted), reverse=True)


def build_row(name: str, prospects: list[Prospect], events: int) -> FeedbackRow:
    contacted = sum(1 for prospect in prospects if prospect.status in POSITIVE_STATUSES)
    trial_sent = sum(1 for prospect in prospects if prospect.status == "trial_sent")
    won = sum(1 for prospect in prospects if prospect.status == "won")
    invalid = sum(1 for prospect in prospects if prospect.status == "invalid")
    score = calculate_feedback_score(
        prospects=len(prospects),
        contacted=contacted,
        trial_sent=trial_sent,
        won=won,
        invalid=invalid,
        avg_score=sum(prospect.lead_score for prospect in prospects) / len(prospects) if prospects else 0,
    )
    return FeedbackRow(
        name=name,
        prospects=len(prospects),
        contacted=contacted,
        trial_sent=trial_sent,
        won=won,
        invalid=invalid,
        events=events,
        score=score,
    )


def calculate_feedback_score(
    prospects: int,
    contacted: int,
    trial_sent: int,
    won: int,
    invalid: int,
    avg_score: float,
) -> int:
    if prospects <= 0:
        return 0
    score = 20
    score += min(contacted * 4, 24)
    score += min(trial_sent * 10, 30)
    score += min(won * 25, 50)
    score += min(int(avg_score / 5), 18)
    score -= min(invalid * 8, 35)
    if prospects >= 10 and contacted == 0:
        score -= 12
    return max(0, min(100, score))


def build_recommendations(
    platform_rows: list[FeedbackRow],
    customer_type_rows: list[FeedbackRow],
    summary: FeedbackSummary,
) -> list[str]:
    recommendations: list[str] = []
    if summary.event_coverage < 0.2:
        recommendations.append("先把触达、测试、成交、无效都记录下来；没有反馈闭环，评分会越来越像猜。")
    top_platform = next((row for row in platform_rows if row.prospects >= 3), None)
    if top_platform:
        recommendations.append(f"当前优先观察平台：{top_platform.name}，推进分 {top_platform.score}，测试 {top_platform.trial_sent}，成交 {top_platform.won}。")
    weak_platform = next((row for row in reversed(platform_rows) if row.prospects >= 10 and row.contacted == 0), None)
    if weak_platform:
        recommendations.append(f"{weak_platform.name} 有线索但没有推进，先暂停扩量，补联系方式或重查关键词。")
    top_type = next((row for row in customer_type_rows if row.prospects >= 3), None)
    if top_type:
        recommendations.append(f"客户类型优先级：{top_type.name}，不要平均用力，先围绕高推进类型优化话术。")
    return recommendations or ["继续积累反馈事件，至少记录 30 个触达/无效结果后再大幅调整来源。"]


def feedback_snapshot(db: Session) -> dict[str, object]:
    board = build_feedback_board(db)
    return {
        "prospects": board.summary.prospects,
        "contacted": board.summary.contacted,
        "trial_sent": board.summary.trial_sent,
        "won": board.summary.won,
        "invalid": board.summary.invalid,
        "events": board.summary.events,
        "event_coverage": round(board.summary.event_coverage, 4),
        "top_platforms": [
            {
                "platform": row.name,
                "score": row.score,
                "prospects": row.prospects,
                "contacted": row.contacted,
                "trial_sent": row.trial_sent,
                "won": row.won,
                "invalid": row.invalid,
            }
            for row in board.platform_rows[:10]
        ],
        "top_customer_types": [
            {
                "customer_type": row.name,
                "score": row.score,
                "prospects": row.prospects,
                "contacted": row.contacted,
                "trial_sent": row.trial_sent,
                "won": row.won,
                "invalid": row.invalid,
            }
            for row in board.customer_type_rows[:10]
        ],
        "recommendations": board.recommendations,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
