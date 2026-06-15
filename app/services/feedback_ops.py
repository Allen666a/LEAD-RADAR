from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Prospect, ProspectEvent
from app.services.feedback import record_prospect_event
from app.services.learning import build_learning_report


OUTCOME_LABELS = {
    "contacted": "已触达",
    "trial_sent": "已发测试",
    "follow_up": "继续跟进",
    "won": "成交",
    "invalid": "无效",
}

REASON_LABELS = {
    "won_trial_ok": "测试效果好",
    "won_need_urgent": "需求紧急",
    "won_rebuy": "复购/持续用量",
    "no_reply": "暂无回复",
    "need_more_info": "需要补场景",
    "need_contact": "缺联系方式",
    "price_too_high": "价格不合适",
    "quality_concern": "担心质量/稳定性",
    "static_ip_need": "其实要静态/固定 IP",
    "datacenter_need": "其实要机房代理",
    "old_or_stale": "线索过旧",
    "competitor_or_ad": "同行/广告",
    "risk_or_abuse": "高风险用途",
    "not_target": "不是目标客户",
}

POSITIVE_REASONS = {"won_trial_ok", "won_need_urgent", "won_rebuy"}
NEGATIVE_REASONS = {
    "price_too_high",
    "quality_concern",
    "static_ip_need",
    "datacenter_need",
    "old_or_stale",
    "competitor_or_ad",
    "risk_or_abuse",
    "not_target",
}


@dataclass(frozen=True)
class FeedbackCandidate:
    prospect: Prospect
    title: str
    reason_hint: str
    recommended_outcome: str


@dataclass(frozen=True)
class FeedbackReasonRow:
    reason: str
    label: str
    count: int
    positive: int
    negative: int


@dataclass(frozen=True)
class FeedbackOpsBoard:
    candidates: list[FeedbackCandidate]
    reason_rows: list[FeedbackReasonRow]
    missing_feedback: int
    high_value_without_feedback: int


def build_feedback_ops_board(db: Session, limit: int = 12) -> FeedbackOpsBoard:
    candidates = load_feedback_candidates(db, limit=limit)
    reason_rows = build_reason_rows(db)
    high_value_without_feedback = count_high_value_without_feedback(db)
    return FeedbackOpsBoard(
        candidates=candidates,
        reason_rows=reason_rows,
        missing_feedback=len(candidates),
        high_value_without_feedback=high_value_without_feedback,
    )


def load_feedback_candidates(db: Session, limit: int = 12) -> list[FeedbackCandidate]:
    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.status.in_(["qualified", "contacted", "wechat_added", "trial_sent", "follow_up"]))
            .order_by(desc(Prospect.lead_score), desc(Prospect.updated_at), desc(Prospect.last_seen_at))
            .limit(limit * 3)
        )
    )
    rows: list[FeedbackCandidate] = []
    for prospect in prospects:
        if has_recent_outcome(db, prospect.id):
            continue
        rows.append(
            FeedbackCandidate(
                prospect=prospect,
                title=display_title(prospect),
                reason_hint=reason_hint(prospect),
                recommended_outcome=recommended_outcome(prospect),
            )
        )
        if len(rows) >= limit:
            break
    return rows


def has_recent_outcome(db: Session, prospect_id: int) -> bool:
    cutoff = datetime.now() - timedelta(days=2)
    event = db.scalar(
        select(ProspectEvent)
        .where(ProspectEvent.prospect_id == prospect_id)
        .where(ProspectEvent.event_type == "outcome")
        .where(ProspectEvent.created_at >= cutoff)
        .limit(1)
    )
    return event is not None


def build_reason_rows(db: Session) -> list[FeedbackReasonRow]:
    events = list(db.scalars(select(ProspectEvent).where(ProspectEvent.event_type == "outcome")))
    reason_counter: Counter[str] = Counter()
    positive_counter: Counter[str] = Counter()
    negative_counter: Counter[str] = Counter()
    for event in events:
        reason = parse_reason(event.note)
        if not reason:
            continue
        reason_counter[reason] += 1
        if event.value == "won" or reason in POSITIVE_REASONS:
            positive_counter[reason] += 1
        if event.value == "invalid" or reason in NEGATIVE_REASONS:
            negative_counter[reason] += 1
    return [
        FeedbackReasonRow(
            reason=reason,
            label=REASON_LABELS.get(reason, reason),
            count=count,
            positive=positive_counter.get(reason, 0),
            negative=negative_counter.get(reason, 0),
        )
        for reason, count in reason_counter.most_common(12)
    ]


def count_high_value_without_feedback(db: Session) -> int:
    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.lead_score >= 70)
            .where(Prospect.status.notin_(["won", "invalid"]))
            .limit(500)
        )
    )
    return sum(1 for prospect in prospects if not has_any_outcome(db, prospect.id))


def has_any_outcome(db: Session, prospect_id: int) -> bool:
    event = db.scalar(
        select(ProspectEvent)
        .where(ProspectEvent.prospect_id == prospect_id)
        .where(ProspectEvent.event_type == "outcome")
        .limit(1)
    )
    return event is not None


def apply_structured_feedback(
    db: Session,
    prospect_id: int,
    outcome: str,
    reason: str,
    note: str = "",
    follow_up_days: int = 0,
) -> bool:
    prospect = db.get(Prospect, prospect_id)
    if prospect is None or outcome not in OUTCOME_LABELS:
        return False
    reason = reason if reason in REASON_LABELS else ""
    now = datetime.now()

    if outcome == "contacted":
        prospect.status = "contacted"
        prospect.last_contacted_at = now
        prospect.next_follow_up_at = now + timedelta(days=follow_up_days or 3)
    elif outcome == "trial_sent":
        prospect.status = "trial_sent"
        prospect.last_contacted_at = now
        prospect.next_follow_up_at = now + timedelta(days=follow_up_days or 3)
    elif outcome == "follow_up":
        prospect.status = "follow_up"
        prospect.next_follow_up_at = now + timedelta(days=follow_up_days or 3)
    elif outcome == "won":
        prospect.status = "won"
        prospect.next_follow_up_at = None
    elif outcome == "invalid":
        prospect.status = "invalid"
        prospect.suppressed = True
        prospect.suppression_reason = REASON_LABELS.get(reason, "反馈标记无效")
        prospect.next_follow_up_at = None

    prospect.next_action = next_action_for(outcome, reason)
    prospect.follow_up_note = merge_note(
        prospect.follow_up_note,
        f"P20 反馈：{OUTCOME_LABELS[outcome]}；原因：{REASON_LABELS.get(reason, '未填原因')}；{note}".strip("；"),
    )
    prospect.updated_at = now
    record_prospect_event(
        db,
        prospect,
        "outcome",
        value=outcome,
        note=structured_note(reason, note),
        commit=False,
    )
    db.commit()
    build_learning_report(db, apply=True)
    return True


def parse_reason(note: str) -> str:
    for part in (note or "").split(";"):
        if part.startswith("reason="):
            return part.replace("reason=", "", 1).strip()
    return ""


def structured_note(reason: str, note: str) -> str:
    chunks = []
    if reason:
        chunks.append(f"reason={reason}")
        chunks.append(f"reason_label={REASON_LABELS.get(reason, reason)}")
    if note.strip():
        chunks.append(f"note={note.strip()[:1200]}")
    return "; ".join(chunks)


def display_title(prospect: Prospect) -> str:
    name = (prospect.display_name or "").strip()
    if name:
        return name[:80]
    return f"{prospect.platform or 'unknown'} #{prospect.id}"


def reason_hint(prospect: Prospect) -> str:
    if prospect.status == "trial_sent":
        return "优先记录测试结果：稳定性、国家命中、验证码/风控、是否愿意付费。"
    if prospect.status in {"contacted", "wechat_added"}:
        return "记录是否有回复、是否要测试、价格是否卡住。"
    if prospect.status == "follow_up":
        return "复访后记录继续、成交、无效或下一次复查。"
    return "记录触达结果，让系统知道这类客户是否值得继续找。"


def recommended_outcome(prospect: Prospect) -> str:
    if prospect.status == "trial_sent":
        return "follow_up"
    if prospect.status in {"contacted", "wechat_added"}:
        return "trial_sent"
    return "contacted"


def next_action_for(outcome: str, reason: str) -> str:
    if outcome == "won":
        return "已成交，记录来源、关键词和客户类型用于放大。"
    if outcome == "invalid":
        return f"无效：{REASON_LABELS.get(reason, '反馈标记无效')}。后续同类线索降低优先级。"
    if outcome == "trial_sent":
        return "已发测试包，3 天后复访测试结果：连通率、国家命中、稳定性和风控触发。"
    if outcome == "follow_up":
        return "继续跟进，按反馈安排下一次复访。"
    return "已触达，下一步确认平台、国家、并发量和当前代理痛点。"


def merge_note(old: str, new: str) -> str:
    old = (old or "").strip()
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} {new.strip()}"
    return line if not old else f"{old}\n{line}"
